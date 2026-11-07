# S03 — controlled dependencies and source packaging

Reviewed 2026-11-07. [dependency_policy.json](dependency_policy.json) records the selected versions, deployment target and official references. The baseline remains Django 5.2 LTS, Python 3.12, PostgreSQL and templates/Bootstrap. Greek frontend delivery remains required by CR-001; this step changes no screens.

## Runtime selection

| Component | Selection | Reason |
| --- | --- | --- |
| Python | CPython 3.12.16 | Current reviewed 3.12 security patch; pinned in `.python-version` |
| Django | 5.2.19 | Supported 5.2 LTS patch; extended support through April 2028 |
| PostgreSQL driver | Psycopg 3.3.8 with binary distribution | Supported Django backend; no application code imports the old psycopg2 driver directly |
| WSGI server | Gunicorn 26.2.0 | Linux WSGI runtime; actual application configuration is S07 |
| Database server | Planned PostgreSQL 17 | Server image/patch and migration execution remain S05/S07 work |

The old 364-entry workstation freeze is replaced by three direct runtime requirements in `requirements.in` and seven exact packages with SHA-256 distribution hashes in `requirements.txt`. Initial resolution explicitly upgraded transitive dependencies instead of retaining old freeze preferences. The current transitive set is asgiref 3.13.0, sqlparse 0.6.1, typing-extensions 4.16.0 and psycopg-binary 3.3.8.

Use the lock for installation; do not install the `.in` file in a deployed environment. The verified target is **Linux x86_64/glibc with CPython 3.12**, matching the initial Compute Engine candidate. Other platforms and architectures have not been verified. Binary Psycopg bundles client libraries, so library security updates require a reviewed driver upgrade; this is not a separate PostgreSQL server installation.

## Fresh verification

From a full Git checkout with a Python that supports `venv` (Python 3.10+ for bootstrapping), run:

```bash
python3 tools/verify_s03.py
```

This creates disposable maintenance and runtime environments, installs the hash-checked maintenance lock, obtains managed CPython 3.12.16 through uv if missing, and installs the hash-checked runtime lock using wheels only. It requires network access to PyPI and the Python download host. It then runs dependency consistency checks, imports the application modules and PostgreSQL backend, renders the unchanged migration state, validates a standard-library Gunicorn demo configuration, reproduces both locks and scans source/history text for secrets. Temporary environments are removed afterward; uv's managed interpreter/cache may remain. No global Python packages are changed.

To record evidence, add `--report docs/implementation/evidence/S03-verification.json`. Historical S01/S02 verifiers belong to their tagged snapshots and are intentionally unchanged. This S03 verifier also checks the current step statuses, so later steps will have their own checks.

## Installing and maintaining dependencies

For a local runtime environment with CPython 3.12.16 already available:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.txt
.venv/bin/python -m pip check
```

This installs dependencies only; use the configuration and startup commands delivered in S04/S05 before running the application. The legacy settings still have deliberately blank credentials.

Keep maintenance tools in a separate environment:

```bash
python3 -m venv .venv-tools
.venv-tools/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements-tools.txt
.venv-tools/bin/python tools/lock_dependencies.py --check
.venv-tools/bin/python tools/scan_secrets.py
```

Edit the direct `.in` inputs for a feature, then run `tools/lock_dependencies.py` with the tooling environment's Python. Use `--upgrade` deliberately to review newer versions within the declared bounds. Commit the inputs and both regenerated locks together. Changing the lock tool itself also requires updating `requirements-tools.in` and the version assertion in the lock helper. Check current support/security releases before each dependency update; today's pins are not a perpetual security guarantee.

## Packaging and secrets

`.gitignore` excludes local environments, credentials, sessions, dumps, uploads, backups and generated output. `.dockerignore` starts with an exclusion of everything, then permits runtime source/templates/assets and later build scripts, with final sensitive-file exclusions. S03 checks this policy statically; the actual Docker build/context verification is S07. Extend the allowlist deliberately when new runtime inputs are introduced.

The [secret-scan policy](../security/README.md) explains the offline scan and exact reviewed public-hash exceptions. The scanner first proves it can detect an ephemeral synthetic password, then scans candidate text and unique historical Git blobs from local refs. Unknown findings fail. It never sends potential tokens to providers for verification. Binary documents are outside this heuristic text scan.

## Acceptance boundary

S03 demonstrates clean dependency installation, module/driver imports and migration deserialisation. It does not execute schema migrations, business tests, financial regressions, PostgreSQL queries, the production image or Greek UI acceptance. QR-02 and QR-14 remain Pending until their full checks run at later release gates. All existing application models, forms, views, templates and migration files are unchanged.
