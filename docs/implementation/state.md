# Implementation state

Updated 2026-11-09. Current step: **S08 Verified — Google Cloud foundation**. Next step: **S09 — DuckDNS/HTTPS preview**, requiring the actual hostname/control and ACME contact. The selected VM already exists.

## Repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S07 branch: `step/s07-production-delivery`; resolve its implementation commit with `git rev-parse HEAD` after applying the patch.
- Pushed S06 baseline: `53e453b59bda9e2a21cbea59a086ed7ae26a45bb` on `origin/step/s06-financial-regressions`, including successful Docker verification (78 tests: 52 passed, 26 known failures).
- Pushed S05 baseline: `5a65a72906f7d3a5fccdcfd8aad0d0362a2bd7fa` on `origin/step/s05-local-postgresql`, including Docker build/migration/recreation persistence.
- Pushed S04/S03 baselines: `aae1250c441f76b804c532711bc00edc3258943e` and `1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718`.
- S02: `a6a251b434bce295ec04240a63e33a656dc7f92e`, tagged `s02-complete`; S01: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.
- Pushed S07 verification baseline: `a215beb91e2e49a5ffd1fa9ce8c751b8f3572234` on `origin/step/s07-production-delivery`; read through GitHub and fetched before S08. No successful CI run is inferred from that push.
- S08 is supplied as a patch on `step/s08-google-cloud`, based on that pushed baseline. Resolve its applied commit with `git rev-parse HEAD`; no S08 remote push is claimed before the user performs it.

## Completed foundation and selected scope

S01/S02 preserve provenance, decisions, connector evidence, deployment parameters and the confirmed Greek requirement. S03 locks CPython 3.12.16, Django 5.2.19, Psycopg 3.3.8 binary and Gunicorn 26.2.0; seven runtime packages remain. S04 supplies settings/secrets/redaction and Greek locale/templates/catalog. S05's actual Docker environment/migrations/persistence and S06's financial baseline are independently Verified in the pushed records.

S07 adds the root production Dockerfile, Gunicorn configuration, command-only entrypoint, live/ready endpoints, manifest static build/export, committed-source image helper, disposable delivery Compose/verifier and pinned GitHub workflow. Twelve health/configuration tests extend the strict suite to 90 cases. Existing development Compose, local .env/port 8001 and its PostgreSQL volume are preserved.

Original business models, forms, views, app routes, migrations and dependency locks remain unchanged from S06. Core URLs gain only health routes. No new migration/dependency or financial fix is introduced. The 26 known failures remain Open at S18–S24/S29; legacy English generated transfer descriptions remain S21. No new human-facing UI is added; health responses are machine schema keys.

## Current completion gate

<!-- S07-RESULT -->
The production Docker image, explicit migrations, strict PostgreSQL suite, non-root/private-file audit, static export and Gunicorn readiness outage/recovery are Verified. See evidence/S07-verification.json for the immutable image identity. S08 is eligible: create/select the Google Cloud VM and supply the deployment parameters.
<!-- /S07-RESULT -->

## Evidence and commands

- `evidence/S01-verification.json` through `evidence/S06-verification.json`: historical step snapshots; S05/S06 current records include the user's Docker verification.
- `evidence/S07-verification.json`: successful real Docker gate, immutable image/context identity, migrations and 90-test outcomes (64 passed, 26 exact known failures), health/static/log/configuration proof. Earlier failed attempts are historical.
- `evidence/S08-verification.json`, `cloud_inventory.json`, `google_cloud.md`: operator-executed cloud/host/access evidence, actual resources, commands, cost assumptions and limitations.
- `evidence/S07-configuration-checks.json`: observed Compose/YAML configuration-only checks; no Engine execution.
- `evidence/S07-static-export-fix.json`: reported Docker export failure, host regression results and guarded existing-image retry.
- `production_delivery.md`: image identity, explicit migrations, probes, static export, CI artifacts, warnings and next gate.
- `docker/image-pins.json`, `docker/ci-pins.json`: runtime/base image and immutable official action identities.
- `financial_regressions.md`, `evidence/S06-regression-baseline.csv`, `accounting/regression_cases.json`: unchanged financial failure contracts and fix mapping.

```bash
python3 tools/verify_s07.py --record
```

