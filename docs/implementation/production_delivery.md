# S07 production image and delivery checks

S07 supplies the production image, Gunicorn, data-free health endpoints, manifest static assets and a GitHub Actions delivery workflow. S04–S06 are verified prerequisites. The pushed S06 baseline is `53e453b59bda9e2a21cbea59a086ed7ae26a45bb`, including the user's Docker verification.

The implementation workspace has no Docker Engine. Native PostgreSQL/Gunicorn checks pass. The user's local image now builds, but verification stops at static export; the supplied [S07 evidence](evidence/S07-verification.json) remains **Prepared** until the complete Docker gate passes. Do not create the VM before that gate. All 85 application acceptance checks remain Pending; the 26 financial failures are still tracked for their corrective steps.

## Production artifact

The root [Dockerfile](../../Dockerfile) uses the existing digest-pinned Python 3.12.16 image and unchanged seven-package runtime lock. It collects static assets without a database or deployment credentials, then runs as UID/GID `10001:10001`. The default command is Gunicorn with [gunicorn.conf.py](../../gunicorn.conf.py): two sync workers, no reload, 30-second worker/graceful timeouts, temporary worker files in `/tmp` and no control socket. `GUNICORN_WORKERS` accepts 1–16; the provisional two-worker default is not a measured capacity claim.

The entrypoint only executes its command. It never migrates, imports fixtures, creates administrators or loads a dump automatically. The same image can run `python manage.py migrate --noinput` or another management command explicitly. Workers/scheduler reuse this command interface when their dependencies arrive at S26; no worker or scheduler is delivered now. Production defaults to `core.settings.production`, including required secrets, DEBUG false, explicit hosts, HTTPS redirects and secure cookies.

`core.settings.build` is strictly for `collectstatic`: it generates an ephemeral unused signing key and uses Django's dummy database backend. It cannot query a database and is never the runtime image default. The settings/profile conventions remain in [settings_and_locale.md](settings_and_locale.md).

## Controlled source and image identity

```bash
python3 tools/image.py build
```

Build from a clean **committed** checkout. The helper selects regular files from that exact Git commit using an explicit application/build allowlist, then sends a deterministic tar context to Docker. Untracked files, local `.env`, Git metadata, private directories, uploads, database dumps and credentials are excluded. Selected symbolic links and modified tracked files are rejected. `.dockerignore` provides a second exclusion layer. No runtime secret is a build argument. The offline source/history secret scan runs before the verifier builds.

The image is tagged `accounting-platform:<full-commit-sha>`. Its labels record the source commit and context digest; the verifier records the immutable Docker image ID. JSON metadata prefixes the revision with `git:` to distinguish a public commit identity from an opaque credential; the actual image tag/label use the raw SHA. An existing matching commit image is reused; a mismatched identity is rejected rather than overwritten. All migration, regression, HTTP, outage and static-export checks use that same image ID, with no Compose build directive. Build once for a commit, then promote the tested artifact. A registry digest is recorded when an image is actually published at deployment; a local image ID is not described as a registry digest.

A separate synthetic Git repository exercises the actual packer: tracked private files and untracked Python code stay out, dirty tracked source and selected symlinks are rejected, and repeated contexts are byte-identical. Docker verification additionally inserts an untracked canary, audits the running image file list and confirms the process UID. Synthetic packer checks alone are not evidence of a container build.

`--record` writes evidence after verification, so committing that evidence creates a later documentation commit. The recorded image revision remains the code commit that was actually built. CI builds once for its checked-out SHA and saves that tested image; do not replace the recorded identity with a later evidence commit's SHA.

## Health contract

| Endpoint | Success | Failure meaning |
| --- | --- | --- |
| `/health/live/` | HTTP 200, `{"status":"ok"}` | Process/request handling is unavailable; no database query is performed |
| `/health/ready/` | HTTP 200, `{"status":"ready"}` | PostgreSQL query failure returns HTTP 503, `{"status":"unavailable"}` |

Both accept GET/HEAD, validate the Host, disable caching and return no client data, credentials, versions or exception details. These are machine schema keys, not new human-facing English copy. Only these exact paths are exempt from the production HTTPS redirect so internal probes can use HTTP. Other application pages retain HTTPS redirects.

The image healthcheck calls readiness over container-local `127.0.0.1:8000`. Set `HEALTHCHECK_HOST` to a hostname present in `DJANGO_ALLOWED_HOSTS`; it defaults to `127.0.0.1`. Readiness tests database availability; it does not replace the explicit migration/release gate or future dependency checks. Connection establishment uses the S04 five-second timeout. Docker probes have an eight-second request timeout and ten-second process timeout; Gunicorn retains its worker timeout.

