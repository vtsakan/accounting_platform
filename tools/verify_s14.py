#!/usr/bin/env python3
"""S14 isolated PostgreSQL office settings/staff workflow gate; never touches the VM.

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

BASE = "16501f4ffeafc15f7361bce1ef790e8e19031f77"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


def source_checks():
    if json.loads((RECORDS / "evidence/S13-verification.json").read_text())["status"] != "Verified":
        raise RuntimeError("S13 Docker verification required")
    protected = ["requirements.in", "requirements.txt", "requirements-tools.in", "requirements-tools.txt", "Dockerfile",
        "accounting/regression_runner.py", "accounting/regression_cases.json", "accounting/views.py", "accounting/forms.py",
        "accounting/auth_models.py", "accounting/auth_services.py", "core/auth_crypto.py", "core/tests/test_s04.py", "core/tests/test_s07.py"]
    protected += [str(p.relative_to(ROOT)) for p in (ROOT / "accounting/migrations").glob("000[123456]_*.py")]
    protected += ["docs/implementation/evidence/"+step+"-verification.json" for step in ("S10","S11","S12","S13")]
    for name in protected:
        if (ROOT / name).read_bytes() != subprocess.check_output(["git","show",BASE+":"+name],cwd=ROOT):
            raise RuntimeError("Protected baseline changed: "+name)
    def tree(name, original=False):
        data = subprocess.check_output(["git","show",BASE+":"+name],cwd=ROOT) if original else (ROOT/name).read_bytes()
        return ast.parse(data)
    old, new = tree("accounting/models.py",True), tree("accounting/models.py")
    for name in ("Entity","CashAccount","Category","Agreement","Transaction"):
        get = lambda root: next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name==name)
        if ast.dump(get(old)) != ast.dump(get(new)):
            raise RuntimeError("Existing business model/calculations changed: "+name)
    for name in ("Office", "AccountantProfile"):
        def fields(root):
            cls = next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name==name)
            return {n.targets[0].id:ast.dump(n) for n in cls.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
        before, after = fields(old), fields(new)
        if any(after.get(key) != value for key,value in before.items()):
            raise RuntimeError("Existing office/membership field changed: "+name)
    for name in ("accounting/tests_regressions.py", "accounting/tests_authentication.py", "accounting/tests_ownership.py"):
        def tests(root):
            return {n.name:ast.dump(n) for n in ast.walk(root) if isinstance(n,ast.FunctionDef) and n.name.startswith("test_")}
        original = tree(name,True)
        if name == "accounting/tests_authentication.py":
            # The reported browser regression requires one corrected form-header
            # assertion. Preserve every other old auth assertion, including the
            # no-referrer assertion on the secret reset-link redirect.
            node = next(n for n in ast.walk(original) if isinstance(n,ast.FunctionDef)
                and n.name == "test_greek_form_errors_no_store_and_autocomplete_with_english_browser")
            header = next(n for n in ast.walk(node) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                and n.func.attr == "assertEqual" and len(n.args) == 2 and isinstance(n.args[0],ast.Subscript)
                and isinstance(n.args[0].slice,ast.Constant) and n.args[0].slice.value == "Referrer-Policy")
            assert isinstance(header.args[1],ast.Constant) and header.args[1].value == "no-referrer"
            header.args[1].value = "same-origin"
        if tests(original) != tests(tree(name)):
            raise RuntimeError("Existing test assertions changed: "+name)
    policy = json.loads((RECORDS/"office_role_policy.json").read_text())
    if policy["finance_choice"] != "read_and_post" or policy["handover_choice"] != "colleague_accepts" or not policy["explicit_user_selection"]:
        raise RuntimeError("S14 approved policy record is missing")
    _, context = image.candidate_context()
    for name in ("invitation_email.txt","approval_email.txt","handover_email.txt"):
        if "accounting/templates/accounting/office/"+name not in context["paths"]:
            raise RuntimeError("Staff email omitted from production context")
    caddy=(ROOT/"infrastructure/Caddyfile").read_text()
    if any(value not in caddy for value in ("request>uri delete", "?Referrer-Policy same-origin", "header @bearer >Referrer-Policy no-referrer", "not path /auth/password/reset/*/set-password/")):
        raise RuntimeError("Invitation path/referrer privacy missing from proxy configuration")
    return {"original_six_migrations_and_financial_models_assertions_preserved":True,
        "authentication_assertions_preserved_except_form_referrer_policy":True,"s10_through_s13_evidence_preserved":True,
        "dependency_locks_unchanged":True,"approved_s14_role_and_handover_choices_recorded":True,
        "staff_email_templates_in_production_context":True,"invitation_proxy_log_referrer_guards":True,
        "application_context_digest":context["digest"]}


def verification(manage, read_suite):
    packages = json.loads(manage("shell", "--no-imports", "-c",
        "import importlib.metadata as m,json,subprocess,sys; subprocess.run([sys.executable,'-m','pip','check'],check=True,capture_output=True); "
        "print(json.dumps({n:m.version(n) for n in ('Django','django-otp','cryptography','qrcode','psycopg')}))").stdout)
    manage("migrate", "--noinput")
    manage("makemigrations", "--check", "--dry-run")
    manage("check", "--fail-level=WARNING")
    print("[S14] Testing office settings, recipient-bound invitations/approval, role enforcement, handover, audit and PostgreSQL concurrency.", flush=True)
    manage("test", "accounting.tests_staff", "accounting.tests_authentication", "accounting.tests_ownership", "accounting.tests_offices", "core.tests", "accounting.tests_integration", "accounting.tests_regressions",
           "--settings=core.settings.test", "--testrunner=" + RUNNER, "--noinput", "--verbosity=1")
    suite = read_suite()
    new_tests = sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                    for n in ast.walk(ast.parse((ROOT / "accounting/tests_staff.py").read_text())))
    referrer_tests = sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
        for n in ast.walk(ast.parse((ROOT / "core/tests/test_referrer.py").read_text())))
    if suite["tests_run"] != 218 + new_tests + referrer_tests or suite["known_failures_reproduced"] != 26 or any(
            suite[key] for key in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")):
        raise RuntimeError("Unexpected S14/financial test outcome")
    version = int(manage("shell", "--no-imports", "-c", "from django.db import connection; print(connection.pg_version)").stdout.strip())
    if version // 10000 != 17:
        raise RuntimeError("PostgreSQL 17 required")
    return {"postgresql_version_num": version, "runtime_packages": packages, "runtime_pip_check": True, "s14_tests": new_tests, "referrer_regression_tests": referrer_tests,
            "suite": {k: v for k, v in suite.items() if k != "cases"},
            "greek_office_settings_and_stale_update_control":True,
            "recipient_bound_single_use_invitations_and_owner_approval":True,
            "owner_accountant_capabilities_and_deactivation":True,
            "mutual_verified_handover_and_last_owner_database_guards":True,
            "office_scoped_append_only_audit_and_composite_links":True,
            "regular_owner_bootstrap_without_admin_flags":True,
            "migration_drift":False}


def native(args, directory):
    with native_database(args.native_bin, directory) as (environment, version):
        setup = '''import os, psycopg
with psycopg.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                     host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], autocommit=True) as conn:
    conn.execute("CREATE ROLE accounting_s14_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
    conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO accounting_s14_migrator")
'''
        run([args.python, "-c", setup], environment=environment)
        restricted = {**environment, "PGOPTIONS": "-c role=accounting_s14_migrator"}
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
    project = "accounting-s14-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S14] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s14-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s14-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s14-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        result = verification(stable_manage, read_suite)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report):
    old_path = RECORDS / "evidence/S14-verification.json"
    if old_path.exists():
        previous = json.loads(old_path.read_text())
        for key in ("native_restricted_role_ddl",):
            if key in previous and previous.get("application_context_digest") == report.get("application_context_digest") and key not in report:
                report[key] = previous[key]
    (RECORDS / "evidence/S14-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with (RECORDS / "steps.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    row = next(r for r in rows if r["step_id"] == "S14")
    row.update(status=report["status"], branch="step/s14-office-settings", code_reference_commit=report["source_commit"].removeprefix("git:"),
        evidence="docs/implementation/evidence/S14-verification.json; docs/implementation/office_settings_staff.md; accounting/tests_staff.py",
        blocker="" if report["status"] == "Verified" else "Reproduce the prepared PostgreSQL proof with python3 tools/verify_s14.py --record on local Docker",
        manual_acceptance="Live mail/deployment and full Greek/security acceptance remain Pending",
        next_step="S15" if report["status"] == "Verified" else "Complete S14 local Docker gate")
    with (RECORDS / "steps.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    path = RECORDS / "state.md"; text = path.read_text()
    text = re.sub(r"Updated .*?Current step:.*?\n", "Updated " + report["verified_at"][:10]
                  + ". Current step: **S14 " + report["status"] + " — office settings, staff invitations and mutual handover**. Next step: **"
                  + row["next_step"] + "**.\n", text, count=1)
    result = ("<!-- S14-RESULT -->\n" + report["status"] + ": " + str(report["s14_tests"])
              + " office/settings/invitation/role/handover/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. "
              + "Docker execution: " + str(report["docker_execution"]) + ". Live mail/deployment and full release acceptance remain Pending.\n<!-- /S14-RESULT -->")
    if "<!-- S14-RESULT -->" in text:
        text = re.sub(r"<!-- S14-RESULT -->.*?<!-- /S14-RESULT -->", result, text, flags=re.S)
    else:
        text += "\n" + result + "\n"
    path.write_text(text)
    path = RECORDS / "traceability.csv"
    with path.open(newline="") as stream:
        requirements = list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement["requirement_id"] not in {"UR-OFF-02", "UR-OFF-03", "UR-OFF-04", "UR-LOC-01"}:
            continue
        note = (" S14: " + report["status"] + " on " + report["mode"] + "; Greek office settings, recipient-bound single-use invitations with owner approval, the selected role matrix, last-owner guards, mutual verified handover and scoped append-only audit/concurrency pass. Live mail/deployment and full release acceptance remain Pending."
                if requirement["requirement_id"] != "UR-LOC-01" else
                " S14: " + report["status"] + " Greek office/settings/invitation/approval/handover screens, email copy and no-store errors tested. Full staged Greek acceptance remains Pending.")
        requirement["notes"] = re.sub(r" S14:.*$", "", requirement["notes"]) + note
        for evidence in ("docs/implementation/evidence/S14-verification.json", "docs/implementation/office_settings_staff.md", "accounting/tests_staff.py"):
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
        with tempfile.TemporaryDirectory(prefix="accounting-s14-") as temp:
            directory = Path(temp)
            tooling = args.tools_python
            if tooling is None:
                print("[S14] Installing hashed maintenance tools; reproducing locks/catalog and scanning Git history.", flush=True)
                run([sys.executable, "-m", "venv", directory / "tools"])
                tooling = directory / "tools/bin/python"
                run([tooling, "-m", "pip", "--disable-pip-version-check", "install", "--timeout", "120", "--retries", "5",
                     "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "-r", ROOT / "requirements-tools.txt"])
            run([tooling, ROOT / "tools/lock_dependencies.py", "--check"])
            run([tooling, ROOT / "tools/compile_translations.py", "--check"])
            scan = json.loads(run([tooling, ROOT / "tools/scan_secrets.py"]).stdout)
            result = native(args, directory) if args.native_bin else docker(directory)
            result.update(secret_scan=scan, runtime_and_tools_locks_reproduced=True, greek_catalog_verified=True)
        result.update(step="S14", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            live_mail_sent=False, browser_visual_accessibility_acceptance="Pending",
            full_requirement_acceptance="Pending", full_requirement_acceptances_pending=85, **protected)
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S14 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
