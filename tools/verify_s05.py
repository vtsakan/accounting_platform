#!/usr/bin/env python3
"""Verify S05 on an isolated local Compose project, or run supplementary native PG17 checks.

Default Docker verification owns a new random project and deletes only its own
temporary containers/volume. The normal development volume is never selected.
Native mode cannot mark the Docker completion gate Verified.
"""

import argparse
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
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from dev import ROOT, compose_command, compose_environment, require_local_docker
from init_local_env import create_local_env

RECORDS = ROOT / "docs/implementation"
S04 = "aae1250c441f76b804c532711bc00edc3258943e"
HIDDEN_VALUES = set()


def redact(text, environment=None):
    hidden = HIDDEN_VALUES | {value for key, value in {**os.environ, **(environment or {})}.items()
                              if re.search(r"SECRET|PASSWORD|TOKEN|CREDENTIAL", key, re.I) and value}
    for value in sorted(hidden, key=len, reverse=True):
        text = text.replace(value, "[REDACTED]")
    return text


def run(command, *, environment=None):
    result = subprocess.run([str(value) for value in command], cwd=ROOT, env=environment, capture_output=True, text=True)
    if result.returncode:
        # Keep failure diagnostics useful without exposing generated credentials
        # or inherited secret environment values. Evidence contains no raw logs.
        diagnostic = redact((result.stdout + result.stderr)[-12000:], environment)
        raise RuntimeError(f"Verification command failed: {Path(str(command[0])).name} (exit {result.returncode}).\n{diagnostic}")
    return result


def fresh_environment():
    return {key: value for key, value in os.environ.items() if not key.startswith(("DJANGO_", "DB_"))}


def check_probe(probe, *, empty=False, markers=False):
    assert probe["postgresql_version_num"] // 10000 == 17, "PostgreSQL 17 required"
    assert probe["encoding"] == "UTF8", "UTF8 database required"
    if empty:
        assert probe["public_tables"] == [] and probe["applied_migrations"] == [], "Verification must start with an empty database"
    else:
        expected = {"accounting.0001_initial", "accounting.0002_transaction_agreement_alter_agreement_status_and_more"}
        assert expected <= set(probe["applied_migrations"]), "Original migration history missing"
        assert "auth_user" in probe["public_tables"], "Authentication migrations missing"
    if markers:
        data = probe["synthetic_markers"]
        assert data["afm"] == "000000000" and data["greek_name_matches"] and data["opening_balance"] == "1234.56"


def test_count(result):
    match = re.search(r"Ran (\d+) tests?", result.stdout + result.stderr)
    assert match and int(match[1]) >= 35, "Expected S04 and PostgreSQL integration tests"
    return int(match[1])


def compose_config(env_file, project):
    result = run(compose_command(env_file, project) + ["config", "--format", "json"], environment=compose_environment())
    config = json.loads(result.stdout)
    db, web = config["services"]["db"], config["services"]["web"]
    assert not db.get("ports"), "Database must not publish a host port"
    assert all(port.get("host_ip") == "127.0.0.1" for port in web["ports"]), "Web ports must bind to loopback"
    assert db["volumes"][0]["source"] == "postgres17_data", "Legacy volume must not be reused"
    assert all(mount.get("read_only") for mount in web["volumes"]), "Development source mounts must be read-only"
    pins = json.loads((ROOT / "docker/image-pins.json").read_text())
    assert db["image"] == pins["postgresql"]["reference"]
    assert pins["python"]["reference"] in (ROOT / "docker/development.Dockerfile").read_text()
    return {"compose_validated": True, "database_host_ports": 0, "web_bind": "127.0.0.1",
            "volume_key": "postgres17_data", "python_image": pins["python"]["reference"],
            "postgresql_image": pins["postgresql"]["reference"]}


