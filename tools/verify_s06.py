#!/usr/bin/env python3
"""Verify the S06 regression baseline on isolated PostgreSQL 17, never SQLite.

Default: disposable local Docker project. --native-bin: disposable native PG17
cluster. Both can verify this test-capture step; neither claims bugs are fixed.
"""

import argparse
from contextlib import contextmanager
import csv
from datetime import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from dev import ROOT, compose_command, compose_environment, require_local_docker
from init_local_env import create_local_env
from verify_s05 import HIDDEN_VALUES, check_probe, compose_config, redact, run

S05 = "5a65a72906f7d3a5fccdcfd8aad0d0362a2bd7fa"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"
TEST_OPTIONS = ["--settings=core.settings.test", "--verbosity=2", "--noinput"]


@contextmanager
def native_database(bin_dir, directory):
    bin_dir = bin_dir.resolve()
    version = run([bin_dir / "postgres", "--version"]).stdout.strip()
    assert re.search(r"PostgreSQL\) 17\.", version), "PostgreSQL 17 required"
    password = secrets.token_urlsafe(32); HIDDEN_VALUES.add(password)
    pw_file = directory / "pg-password"
    with os.fdopen(os.open(pw_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "w") as stream:
        stream.write(password + "\n")
    data = directory / "pg-data"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("DB_", "DJANGO_", "PG", "ACCOUNTING_"))}
    environment.update({"DJANGO_SETTINGS_MODULE": "core.settings.local", "DJANGO_ENV_FILE": str(directory / "absent-env"),
                        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64), "DB_NAME": "s06_verification",
                        "DB_USER": "accounting_platform", "DB_PASSWORD": password, "DB_HOST": "127.0.0.1", "DB_PORT": str(port),
                        "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": "accounting_platform", "PGPASSWORD": password,
                        "ACCOUNTING_REGRESSION_REPORT": str(directory / "regressions.json")})
    run([bin_dir / "initdb", "-D", data, "--username=accounting_platform", "--encoding=UTF8", "--locale=C.UTF-8",
         "--auth=scram-sha-256", "--pwfile", pw_file])
    options = shlex.join(["-h", "127.0.0.1", "-p", str(port), "-k", ""])
    running = False
    try:
        try:
            run([bin_dir / "pg_ctl", "-D", data, "-l", directory / "postgres.log", "-o", options, "-w", "start"])
        except RuntimeError as error:
            log = directory / "postgres.log"
            raise RuntimeError(str(error) + "\n" + redact(log.read_text()[-6000:], environment)) from None
        running = True
        run([bin_dir / "createdb", "s06_verification"], environment=environment)
        yield environment, version
    finally:
        if running:
            run([bin_dir / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"])


def raw_command(command, environment):
    return subprocess.run([str(value) for value in command], cwd=ROOT, env=environment, capture_output=True, text=True)


def financial_suite(manage, read_report):
    registry = json.loads((ROOT / "accounting/regression_cases.json").read_text())["cases"]
    expected = sum(case["expected_outcome"] == "known_failure" for case in registry)
    print("[S06] Running configuration, integration, runner guards and financial regressions.", flush=True)
    manage("test", "core.tests", "accounting.tests_integration", "accounting.tests_regressions",
           "--testrunner=" + RUNNER, *TEST_OPTIONS)
    suite = read_report()
    assert suite["tests_run"] == 35 + 7 + len(registry), "Unexpected baseline test count"
    for field in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips"):
        assert suite[field] == 0, field
    assert suite["known_failures_reproduced"] == expected
    observed = {case["case_id"]: case for case in suite["cases"]}
    assert set(observed) == {case["case_id"] for case in registry} and len(suite["cases"]) == len(registry)
    for case in registry:
        row = observed[case["case_id"]]
        assert row["test"] == case["test"]
        assert row["outcome"] == ("known_failure_reproduced" if case["expected_outcome"] == "known_failure" else "passed")
    print("[S06] Confirming the ordinary Django runner exposes the unfixed financial assertions.", flush=True)
    raw = manage("test", "accounting.tests_regressions", "--testrunner=django.test.runner.DiscoverRunner",
                 *TEST_OPTIONS, allow_failure=True)
    output = raw.stdout + raw.stderr
    summary = re.search(r"FAILED \(([^)]+)\)", output)
    counts = dict(item.split("=") for item in summary[1].split(", ")) if summary else {}
    raw_count = re.search(r"Ran (\d+) tests?", output)
    if not (raw.returncode == 1 and int(counts.get("failures", 0)) == expected and not int(counts.get("errors", 0))
            and raw_count and int(raw_count[1]) == len(registry)):
        raise RuntimeError("Ordinary runner did not reproduce the expected assertion baseline.\n" + redact(output[-6000:]))
    return {"suite": suite, "raw_regression_exit_code": raw.returncode,
            "raw_regression_tests_run": int(raw_count[1]), "raw_assertion_failures": int(counts["failures"]),
            "raw_unexpected_errors": int(counts.get("errors", 0))}


def native_verification(bin_dir, directory, python):
    with native_database(bin_dir, directory) as (environment, version):
        def manage(*arguments, allow_failure=False):
            command = [python, "manage.py", *arguments]
            return raw_command(command, environment) if allow_failure else run(command, environment=environment)

        before = json.loads(manage("probe_development_database").stdout); check_probe(before, empty=True)
        manage("migrate", "--noinput")
        migrated = json.loads(manage("probe_development_database").stdout); check_probe(migrated)
        result = financial_suite(manage, lambda: json.loads(Path(environment["ACCOUNTING_REGRESSION_REPORT"]).read_text()))
        return {"mode": "native-postgresql17", "docker_execution_this_step": False,
                "postgresql_binary_version": version, "postgresql_version_num": migrated["postgresql_version_num"],
                "applied_migrations": migrated["applied_migrations"], **result}


def docker_verification(directory):
    require_local_docker()
    env_file = directory / "env"; create_local_env(env_file)
    HIDDEN_VALUES.update(line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(("DJANGO_SECRET_KEY=", "DB_PASSWORD=")))
    with env_file.open("a") as stream:
        stream.write("WEB_PORT=0\n")
    project = "accounting-s06-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    config = compose_config(env_file, project)

    def compose(*arguments, allow_failure=False):
        return raw_command(command + list(arguments), environment) if allow_failure else run(command + list(arguments), environment=environment)

    assert not run(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={project}", "--quiet"],
                   environment=environment).stdout.strip(), "Refusing to adopt an existing project"
    assert not compose("ps", "--all", "--quiet").stdout.strip(), "Project already has containers"
    owned = False
    try:
        print(f"[S06] Temporary Docker project: {project}; using an unused loopback web port.", flush=True)
        compose("build", "--pull", "web")
        owned = True
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        before = json.loads(compose("run", "--rm", "--no-deps", "--entrypoint", "python", "web", "manage.py",
                                    "probe_development_database").stdout); check_probe(before, empty=True)
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "web")

        def manage(*arguments, allow_failure=False):
            return compose("exec", "-T", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s06-regressions.json", "web",
                           "python", "manage.py", *arguments, allow_failure=allow_failure)

        migrated = json.loads(manage("probe_development_database").stdout); check_probe(migrated)
        result = financial_suite(manage, lambda: json.loads(compose("exec", "-T", "web", "python", "-c",
            "from pathlib import Path; print(Path('/tmp/s06-regressions.json').read_text())").stdout))
        container = compose("ps", "--quiet", "web").stdout.strip()
        image = run(["docker", "inspect", "--format", "{{.Image}}", container], environment=environment).stdout.strip()
        return {"mode": "docker-compose", "docker_execution_this_step": True, "development_image_id": image,
                "compose": config, "postgresql_version_num": migrated["postgresql_version_num"],
                "applied_migrations": migrated["applied_migrations"], **result}
    finally:
        if owned:
            compose("down", "--volumes", "--remove-orphans")


def record_verified(report, path):
    assert report["status"] == "Verified" and report["suite"]["unexpected_errors"] == 0
    with (RECORDS / "steps.csv").open(newline="", encoding="utf-8") as stream:
        steps = list(csv.DictReader(stream))
    step = next(row for row in steps if row["step_id"] == "S06")
    step.update(status="Verified", blocker="", next_step="S07", manual_acceptance=
                "Known legacy failures reproduced on PostgreSQL; financial fixes and full acceptance remain Pending")
    with (RECORDS / "steps.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=steps[0], lineterminator="\n"); writer.writeheader(); writer.writerows(steps)
    state = RECORDS / "state.md"; text = state.read_text()
    text = re.sub(r"Updated .*?Current step:.*?\n", f"Updated {report['verified_at'][:10]}. Current step: **S06 Verified — financial regression baseline**. Next step: **S07**.\n", text, count=1)
    summary = (f"<!-- S06-RESULT -->\nS06 test capture is Verified on {report['mode']}, PostgreSQL {report['postgresql_version_num']}. "
               f"The strict suite ran {report['suite']['tests_run']} tests: {report['suite']['tests_passed']} passed and "
               f"{report['suite']['known_failures_reproduced']} exact known failures were reproduced, with no unexpected outcomes. "
               "The ordinary runner still fails the unfixed assertions. S07 is eligible; financial fixes remain in their assigned steps.\n<!-- /S06-RESULT -->")
    text = re.sub(r"<!-- S06-RESULT -->.*?<!-- /S06-RESULT -->", summary, text, flags=re.S)
    state.write_text(text, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["case_id", "issue_id", "test", "expected_outcome", "outcome", "required", "observed", "requirements", "fix_steps"]
    with (RECORDS / "evidence/S06-regression-baseline.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n"); writer.writeheader()
        for case in report["suite"]["cases"]:
            writer.writerow({key: (json.dumps(case[key], ensure_ascii=False) if key in {"required", "observed"} and key in case
                                   else " ".join(case[key]) if key in {"requirements", "fix_steps"}
                                   else case.get(key, "")) for key in columns})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path, help="Use a disposable native PostgreSQL 17 cluster")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--record", action="store_true", help="Update S06 evidence, steps and state after successful checks")
    args = parser.parse_args()
    s05 = json.loads((RECORDS / "evidence/S05-verification.json").read_text())
    assert s05["status"] == "Verified" and s05["docker_build_run"] and s05["docker_restart_persistence_verified"], "S05 Docker gate required"
    protected = ["accounting/models.py", "accounting/views.py", "accounting/forms.py", "accounting/urls.py",
                 "requirements.txt", "requirements-tools.txt", "core/tests/test_s04.py",
                 *[str(path.relative_to(ROOT)) for path in (ROOT / "accounting/migrations").glob("*.py")]]
    for path in protected:
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", f"{S05}:{path}"], cwd=ROOT), path + " changed"
    if not args.native_bin:
        require_local_docker()
    with tempfile.TemporaryDirectory(prefix="accounting-s06-") as temp:
        directory = Path(temp)
        print("[S06] Reproducing hashed tools/runtime locks and checking the Greek catalog.", flush=True)
        run([sys.executable, "-m", "venv", directory / "tools"])
        tools_python = directory / "tools/bin/python"
        install = ["-m", "pip", "--disable-pip-version-check", "install", "--require-hashes", "--only-binary=:all:",
                   "--index-url", "https://pypi.org/simple", "-r"]
        run([tools_python, *install, ROOT / "requirements-tools.txt"])
        target = (ROOT / ".python-version").read_text().strip()
        run([tools_python, "-m", "uv", "python", "install", target])
        run([tools_python, ROOT / "tools/lock_dependencies.py", "--check"])
        run([tools_python, ROOT / "tools/compile_translations.py", "--check"])
        if args.native_bin:
            python = run([tools_python, "-m", "uv", "python", "find", "--managed-python", target]).stdout.strip()
            run([python, "-m", "venv", directory / "runtime"])
            runtime = directory / "runtime/bin/python"
            run([runtime, *install, ROOT / "requirements.txt"])
            result = native_verification(args.native_bin, directory, runtime)
        else:
            result = docker_verification(directory)
        scan = json.loads(run([tools_python, ROOT / "tools/scan_secrets.py"]).stdout)
        assert scan["unreviewed_findings"] == 0
    report = {"step": "S06", "status": "Verified", "verified_at": datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
              "source_reference_commit": S05, "dependency_S05_docker_verified": True, **result,
              "secret_scan": scan, "dependency_locks_reproduced": True, "compiled_catalog_in_sync": True,
              "business_code_and_migrations_unchanged": True, "financial_defects_fixed": False,
              "database_or_migration_execution": True, "real_data_imported": False,
              "google_cloud_resources_created": False, "full_requirement_acceptance": "Pending"}
    path = args.report or RECORDS / "evidence/S06-verification.json"
    if args.record:
        record_verified(report, path)
    elif args.report:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
