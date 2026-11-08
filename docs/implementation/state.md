# Implementation state

Updated 2026-11-08. Current step: **S06 Verified — financial regression baseline**. Next step: **S07**.

## Repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S06 branch: `step/s06-financial-regressions`; resolve its implementation commit with `git rev-parse HEAD` after applying the patch.
- Pushed S05 baseline: `5a65a72906f7d3a5fccdcfd8aad0d0362a2bd7fa` on `origin/step/s05-local-postgresql`. The user committed successful Docker verification; S06 starts from this branch.
- Pushed S04 baseline: `aae1250c441f76b804c532711bc00edc3258943e` on `origin/step/s04-settings-greek`.
- Pushed S03 baseline: `1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718` on `origin/step/s03-dependencies`.
- S02 completion: `a6a251b434bce295ec04240a63e33a656dc7f92e`, tagged `s02-complete`.
- S01 completion: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.
- Publication: S05 is confirmed pushed. S06 is supplied as a local commit/patch for the user's terminal workflow; no remote S06 branch or pull request is claimed. The integration previously rejected writes.

## Completed foundation

S01 preserved source/baseline provenance and inventoried original models, routes and migrations. Three embedded credentials were cleared before the first controlled commit. S02 recorded D01–D09, connector evidence, deployment parameters and the confirmed Greek frontend requirement. Domain/accountant approvals remain pending.

S03 replaced the workstation freeze with three direct runtime dependencies and seven hash-locked packages. CPython 3.12.16, Django 5.2.19, Psycopg 3.3.8 binary and Gunicorn 26.2.0 remain selected. Source packaging and offline scanning were established. S04 separated settings, secret handling, safe errors/logging and Greek locale; its 17 staff templates and catalog remain implemented.

S05 supplies the digest-pinned development Compose environment, a separate PostgreSQL 17 volume, localhost web access and guarded local commands. The user's pushed S05 evidence verifies the actual Docker build, all 20 migrations, 35 tests, Greek HTTP login and retained markers after container recreation. The existing WEB_PORT option resolved the normal local stack's port conflict without removing its volume or stopping the other application.

## S06 scope and current gate

S06 adds a synthetic PostgreSQL fixture, a 36-case registry, financial contract tests, a strict result adapter, seven runner guard tests and an isolated verifier. Known financial failures are reproduced, not fixed. Models, forms, views, routes, original migrations and both dependency locks remain unchanged from S05. No migration or new Python dependency is needed. The Greek locale and staff templates are retained; no new product UI is introduced. Legacy generated transfer descriptions still contain English copy, to be corrected at S21 under UR-LOC-01.

<!-- S06-RESULT -->
S06 test capture is Verified on native-postgresql17, PostgreSQL 170011. The strict suite ran 78 tests: 52 passed and 26 exact known failures were reproduced, with no unexpected outcomes. The ordinary runner still fails the unfixed assertions. S07 is eligible; financial fixes remain in their assigned steps.
<!-- /S06-RESULT -->

The 26 cases cover null balances, transfer gross totals, cross-counterparty settlement, nonpositive amounts, stale settlement after correction/deletion, overwritten cancellation and malformed filters. The cases include the required 100 + 50 = 150 contract (still a known failure). Ten passing financial controls cover partial settlement 100 - 25 = 75, paired transfer 1000 and actual second-leg rollback, among other working paths. The runner recognises only exact registered financial mismatches; unrelated errors, skips, changed failure patterns and unexpected passes fail. The ordinary runner exposes all 26 unfixed assertions as failures.

## Evidence and repeatable commands

- `evidence/S01-verification.json` through `evidence/S05-verification.json`: historical step evidence; S05's current record is the user's successful Docker run.
- `evidence/S06-verification.json`: actual mode, migrations, 78-test strict result, ordinary-runner failures, case observations, locks/catalog and secret scan.
- `evidence/S06-regression-baseline.csv`: per-case requirement, observed value, correct expectation and corrective steps.
- `financial_regressions.md`, `accounting/regression_cases.json` and `known_issues.csv`: fixture design, strict tracking rules and the issue/test/fix mapping.
- `local_development.md`, `settings_and_locale.md`, `dependencies.md` and `../security/README.md`: local operation and security/configuration conventions.

```bash
python3 tools/dev.py test
python3 tools/verify_s06.py --record
```

The first command checks the running development stack. The second uses a new disposable Docker project and unused loopback port; it never selects the normal .env or development volume. S06 can also be verified with `--native-bin` on a real isolated PostgreSQL 17 cluster. The supplied S06 run uses native PostgreSQL and records no Docker execution this step. S05's Docker proof remains independent. After a successful local `--record`, commit the S06 evidence, case CSV, steps and state.

All 85 requirement acceptance statuses remain Pending. Capturing regressions is not financial, office-isolation, production or full Greek frontend acceptance. No real data, live messages/connectors or Google Cloud resources were used. Policy approvals D01–D09 remain open at their assigned gates.

## Next step and cloud checkpoint

After S06 verification, **S07** creates the production image, Gunicorn service, liveness/readiness endpoints, static asset path and delivery checks while retaining the explicit financial failure inventory. The principal financial corrections remain S19–S24, with supporting constraints at S18 and reporting at S29.

**Create or select the Google Cloud VM at S08, after S07 is verified. No VM is needed for S06 or S07.** Collect the project/billing, EU region/zone, administrator identity, resource choice and DuckDNS hostname then. S09 demonstrates HTTPS/proxy behaviour; S10 proves off-VM restore before live client data is accepted. PostgreSQL 15 legacy export/import and reconciliation remain S25; never attach its old data directory to PostgreSQL 17.
