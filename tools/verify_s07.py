#!/usr/bin/env python3
"""S07 delivery gate. Native proof is Prepared; only Docker can record Verified."""

import argparse
import ast
import csv
from datetime import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

from dev import ROOT, compose_environment, require_local_docker
import image as production_image
from init_local_env import create_local_env
from verify_s05 import HIDDEN_VALUES, check_probe, redact, run
from verify_s06 import native_database

S06 = "53e453b59bda9e2a21cbea59a086ed7ae26a45bb"
RECORDS = ROOT / "docs/implementation"
REVIEWED_WARNINGS = {"security.W005", "security.W021"}
TEST_ARGS = ["manage.py", "test", "core.tests", "accounting.tests_integration", "accounting.tests_regressions",
             "--settings=core.settings.test", "--testrunner=accounting.regression_runner.FinancialRegressionRunner", "--noinput"]


def context_policy_check(directory):
    """Exercise the real packer in a separate synthetic Git repository."""
    fixture = directory / "context-fixture"; fixture.mkdir()
    def git(*args):
        return run(["git", "-C", fixture, "-c", "core.hooksPath=/dev/null", *args], environment=production_image.git_environment())
    git("init", "--quiet")
    git("config", "user.name", "S07 context test")
    git("config", "user.email", "synthetic@example.invalid")
    git("config", "commit.gpgsign", "false")
    for name in production_image.EXACT | {"core/wsgi.py", ".env", "accounting/private/data.py", "accounting/legacy.sql"}:
        path = fixture / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# S07 synthetic context fixture\n")
    git("add", "--force", "."); git("commit", "--quiet", "-m", "Synthetic context fixture")
    (fixture / "accounting/untracked.py").write_text("# Untracked synthetic fixture\n")
    original = production_image.ROOT
    production_image.ROOT = fixture
    try:
        first = production_image.committed_context()
        second = production_image.committed_context()
        assert first[1] == second[1], "Archive is not deterministic"
        paths = set(first[2]["paths"])
        assert not {".env", "accounting/private/data.py", "accounting/legacy.sql", "accounting/untracked.py"} & paths
        (fixture / "manage.py").write_text("# Modified tracked fixture\n")
        try:
            production_image.committed_context()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Dirty tracked source was accepted")
        git("checkout", "--", "manage.py")
        (fixture / "core/linked.py").symlink_to(fixture / ".env")
        git("add", "core/linked.py");git("commit", "--quiet", "-m", "Synthetic symbolic-link rejection case")
        try:
            production_image.committed_context()
        except RuntimeError:
            pass
        else:
            raise AssertionError("Selected symbolic link was accepted")
    finally:
        production_image.ROOT = original
    return {"deterministic_archive": True, "tracked_private_files_excluded": True,
            "untracked_code_excluded": True, "dirty_tracked_source_rejected": True, "selected_symlink_rejected": True}


def strict_suite(execute, read_report, *, current_source=False):
    arguments = ["manage.py", "test", *TEST_ARGS[5:]] if current_source else TEST_ARGS
    execute(*arguments)
    report = read_report()
    new_tests = sum(isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
                    for node in ast.walk(ast.parse((ROOT / "core/tests/test_s07.py").read_text())))
    expected_count = 78 + new_tests
    if current_source:
        assert report["tests_run"] >= expected_count
    else:
        assert report["tests_run"] == expected_count
    assert all(report[key] == 0 for key in ("unexpected_errors", "unexpected_failures", "unexpected_successes", "skips"))
    cases = json.loads((ROOT / "accounting/regression_cases.json").read_text())["cases"]
    assert report["known_failures_reproduced"] == sum(case["expected_outcome"] == "known_failure" for case in cases)
    assert {row["case_id"] for row in report["cases"]} == {case["case_id"] for case in cases}
    assert len(report["cases"]) == len(cases)
    observed = {row["case_id"]: row for row in report["cases"]}
    for case in cases:
        assert observed[case["case_id"]]["outcome"] == ("known_failure_reproduced" if case["expected_outcome"] == "known_failure" else "passed")
    return report


