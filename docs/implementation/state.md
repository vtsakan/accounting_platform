# Implementation state

Updated 2026-11-08. Current step: **S05 Verified — local Docker/PostgreSQL environment**. Next step: **S06**.

## Repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S05 branch: `step/s05-local-postgresql`; resolve its actual implementation commit with `git rev-parse HEAD` after applying the patch.
- Pushed S04 baseline: `aae1250c441f76b804c532711bc00edc3258943e` on `origin/step/s04-settings-greek`. S05 starts from that branch; `main` still pointed to S02 when checked.
- Pushed S03 baseline: `1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718` on `origin/step/s03-dependencies`.
- S02 completion: `a6a251b434bce295ec04240a63e33a656dc7f92e`, tagged `s02-complete`.
- S01 completion: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.
- Publication: S04 is confirmed pushed. S05 is supplied as a local commit/patch for the user's terminal workflow; no remote S05 branch or pull request is claimed. The GitHub integration previously rejected writes.

## Completed scope

S01 preserved source/baseline provenance and inventoried the original models, routes and migrations. Three embedded credential values were cleared before the first controlled commit. S02 recorded D01–D09, six connector evidence records, deployment parameters and the explicit Greek frontend requirement. Domain/accountant approvals remain pending.

S03 replaced the 364-entry workstation freeze with three direct runtime dependencies and seven hash-locked packages. CPython 3.12.16, Django 5.2.19, Psycopg 3.3.8 binary and Gunicorn 26.2.0 remain selected. Source packaging and offline secret scanning were established.

S04 separates common/local/test/production settings, adds safe local secret generation, environment/mounted-file inputs, production validation, redacted logging and Greek error pages. It sets el and Europe/Athens, implements Decimal/date/DST helpers, translates all 17 existing staff templates and form labels, and supplies a checked Greek message catalog. polib is maintenance-only; the runtime lock remains unchanged.

S05 supplies a development Dockerfile/entrypoint, Compose with PostgreSQL 17.11, a new persistent volume, local-only web access and no database host port. `tools/dev.py` supplies startup, administrator, migration, test, explicit seed and volume-preserving shutdown commands. Two guarded management commands supply synthetic markers and non-secret database evidence. Five real PostgreSQL integration tests supplement S04's 30 configuration/locale tests. A disposable verifier checks the Docker lifecycle and records completion only after it succeeds.

Business models, view logic, routes and original migrations remain byte-identical to the pushed S04 baseline. No new migration or runtime Python dependency is required. Known financial defects remain scheduled for S06 and their later corrective steps.

## Current completion gate

<!-- S05-RESULT -->
Local Docker build, empty-database migrations, focused/PostgreSQL tests and persisted markers after container recreation are Verified. See evidence/S05-verification.json. S06 is eligible.
<!-- /S05-RESULT -->

## Evidence and commands

- `evidence/S01-verification.json` through `evidence/S04-verification.json`: historical step snapshots; earlier verifiers remain unchanged and target those snapshots.
- `evidence/S05-verification.json`: actual mode, migrations, synthetic markers, test count, native/Docker persistence flags, secret scan and outstanding blocker. Check its status before proceeding.
- `evidence/S05-native-provenance.json`: official PGDG package identities and checksums for the supplementary native run.
- `local_development.md`: Docker requirements, startup/admin/test/seed/shutdown, volume safety, verification and official references.
- `docker/image-pins.json`: reviewed official image references and platform identities.
- `settings_and_locale.md`, `dependencies.md` and `../security/README.md`: configuration, locale, dependency and secret-scan policies.
- `effective_baseline.json` and `../requirements/CR-001-Greek-frontend.md`: effective 71 UR / 14 QR baseline.

```bash
python3 tools/verify_s05.py --record
```

The verifier uses its own random project, credentials, loopback port and volume, then removes only that temporary project. Successful `--record` updates this state, `steps.csv` and the S05 evidence; commit those three files after it passes. Normal development data is not selected. `python3 tools/dev.py up` starts the usual local environment; `python3 tools/dev.py admin` creates an interactive development administrator.

All 85 application acceptance statuses remain Pending. Native migration/test evidence does not prove Docker delivery, financial correctness, office isolation, live government APIs or production readiness. Full Greek admin/portal/email/export and staged release acceptance remains pending in the planned steps. No real data or Google Cloud resources have been used.

## Next work and open inputs

After S05 Docker verification passes, S06 captures the known financial defects as PostgreSQL regression tests using synthetic fixtures. S07 builds the production image and delivery checks. Do not reuse a PostgreSQL 15 data directory as a version 17 volume; logical export/import and reconciliation remain S25.

D01–D09 still identify role/grant policy, financial rules, tax reference cases, legacy ownership, scale, retention and operational responsibilities. Technical defaults and passing foundation tests do not approve those policies. S49 must revalidate connector eligibility and contracts; conditional government retrieval remains unavailable until approved access exists.

## Google Cloud VM checkpoint

**Create or select the VM at S08, after S07 is verified. No VM is needed for S05–S07.** Collect the real project/billing, EU region/zone, resource choice, administrator identity and DuckDNS hostname at that checkpoint. S09 demonstrates HTTPS/proxy behaviour and S10 proves off-VM restore before live client data is accepted.
