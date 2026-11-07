# Implementation state

Updated 2026-11-07. Current step: **S04 Verified — settings and Greek locale foundation**. Next step: **S05**.

## Repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S04 branch: `step/s04-settings-greek`; resolve its actual commit with `git rev-parse HEAD`.
- Pushed S03 baseline: `1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718` on `origin/step/s03-dependencies`. At the baseline check, `main` still pointed to S02, so S04 starts from the pushed S03 branch.
- S02 completion: `a6a251b434bce295ec04240a63e33a656dc7f92e`, tagged `s02-complete`.
- S01 completion: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.
- Publication: S04 is prepared locally as a commit/patch for the user's terminal workflow. No S04 remote branch or pull request has been created. The integration previously rejected writes; no new write attempt is claimed.

## Completed scope

S01 preserved source/baseline provenance and inventoried the original models, routes and migrations. Three embedded credential values were cleared before the first controlled commit. S02 recorded D01–D09, six connector evidence records, deployment parameters and the explicit Greek frontend requirement. Domain/accountant approvals remain pending.

S03 replaced the 364-entry workstation freeze with three direct runtime dependencies and seven hash-locked packages. CPython 3.12.16, Django 5.2.19, Psycopg 3.3.8 binary and Gunicorn 26.2.0 remain selected. Source packaging and offline secret scanning were established.

S04 splits common/local/test/production settings, adds safe local secret generation, environment/mounted-file inputs, production validation, redacted logging and Greek error pages. It sets el and Europe/Athens, implements Decimal/date/DST helpers, translates all 17 existing staff templates and form labels, and supplies a checked Greek message catalog. Native HTML date values remain ISO. polib is added only to the maintenance lock; the runtime lock is unchanged.

Business models, view logic, routes and original migrations are byte-identical to the S03 baseline. No accounting model-state change or new migration is required. Existing financial defects remain scheduled for S06 and the later finance steps.

## Evidence

- `evidence/S01-verification.json`, `evidence/S02-verification.json`, `evidence/S03-verification.json`: historical snapshot evidence.
- `evidence/S04-verification.json`: fresh isolated installs, focused Django configuration/locale tests, catalog and lock checks, schema-state inspection and source/history scan.
- `settings_and_locale.md`: profiles, variables, secret loading, locale conventions, commands and official references.
- `core/tests/test_s04.py`: positive/negative configuration, secret files, logging, Greek rendering/validation, UTF-8, Decimal and DST cases.
- `dependencies.md`, `dependency_policy.json`, `../security/README.md`: dependency and scan policy.
- `effective_baseline.json` and `../requirements/CR-001-Greek-frontend.md`: effective 71 UR / 14 QR baseline.

Run `python3 tools/verify_s04.py` for this snapshot. It bootstraps disposable environments and obtains the pinned Python if needed. Earlier verifiers remain unchanged and target their recorded snapshots.

The focused tests use SimpleTestCase and prohibit database queries. No PostgreSQL persistence/migration execution, Docker build, live government API, cloud deployment or full financial acceptance is demonstrated. All 85 requirements remain Pending. UR-LOC-01 is confirmed and its current staff-screen foundation is implemented; complete authenticated admin, portal, mail/export and staged release checks remain pending in their planned steps.

## Next work and open inputs

S05 can now build the Docker Compose development environment on PostgreSQL 17 and run the preserved migration history on a fresh database. Use the generated .env and explicit settings profile. The old PostgreSQL 15 Compose file has not been used as the new environment. Do not reuse a PostgreSQL 15 data directory as a version 17 volume.

D01–D09 still identify role/grant policy, financial rules, tax reference cases, legacy ownership, scale, retention and operational responsibilities. Settings defaults and translations do not constitute approval of these policies. S49 must revalidate connector eligibility and contracts; conditional government retrieval remains unavailable until approved access exists.

## Google Cloud VM checkpoint

**Create or select the VM at S08, after S07 is verified. No VM is needed for S05–S07.** Collect the real project/billing, EU region/zone, resource choice, administrator identity and DuckDNS hostname at that checkpoint. S09 demonstrates HTTPS/proxy behaviour and S10 proves off-VM restore before live client data is accepted.
