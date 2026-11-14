#!/usr/bin/env python3
"""S13 isolated PostgreSQL staff authentication/MFA gate; never touches the VM.

Default: disposable Docker Compose project. Native PG17 proof is Prepared until
the operator reproduces the same checks in the local Docker environment.
"""

import argparse
import ast
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from dev import ROOT, compose_command, compose_environment, require_local_docker
from init_local_env import create_local_env
from verify_s05 import HIDDEN_VALUES, run
from verify_s06 import native_database
import image

BASE = "13ef2a1c8c96984da88c4cf73e695d128023555b"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


def source_checks():
    if json.loads((RECORDS / "evidence/S12-verification.json").read_text())["status"] != "Verified":
        raise RuntimeError("S12 Docker verification is required first")
    protected = ["requirements-tools.in", "requirements-tools.txt", "accounting/regression_runner.py",
        "accounting/regression_cases.json", "accounting/membership.py", "accounting/legacy_membership.py",
        "accounting/legacy_ownership.py", "accounting/office_access.py", "accounting/ownership.py", "accounting/forms.py",
        "accounting/views.py", "accounting/admin.py", "Dockerfile"]
    protected += [str(path.relative_to(ROOT)) for path in (ROOT / "accounting/migrations").glob("000[12345]_*.py")]
    protected += ["docs/implementation/evidence/" + step + "-verification.json" for step in ("S10", "S11", "S12")]
    for name in protected:
        if (ROOT / name).read_bytes() != subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT):
            raise RuntimeError("Protected baseline changed: " + name)
    def tree(name, original=False):
        source = subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT) if original else (ROOT / name).read_bytes()
        return ast.parse(source)
    old_config, new_config = tree("core/tests/test_s04.py", True), tree("core/tests/test_s04.py")
    helper = next(node for node in new_config.body if isinstance(node, ast.FunctionDef) and node.name == "load_profile")
    prefix_filter = next(node for node in ast.walk(helper) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute) and node.func.attr == "startswith")
    if ast.literal_eval(prefix_filter.args[0]) != ("DJANGO_", "DB_", "AUTH_", "EMAIL_", "DEFAULT_FROM_EMAIL"):
        raise RuntimeError("Unexpected profile-probe environment policy")
    prefix_filter.args[0].elts = prefix_filter.args[0].elts[:2]
    if ast.dump(old_config) != ast.dump(new_config):
        raise RuntimeError("Original configuration tests or assertions changed beyond profile environment isolation")
    before, after = tree("accounting/models.py", True), tree("accounting/models.py")
    classes = lambda root: {node.name: ast.dump(node) for node in root.body if isinstance(node, ast.ClassDef)}
    if classes(before) != classes(after):
        raise RuntimeError("Existing office/business models or calculations changed")
    def assertions(root):
        return {node.name: ast.dump(node) for node in ast.walk(root)
                if isinstance(node, ast.FunctionDef) and node.name not in {"setUpTestData", "setUp"}}
    if assertions(tree("accounting/tests_regressions.py", True)) != assertions(tree("accounting/tests_regressions.py")):
        raise RuntimeError("Financial assertions changed")
    versions = lambda data: dict(re.findall(r"(?m)^([a-z0-9-]+)==([^ \\]+)", data))
    old = versions(subprocess.check_output(["git", "show", BASE + ":requirements.txt"], cwd=ROOT, text=True))
    new = versions((ROOT / "requirements.txt").read_text())
    if any(new.get(name) != version for name, version in old.items()) or set(new) - set(old) != {"django-otp", "cryptography", "qrcode", "cffi", "pycparser"}:
        raise RuntimeError("Unexpected runtime dependency changes")
    _, context = image.candidate_context()
    for path in ("accounting/templates/accounting/auth/reset_email.txt", "accounting/templates/accounting/auth/reset_subject.txt"):
        if path not in context["paths"]:
            raise RuntimeError("Recovery email template excluded from the production image")
    if image.allowed("accounting/templates/accounting/auth/captured.eml"):
        raise RuntimeError("Captured recovery mail must never enter the production image")
    return {"original_migrations_office_business_schema_and_financial_assertions_preserved": True,
            "configuration_test_assertions_preserved": True,
            "s10_s11_s12_evidence_preserved": True, "existing_runtime_versions_and_tools_lock_preserved": True,
            "recovery_templates_in_production_context": True,
            "application_context_digest": context["digest"]}


