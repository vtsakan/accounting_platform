# Accounting platform

A Django/PostgreSQL accounting-office platform combining the existing application with office management, collaboration, a client portal and authorised tax-data services. **All frontend content must be Greek**, including authentication, errors, emails and human-facing report headings.

S01 through S04 are complete. **S05 supplies the local Docker/PostgreSQL 17 environment.** Native PostgreSQL migration/test/restart checks passed; run the local Docker verifier to complete S05 before S06. All product screens continue to use the S04 Greek locale and translations.

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

Open [http://localhost:8000/login/](http://localhost:8000/login/). `up` generates private local credentials once and applies migrations; it never imports data. `python3 tools/dev.py down` retains the PostgreSQL volume. [Local development instructions](docs/implementation/local_development.md) cover seeding, tests, ports, restart persistence and the PostgreSQL 15/17 boundary.

Run `python3 tools/verify_s05.py --record` to build/migrate/test a separate disposable Docker project and verify persisted records after container recreation. It records S05 as Verified only after the Docker checks pass. The supplied evidence records native PostgreSQL checks and leaves Docker execution pending because the implementation workspace has no engine.

Earlier verifiers remain historical snapshot checks at their recorded commits. [Dependency instructions](docs/implementation/dependencies.md) cover the hashed locks and scan limits; [settings and locale](docs/implementation/settings_and_locale.md) covers the three profiles and Greek conventions.

## Baseline and acceptance

[Source inventory](docs/implementation/source_inventory.md), [module map](docs/implementation/module_map.md), [source manifest](docs/implementation/source_manifest.csv) and [baseline identities](docs/implementation/baseline_sources.json) preserve the original `accountant_v6.zip` provenance. Original models, views and both accounting migrations remain unchanged through S05. Private archives and runtime inputs are excluded from this public repository and the Docker build context.

The original ACC-URS-001 v0.1 documents remain immutable. [CR-001](docs/requirements/CR-001-Greek-frontend.md) adds UR-LOC-01, making **71 user requirements and 14 quality requirements** in the effective baseline. All 85 application acceptance checks remain Pending. S02 documentary feasibility does not prove live service access.

## Deployment checkpoint

**Create or select the Google Cloud VM at S08, after S07.** S03–S07 run locally. S08 prepares the selected VM, storage and static address; S09 deploys the DuckDNS HTTPS preview; S10 verifies off-VM backup and recovery. No cloud resources have been created through S05.

## Scope boundary

Every active accountant belongs to exactly one office; several accountants may share it. Portal identity and client grants remain separate. Keep cash, charges, allocations, transfers, reversals and client tax sources distinct. Statutory general-ledger bookkeeping, invoice issuance, payroll, automatic tax filing, bank-payment execution, native mobile apps and subscription billing are outside the current baseline.
