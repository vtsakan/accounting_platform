# Accounting platform

A Django/PostgreSQL accounting-office platform combining the existing application with office management, collaboration, a client portal and authorised tax-data services. **All frontend content must be Greek**, including authentication, errors, emails and human-facing report headings.

S01 through S04 are complete. **S05 is next.** Dependencies have a minimal hashed lock; settings profiles, Greek locale, translated staff templates and decimal/date helpers are implemented. S05 supplies the runnable PostgreSQL environment.

## Start here

1. Read [implementation state](docs/implementation/state.md) and the repository instructions.
2. Review [settings and Greek locale](docs/implementation/settings_and_locale.md), [decisions](docs/implementation/decisions.md), [dependencies](docs/implementation/dependencies.md), [connector feasibility](docs/implementation/connector_feasibility.md) and [deployment parameters](docs/implementation/deployment_parameters.md).
3. Use the original [prompt reference](docs/baselines/Accounting_Platform_Prompt_by_Prompt_Implementation_Reference_v01.md) with the effective [prompt records](docs/implementation/prompts.json) and [Greek frontend change](docs/requirements/CR-001-Greek-frontend.md).
4. Track [steps](docs/implementation/steps.csv), [requirements](docs/implementation/traceability.csv) and the [Greek copy guide](docs/implementation/frontend_language.md).

## Checks and local prerequisites

The S04 check needs a full Git checkout, Linux x86_64/glibc, Python with `venv` support (3.10+ for bootstrapping), and package-download access. It creates disposable environments and installs the hash-checked dependencies with CPython 3.12.16:

```bash
python3 tools/verify_s04.py
git log --oneline --decorate
git status --short
```

Earlier verifiers remain historical snapshot checks at their recorded commits. [Dependency instructions](docs/implementation/dependencies.md) cover installation, isolated maintenance tools, lock updates and scan limits. For application development, provide Docker Engine with Compose v2 and Git. S04 settings and local-secret instructions are in [settings_and_locale.md](docs/implementation/settings_and_locale.md). S05 delivers the runnable PostgreSQL environment; the old Compose file still describes PostgreSQL 15.

## Baseline and acceptance

[Source inventory](docs/implementation/source_inventory.md), [module map](docs/implementation/module_map.md), [source manifest](docs/implementation/source_manifest.csv) and [baseline identities](docs/implementation/baseline_sources.json) preserve the original `accountant_v6.zip` provenance. Original models and both migrations remain unchanged through S04. Private archives and runtime inputs are excluded from this public repository and the Docker build context.

The original ACC-URS-001 v0.1 documents remain immutable. [CR-001](docs/requirements/CR-001-Greek-frontend.md) adds UR-LOC-01, making **71 user requirements and 14 quality requirements** in the effective baseline. All 85 application acceptance checks remain Pending. S02 documentary feasibility does not prove live service access.

## Deployment checkpoint

**Create or select the Google Cloud VM at S08, after S07.** S03–S07 run locally. S08 prepares the selected VM, storage and static address; S09 deploys the DuckDNS HTTPS preview; S10 verifies off-VM backup and recovery. No cloud resources have been created by S01 or S02.

## Scope boundary

Every active accountant belongs to exactly one office; several accountants may share it. Portal identity and client grants remain separate. Keep cash, charges, allocations, transfers, reversals and client tax sources distinct. Statutory general-ledger bookkeeping, invoice issuance, payroll, automatic tax filing, bank-payment execution, native mobile apps and subscription billing are outside the current baseline.
