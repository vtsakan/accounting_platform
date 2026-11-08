# Implementation state

Updated 2026-11-08. Current step: **S07 Verified — production image and delivery checks**. Next step: **S08 — Google Cloud VM checkpoint**.

## Repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S07 branch: `step/s07-production-delivery`; resolve its implementation commit with `git rev-parse HEAD` after applying the patch.
- Pushed S06 baseline: `53e453b59bda9e2a21cbea59a086ed7ae26a45bb` on `origin/step/s06-financial-regressions`, including successful Docker verification (78 tests: 52 passed, 26 known failures).
- Pushed S05 baseline: `5a65a72906f7d3a5fccdcfd8aad0d0362a2bd7fa` on `origin/step/s05-local-postgresql`, including Docker build/migration/recreation persistence.
- Pushed S04/S03 baselines: `aae1250c441f76b804c532711bc00edc3258943e` and `1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718`.
- S02: `a6a251b434bce295ec04240a63e33a656dc7f92e`, tagged `s02-complete`; S01: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.
- S07 is a local commit/patch for the user's terminal workflow; no remote S07 branch, CI run or pull request is claimed. The integration previously rejected writes.

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
- `evidence/S07-verification.json`: actual mode, migrations, 90-test outcomes, native health/static/log/configuration proof and pending image blocker.
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

All 71 user and 14 quality acceptance statuses remain Pending. D01–D09 domain/operator approvals remain open. No real client data, live messages/connectors, cloud resources, off-VM restore or full financial/office/Greek frontend acceptance is claimed.

## Google Cloud VM checkpoint

**After S07 Docker verification passes, create/select the VM at S08.** No VM is needed for the remaining S07 local checks. Use deployment_parameters.md for project/billing, EU region/zone, operator identity, VM/disks, reserved static IP, DuckDNS hostname and private storage/secret references. S09 deploys HTTPS; S10 proves off-VM restore before live data. Legacy PostgreSQL 15 export/import remains S25; never attach its old data directory to PostgreSQL 17.
