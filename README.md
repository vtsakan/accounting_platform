# Accounting platform

A Django/PostgreSQL accounting-office platform combining the existing application with office management, collaboration, a client portal and authorised tax-data services. **All frontend content must be Greek**, including authentication, errors, emails and human-facing report headings.

S01–S10 are Verified, including the DuckDNS HTTPS preview and actual encrypted backup, independent-key recovery and alert checks. **S11 prepares the office/profile foundation:** additive schema, explicit membership/backfill and a missing/inactive-profile gate. Native PostgreSQL verification runs 120 tests: 94 pass and 26 known financial failures remain reproduced. Local Docker reproduction completes S11. Full record ownership follows at S12; authentication and office settings follow at S13/S14.

## Start here

1. Read [implementation state](docs/implementation/state.md) and the repository instructions.
2. Review [settings and Greek locale](docs/implementation/settings_and_locale.md), [decisions](docs/implementation/decisions.md), [dependencies](docs/implementation/dependencies.md), [connector feasibility](docs/implementation/connector_feasibility.md) and [deployment parameters](docs/implementation/deployment_parameters.md).
3. Use the original [prompt reference](docs/baselines/Accounting_Platform_Prompt_by_Prompt_Implementation_Reference_v01.md) with the effective [prompt records](docs/implementation/prompts.json) and [Greek frontend change](docs/requirements/CR-001-Greek-frontend.md).
4. Track [steps](docs/implementation/steps.csv), [requirements](docs/implementation/traceability.csv) and the [Greek copy guide](docs/implementation/frontend_language.md).

## Local development and verification

Use a full Git checkout, Linux x86_64/glibc, Python 3.10+ with `venv`, a running local Docker Engine/Compose plugin and package-download access. Start the development stack:

```bash
python3 tools/dev.py up
```

Open [http://localhost:8000/login/](http://localhost:8000/login/), or [localhost:8001/login/](http://localhost:8001/login/) when `.env` sets `WEB_PORT=8001`. `up` generates private local credentials once and applies migrations; it never imports data. `python3 tools/dev.py down` retains the PostgreSQL volume. [Local development instructions](docs/implementation/local_development.md) cover seeding, tests, ports, restart persistence and the PostgreSQL 15/17 boundary.

Run `python3 tools/dev.py test` for the strict 120-test PostgreSQL command. Use `python3 tools/verify_s11.py --record` for the isolated S11 migration/concurrency gate. Accountants now need an explicitly reviewed profile; an administrator alone does not grant business access. Human account onboarding remains S13/S14. `tools/verify_delivery.py` is the continuing production-image gate; historical S07 verifiers are used only at their tagged snapshots.

[Financial regression instructions](docs/implementation/financial_regressions.md) explain the 26 known failures, ten passing financial controls, exact failure tracking and future fixes. `python3 tools/dev.py test-raw` deliberately exposes the 26 unfixed assertions with a nonzero exit. A passing strict command confirms the recorded baseline, not financial correctness.

[Production delivery instructions](docs/implementation/production_delivery.md) explain image identity, CI artifacts, the static export for Caddy, reviewed deployment warnings and the S07 completion gate. The production image uses the root Dockerfile; local development still uses `docker/development.Dockerfile`.

Earlier verifiers remain historical snapshot checks at their recorded commits. [Dependency instructions](docs/implementation/dependencies.md) cover the hashed locks and scan limits; [settings and locale](docs/implementation/settings_and_locale.md) covers the three profiles and Greek conventions.

## Baseline and acceptance

[Source inventory](docs/implementation/source_inventory.md), [module map](docs/implementation/module_map.md), [source manifest](docs/implementation/source_manifest.csv) and [baseline identities](docs/implementation/baseline_sources.json) preserve the original `accountant_v6.zip` provenance. Original business models, views and both accounting migrations remain unchanged through S07. Private archives and runtime inputs are excluded from this public repository and the committed build context.

The original ACC-URS-001 v0.1 documents remain immutable. [CR-001](docs/requirements/CR-001-Greek-frontend.md) adds UR-LOC-01, making **71 user requirements and 14 quality requirements** in the effective baseline. All 85 application acceptance checks remain Pending. S02 documentary feasibility does not prove live service access.

## Deployment checkpoint

The selected `accounting-514109/accounting-preview` VM and `totalaccounting.duckdns.org` preview already exist and have passed S08–S10. S11 runs locally with synthetic data. Its schema is not deployed to the VM; complete S12 ownership and S13 authentication before enabling office onboarding.

## Scope boundary

Every active accountant belongs to exactly one office; several accountants may share it. Portal identity and client grants remain separate. Keep cash, charges, allocations, transfers, reversals and client tax sources distinct. Statutory general-ledger bookkeeping, invoice issuance, payroll, automatic tax filing, bank-payment execution, native mobile apps and subscription billing are outside the current baseline.
\n## S11 — offices and accountant profiles

The office/profile foundation and reviewed legacy mapping tools are described in
[office_profiles.md](docs/implementation/office_profiles.md). Run
`python3 tools/verify_s11.py --record` on a local Docker Engine for the isolated
PostgreSQL gate. S11 makes no VM change; full record ownership follows at S12,
regular authentication at S13 and office settings/invitations at S14.
