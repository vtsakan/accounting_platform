#!/usr/bin/env python3
"""S12 isolated PostgreSQL ownership migration/boundary gate; never touches the VM.

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

BASE = "e314645a4c6decc701fc0dca928d52d6f9b76491"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


def source_checks():
    protected = ["requirements.in", "requirements.txt", "requirements-tools.in", "requirements-tools.txt",
        "accounting/regression_runner.py", "accounting/regression_cases.json", "accounting/membership.py",
        "accounting/legacy_membership.py", "accounting/urls.py", "Dockerfile", "docker-compose.yml",
        "core/tests/test_s04.py", "docs/implementation/evidence/S10-verification.json",
        "docs/implementation/evidence/S11-verification.json"]
    protected += [str(path.relative_to(ROOT)) for path in (ROOT / "accounting/migrations").glob("000[123]_*.py")]
    for name in protected:
        if (ROOT / name).read_bytes() != subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT):
            raise RuntimeError("Protected baseline changed: " + name)
    def tree(name, original=False):
        source = subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT) if original else (ROOT / name).read_bytes()
        return ast.parse(source)
    old, new = tree("accounting/models.py", True), tree("accounting/models.py")
    for name in ("Office", "AccountantProfile"):
        before = next(n for n in old.body if isinstance(n, ast.ClassDef) and n.name == name)
        after = next(n for n in new.body if isinstance(n, ast.ClassDef) and n.name == name)
        if ast.dump(before) != ast.dump(after):
            raise RuntimeError("S11 membership schema changed")
    def methods(root):
        for node in ast.walk(root):
            if isinstance(node, ast.Call):
                node.keywords = [kw for kw in node.keywords if kw.arg != "office"]
        return {n.name: ast.dump(n) for n in ast.walk(root)
                if isinstance(n, ast.FunctionDef) and n.name != "setUpTestData"}
    if methods(tree("accounting/tests_regressions.py", True)) != methods(tree("accounting/tests_regressions.py")):
        raise RuntimeError("Financial regression assertions changed")
    before = next(n for n in ast.walk(old) if isinstance(n, ast.ClassDef) and n.name == "Transaction")
    after = next(n for n in ast.walk(new) if isinstance(n, ast.ClassDef) and n.name == "Transaction")
    financial_save = lambda node: ast.dump(next(n for n in node.body if isinstance(n, ast.FunctionDef) and n.name == "save"))
    if financial_save(before) != financial_save(after):
        raise RuntimeError("Legacy financial save calculation changed")
    _, context = image.candidate_context()
    return {"original_migrations_membership_schema_and_locks_preserved": True,
            "financial_assertions_registry_and_calculations_preserved": True,
            "s10_s11_live_evidence_preserved": True, "application_context_digest": context["digest"]}


def verification(manage, read_suite):
    manage("migrate", "--noinput")
    manage("makemigrations", "--check", "--dry-run")
    manage("check", "--fail-level=WARNING")
    print("[S12] Testing staged backfill, two-office HTTP/admin denial, database links and concurrency.", flush=True)
    manage("test", "accounting.tests_ownership", "accounting.tests_offices", "core.tests", "accounting.tests_integration", "accounting.tests_regressions",
           "--settings=core.settings.test", "--testrunner=" + RUNNER, "--noinput", "--verbosity=1")
    suite = read_suite()
    new_tests = sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                    for n in ast.walk(ast.parse((ROOT / "accounting/tests_ownership.py").read_text())))
    if suite["tests_run"] != 120 + new_tests or suite["known_failures_reproduced"] != 26 or any(
            suite[key] for key in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")):
        raise RuntimeError("Unexpected S12/financial test outcome")
    version = int(manage("shell", "--no-imports", "-c", "from django.db import connection; print(connection.pg_version)").stdout.strip())
    if version // 10000 != 17:
        raise RuntimeError("PostgreSQL 17 required")
    return {"postgresql_version_num": version, "s12_tests": new_tests,
            "suite": {k: v for k, v in suite.items() if k != "cases"},
            "reviewed_nullable_backfill_and_final_nonnull_guard": True,
            "legacy_record_hashes_preserved_and_retry_safe": True,
            "database_same_office_foreign_keys_and_immutable_ownership": True,
            "two_office_http_forms_admin_and_autocomplete_scoped": True,
            "scoped_uniqueness_concurrency_passed": True,
            "execution_adapter_revocation_checked": True,
            "migration_drift": False}


def native(args, directory):
    with native_database(args.native_bin, directory) as (environment, version):
        def manage(*arguments):
            return run([args.python, ROOT / "manage.py", *arguments], environment=environment)
        result = verification(manage, lambda: json.loads(Path(environment["ACCOUNTING_REGRESSION_REPORT"]).read_text()))
    return {"mode": "native-postgresql17", "status": "Prepared", "docker_execution": False,
            "postgresql_binary_version": version, **result}


def docker(directory):
    require_local_docker()
    env_file = directory / "env"; create_local_env(env_file)
    HIDDEN_VALUES.update(line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(("DJANGO_SECRET_KEY=", "DB_PASSWORD=")))
    with env_file.open("a") as stream:
        stream.write("WEB_PORT=0\n")
    project = "accounting-s12-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S12] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s12-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s12-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s12-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        result = verification(stable_manage, read_suite)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report):
    old_path = RECORDS / "evidence/S12-verification.json"
    if old_path.exists():
        previous = json.loads(old_path.read_text())
        for key in ("secret_scan", "native_restricted_role_ddl"):
            if key in previous:
                report[key] = previous[key]
    (RECORDS / "evidence/S12-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with (RECORDS / "steps.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    row = next(r for r in rows if r["step_id"] == "S12")
    row.update(status=report["status"], branch="step/s12-office-ownership", code_reference_commit=report["source_commit"].removeprefix("git:"),
        evidence="docs/implementation/evidence/S12-verification.json; docs/implementation/office_ownership.md; accounting/tests_ownership.py",
        blocker="" if report["status"] == "Verified" else "Reproduce the prepared PostgreSQL proof with python3 tools/verify_s12.py --record on local Docker",
        manual_acceptance="Actual legacy ownership review, D01 capability policy and S16/Greek release acceptance remain Pending",
        next_step="S13" if report["status"] == "Verified" else "Complete S12 local Docker gate")
    with (RECORDS / "steps.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    path = RECORDS / "state.md"; text = path.read_text()
    text = re.sub(r"Updated .*?Current step:.*?\n", "Updated " + report["verified_at"][:10]
                  + ". Current step: **S12 " + report["status"] + " — office ownership and isolation**. Next step: **"
                  + row["next_step"] + "**.\n", text, count=1)
    result = ("<!-- S12-RESULT -->\n" + report["status"] + ": " + str(report["s12_tests"])
              + " ownership/backfill/access/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. "
              + "Docker execution: " + str(report["docker_execution"]) + ". Future entry-point coverage, policy and full release acceptance remain Pending.\n<!-- /S12-RESULT -->")
    if "<!-- S12-RESULT -->" in text:
        text = re.sub(r"<!-- S12-RESULT -->.*?<!-- /S12-RESULT -->", result, text, flags=re.S)
    else:
        text += "\n" + result + "\n"
    path.write_text(text)
    path = RECORDS / "traceability.csv"
    with path.open(newline="") as stream:
        requirements = list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement["requirement_id"] not in {"UR-OFF-05", "UR-OFF-07", "QR-01", "UR-LOC-01"}:
            continue
        note = (" S12: " + report["status"] + " on " + report["mode"] + "; five owned business tables, reviewed backfill, same-office database links, scoped views/forms/admin and execution-time revocation checks pass. Complete boundary acceptance remains S16."
                if requirement["requirement_id"] != "UR-LOC-01" else
                " S12: " + report["status"] + " Greek ownership validation and no-store access denial tested with English browser preference. Full staged Greek acceptance remains Pending.")
        requirement["notes"] = re.sub(r" S12:.*$", "", requirement["notes"]) + note
        requirement["last_reviewed"] = report["verified_at"][:10]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=requirements[0], lineterminator="\n"); writer.writeheader(); writer.writerows(requirements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    try:
        protected = source_checks()
        with tempfile.TemporaryDirectory(prefix="accounting-s12-") as temp:
            result = native(args, Path(temp)) if args.native_bin else docker(Path(temp))
        result.update(step="S12", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            full_requirement_acceptance="Pending", full_requirement_acceptances_pending=85, **protected)
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S12 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