Use a committed checkout and local Docker Engine/Compose. Verification builds/reuses one full-commit image, uses its immutable ID throughout, explicitly migrates an empty PostgreSQL 17 database, tests the image, checks real outage/recovery and exports static from that same image. A random project/unused loopback port separates it from normal local services. Only its temporary containers/network/volume are removed; the tested image remains. Successful --record updates this state, steps and evidence, then announces the S08 VM checkpoint. Commit those evidence/state changes afterwards; the recorded image revision remains the code commit that was actually built.

For the already built user image, append `--image sha256:68e1e362af3d7d22e59f57ed7b0c3014093737ab621009044964fcb3c9b9af2f` after applying the static-export fix. The helper refuses application-context mismatches; the host-only fix does not change that context. See production_delivery.md for the full retry command and identity checks.

For daily tests use `python3 tools/dev.py test`. Earlier verifiers remain historical snapshots, including S06's exact 78-test count. The CI workflow uses tools/verify_delivery.py to discover all current tests and follow reviewed registry outcomes as future features change models/migrations; it saves evidence/tested image artifacts and cannot rewrite historical step records. No live deployment or credentials are configured.

## Limits and open inputs

Django production checks show zero errors and reviewed warnings W005/W021: HSTS includeSubDomains/preload remain disabled pending S09 hostname/TLS verification. Other warnings fail delivery verification. Actual Caddy/static/TLS serving is S09; restore/incident operations are S10. Two Gunicorn workers are a provisional default, not workload evidence.

All 71 user and 14 quality acceptance statuses remain Pending. D01–D09 unresolved domain/operator approvals remain open. S08 cloud resources are actually provisioned; no real client data, live messages/connectors, application deployment, off-VM restore or full financial/office/Greek frontend acceptance is claimed.

## Google Cloud VM checkpoint

**S08 is complete from operator execution; another VM purchase is not needed.** The user selected the new accounting-only project accounting-514109 and accounting-preview in europe-west1-b. See cloud_inventory.json for the exact retained disk, Premium static IPv4, private buckets, IAM and secret metadata. The biomedical/research project is outside this scope. S09 deploys HTTPS; S10 proves off-VM restore before live data. Legacy PostgreSQL 15 logical migration remains S25.

## S08 execution and repository tools

The actual lower-cost selection is regular e2-medium (4 GB RAM/shared core) with
Ubuntu 26.04.1 LTS amd64. Host Docker 29.9.3, Compose 5.7.0 and containerd 2.4.2
use the retained 50-GiB ext4 data disk at /srv/accounting. Mount dependencies/UUID
guards were configured, and mount/runtime startup plus cached network-disabled
hello-world passed after reboot. A physical missing-disk boot test was not run.

IAP SSH works from Cloud Shell and laptop. Effective public ingress is TCP 80/443;
TCP 22 is limited to IAP. Metadata-key SSH was observed; OS Login was not independently
verified. The dedicated accounting-vm service account has cloud-platform scope and
resource-specific roles. The final project IAM query returned no VM project-role
rows. Pinned signing/database secret version-1 reads passed without printing values;
project-wide secret listing was denied. No service-account JSON key was used.

Document CRUD/listing passed. Backup upload passed while VM reads/listing/overwrite/
delete returned 403. Anonymous requests returned 401, correctly allowed by the
fixed 401/403 expectation. The administrator removed the exact backup probe object.
Registry listing and reported read permissions passed; a real image pull is S09
proof after publishing an image. Seven-day soft deletion is not retention approval
or immutable-backup acceptance. Automated encrypted backup/key recovery/restore
remain S10 work.

The implementation workspace reviewed the user's output rather than executing GCP
itself. New configurable cloud/host/access replay tools have offline safeguards;
their own live execution is not claimed. Actual configuration is Git-ignored under
private/gcp.json. See google_cloud.md for init/inspect/reference provisioning and
evidence/S08-verification.json for exact local check counts/code commit.

```bash
python3 tools/verify_s08.py
```

Run from a clean committed checkout. This verifies the offline safeguards and
unchanged S07 application build context, not live cloud availability. No new app/
database suite, migration or financial fix was run by S08; all 26 known defects
remain scheduled. Application code, dependencies and Greek frontend are unchanged.
Monthly budget/alerts, measured workload and incident/restore/key custodians remain
open D06/D07 inputs. S09 still needs actual DuckDNS control and ACME contact, then
must prove Caddy/Compose/secret loading, HTTPS/login/static/reboot behaviour. The
app is not deployed yet. Redis/worker/exactly-one scheduler arrive only at S26.