def deployment_checks(execute):
    execute("manage.py", "check", "--deploy", "--fail-level", "ERROR", "--settings=core.settings.production")
    code = "import django,json;django.setup();from django.core.checks import run_checks;print(json.dumps([{'id':c.id,'level':c.level} for c in run_checks(include_deployment_checks=True)]))"
    checks = json.loads(execute("-c", code).stdout)
    assert not any(item["level"] >= 40 for item in checks)
    assert {item["id"] for item in checks} == REVIEWED_WARNINGS, "Unreviewed deployment warning"
    return {"errors": 0, "warning_ids": sorted(REVIEWED_WARNINGS),
            "warning_disposition": "HSTS includeSubDomains and preload intentionally disabled pending S09 hostname/TLS verification; not silenced."}


def static_proof(path):
    manifest = path / "staticfiles.json"
    data = json.loads(manifest.read_text())
    assert (path / "admin/css/base.css").is_file()
    assert all((path / name).is_file() for name in data["paths"].values())
    return {"file_count": sum(file.is_file() for file in path.rglob("*")), "manifest_entries": len(data["paths"]),
            "manifest_digest": "sha256:" + hashlib.sha256(manifest.read_bytes()).hexdigest()}


def request(address, path, headers=None):
    host, port = address.rsplit(":", 1)
    connection = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        connection.request("GET", path, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def wait_ready(address):
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            if request(address, "/health/ready/")[0] == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(0.2)
    raise RuntimeError("Gunicorn readiness did not recover within 25 seconds")


def live_ready(address, ready=True):
    live = request(address, "/health/live/")
    database = request(address, "/health/ready/")
    assert live[0] == 200 and json.loads(live[2]) == {"status": "ok"}
    assert database[0] == (200 if ready else 503)
    assert json.loads(database[2]) == {"status": "ready" if ready else "unavailable"}
    assert "no-store" in {key.lower(): value for key, value in database[1].items()}["cache-control"]


def native_verification(bin_dir, directory, python):
    with native_database(bin_dir, directory) as (environment, version):
        static = directory / "static"
        environment.update({"DJANGO_SETTINGS_MODULE": "core.settings.production", "DJANGO_DEBUG": "false",
                            "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1", "DJANGO_CSRF_TRUSTED_ORIGINS": "https://localhost",
                            "DJANGO_STATIC_ROOT": str(static), "GUNICORN_WORKERS": "1"})
        def execute(*arguments):
            return run([python, *arguments], environment=environment)

        before = json.loads(execute("manage.py", "probe_development_database", "--settings=core.settings.local").stdout)
        check_probe(before, empty=True)
        execute("manage.py", "collectstatic", "--noinput", "--settings=core.settings.build")
        assets = static_proof(static)
        checks = deployment_checks(execute)
        execute("manage.py", "migrate", "--noinput")
        migrated = json.loads(execute("manage.py", "probe_development_database", "--settings=core.settings.local").stdout); check_probe(migrated)
        print("[S07] Running PostgreSQL tests with the 26 tracked financial failures.", flush=True)
        suite = strict_suite(execute, lambda: json.loads(Path(environment["ACCOUNTING_REGRESSION_REPORT"]).read_text()))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
        address = "127.0.0.1:" + str(port)
        log = directory / "gunicorn.log"
        marker = secrets.token_urlsafe(32)
        with log.open("w") as stream:
            process = subprocess.Popen([str(python), "-m", "gunicorn", "--config", str(ROOT / "gunicorn.conf.py"), "--bind", address],
                cwd=ROOT, env=environment, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                wait_ready(address); live_ready(address)
                assert request(address, "/login/")[0] == 301
                login = request(address, "/login/?api_token=" + marker,
                                {"X-Forwarded-Proto": "https", "Accept-Language": "en-US,en"})
                assert login[0] == 200 and "Όνομα χρήστη" in login[2].decode()
                assert {key.lower(): value for key, value in login[1].items()}["content-language"] == "el"
                admin = request(address, "/admin/login/", {"X-Forwarded-Proto": "https", "Accept-Language": "en"})
                assert admin[0] == 200 and b"/static/admin/css/base." in admin[2]
                print("[S07] Stopping PostgreSQL: readiness must fail while liveness stays available.", flush=True)
                run([bin_dir / "pg_ctl", "-D", directory / "pg-data", "-m", "fast", "-w", "stop"])
                try:
                    live_ready(address, ready=False)
                finally:
                    options = shlex.join(["-h", "127.0.0.1", "-p", environment["PGPORT"], "-k", ""])
                    run([bin_dir / "pg_ctl", "-D", directory / "pg-data", "-l", directory / "postgres.log", "-o", options, "-w", "start"])
                wait_ready(address); live_ready(address)
            except Exception as error:
                raise RuntimeError(str(error) + "\n" + redact(log.read_text()[-6000:], environment)) from None
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL); process.wait()
        assert marker not in log.read_text(), "Query canary leaked into Gunicorn access logging"
        return {"status": "Prepared", "mode": "native-postgresql17-gunicorn", "docker_execution_this_step": False,
                "production_image_built_verified": False, "postgresql_binary_version": version,
                "postgresql_version_num": migrated["postgresql_version_num"], "applied_migrations": migrated["applied_migrations"],
                "suite": suite, "deployment_checks": checks, "static_assets": assets,
                "gunicorn_http_verified": True, "readiness_outage_recovery_verified": True,
                "greek_login_verified": True, "query_string_excluded_from_access_log": True,
                "admin_manifest_references_verified": True,
                "context": production_image.candidate_context()[1],
                "blocker": "Docker Engine unavailable here. Run tools/verify_s07.py --record on a local Docker Engine before S08."}


def docker_verification(directory, *, current_source=False):
    require_local_docker()
    # This allowed-looking untracked source must not enter a committed build.
    canary = ROOT / "accounting" / ("s07_untracked_" + secrets.token_hex(6) + ".py")
    try:
        with canary.open("x") as stream:
            stream.write("# Synthetic untracked build-context canary\n")
        image = production_image.build()
        assert str(canary.relative_to(ROOT)) not in image["context"]["paths"]
    finally:
        canary.unlink(missing_ok=True)
    env_file = directory / "env"; create_local_env(env_file)
    HIDDEN_VALUES.update(line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(("DJANGO_SECRET_KEY=", "DB_PASSWORD=")))
    with env_file.open("a") as stream:
        stream.write("DELIVERY_IMAGE=" + image["image_id"] + "\n")
    project = "accounting-s07-check-" + secrets.token_hex(6)
    command = ["docker", "compose", "--project-directory", str(ROOT), "--file", str(ROOT / "compose.delivery.yml"),
               "--env-file", str(env_file), "--project-name", project]
    environment = {key: value for key, value in compose_environment().items() if key != "DELIVERY_IMAGE"}
    def compose(*arguments, checked=True):
        if checked:
            return run(command + list(arguments), environment=environment)
        return subprocess.run(command + list(arguments), cwd=ROOT, env=environment, capture_output=True, text=True)

    config = json.loads(compose("config", "--format", "json").stdout)
    assert not config["services"]["db"].get("ports")
    web = config["services"]["web"]
    assert web["read_only"] and not web.get("volumes") and all(port["host_ip"] == "127.0.0.1" for port in web["ports"])
    assert web["image"] == image["image_id"] and "build" not in web
    assert not run(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={project}", "--quiet"], environment=environment).stdout.strip()
    assert not compose("ps", "--all", "--quiet").stdout.strip()
    owned = False
    try:
        print(f"[S07] Testing immutable image {image['image_id']} in {project}.", flush=True)
        owned = True
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        probe = ["python", "manage.py", "probe_development_database", "--settings=core.settings.local"]
        before = json.loads(compose("run", "--rm", "--no-deps", "web", *probe).stdout); check_probe(before, empty=True)
        compose("run", "--rm", "--no-deps", "web", "python", "manage.py", "migrate", "--noinput")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "web")
        def execute(*arguments):
            return compose("exec", "-T", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s07-suite.json", "web", "python", *arguments)

        migrated = json.loads(execute(*probe[1:]).stdout); check_probe(migrated)
        checks = deployment_checks(execute)
        suite = strict_suite(execute, lambda: json.loads(execute("-c", "from pathlib import Path;print(Path('/tmp/s07-suite.json').read_text())").stdout), current_source=current_source)
        metadata = json.loads(execute("-c", "import os,json;from pathlib import Path;print(json.dumps({'uid':os.geteuid(),'files':[str(p.relative_to('/app')) for p in Path('/app').rglob('*') if p.is_file()]}))").stdout)
        assert metadata["uid"] == 10001
        files = set(metadata["files"])
        assert ".env" not in files and str(canary.relative_to(ROOT)) not in files
        assert all(production_image.allowed(path) or path.startswith("staticfiles/") for path in files)
        static = directory / "exported-static"
        production_image.export_static(image["image_id"], static)
        assets = static_proof(static)
        address = compose("port", "web", "8000").stdout.strip()
        assert address.startswith("127.0.0.1:")
        live_ready(address)
        assert request(address, "/login/")[0] == 301
        login_code = "import urllib.request,json;r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/login/',headers={'X-Forwarded-Proto':'https','Accept-Language':'en'}));print(json.dumps({'status':r.status,'language':r.headers['Content-Language'],'greek':'Όνομα χρήστη' in r.read().decode()}))"
        assert json.loads(execute("-c", login_code).stdout) == {"status": 200, "language": "el", "greek": True}
        admin_code = "import urllib.request; r=urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8000/admin/login/',headers={'X-Forwarded-Proto':'https'})); assert r.status==200 and b'/static/admin/css/base.' in r.read()"
        execute("-c", admin_code)
        marker = secrets.token_urlsafe(32)
        request(address, "/health/live/?api_token=" + marker)
        print("[S07] Verifying real database outage, independent liveness and recovery.", flush=True)
        compose("stop", "db")
        try:
            live_ready(address, ready=False)
            assert compose("exec", "-T", "web", "python", "/app/docker/healthcheck.py", checked=False).returncode == 1
        finally:
            compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        wait_ready(address); live_ready(address)
        execute("/app/docker/healthcheck.py")
        logs = compose("logs", "--no-color", "web")
        assert marker not in logs.stdout + logs.stderr
        return {"status": "Verified", "mode": "docker-production-image", "docker_execution_this_step": True,
                "production_image_built_verified": True, "image": image, "postgresql_version_num": migrated["postgresql_version_num"],
                "applied_migrations": migrated["applied_migrations"], "suite": suite, "deployment_checks": checks,
                "static_assets": assets, "gunicorn_http_verified": True, "readiness_outage_recovery_verified": True,
                "greek_login_verified": True, "query_string_excluded_from_access_log": True,
                "admin_manifest_references_verified": True,
                "container_uid": metadata["uid"], "image_private_file_audit_passed": True,
                "untracked_source_canary_excluded": True, "static_export_from_same_image_verified": True}
    finally:
        if owned:
            compose("down", "--volumes", "--remove-orphans")


def record_verified(report, path):
    if report["status"] != "Verified" or not report["production_image_built_verified"]:
        raise RuntimeError("Only successful Docker production-image verification can complete S07.")
    with (RECORDS / "steps.csv").open(newline="", encoding="utf-8") as stream:
        steps = list(csv.DictReader(stream))
    row = next(row for row in steps if row["step_id"] == "S07")
    row.update(status="Verified", blocker="", next_step="S08", manual_acceptance="Production image/health/static/PG checks verified; TLS, VM, restore and full release acceptance remain Pending")
    with (RECORDS / "steps.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=steps[0], lineterminator="\n");writer.writeheader();writer.writerows(steps)
    state = RECORDS / "state.md"; text = state.read_text()
    text = re.sub(r"Updated .*?Current step:.*?\n", f"Updated {report['verified_at'][:10]}. Current step: **S07 Verified — production image and delivery checks**. Next step: **S08 — Google Cloud VM checkpoint**.\n", text, count=1)
    text = re.sub(r"<!-- S07-RESULT -->.*?<!-- /S07-RESULT -->", "<!-- S07-RESULT -->\nThe production Docker image, explicit migrations, strict PostgreSQL suite, non-root/private-file audit, static export and Gunicorn readiness outage/recovery are Verified. See evidence/S07-verification.json for the immutable image identity. S08 is eligible: create/select the Google Cloud VM and supply the deployment parameters.\n<!-- /S07-RESULT -->", text, flags=re.S)
    state.write_text(text, encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


def main(*, current_source=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    if current_source and (args.record or args.native_bin):
        parser.error("The continuing CI gate requires Docker and cannot rewrite the historical S07 step records.")
    if args.native_bin and args.record:
        parser.error("Native proof is Prepared and cannot complete the production image gate.")
    if args.record and args.report and args.report.resolve() != (RECORDS / "evidence/S07-verification.json").resolve():
        parser.error("--record writes canonical S07 evidence; use --report without --record for another destination.")
    baseline = json.loads((RECORDS / "evidence/S06-verification.json").read_text())
    assert baseline["status"] == "Verified" and baseline["suite"]["known_failures_reproduced"] == 26
    if not current_source:
        for path in ["accounting/models.py", "accounting/views.py", "accounting/forms.py", "accounting/urls.py", "requirements.txt", "requirements-tools.txt",
                     *[str(p.relative_to(ROOT)) for p in (ROOT / "accounting/migrations").glob("*.py")]]:
            assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", f"{S06}:{path}"], cwd=ROOT), path + " changed"
    if not args.native_bin:
        require_local_docker()
    with tempfile.TemporaryDirectory(prefix="accounting-s07-") as temp:
        directory = Path(temp)
        context_policy = context_policy_check(directory)
        print("[S07] Installing hashed tools, reproducing locks and checking the Greek catalog.", flush=True)
        run([sys.executable, "-m", "venv", directory / "tools"])
        tools_python = directory / "tools/bin/python"
        install = ["-m", "pip", "--disable-pip-version-check", "install", "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "-r"]
        run([tools_python, *install, ROOT / "requirements-tools.txt"])
        target = (ROOT / ".python-version").read_text().strip()
        run([tools_python, "-m", "uv", "python", "install", target])
        run([tools_python, ROOT / "tools/lock_dependencies.py", "--check"])
        run([tools_python, ROOT / "tools/compile_translations.py", "--check"])
        scan = json.loads(run([tools_python, ROOT / "tools/scan_secrets.py"]).stdout)
        assert scan["unreviewed_findings"] == 0
        if args.native_bin:
            python = run([tools_python, "-m", "uv", "python", "find", "--managed-python", target]).stdout.strip()
            run([python, "-m", "venv", directory / "runtime"])
            runtime = directory / "runtime/bin/python"
            run([runtime, *install, ROOT / "requirements.txt"])
            result = native_verification(args.native_bin, directory, runtime)
        else:
            result = docker_verification(directory, current_source=current_source)
    report = {"step": "delivery" if current_source else "S07", "verified_at": datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
              "source_reference_commit": result["image"]["revision"] if current_source else S06,
              **result, "secret_scan": scan, "dependency_locks_reproduced": True, "compiled_catalog_in_sync": True,
              "committed_context_policy": context_policy,
              **({"known_financial_failures_remaining": result["suite"]["known_failures_reproduced"]} if current_source else
                 {"financial_defects_fixed": False, "business_models_views_forms_migrations_unchanged": True}),
              "https_deployment_verified": False, "google_cloud_resources_created": False, "real_data_imported": False,
              "full_requirement_acceptance": "Not evaluated by delivery gate" if current_source else "Pending"}
    path = args.report or RECORDS / "evidence/S07-verification.json"
    if args.record:
        record_verified(report, path)
    elif args.report:
        path.parent.mkdir(parents=True, exist_ok=True);path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.record:
        print("S07 Verified. Next is S08: create/select the Google Cloud VM and complete the deployment parameter sheet.")


if __name__ == "__main__":
    main()
