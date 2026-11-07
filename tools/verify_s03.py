#!/usr/bin/env python3
"""Verify S03 in disposable environments; downloads pinned tools/Python/wheels if needed.

Requires Git, a Python with venv support, Linux x86_64/glibc and package-index access.
Does not start the application, connect to PostgreSQL or execute migrations.
"""

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs/implementation"
S02 = "a6a251b434bce295ec04240a63e33a656dc7f92e"

RUNTIME_PROBE = r'''
import ast, importlib, importlib.metadata, json, platform, sys
from pathlib import Path
import django, psycopg
from django.conf import settings
tree = ast.parse(Path('core/settings.py').read_text())
apps = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == 'INSTALLED_APPS' for t in n.targets))
settings.configure(INSTALLED_APPS=apps, USE_TZ=True,
                   DATABASES={'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': 's03_dependency_probe'}})
django.setup()
for name in ['accounting.models', 'accounting.forms', 'accounting.views', 'accounting.urls',
             'django.db.backends.postgresql.base']:
    importlib.import_module(name)
from django.db.migrations.loader import MigrationLoader
loader = MigrationLoader(None)
leaves = [n for n in loader.graph.leaf_nodes() if n[0] == 'accounting']
state = loader.project_state(leaves)
normalise = lambda name: name.lower().replace('_', '-')
packages = {normalise(d.metadata['Name']): d.version for d in importlib.metadata.distributions()
            if normalise(d.metadata['Name']) not in {'pip', 'setuptools'}}
print(json.dumps({'python': platform.python_version(), 'packages': packages,
    'driver_implementation': psycopg.pq.__impl__,
    'migration_nodes': sorted(n[1] for n in loader.disk_migrations if n[0] == 'accounting'),
    'historical_models': sorted(m.__name__ for m in state.apps.get_app_config('accounting').get_models()),
    'database_connected': False}))
'''


