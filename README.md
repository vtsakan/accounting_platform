# Accounting platform

A Django/PostgreSQL accounting-office platform combining the existing application with office management, collaboration, a client portal and authorised tax-data services. **All frontend content must be Greek**, including authentication, errors, emails and human-facing report headings.

S05's local Docker/PostgreSQL 17 environment is Verified. **S06 captures the financial regression baseline:** 78 tests run, 52 passed and 26 known failures reproduced. These defects remain assigned to their corrective steps. S07 builds the production image and delivery checks. The Greek locale and existing staff-template translations are retained.

## Start here

1. Read [implementation state](docs/implementation/state.md) and the repository instructions.
2. Review [settings and Greek locale](docs/implementation/settings_and_locale.md), [decisions](docs/implementation/decisions.md), [dependencies](docs/implementation/dependencies.md), [connector feasibility](docs/implementation/connector_feasibility.md) and [deployment parameters](docs/implementation/deployment_parameters.md).
3. Use the original [prompt reference](docs/baselines/Accounting_Platform_Prompt_by_Prompt_Implementation_Reference_v01.md) with the effective [prompt records](docs/implementation/prompts.json) and [Greek frontend change](docs/requirements/CR-001-Greek-frontend.md).
4. Track [steps](docs/implementation/steps.csv), [requirements](docs/implementation/traceability.csv) and the [Greek copy guide](docs/implementation/frontend_language.md).

## Local development and verification

Use a full Git checkout, Linux x86_64/glibc, Python 3.10+ with `venv`, a running local Docker Engine/Compose plugin and package-download access. Start the development stack and create your administrator:

```bash
python3 tools/dev.py up
python3 tools/dev.py admin
```

Open [http://localhost:8000/login/](http://localhost:8000/login/), or [localhost:8001/login/](http://localhost:8001/login/) when `.env` sets `WEB_PORT=8001`. `up` generates private local credentials once and applies migrations; it never imports data. `python3 tools/dev.py down` retains the PostgreSQL volume. [Local development instructions](docs/implementation/local_development.md) cover seeding, tests, ports, restart persistence and the PostgreSQL 15/17 boundary.

Run `python3 tools/dev.py test` for the strict PostgreSQL test command. Run `python3 tools/verify_s06.py --record` for an isolated Docker build, empty-database migrations, complete test baseline and evidence update. It selects an unused loopback port and cleans up only its own temporary project. The supplied S06 evidence uses native PostgreSQL 17.11, with the already-pushed S05 Docker gate preserved separately.

[Financial regression instructions](docs/implementation/financial_regressions.md) explain the 26 known failures, ten passing financial controls, exact failure tracking and future fixes. `python3 tools/dev.py test-raw` deliberately exposes the 26 unfixed assertions with a nonzero exit. A passing strict command confirms the recorded baseline, not financial correctness.

Earlier verifiers remain historical snapshot checks at their recorded commits. [Dependency instructions](docs/implementation/dependencies.md) cover the hashed locks and scan limits; [settings and locale](docs/implementation/settings_and_locale.md) covers the three profiles and Greek conventions.

## Baseline and acceptance

[Source inventory](docs/implementation/source_inventory.md), [module map](docs/implementation/module_map.md), [source manifest](docs/implementation/source_manifest.csv) and [baseline identities](docs/implementation/baseline_sources.json) preserve the original `accountant_v6.zip` provenance. Original models, views and both accounting migrations remain unchanged through S06. Private archives and runtime inputs are excluded from this public repository and the Docker build context.

The original ACC-URS-001 v0.1 documents remain immutable. [CR-001](docs/requirements/CR-001-Greek-frontend.md) adds UR-LOC-01, making **71 user requirements and 14 quality requirements** in the effective baseline. All 85 application acceptance checks remain Pending. S02 documentary feasibility does not prove live service access.

## Deployment checkpoint

**Create or select the Google Cloud VM at S08, after S07.** S03–S07 run locally. S08 prepares the selected VM, storage and static address; S09 deploys the DuckDNS HTTPS preview; S10 verifies off-VM backup and recovery. No cloud resources have been created through S06.

## Scope boundary

Every active accountant belongs to exactly one office; several accountants may share it. Portal identity and client grants remain separate. Keep cash, charges, allocations, transfers, reversals and client tax sources distinct. Statutory general-ledger bookkeeping, invoice issuance, payroll, automatic tax filing, bank-payment execution, native mobile apps and subscription billing are outside the current baseline.