def docker_verification(env_file, project):
    require_local_docker()
    command = compose_command(env_file, project)
    environment = compose_environment()

    def compose(*arguments):
        return run(command + list(arguments), environment=environment)

    # Never adopt an existing project, even if a random identifier collides.
    existing = run(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={project}", "--quiet"], environment=environment)
    assert not existing.stdout.strip(), "Refusing to reuse an existing verification project"
    assert not compose("ps", "--all", "--quiet").stdout.strip(), "Verification project already has containers"
    owned = False
    try:
        print(f"[S05] Temporary Docker project: {project}", flush=True)
        print("[S05] Building the development image and starting a new PostgreSQL 17 volume.", flush=True)
        compose("build", "--pull", "web")
        owned = True
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        before = json.loads(compose("run", "--rm", "--no-deps", "--entrypoint", "python", "web",
                                    "manage.py", "probe_development_database").stdout)
        check_probe(before, empty=True)
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "web")
        migrated = json.loads(compose("exec", "-T", "web", "python", "manage.py", "probe_development_database").stdout)
        check_probe(migrated)
        compose("exec", "-T", "web", "python", "manage.py", "migrate", "--noinput")
        print("[S05] Running configuration and real PostgreSQL integration tests.", flush=True)
        tests = compose("exec", "-T", "web", "python", "manage.py", "test", "core.tests", "accounting.tests_integration",
                        "--settings=core.settings.test", "--verbosity=2")
        count = test_count(tests)
        for _ in range(2):
            compose("exec", "-T", "web", "python", "manage.py", "seed_development_data")
        seeded = json.loads(compose("exec", "-T", "web", "python", "manage.py", "probe_development_database").stdout)
        check_probe(seeded, markers=True)
        address = compose("port", "web", "8000").stdout.strip()
        assert address.startswith("127.0.0.1:"), "Expected loopback web address"
        with urlopen(Request("http://" + address + "/login/", headers={"Accept-Language": "en-US,en"}), timeout=10) as response:
            assert response.status == 200 and response.headers["Content-Language"] == "el"
            assert "Όνομα χρήστη" in response.read().decode("utf-8")
        container = compose("ps", "--quiet", "web").stdout.strip()
        image_id = run(["docker", "inspect", "--format", "{{.Image}}", container], environment=environment).stdout.strip()
        print("[S05] Recreating containers without deleting the volume and checking persisted markers.", flush=True)
        compose("down")
        compose("up", "--detach", "--no-build", "--wait", "--wait-timeout", "180")
        after = json.loads(compose("exec", "-T", "web", "python", "manage.py", "probe_development_database").stdout)
        check_probe(after, markers=True)
        assert after["synthetic_markers"] == seeded["synthetic_markers"]
        assert after["applied_migrations"] == migrated["applied_migrations"]
        return {"mode": "docker-compose", "status": "Verified", "docker_build_run": True,
                "docker_restart_persistence_verified": True, "native_restart_persistence_verified": False,
                "postgresql_version_num": after["postgresql_version_num"], "applied_migrations": after["applied_migrations"],
                "synthetic_markers": after["synthetic_markers"], "tests_passed": count,
                "greek_http_login_verified": True, "development_image_id": image_id,
                "cleanup": "Only the verifier's generated project containers/volume are removed; the normal dev stack is untouched."}
    finally:
        if owned:
            compose("down", "--volumes", "--remove-orphans")