def run(command, cwd=ROOT):
    result = subprocess.run([str(v) for v in command], cwd=cwd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {command[0]}\n" + result.stdout[-2500:] + result.stderr[-2500:])
    return result.stdout


def load_json(name):
    return json.loads((RECORDS / name).read_text(encoding="utf-8"))


def lock_packages(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    packages = {}
    for logical in text.replace("\\\n", " ").splitlines():
        line = logical.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([a-z0-9-]+)==([^\s]+)(?:\s+--hash=sha256:[a-f0-9]{64})+", line)
        if not match:
            raise AssertionError(f"Non-pinned or unhashed requirement in {name}")
        if match[1] in packages:
            raise AssertionError(f"Duplicate package in {name}")
        packages[match[1]] = match[2]
    return packages


def verify():
    checks = []

    def check(name, condition, detail):
        if not condition:
            raise AssertionError(f"{name}: {detail}")
        checks.append({"check": name, "result": "PASS", "detail": detail})

    check("verification platform", platform.system() == "Linux" and platform.machine() == "x86_64" and platform.libc_ver()[0] == "glibc",
          "the locked deployment target is Linux x86_64/glibc")
    policy = load_json("dependency_policy.json")
    target_python = (ROOT / ".python-version").read_text().strip()
    runtime_lock = lock_packages("requirements.txt")
    tools_lock = lock_packages("requirements-tools.txt")
    check("minimal runtime", len(runtime_lock) == policy["runtime_package_count"] == 7
          and {d["name"] for d in policy["runtime_direct"]} == {"django", "gunicorn", "psycopg"},
          "three declared direct runtime dependencies, seven locked packages")
    check("supported selections recorded", target_python == policy["python"] == "3.12.16"
          and all(runtime_lock[d["name"]] == d["version"] for d in policy["runtime_direct"]),
          "selected versions agree with the dated official-source review")
    check("maintenance tools isolated", tools_lock["uv"] == "0.13.7" and tools_lock["detect-secrets"] == "1.5.0"
          and not ({"uv", "detect-secrets", "requests", "pyyaml"} & set(runtime_lock)),
          "locking and secret scanning do not enter the runtime environment")
    for row in csv.DictReader((RECORDS / "source_manifest.csv").open(encoding="utf-8")):
        path = row["working_path"]
        if path and path not in {".gitignore", "requirements.txt"}:
            check("source " + path, hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == row["working_sha256"],
                  "legacy application/configuration bytes preserved")
    for path in [*sorted((ROOT / "docs/baselines").iterdir()), RECORDS / "baseline_sources.json", RECORDS / "source_manifest.csv"]:
        if path.is_file():
            relative = str(path.relative_to(ROOT))
            old = subprocess.check_output(["git", "show", f"{S02}:{relative}"], cwd=ROOT)
            check("baseline " + relative, path.read_bytes() == old, "controlled historical baseline unchanged")
    for name in ("verify_s01.py", "verify_s02.py"):
        check("historical verifier " + name,
              (ROOT / "tools" / name).read_bytes() == subprocess.check_output(["git", "show", f"{S02}:tools/{name}"], cwd=ROOT),
              "earlier snapshot verifiers are not weakened")
    for name in (".env", ".env.production", ".venv/pyvenv.cfg", ".venv-tools/pyvenv.cfg", "media/client.pdf",
                 "private/document.pdf", "sessions/session.dat", "backup.sql", "backup.sql.gz", "db.dump", "db.sqlite3",
                 "secrets/service-account.json", "service-account-preview.json", "runtime.key"):
        result = subprocess.run(["git", "check-ignore", "--no-index", "-q", name], cwd=ROOT)
        check("Git excludes " + name, result.returncode == 0, "runtime/private input excluded from version control")
    for name in (".env.example", "requirements.txt", "accounting/migrations/0001_initial.py"):
        result = subprocess.run(["git", "check-ignore", "--no-index", "-q", name], cwd=ROOT)
        check("Git permits " + name, result.returncode == 1, "controlled source/configuration example remains trackable")
    dockerignore = (ROOT / ".dockerignore").read_text()
    check("Docker context policy", dockerignore.splitlines()[1] == "**"
          and all(p in dockerignore.splitlines() for p in ["!requirements.txt", "!core/**/*.py", "!accounting/**/*.py", "**/.env", "**/private/**", "**/media/**"]),
          "static review: runtime-input allowlist followed by sensitive-file exclusions; actual build is S07")
    tracked = run(["git", "ls-files", "-z"]).split("\0")
    forbidden = [p for p in tracked if p and (re.search(r"(^|/)(venv|\.venv[^/]*|media|uploads|sessions|private|secrets|backups)/", p)
                 or re.search(r"\.(sql|dump|sqlite3|pem|key|whl|zip)(\.|$)", p))]
    check("tracked payload clean", not forbidden, "no tracked environment, dump, sessions, uploads or private-key payload")
    reqs = load_json("requirements.json")
    with (RECORDS / "traceability.csv").open(encoding="utf-8", newline="") as stream:
        check("requirement parity", list(csv.DictReader(stream)) == reqs, "CSV and JSON agree")
    check("requirements remain pending", len(reqs) == 85 and all(r["acceptance_status"] == "Pending" for r in reqs)
          and next(r for r in reqs if r["requirement_id"] == "UR-LOC-01")["definition_status"] == "Confirmed",
          "71 UR / 14 QR retained; Greek requirement confirmed; application acceptance unrun")
    with (RECORDS / "steps.csv").open(encoding="utf-8", newline="") as stream:
        steps = list(csv.DictReader(stream))
    check("step checkpoint", len(steps) == 64 and all(s["status"] == "Verified" for s in steps[:3])
          and all(s["status"] == "Not started" for s in steps[3:]), "S01–S03 complete; S04 is next")
    for path in (ROOT / "tools").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"))
    check("tool syntax", True, "all maintenance Python scripts parse")

    with tempfile.TemporaryDirectory(prefix="accounting-s03-") as temp:
        directory = Path(temp)
        print("[S03] Installing the hashed maintenance lock in a disposable environment.", flush=True)
        run([sys.executable, "-m", "venv", directory / "tools"])
        tools_python = directory / "tools/bin/python"
        install_args = ["-m", "pip", "--disable-pip-version-check", "install", "--require-hashes", "--only-binary=:all:",
                        "--index-url", "https://pypi.org/simple", "-r"]
        run([tools_python, *install_args, ROOT / "requirements-tools.txt"])
        run([tools_python, "-m", "pip", "check"])
        check("fresh tools install", True, "requirements-tools.txt installs with enforced hashes; pip check passes")
        print("[S03] Selecting the pinned Python and installing the hashed runtime lock.", flush=True)
        run([tools_python, "-m", "uv", "python", "install", target_python])
        selected_python = run([tools_python, "-m", "uv", "python", "find", "--managed-python", target_python]).strip()
        run([selected_python, "-m", "venv", directory / "runtime"])
        runtime_python = directory / "runtime/bin/python"
        run([runtime_python, *install_args, ROOT / "requirements.txt"])
        run([runtime_python, "-m", "pip", "check"])
        runtime = json.loads(run([runtime_python, "-c", RUNTIME_PROBE]))
        check("fresh runtime install", runtime["python"] == target_python and runtime["packages"] == runtime_lock,
              "fresh CPython environment contains exactly the seven locked runtime packages; pip check passes")
        check("PostgreSQL driver", runtime["driver_implementation"] == "binary", "Psycopg binary implementation and Django backend import without a database connection")
        check("migration compatibility", runtime["migration_nodes"] == ["0001_initial", "0002_transaction_agreement_alter_agreement_status_and_more"]
              and runtime["historical_models"] == ["Agreement", "CashAccount", "Category", "Entity", "Transaction"],
              "original migration graph loads and renders all five historical models; no migration execution")
        run([runtime_python, "-m", "gunicorn", "--check-config", "wsgiref.simple_server:demo_app"])
        check("Gunicorn import/configuration", True, "selected WSGI server passes a standard-library demo configuration check; no application server started")
        print("[S03] Checking lock reproduction and scanning candidate/history text for secrets.", flush=True)
        run([tools_python, ROOT / "tools/lock_dependencies.py", "--check"])
        check("lock reproduction", True, "both locks recompile byte for byte from their declared inputs")
        secret_scan = json.loads(run([tools_python, ROOT / "tools/scan_secrets.py"]))
        check("secret scan", secret_scan["unreviewed_findings"] == 0 and secret_scan["reviewed_non_secret_matches"] > 0
              and secret_scan["network_verification"] is False and bool(secret_scan["scanner_self_check"]),
              "offline candidate/history scan passes; synthetic detection self-check passes; public hashes reviewed")
    return {"step": "S03", "verified_at": "2026-11-07", "status": "Verified", "checks_passed": len(checks),
            "source_reference_commit": S02, "fresh_install_performed": True, "runtime": runtime,
            "secret_scan": secret_scan, "application_tests_run": False, "database_or_migration_execution": False,
            "docker_build_run": False, "greek_frontend_implemented": False, "google_cloud_resources_created": False,
            "checks": checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2))
