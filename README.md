# Accounting platform

A Django/PostgreSQL accounting-office platform combining the existing application with office management, collaboration, a client portal and authorised tax-data services. **All frontend content must be Greek**, including authentication, errors, emails and human-facing report headings.

S01 and S02 are complete. **S03 is next.** The application runtime and existing templates have not yet been modernised or translated; follow the controlled implementation sequence.

## Start here

1. Read [implementation state](docs/implementation/state.md) and the repository instructions.
2. Review [decisions](docs/implementation/decisions.md), [connector feasibility](docs/implementation/connector_feasibility.md) and [deployment parameters](docs/implementation/deployment_parameters.md).
3. Use the original [prompt reference](docs/baselines/Accounting_Platform_Prompt_by_Prompt_Implementation_Reference_v01.md) with the effective [prompt records](docs/implementation/prompts.json) and [Greek frontend change](docs/requirements/CR-001-Greek-frontend.md).
4. Track [steps](docs/implementation/steps.csv), [requirements](docs/implementation/traceability.csv) and the [Greek copy guide](docs/implementation/frontend_language.md).

## Checks and local prerequisites

The current documentation checks need Python 3.12+ and Git, with no application dependencies or database:

```bash
python3 tools/verify_s02.py
git log --oneline --decorate
git status --short
```

The S01 verifier remains a historical snapshot check at `s01-complete`. For application development, provide Docker Engine with Compose v2 and Git. S03 locks dependencies, S04 separates settings and establishes Greek locale, and S05 delivers the runnable local PostgreSQL environment. Do not use the legacy configuration as a production setup.

## Baseline and acceptance

[Source inventory](docs/implementation/source_inventory.md), [module map](docs/implementation/module_map.md), [source manifest](docs/implementation/source_manifest.csv) and [baseline identities](docs/implementation/baseline_sources.json) preserve the original `accountant_v6.zip` provenance. Original models and both migrations remain unchanged through S02. Private archives and runtime inputs are excluded from this public repository.

The original ACC-URS-001 v0.1 documents remain immutable. [CR-001](docs/requirements/CR-001-Greek-frontend.md) adds UR-LOC-01, making **71 user requirements and 14 quality requirements** in the effective baseline. All 85 application acceptance checks remain Pending. S02 documentary feasibility does not prove live service access.

## Deployment checkpoint

**Create or select the Google Cloud VM at S08, after S07.** S03–S07 run locally. S08 prepares the selected VM, storage and static address; S09 deploys the DuckDNS HTTPS preview; S10 verifies off-VM backup and recovery. No cloud resources have been created by S01 or S02.

## Scope boundary

Every active accountant belongs to exactly one office; several accountants may share it. Portal identity and client grants remain separate. Keep cash, charges, allocations, transfers, reversals and client tax sources distinct. Statutory general-ledger bookkeeping, invoice issuance, payroll, automatic tax filing, bank-payment execution, native mobile apps and subscription billing are outside the current baseline.