S07 verifies real PostgreSQL stop/start: readiness becomes 503, liveness stays 200 and readiness recovers. Local positive login checks simulate a trusted loopback forwarded scheme and inspect Greek content; they are not a TLS deployment. Gunicorn trusts forwarded scheme information only from loopback by default. S09 must configure and test the actual private Caddy connection, header overwrite and HTTPS boundary before enabling Django's proxy-header trust for deployment.

Gunicorn access logs include peer, method, path, status and duration. They omit queries, cookies, authorisation, referrers and user-agent headers, and use the existing redacting formatter. A synthetic query marker is checked against actual Gunicorn logs. Existing path identifiers are not a substitute for the later approved log-retention/access policy.

## Static files for Caddy

The build creates `/app/staticfiles` with `ManifestStaticFilesStorage`: 127 manifest entries and 255 files in the observed baseline. The native verification also checks admin pages reference hashed static URLs. No WhiteNoise or new runtime dependency is introduced; Gunicorn is not the static file server.

Export assets from the **same tested image** into a new host directory:

```bash
python3 tools/image.py static \
  --image accounting-platform:FULL_CODE_COMMIT_SHA \
  --output /absolute/path/to/static/FULL_CODE_COMMIT_SHA
```

Replace the uppercase placeholder with the source revision recorded by `image.py build` or verification JSON; `--image` also accepts the immutable `image_id`. Export starts a short-lived Python process in that image with networking disabled, a read-only root filesystem, no healthcheck and dropped capabilities. It needs no application credentials or database. Python streams `/app/staticfiles` as a binary tar archive through Docker's attached stdout; host Python owns the destination and Docker never receives a host output path.

[static_export.py](../../tools/static_export.py) validates paths, regular-file types, size/entry limits and manifest targets before publishing the completed staging directory. It rejects links, traversal and duplicate paths. Image UID/GID and modes are not restored: host directories are `0755` and files `0644`, including when the image directories are `0555`. Existing destinations, including dangling symlinks, are refused. Failures retain redacted Docker/exporter diagnostics and remove only the owned temporary container/staging files. S09 mounts the versioned host directory into Caddy read-only at `/srv/static` and routes `/static/*` to it. Keep the image and static export from the same release. Actual Caddy/TLS serving remains S09.

## Run the complete delivery gate

From a committed checkout with local Docker Engine/Compose and the S05 prerequisites:

```bash
python3 tools/verify_s07.py --record
```

The verifier first runs the standalone host export regressions in [test_image_export.py](../../tools/test_image_export.py). It then bootstraps hash-checked tools and pinned Python, reproduces both locks, checks the Greek catalog and scans source/history. It builds/reuses the commit image, creates a unique `accounting-s07-check-*` Compose project and an empty PostgreSQL 17 volume, probes before migration, explicitly migrates, and runs the strict 90-test application suite (64 passed, 26 known failures in this snapshot). Host export tests are separate from that application count. New errors, changed failure patterns, tracked skips or unexpected passes fail the command. Business models/forms/views/routes, migrations and dependency locks remain unchanged from S06.

The disposable [delivery Compose file](../../compose.delivery.yml) uses the immutable image ID, a read-only application filesystem, `/tmp` tmpfs, dropped capabilities and no-new-privileges. PostgreSQL has no host port. The web port uses an unused loopback port, preserving your normal port 8001 and development volume. Verification checks production settings, actual process UID/private-file exclusion, static export, Greek login/admin static references, HTTPS redirect, log query exclusion and database outage/recovery. It removes only its own containers/network/volume and retains the tested image for reuse/export.

Successful `--record` promotes S07 to **Verified** in the evidence JSON, steps and state. It then announces the **S08 Google Cloud VM checkpoint**. A failure does not promote the gate. `--report /path/report.json` saves a result without changing step state. Native `--native-bin /path/to/postgresql/17/bin --report /path/report.json` provides supplementary real PostgreSQL/Gunicorn proof and remains Prepared; it cannot be combined with `--record`.

