# S05 local development

S05 supplies a local Django/PostgreSQL 17 stack. It uses the S04 Greek settings and the original migration history. The production image, Gunicorn, readiness endpoints and delivery workflow belong to S07. The Google Cloud VM is needed at S08, after S07.

## Prerequisites

- A full Git checkout on Linux x86_64/glibc, matching the S03 dependency target.
- Python 3.10+ with `venv` for the host-side helpers/verifier. The application uses the pinned CPython 3.12.16 inside its image.
- A running **local** Docker Engine with the Compose plugin supporting `up --wait` and `config --format json`. Docker Desktop may supply the local engine. Remote Docker contexts are deliberately rejected.
- Download access to the official Docker images, Debian packages, PyPI and the managed CPython distribution used by verification.
- An unused local port 8000, or `WEB_PORT=8001` in the generated `.env`.

The checked Compose client was 5.7.0; use `docker compose version` to inspect yours. The verifier checks actual configuration and execution rather than assuming a version string proves compatibility.

## Start and create an administrator

Run these commands from the repository root:

```bash
python3 tools/dev.py up
python3 tools/dev.py admin
```

Open [http://localhost:8000/login/](http://localhost:8000/login/) and use the administrator you just created. The interface remains Greek even when the browser requests English. Choose development-only administrator credentials interactively; no default administrator or password is shipped.

The `up` command generates a private `.env` with random local credentials if the file is absent. It never overwrites an existing file or prints its contents. It builds the development image, waits for PostgreSQL, applies pending migrations and starts Django's development server. No client records, synthetic fixtures or database dumps are loaded by startup.

Keep the generated `.env` across restarts. PostgreSQL initialization variables apply only to a new volume: regenerating `DB_PASSWORD` does not change a password in an existing cluster. Back up any wanted development data before making deliberate credential or volume changes. `.env`, dumps and runtime data remain excluded from Git and the build context.

## Daily commands

| Command | Result |
| --- | --- |
| `python3 tools/dev.py up` | Build and start; apply migrations; wait for the local web service |
| `python3 tools/dev.py admin` | Interactively create a development superuser |
| `python3 tools/dev.py migrate` | Reapply pending migrations explicitly; repeated execution is safe |
| `python3 tools/dev.py seed` | Explicitly create/verify two clearly labelled synthetic S05 records |
| `python3 tools/dev.py test` | Run configuration/locale tests and PostgreSQL integration tests |
| `python3 tools/dev.py status` | Show service state and the published local web port |
| `python3 tools/dev.py logs` | Show the most recent local service logs |
| `python3 tools/dev.py config` | Validate Compose quietly without printing resolved secrets |
| `python3 tools/dev.py down` | Stop and remove containers/network while retaining the database volume |

Source directories are mounted read-only into the development container; Django autoreloads Python edits. Rebuild with `up` after dependency or image changes. Translation-source changes still require the S04 maintenance-tool catalog compilation procedure; commit both the reviewed PO and compiled MO.

The seed is a management command, separate from migrations. It uses AFM `000000000`, `ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S05` and `ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S05`, with an opening balance of `1234.56`. It is atomic, repeats without duplicates, refuses another settings profile and refuses to overwrite conflicting data. These are explicitly synthetic markers, not an approved financial fixture or a legacy import. The focused PostgreSQL tests use a separate Django test database and roll back their records.

## Ports, images and data

The web port binds only to `127.0.0.1`; PostgreSQL publishes **no host port**. Django connects to the Compose service `db:5432`. `tools/dev.py` strips inherited `DB_*`, `DJANGO_*` and Compose interpolation variables so the explicit local `.env` determines this stack. It preserves the selected local Docker context and rejects remote endpoints. Use `config` rather than printing a resolved Compose configuration containing credentials.

The official Python 3.12.16 and PostgreSQL 17.11 images are pinned by manifest digest in [image-pins.json](../../docker/image-pins.json), with the same references in the Dockerfile and Compose definition. The development application process is configured as UID/GID 10001. Runtime Python packages install from the existing hash-checked lock; the runtime lock is unchanged. The local database owner can create Django's temporary test database; production database privileges are a later deployment concern.

The default project is `accounting-platform-dev`; its new named volume is `accounting-platform-dev_postgres17_data`. This deliberately does not reuse the old PostgreSQL 15 `postgres_data` volume. **Never point PostgreSQL 17 at the old PostgreSQL 15 data directory.** Keep the legacy volume untouched; the controlled logical export/import, ownership mapping and reconciliation rehearsal is S25. No dump mount or startup import is included.

`down` preserves the volume. Avoid adding `--volumes` to normal shutdown commands when you want to retain development data. Changing the Compose project name selects a different volume and may make existing data appear absent.

## Completion verification

On your local computer, run:

```bash
python3 tools/verify_s05.py --record
```

This is a separate, disposable check. It generates a unique `accounting-s05-check-*` project, private credentials and an unused loopback port. It refuses to adopt an existing project, builds the development image, starts a fresh PostgreSQL volume and probes the empty database **before** the entrypoint can migrate it. It then applies all migrations, reruns them, runs the focused/integration tests, explicitly seeds twice and checks the Greek HTTP login page. Finally it removes and recreates the containers with the same volume, checks the persisted record identities/values and migration history, and removes only its own temporary containers/network/volume. The normal development stack is not selected.

The verifier also checks both dependency locks, the compiled catalog, original models/views/migration identity, safe Compose port/volume settings and the offline source/history secret scan. It installs maintenance tools in a disposable environment. Network downloads and an actual local Docker Engine are required; configuration parsing alone cannot pass the completion gate.

Only successful Docker verification with `--record` promotes S05 to **Verified** in:

- `docs/implementation/evidence/S05-verification.json`
- `docs/implementation/steps.csv`
- `docs/implementation/state.md`

After a successful run, commit these three evidence/state files and push the S05 branch. A failed run exits nonzero and does not promote the step. If a run is forcibly interrupted, inspect its printed/generated project identity before manually removing anything; do not use broad volume-pruning commands.

## Evidence supplied with this step

The implementation workspace has a Docker client and Compose, but **no Docker Engine**. Actual Compose configuration parsing passed. Supplementary checks ran against an empty, native PostgreSQL 17.11 cluster using authenticated loopback TCP: all 20 migrations (including both original accounting migrations), an idempotent second migration run, 35 configuration/integration tests, repeatable synthetic seeding and persistence after a real PostgreSQL stop/start passed. PostgreSQL packages were checked against hashes in the official PGDG HTTPS repository index; [native provenance](evidence/S05-native-provenance.json) records their identities.

The supplied [S05 evidence](evidence/S05-verification.json) therefore records **Prepared**, with native persistence true and Docker build/recreation false. Native proof does not demonstrate a container build or a container-volume lifecycle. Run the Docker verifier above before proceeding to S06. For an explicitly supplementary native check, `--native-bin /absolute/path/to/postgresql/17/bin --report /path/to/report.json` is available; it cannot be combined with `--record` and still requires the Compose client for configuration validation.

No original model, view or migration change was needed for PostgreSQL 17. No real data, live connector, cloud resource or full financial acceptance was exercised. All 85 application acceptance statuses remain Pending. Existing financial defects are intentionally captured at S06 rather than silently changed here.

## Official references

- [Docker Compose startup dependencies](https://docs.docker.com/compose/how-tos/startup-order/)
- [Official Python image](https://hub.docker.com/_/python)
- [Official PostgreSQL image and volume conventions](https://hub.docker.com/_/postgres)
- [PostgreSQL supported major versions and upgrade boundaries](https://www.postgresql.org/support/versioning/)
- [PostgreSQL Debian repository](https://www.postgresql.org/download/linux/debian/)
