# Implementation state

Updated 2026-11-07. Current step: **S03 Verified — source packaging and clean dependency installation**. Next step: **S04**.

## Repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S03 branch: `step/s03-dependencies`; completion reference is the branch head containing these records. Resolve the actual commit with `git rev-parse HEAD`.
- Verified S02 remote baseline: `a6a251b434bce295ec04240a63e33a656dc7f92e`, on GitHub `main` and tagged `s02-complete`.
- Publication: the user pushed and finalised S02 successfully. S03 is prepared as a local commit/patch for the same terminal workflow; no S03 remote branch or pull request has been created. The connected integration previously rejected writes with HTTP 403; no new write attempt is claimed.
- S01 completion commit: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source commit: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.

## Completed scope

S01 inventoried the legacy application and established the immutable baseline, 64-step register and original 84 requirements. Three embedded credential values were cleared before the first commit. Source models and migrations retain their identities.

S02 expands D01–D09 with owners, options, recommendations, open questions, gates and affected steps. It records documentary evidence for six connectors and prepares the GCP/DuckDNS parameter template. Future domain/accountant approvals remain pending. No service credentials, live client data or Google Cloud resources were used.

The user-confirmed Greek frontend instruction is recorded as CR-001 / UR-LOC-01. The effective requirements baseline is **71 UR + 14 QR = 85**, all application acceptance Pending. Greek includes staff/portal/authentication screens, errors, email and report headings. S04 establishes language settings; each later UI feature includes Greek copy. Existing source templates are unchanged through S03.

S03 replaces the 364-entry workstation dependency freeze with three direct runtime dependencies and seven hash-locked packages. CPython 3.12.16, Django 5.2.19, Psycopg 3.3.8 binary and Gunicorn 26.2.0 are selected for Linux x86_64/glibc. Maintenance tools have a separate hashed lock. Git and Docker ignore policies exclude private/runtime inputs. All application models, forms, views, templates and migrations remain unchanged.

## Evidence and checks

- `evidence/S01-verification.json`: historical S01 inventory evidence.
- `evidence/S02-verification.json`: historical S02 planning/record evidence.
- `evidence/S03-verification.json`: actual fresh hash-checked installs, dependency checks, migration loading, lock reproduction and source/history secret scan.
- `dependencies.md` / `dependency_policy.json`: selected versions, official-source evidence, commands and scope.
- `../security/README.md` and its fingerprint allowlist: offline secret-scan policy and reviewed non-secret exceptions.
- `decision_register.json` / `decisions.md`: D01–D09 and the confirmed constraints.
- `connector_feasibility.json` / `.md`: dated official sources, access conditions and review limitations.
- `deployment_parameters.example.json` / `.md`: unknown target values, owners and S08 checkpoint.
- `effective_baseline.json` and `../requirements/CR-001-Greek-frontend.md`: controlled requirement change.

Run `python3 tools/verify_s03.py` for the current snapshot. It creates disposable environments, obtains the pinned managed Python if needed and enforces package hashes. See `dependencies.md` for prerequisites and maintenance commands. Earlier S01/S02 verifiers intentionally target their tagged snapshots; they are not weakened to accept later steps.

The fresh-environment probe imports the application and PostgreSQL backend, renders the original migration graph/model state, and checks a standard-library Gunicorn demo configuration. These are dependency compatibility checks. No PostgreSQL connection, schema migration, financial regression, production Docker build, Greek UI acceptance or live API test is performed. All 85 application requirements remain Pending.

## Open inputs and next work

S04 can proceed now: separate settings, environment configuration and Greek locale. Read `prompts.json` and `frontend_language.md` for its full scope. S05 then supplies PostgreSQL and the runnable local environment. Current legacy settings retain deliberately blank credentials. One-office membership, Greek frontend, public GitHub and VM/DuckDNS hosting are confirmed; role details, client authority, financial policy, tax coverage, legacy ownership, scale, retention and operational ownership are not inferred as approved. Their exact blockers are in D01–D09.

AADE basic registry, myDATA and VIES have documentary routes, with registration/contract verification still needed. Full TAXISnet profile, AADE debt and e-EFKA retrieval remain conditional until approved private-application access is demonstrated. All six have unrun live tests and production disabled. S49 revalidates current contracts before implementation.

## Google Cloud VM checkpoint

**Create or select the VM at S08, after S02 and S07 are verified. No VM is needed for S03–S07.** At S08 collect the real project/billing, EU region/zone, existing-resource choice, administrator identity and DuckDNS hostname from the parameter sheet. Notify the user before that checkpoint. S09 deploys the HTTPS preview and S10 proves off-VM restore; live client data waits for the R1 gates.