The first user-side S07 attempt stopped during the `psycopg-binary` wheel download with a read timeout from files.pythonhosted.org, before application checks or the disposable database stack ran. Both Dockerfiles now give pip a 120-second socket timeout and five new-connection attempts while retaining HTTPS, pinned versions, binary wheels and hash verification. This does not upgrade pip or promise to resume incomplete downloads. Apply/commit this follow-up fix before retrying `python3 tools/verify_s07.py --record`: the builder uses committed source, so a host `PIP_DEFAULT_TIMEOUT` setting or an uncommitted Dockerfile edit does not change its build input. Existing successful Docker layers can be reused; no volume reset is needed. [Timeout-fix evidence](evidence/S07-download-timeout-fix.json) records the limited validation; the actual Docker gate remains pending until a complete successful run.

The next two user runs built the same immutable image and reached `docker cp` in static export. The old helper captured stderr without showing it, so the underlying Docker error is unconfirmed. The streamed replacement avoids both restoring restrictive image directory modes during copying and asking Docker to access a host temporary path. [Static-export fix evidence](evidence/S07-static-export-fix.json) records host regressions and the remaining Docker gate. No image/build input changes are needed for this fix.

After applying the static-export fix, the user's existing image can be verified again without rebuilding it:

```bash
python3 tools/verify_s07.py --record \
  --image sha256:68e1e362af3d7d22e59f57ed7b0c3014093737ab621009044964fcb3c9b9af2f
```

`--image` requires a clean committed checkout and a local image whose source-context digest exactly matches the current committed production inputs. It also checks repository/revision labels, architecture and non-root user, resolves the immutable image ID, and preserves the original image revision separately from the current `verification_revision`. A missing or mismatched image is refused; run without `--image` to build the current commit when needed. Every migration, test, health check and export still uses the selected image ID. Maintenance-tool installation/lock checks still run. Normal verification and CI continue to build/reuse a per-commit image by default. `--image` cannot be combined with native verification.

Django deployment checks run with production settings and generated synthetic credentials. There are zero errors and two explicitly reviewed warnings: `security.W005` (HSTS includeSubDomains) and `security.W021` (preload). Both remain disabled pending the actual S09 hostname/TLS policy; the warnings are recorded, not silenced. Any other warning fails verification. Live HTTPS, HSTS deployment, backup/restore and complete QR-02/QR-12/QR-14 acceptance remain Pending.

## GitHub Actions

[delivery.yml](../../.github/workflows/delivery.yml) runs on `main`, `step/**` pushes and pull requests, with manual dispatch available after the workflow is on the default branch. It uses Ubuntu 24.04 and immutable official action commits recorded in [ci-pins.json](../../docker/ci-pins.json). Repository permission is `contents: read`; checkout credentials are not persisted. There is no cloud/registry secret, live deployment, PR comment or external message action.

CI runs `tools/verify_delivery.py` without changing tracked records, uploads the JSON evidence and saves the tested image archive for later deployment. This continuing command discovers all current tests and follows reviewed registry outcomes as later steps add features or resolve defects; it permits planned model/migration changes. It shares the real image, health, migration, lock, secret-scan and static checks, while `verify_s07.py` remains the stricter historical snapshot gate. CI cannot rewrite historical step records. Evidence retention is 14 days; image retention is seven days. Image archives contain application/runtime files only, not verification credentials, client records, volumes or secrets. Load a downloaded tested archive with `docker image load --input accounting-platform-image.tar.gz`, confirm its recorded image ID, and promote it when deployment is authorised. Source packaging has been checked locally; GitHub workflow execution remains unrun until the branch is pushed.

Earlier verifiers remain historical snapshot tools. In particular, S06's exact 78-test snapshot remains unchanged; S07 uses the shared strict runner plus the 12 new health/configuration tests. Rebuild the normal development image after applying S07 so the configuration tests can read the new root Gunicorn file:

```bash
python3 tools/dev.py up
python3 tools/dev.py test
```

This retains the existing .env/port and database volume. The development Dockerfile now also copies gunicorn.conf.py; it still starts Django's development server. The daily strict suite discovers 90 tests. Known injected error-page/rollback and malformed-filter traces remain expected diagnostic output.

## Next checkpoint

**After S07 Docker verification passes, S08 is when you create/select the Google Cloud VM.** Use [deployment_parameters.md](deployment_parameters.md) to supply the project/billing, EU region/zone, operator identity, VM/disks, static IP, DuckDNS hostname and private storage/secret references. S07 creates no cloud resources. S09 deploys the DuckDNS HTTPS preview and S10 verifies off-VM restore before real client data.

Official references: [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/), [static deployment](https://docs.djangoproject.com/en/5.2/howto/static-files/deployment/), [Gunicorn settings](https://gunicorn.org/reference/settings/), [Docker contexts](https://docs.docker.com/build/concepts/context/) and [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use).
