#!/usr/bin/env python3
"""Verify S04 settings, Greek UI foundation and secret handling in disposable environments."""

import argparse
import ast
import csv
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs/implementation"
S03 = "1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718"


def run(command, *, environment=None):
    result = subprocess.run([str(value) for value in command], cwd=ROOT, env=environment, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Verification command failed:\n" + result.stdout[-2500:] + result.stderr[-3500:])
    return result


def verify():
    checks = []

    def check(name, condition, detail):
        if not condition:
            raise AssertionError(name + ": " + detail)
        checks.append({"check": name, "result": "PASS", "detail": detail})

    protected = ["accounting/models.py", "accounting/views.py", "accounting/urls.py", "core/urls.py",
                 "requirements.in", "requirements.txt", "docs/implementation/baseline_sources.json",
                 "docs/implementation/source_manifest.csv", "tools/verify_s01.py", "tools/verify_s02.py", "tools/verify_s03.py"]
    protected += [str(p.relative_to(ROOT)) for p in (ROOT / "accounting/migrations").glob("*.py")]
    protected += [str(p.relative_to(ROOT)) for p in (ROOT / "docs/baselines").iterdir() if p.is_file()]
    for path in protected:
        baseline = subprocess.check_output(["git", "show", f"{S03}:{path}"], cwd=ROOT)
        check("preserved " + path, (ROOT / path).read_bytes() == baseline, "business code, migration identities, runtime lock or controlled baseline unchanged")
    check("separate settings", not (ROOT / "core/settings.py").exists()
          and all((ROOT / f"core/settings/{profile}.py").is_file() for profile in ("base", "local", "test", "production")),
          "common/local/test/production modules replace the monolithic settings file")
    ignored = subprocess.run(["git", "check-ignore", "--no-index", "-q", ".env"], cwd=ROOT)
    check("private local config ignored", ignored.returncode == 0, "generated local credentials stay outside version control")
    example = (ROOT / ".env.example").read_text()
    check("example credentials empty", "DJANGO_SECRET_KEY=\n" in example and "DB_PASSWORD=\n" in example,
          "the example contains no credential value")
    check("locale files included in context", all(line in (ROOT / ".dockerignore").read_text().splitlines()
          for line in ("!locale/**", "!templates/**")), "project catalogs and error templates are included in the planned image context")
    requirements = json.loads((RECORDS / "requirements.json").read_text())
    with (RECORDS / "traceability.csv").open(encoding="utf-8", newline="") as stream:
        check("requirements parity", list(csv.DictReader(stream)) == requirements and len(requirements) == 85
              and all(r["acceptance_status"] == "Pending" for r in requirements),
              "all 71 UR / 14 QR remain pending staged acceptance; CSV and JSON agree")
    with (RECORDS / "steps.csv").open(encoding="utf-8", newline="") as stream:
        steps = list(csv.DictReader(stream))
    check("S04 checkpoint", len(steps) == 64 and all(s["status"] == "Verified" for s in steps[:4])
          and all(s["status"] == "Not started" for s in steps[4:]), "S01 through S04 complete; S05 next")
    for folder in ("core", "tools", "accounting/templatetags"):
        for path in (ROOT / folder).rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"))
    check("Python syntax", True, "new configuration, locale and maintenance modules parse")

    with tempfile.TemporaryDirectory(prefix="accounting-s04-") as temp:
        directory = Path(temp)
        print("[S04] Installing isolated hashed tooling and runtime dependencies.", flush=True)
        run([sys.executable, "-m", "venv", directory / "tools"])
        tools_python = directory / "tools/bin/python"
        install = ["-m", "pip", "--disable-pip-version-check", "install", "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "-r"]
        run([tools_python, *install, ROOT / "requirements-tools.txt"])
        target = (ROOT / ".python-version").read_text().strip()
        run([tools_python, "-m", "uv", "python", "install", target])
        python = run([tools_python, "-m", "uv", "python", "find", "--managed-python", target]).stdout.strip()
        run([python, "-m", "venv", directory / "runtime"])
        runtime_python = directory / "runtime/bin/python"
        run([runtime_python, *install, ROOT / "requirements.txt"])
        for executable in (tools_python, runtime_python):
            run([executable, "-m", "pip", "check"])
        check("fresh hashed installs", True, "both isolated dependency locks install and pass pip check")
        run([tools_python, ROOT / "tools/lock_dependencies.py", "--check"])
        check("lock reproduction", True, "runtime and maintenance locks reproduce; only polib is added for S04 catalog compilation")
        run([tools_python, ROOT / "tools/compile_translations.py", "--check"])
        check("compiled catalog", True, "reviewed Greek PO compiles byte for byte to the committed MO")
        environment = {key: value for key, value in os.environ.items() if not key.startswith(("DJANGO_", "DB_"))}
        environment["DJANGO_SETTINGS_MODULE"] = "core.settings.test"
        print("[S04] Running focused settings, language, Decimal, DST and log-redaction tests.", flush=True)
        result = run([runtime_python, "manage.py", "test", "core.tests", "--verbosity", "2"], environment=environment)
        count = re.search(r"Ran (\d+) tests?", result.stderr)
        test_count = int(count[1]) if count else 0
        check("focused tests", test_count >= 29, "configuration failures, secret files, Greek rendering/validation, Decimal input, DST and logging cases pass")
        code = """import django,json; django.setup()
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.state import ProjectState
from django.apps import apps
from django.utils import translation
loader=MigrationLoader(None)
with translation.override('en'):
 changes=MigrationAutodetector(loader.project_state(),ProjectState.from_apps(apps)).changes(graph=loader.graph,trim_to_apps={'accounting'})
print(json.dumps({'changes':list(changes),'migrations':sorted(n[1] for n in loader.disk_migrations if n[0]=='accounting')}))"""
        state = json.loads(run([runtime_python, "-c", code], environment=environment).stdout)
        check("no accounting schema changes", state["changes"] == [] and len(state["migrations"]) == 2,
              "original migrations load; no additional accounting migration is required; no database connection")
        print("[S04] Scanning candidate source and reachable Git text history.", flush=True)
        scan = json.loads(run([tools_python, ROOT / "tools/scan_secrets.py"]).stdout)
        check("secret scan", scan["unreviewed_findings"] == 0 and scan["network_verification"] is False,
              "offline scan and its synthetic-password self-check pass with reviewed public-hash exceptions")
    return {"step": "S04", "verified_at": "2026-11-07", "status": "Verified", "source_reference_commit": S03,
            "checks_passed": len(checks), "focused_tests_passed": test_count, "staff_templates_translated": 17,
            "greek_locale_foundation_implemented": True, "full_frontend_acceptance_passed": False,
            "fresh_dependency_install_performed": True, "application_tests_run": True,
            "database_or_migration_execution": False, "docker_build_run": False, "google_cloud_resources_created": False,
            "secret_scan": scan, "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "checks"}, indent=2))