def verification(manage, read_suite):
    packages = json.loads(manage("shell", "--no-imports", "-c",
        "import importlib.metadata as m,json,subprocess,sys; subprocess.run([sys.executable,'-m','pip','check'],check=True,capture_output=True); "
        "print(json.dumps({n:m.version(n) for n in ('Django','django-otp','cryptography','qrcode','psycopg')}))").stdout)
    manage("migrate", "--noinput")
    manage("makemigrations", "--check", "--dry-run")
    manage("check", "--fail-level=WARNING")
    print("[S13] Testing Greek authentication, MFA/reset/recovery, shared limits and independent PostgreSQL concurrency.", flush=True)
    manage("test", "accounting.tests_authentication", "accounting.tests_ownership", "accounting.tests_offices", "core.tests", "accounting.tests_integration", "accounting.tests_regressions",
           "--settings=core.settings.test", "--testrunner=" + RUNNER, "--noinput", "--verbosity=1")
    suite = read_suite()
    new_tests = sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                    for n in ast.walk(ast.parse((ROOT / "accounting/tests_authentication.py").read_text())))
    if suite["tests_run"] != 157 + new_tests or suite["known_failures_reproduced"] != 26 or any(
            suite[key] for key in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")):
        raise RuntimeError("Unexpected S13/financial test outcome")
    version = int(manage("shell", "--no-imports", "-c", "from django.db import connection; print(connection.pg_version)").stdout.strip())
    if version // 10000 != 17:
        raise RuntimeError("PostgreSQL 17 required")
    return {"postgresql_version_num": version, "runtime_packages": packages, "runtime_pip_check": True, "s13_tests": new_tests,
            "suite": {k: v for k, v in suite.items() if k != "cases"},
            "greek_password_auth_and_captured_recovery": True,
            "privileged_mfa_enrollment_and_recovery": True,
            "encrypted_seeds_hashed_single_use_backup_codes": True,
            "session_limits_revocation_and_safe_redirects": True,
            "shared_postgresql_limits_and_single_use_concurrency": True,
            "migration_drift": False}


def native(args, directory):
    with native_database(args.native_bin, directory) as (environment, version):
        setup = '''import os, psycopg
with psycopg.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                     host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], autocommit=True) as conn:
    conn.execute("CREATE ROLE accounting_s13_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
    conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO accounting_s13_migrator")
'''
        run([args.python, "-c", setup], environment=environment)
        restricted = {**environment, "PGOPTIONS": "-c role=accounting_s13_migrator"}
        run([args.python, ROOT / "manage.py", "migrate", "--noinput"], environment=restricted)
        probe = run([args.python, ROOT / "manage.py", "shell", "--no-imports", "-c",
            "from django.db import connection; c=connection.cursor(); c.execute('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user'); print(c.fetchone())"], environment=restricted)
        if probe.stdout.strip() != "(False, False, False)":
            raise RuntimeError("Restricted migration role unexpectedly elevated")
        def manage(*arguments):
            return run([args.python, ROOT / "manage.py", *arguments], environment=environment)
        result = verification(manage, lambda: json.loads(Path(environment["ACCOUNTING_REGRESSION_REPORT"]).read_text()))
    return {"mode": "native-postgresql17", "status": "Prepared", "docker_execution": False,
            "postgresql_binary_version": version, "native_restricted_role_ddl": {
                "all_migrations_passed": True, "superuser": False, "createdb": False, "createrole": False}, **result}


def docker(directory):
    require_local_docker()
    env_file = directory / "env"; create_local_env(env_file)
    HIDDEN_VALUES.update(line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(("DJANGO_SECRET_KEY=", "DB_PASSWORD=")))
    with env_file.open("a") as stream:
        stream.write("WEB_PORT=0\n")
    project = "accounting-s13-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S13] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s13-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s13-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s13-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        result = verification(stable_manage, read_suite)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report):
    old_path = RECORDS / "evidence/S13-verification.json"
    if old_path.exists():
        previous = json.loads(old_path.read_text())
        for key in ("native_restricted_role_ddl",):
            if key in previous and previous.get("application_context_digest") == report.get("application_context_digest") and key not in report:
                report[key] = previous[key]
    (RECORDS / "evidence/S13-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with (RECORDS / "steps.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    row = next(r for r in rows if r["step_id"] == "S13")
    row.update(status=report["status"], branch="step/s13-authentication-mfa", code_reference_commit=report["source_commit"].removeprefix("git:"),
        evidence="docs/implementation/evidence/S13-verification.json; docs/implementation/staff_authentication.md; accounting/tests_authentication.py",
        blocker="" if report["status"] == "Verified" else "Reproduce the prepared PostgreSQL proof with python3 tools/verify_s13.py --record on local Docker",
        manual_acceptance="Live mail/sender and deployment, D01/S14 onboarding and full Greek/security acceptance remain Pending",
        next_step="S14" if report["status"] == "Verified" else "Complete S13 local Docker gate")
    with (RECORDS / "steps.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    path = RECORDS / "state.md"; text = path.read_text()
    text = re.sub(r"Updated .*?Current step:.*?\n", "Updated " + report["verified_at"][:10]
                  + ". Current step: **S13 " + report["status"] + " — staff authentication and privileged MFA**. Next step: **"
                  + row["next_step"] + "**.\n", text, count=1)
    result = ("<!-- S13-RESULT -->\n" + report["status"] + ": " + str(report["s13_tests"])
              + " authentication/MFA/recovery/session/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. "
              + "Docker execution: " + str(report["docker_execution"]) + ". Live mail/deployment, S14 onboarding and full release acceptance remain Pending.\n<!-- /S13-RESULT -->")
    if "<!-- S13-RESULT -->" in text:
        text = re.sub(r"<!-- S13-RESULT -->.*?<!-- /S13-RESULT -->", result, text, flags=re.S)
    else:
        text += "\n" + result + "\n"
    path.write_text(text)
    path = RECORDS / "traceability.csv"
    with path.open(newline="") as stream:
        requirements = list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement["requirement_id"] not in {"UR-OFF-06", "UR-OFF-07", "QR-02", "UR-LOC-01"}:
            continue
        note = (" S13: " + report["status"] + " on " + report["mode"] + "; Greek staff sign-in/out, expiring single-use password reset, active office rechecks, owner/platform MFA, encrypted factors, hashed one-use recovery, bounded sessions and shared PostgreSQL throttles/concurrency pass. Live mail/deployment and full release acceptance remain Pending."
                if requirement["requirement_id"] != "UR-LOC-01" else
                " S13: " + report["status"] + " Greek authentication/recovery/MFA screens, email copy and no-store errors tested. Full staged Greek acceptance remains Pending.")
        requirement["notes"] = re.sub(r" S13:.*$", "", requirement["notes"]) + note
        for evidence in ("docs/implementation/evidence/S13-verification.json", "docs/implementation/staff_authentication.md", "accounting/tests_authentication.py"):
            if evidence not in requirement["evidence"].split("; "):
                requirement["evidence"] = "; ".join(filter(None, [requirement["evidence"], evidence]))
        requirement["last_reviewed"] = report["verified_at"][:10]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=requirements[0], lineterminator="\n"); writer.writeheader(); writer.writerows(requirements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--tools-python", type=Path, help="Reuse an existing pinned maintenance environment")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    try:
        if args.record and subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
            raise RuntimeError("Commit the candidate source before recording its verification")
        protected = source_checks()
        with tempfile.TemporaryDirectory(prefix="accounting-s13-") as temp:
            directory = Path(temp)
            tooling = args.tools_python
            if tooling is None:
                print("[S13] Installing hashed maintenance tools; reproducing locks/catalog and scanning Git history.", flush=True)
                run([sys.executable, "-m", "venv", directory / "tools"])
                tooling = directory / "tools/bin/python"
                run([tooling, "-m", "pip", "--disable-pip-version-check", "install", "--timeout", "120", "--retries", "5",
                     "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "-r", ROOT / "requirements-tools.txt"])
            run([tooling, ROOT / "tools/lock_dependencies.py", "--check"])
            run([tooling, ROOT / "tools/compile_translations.py", "--check"])
            scan = json.loads(run([tooling, ROOT / "tools/scan_secrets.py"]).stdout)
            result = native(args, directory) if args.native_bin else docker(directory)
            result.update(secret_scan=scan, runtime_and_tools_locks_reproduced=True, greek_catalog_verified=True)
        result.update(step="S13", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            full_requirement_acceptance="Pending", full_requirement_acceptances_pending=85, **protected)
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S13 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