def native_verification(bin_dir, directory, runtime_python):
    """Supplementary real DB proof; deliberately cannot pass the Docker gate."""
    bin_dir = bin_dir.resolve()
    version = run([bin_dir / "postgres", "--version"]).stdout.strip()
    assert re.search(r"PostgreSQL\) 17\.", version), "Native PostgreSQL 17 binaries required"
    password = secrets.token_urlsafe(32)
    HIDDEN_VALUES.add(password)
    password_file = directory / "pg-password"
    descriptor = os.open(password_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(password + "\n")
    data = directory / "pg-data"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    run([bin_dir / "initdb", "-D", data, "--username=accounting_platform", "--encoding=UTF8", "--locale=C.UTF-8",
         "--auth=scram-sha-256", "--pwfile", password_file])
    environment = fresh_environment()
    environment.update({"DJANGO_SETTINGS_MODULE": "core.settings.local", "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
                        "DJANGO_ENV_FILE": str(directory / "absent-env"), "DB_NAME": "s05_verification",
                        "DB_USER": "accounting_platform", "DB_PASSWORD": password, "DB_HOST": "127.0.0.1", "DB_PORT": str(port),
                        "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": "accounting_platform", "PGPASSWORD": password})
    # All connections use authenticated loopback TCP; no Unix socket is needed.
    options = shlex.join(["-h", "127.0.0.1", "-p", str(port), "-k", ""])

    def start():
        log = directory / "postgres.log"
        try:
            run([bin_dir / "pg_ctl", "-D", data, "-l", log, "-o", options, "-w", "start"])
        except RuntimeError as error:
            diagnostic = redact(log.read_text()[-6000:], environment) if log.exists() else "No server log was created."
            raise RuntimeError(str(error) + "\n" + diagnostic) from None

    def manage(*arguments):
        return run([runtime_python, "manage.py", *arguments], environment=environment)

    running = False
    try:
        start(); running = True
        run([bin_dir / "createdb", "s05_verification"], environment=environment)
        before = json.loads(manage("probe_development_database").stdout)
        check_probe(before, empty=True)
        print("[S05] Applying the complete migration history to native PostgreSQL 17.", flush=True)
        manage("migrate", "--noinput")
        migrated = json.loads(manage("probe_development_database").stdout); check_probe(migrated)
        manage("migrate", "--noinput")
        tests = manage("test", "core.tests", "accounting.tests_integration", "--settings=core.settings.test", "--verbosity=2")
        count = test_count(tests)
        for _ in range(2):
            manage("seed_development_data")
        seeded = json.loads(manage("probe_development_database").stdout); check_probe(seeded, markers=True)
        run([bin_dir / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"]); running = False
        start(); running = True
        after = json.loads(manage("probe_development_database").stdout); check_probe(after, markers=True)
        assert after["synthetic_markers"] == seeded["synthetic_markers"]
        assert after["applied_migrations"] == migrated["applied_migrations"]
        return {"mode": "native-postgresql17", "status": "Prepared", "docker_build_run": False,
                "docker_restart_persistence_verified": False, "native_restart_persistence_verified": True,
                "postgresql_version_num": after["postgresql_version_num"], "postgresql_binary_version": version,
                "applied_migrations": after["applied_migrations"], "synthetic_markers": after["synthetic_markers"],
                "tests_passed": count, "greek_http_login_verified": False,
                "blocker": "A local Docker Engine is unavailable here. Run default Docker verification with --record before S06."}
    finally:
        if running:
            run([bin_dir / "pg_ctl", "-D", data, "-m", "fast", "-w", "stop"])


def record_verified(report, report_path):
    if report["status"] != "Verified" or not report["docker_restart_persistence_verified"]:
        raise RuntimeError("Only successful Docker verification may record S05 as Verified.")
    with (RECORDS / "steps.csv").open(newline="", encoding="utf-8") as stream:
        steps = list(csv.DictReader(stream))
    step = next(row for row in steps if row["step_id"] == "S05")
    step.update(status="Verified", blocker="", next_step="S06",
                manual_acceptance="Isolated local Docker build, migration and volume persistence verified; release acceptance remains Pending")
    with (RECORDS / "steps.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=steps[0], lineterminator="\n"); writer.writeheader(); writer.writerows(steps)
    path = RECORDS / "state.md"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"Updated .*?Current step:.*?\n", f"Updated {report['verified_at'][:10]}. Current step: **S05 Verified — local Docker/PostgreSQL environment**. Next step: **S06**.\n", text, count=1)
    text = re.sub(r"<!-- S05-RESULT -->.*?<!-- /S05-RESULT -->",
                  "<!-- S05-RESULT -->\nLocal Docker build, empty-database migrations, focused/PostgreSQL tests and persisted markers after container recreation are Verified. See evidence/S05-verification.json. S06 is eligible.\n<!-- /S05-RESULT -->", text, flags=re.S)
    path.write_text(text, encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path, help="Supplementary real-PG17 checks; does not verify Docker")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--record", action="store_true", help="Record a successful Docker gate in evidence, steps and state")
    args = parser.parse_args()
    if args.record and args.native_bin:
        parser.error("Native mode cannot record the Docker gate as Verified.")
    for path in ["accounting/models.py", "accounting/views.py", *[str(p.relative_to(ROOT)) for p in (ROOT / "accounting/migrations").glob("*.py")]]:
        assert (ROOT / path).read_bytes() == subprocess.check_output(["git", "show", f"{S04}:{path}"], cwd=ROOT), path + " changed"
    if not args.native_bin:
        require_local_docker()
    with tempfile.TemporaryDirectory(prefix="accounting-s05-") as temp:
        directory = Path(temp)
        env_file = directory / "env"; create_local_env(env_file)
        HIDDEN_VALUES.update(line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                             if line.startswith(("DJANGO_SECRET_KEY=", "DB_PASSWORD=")))
        # Port zero asks Docker for an unused loopback port in the isolated verifier.
        with env_file.open("a") as stream:
            stream.write("WEB_PORT=0\n")
        project = "accounting-s05-check-" + secrets.token_hex(6)
        config = compose_config(env_file, project)
        print("[S05] Installing isolated, hash-checked maintenance tools.", flush=True)
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
            runtime_python = directory / "runtime/bin/python"
            run([runtime_python, *install, ROOT / "requirements.txt"])
            result = native_verification(args.native_bin, directory, runtime_python)
        else:
            result = docker_verification(env_file, project)
        scan = json.loads(run([tools_python, ROOT / "tools/scan_secrets.py"]).stdout)
        assert scan["unreviewed_findings"] == 0
    report = {"step": "S05", "verified_at": datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
              "source_reference_commit": S04, **result, "compose": config, "secret_scan": scan,
              "dependency_locks_reproduced": True, "compiled_catalog_in_sync": True,
              "original_models_views_migrations_unchanged": True, "application_tests_run": True,
              "database_backed_login_verified": True,
              "database_or_migration_execution": True, "real_data_imported": False, "google_cloud_resources_created": False,
              "full_requirement_acceptance": "Pending"}
    report_path = args.report or RECORDS / "evidence/S05-verification.json"
    if args.record:
        record_verified(report, report_path)
    elif args.report:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
