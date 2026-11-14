#!/usr/bin/env python3
"""S11 isolated PostgreSQL migration/membership gate; never touches the VM.

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

BASE = "06cb37d3342115aebf53dd47e36b7900c3918fcd"
RECORDS = ROOT / "docs/implementation"
LEGACY = "0002_transaction_agreement_alter_agreement_status_and_more"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


def source_checks():
    protected = ["requirements.in", "requirements.txt", "requirements-tools.in", "requirements-tools.txt",
        "accounting/views.py", "accounting/forms.py", "accounting/urls.py", "accounting/admin.py",
        "accounting/regression_runner.py", "accounting/regression_cases.json", "Dockerfile", "docker-compose.yml",
        "accounting/migrations/0001_initial.py", "accounting/migrations/" + LEGACY + ".py",
        "docs/implementation/evidence/S10-verification.json"]
    for name in protected:
        before = subprocess.check_output(["git", "show", BASE + ":" + name], cwd=ROOT)
        if (ROOT / name).read_bytes() != before:
            raise RuntimeError("Protected baseline changed: " + name)
    for filename in ("accounting/tests_regressions.py", "accounting/models.py"):
        before = ast.parse(subprocess.check_output(["git", "show", BASE + ":" + filename], cwd=ROOT))
        after = ast.parse((ROOT / filename).read_text())
        if filename.endswith("models.py"):
            nodes = lambda tree: {node.name: ast.dump(node) for node in tree.body if isinstance(node, ast.ClassDef)}
        else:
            nodes = lambda tree: {node.name: ast.dump(node) for node in ast.walk(tree)
                                  if isinstance(node, ast.FunctionDef) and node.name != "setUpTestData"}
        old, new = nodes(before), nodes(after)
        if any(new.get(name) != value for name, value in old.items()):
            raise RuntimeError("Legacy model or regression assertion changed: " + filename)
    _, context = image.candidate_context()
    if "accounting/fixtures/s11_offices.json" not in context["paths"] or any(
            path.startswith("private/") for path in context["paths"]):
        raise RuntimeError("Fixture/private-file build context policy differs")
    return {"legacy_models_financial_assertions_migrations_locks_preserved": True,
            "s10_live_evidence_preserved": True, "application_context_digest": context["digest"],
            "synthetic_fixture_in_context_and_private_mapping_excluded": True}


SEED = """from django.contrib.auth import get_user_model
from accounting.models import Entity,CashAccount
get_user_model().objects.create_user('s11-upgrade-synthetic')
Entity.objects.create(name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ ΑΝΑΒΑΘΜΙΣΗΣ S11',entity_type='CUSTOMER',vat_number='000000091')
CashAccount.objects.create(name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ ΑΝΑΒΑΘΜΙΣΗΣ S11',opening_balance='1234.56')
"""
PROBE = """import json
from django.contrib.auth import get_user_model
from django.db import connection
from accounting.models import Entity,CashAccount
print(json.dumps({'users':list(get_user_model().objects.values_list('id','username')),
'entities':list(Entity.objects.values_list('id','name','vat_number')),
'accounts':[(a.pk,a.name,str(a.opening_balance)) for a in CashAccount.objects.all()],
'version':connection.pg_version},ensure_ascii=False))
"""


def verification(manage, read_suite):
    manage("migrate", "accounting", LEGACY, "--noinput")
    manage("migrate", "auth", "--noinput")
    manage("shell", "--no-imports", "-c", SEED)
    original = json.loads(manage("shell", "--no-imports", "-c", PROBE).stdout)
    if original["version"] // 10000 != 17:
        raise RuntimeError("Real PostgreSQL 17 required")
    manage("migrate", "--noinput")
    if json.loads(manage("shell", "--no-imports", "-c", PROBE).stdout) != original:
        raise RuntimeError("Additive migration changed legacy data")
    check = "from accounting.models import Office,AccountantProfile; assert Office.objects.count()==0 and AccountantProfile.objects.count()==0"
    manage("shell", "--no-imports", "-c", check)
    # Rehearsal only, on this freshly created disposable database; never a live
    # rollback instruction. It proves the two older migrations remain usable.
    manage("migrate", "accounting", LEGACY, "--noinput")
    manage("migrate", "--noinput")
    if json.loads(manage("shell", "--no-imports", "-c", PROBE).stdout) != original:
        raise RuntimeError("Migration rehearsal changed legacy data")
    manage("makemigrations", "--check", "--dry-run")
    manage("check", "--fail-level=WARNING")
    print("[S11] Testing membership, backfill, request denials and independent PostgreSQL concurrency.", flush=True)
    manage("test", "accounting.tests_offices", "core.tests", "accounting.tests_integration", "accounting.tests_regressions",
           "--settings=core.settings.test", "--testrunner=" + RUNNER, "--noinput", "--verbosity=1")
    suite = read_suite()
    office_tests = sum(isinstance(n, ast.FunctionDef) and n.name.startswith("test_")
                       for n in ast.walk(ast.parse((ROOT / "accounting/tests_offices.py").read_text())))
    if suite["tests_run"] != 90 + office_tests or suite["known_failures_reproduced"] != 26 or any(
            suite[key] for key in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")):
        raise RuntimeError("Unexpected S11/financial test outcome")
    return {"postgresql_version_num": original["version"], "s11_tests": office_tests,
            "suite": {key: value for key, value in suite.items() if key != "cases"},
            "legacy_data_preserved_in_upgrade_and_rehearsal": True,
            "no_automatic_membership_backfill": True, "migration_drift": False,
            "two_office_fixture_and_real_concurrency": True}


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
    project = "accounting-s11-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S11] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s11-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s11-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s11-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        result = verification(stable_manage, read_suite)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report):
    old_path = RECORDS / "evidence/S11-verification.json"
    if old_path.exists():
        previous = json.loads(old_path.read_text())
        if "secret_scan" in previous:
            report["secret_scan"] = previous["secret_scan"]
    (RECORDS / "evidence/S11-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with (RECORDS / "steps.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    row = next(r for r in rows if r["step_id"] == "S11")
    row.update(status=report["status"], branch="step/s11-office-profiles", code_reference_commit=report["source_commit"].removeprefix("git:"),
        evidence="docs/implementation/evidence/S11-verification.json; docs/implementation/office_profiles.md; accounting/tests_offices.py",
        blocker="" if report["status"] == "Verified" else "Reproduce the prepared PostgreSQL proof with python3 tools/verify_s11.py --record on local Docker",
        manual_acceptance="D01 capability/handover policy, actual legacy ownership review and complete S16/Greek release acceptance remain Pending",
        next_step="S12" if report["status"] == "Verified" else "Complete S11 local Docker gate")
    with (RECORDS / "steps.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    path = RECORDS / "state.md"; text = path.read_text()
    text = re.sub(r"Updated .*?Current step:.*?\n", "Updated " + report["verified_at"][:10]
                  + ". Current step: **S11 " + report["status"] + " — offices and accountant profiles**. Next step: **"
                  + row["next_step"] + "**.\n", text, count=1)
    result = ("<!-- S11-RESULT -->\n" + report["status"] + ": " + str(report["s11_tests"])
              + " membership/backfill/access/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. "
              + "Docker execution: " + str(report["docker_execution"]) + ". Full office ownership, policy and release acceptance remain Pending.\n<!-- /S11-RESULT -->")
    if "<!-- S11-RESULT -->" in text:
        text = re.sub(r"<!-- S11-RESULT -->.*?<!-- /S11-RESULT -->", result, text, flags=re.S)
    else:
        text += "\n" + result + "\n"
    path.write_text(text)
    path = RECORDS / "traceability.csv"
    with path.open(newline="") as stream:
        requirements = list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement["requirement_id"] not in {"UR-OFF-01", "UR-LOC-01"}:
            continue
        note = (" S11: " + report["status"] + " on " + report["mode"] + "; unique mandatory-office profile, locked service, complete reviewed backfill and actual concurrent assignment tests pass. Full office-boundary acceptance remains S16."
                if requirement["requirement_id"] == "UR-OFF-01" else
                " S11: " + report["status"] + " Greek field/role labels and Greek no-store membership denial tested with English browser preference. Full staged Greek acceptance remains Pending.")
        requirement["notes"] = re.sub(r" S11:.*$", "", requirement["notes"]) + note
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
        with tempfile.TemporaryDirectory(prefix="accounting-s11-") as temp:
            result = native(args, Path(temp)) if args.native_bin else docker(Path(temp))
        result.update(step="S11", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            full_requirement_acceptance="Pending", **protected)
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S11 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
