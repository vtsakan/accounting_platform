# Accounting platform

S01 source inventory and implementation baseline, completed 2026-11-07. The project combines the existing accounting application with the documented requirements for office management, collaboration, a client portal and authorised tax-data services.

## Start here

1. Read [implementation state](docs/implementation/state.md).
2. Review the [source inventory](docs/implementation/source_inventory.md) and [module map](docs/implementation/module_map.md).
3. Use [the prompt sequence](docs/baselines/Accounting_Platform_Prompt_by_Prompt_Implementation_Reference_v01.md), starting with S02 next.
4. Track progress in [steps.csv](docs/implementation/steps.csv), decisions in [decisions.md](docs/implementation/decisions.md), and requirement evidence in [traceability.csv](docs/implementation/traceability.csv).

## Local prerequisites and checks

For the S01 inventory check, use Python 3.12 or newer and Git. No third-party Python dependency or database is needed:

```bash
python3 tools/verify_s01.py
git log --oneline --decorate
git status --short
```

For later development, provide Docker Engine with Compose v2, Git and a code editor. S03 locks minimal application dependencies, S04 separates configuration and S05 establishes the reproducible local PostgreSQL environment. The legacy dependency freeze and settings have not been made production-ready in S01; three original secret values are intentionally absent from the working export. Start the application using the commands delivered in S05, after those steps pass.

## Source and planning references

The original `accountant_v6.zip` archive contains an `accountant_v3` Django application. The untouched original remains saved separately. Its checksum, identity and all member checksums are recorded in [baseline_sources.json](docs/implementation/baseline_sources.json) and [source_manifest.csv](docs/implementation/source_manifest.csv). Working models and both migrations are preserved byte for byte.

`docs/baselines/` contains current copies of ACC-URS-001, ACC-IMP-001 and the Markdown ACC-IMP-002 prompt reference. Requirement definitions and acceptance checks are also available as [requirements.json](docs/implementation/requirements.json). All 70 user requirements and 14 quality requirements remain Pending until their actual acceptance checks run.

## Deployment checkpoint

**You need the Google Cloud VM at S08, after S07.** S01 to S07 can be completed locally. S08 prepares the selected VM, storage and address; S09 deploys the DuckDNS HTTPS preview; S10 verifies backup and recovery. No cloud resource has been created during S01.

## Repository history

The local Git history starts with `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`. The `s01-complete` tag identifies the completed S01 records. No remote is configured; the private Git destination can be selected when repository setup continues. Model/table and migration identities must remain stable unless an explicit later migration changes them.

## Scope boundary

Every active accountant belongs to exactly one office; several accountants may share that office. Portal identity and client grants are separate from office membership. Keep cash, charges, allocations, transfers, reversals and client tax sources distinct. Statutory general-ledger bookkeeping, invoice issuance, payroll, automatic tax filing, bank-payment execution, native mobile apps and subscription billing are outside the current baseline.
