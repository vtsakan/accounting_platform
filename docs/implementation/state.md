# Implementation state

Updated 2026-11-07. Current step: **S02 Verified — documentation and planning records**. Next step: **S03**.

## Repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S02 branch: `step/s02-decisions-greek-ui`; completion reference is the branch head containing these records. Resolve the actual commit with `git rev-parse HEAD`.
- Publication: local branch prepared. The connected GitHub integration rejected repository writes with HTTP 403; apply the S02 patch and push from the user's authorised terminal. No remote S02 branch or pull request was created.
- S01 completion commit: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source commit: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.

## Completed scope

S01 inventoried the legacy application and established the immutable baseline, 64-step register and original 84 requirements. Three embedded credential values were cleared before the first commit. Source models and migrations retain their identities.

S02 expands D01–D09 with owners, options, recommendations, open questions, gates and affected steps. It records documentary evidence for six connectors and prepares the GCP/DuckDNS parameter template. Future domain/accountant approvals remain pending. No service credentials, live client data or Google Cloud resources were used.

The user-confirmed Greek frontend instruction is recorded as CR-001 / UR-LOC-01. The effective requirements baseline is **71 UR + 14 QR = 85**, all application acceptance Pending. Greek includes staff/portal/authentication screens, errors, email and report headings. S04 establishes language settings; each later UI feature includes Greek copy. Existing source templates are unchanged by S02.

## Evidence and checks

- `evidence/S01-verification.json`: historical S01 inventory evidence.
- `evidence/S02-verification.json`: current record consistency, immutable-baseline and source-preservation checks.
- `decision_register.json` / `decisions.md`: D01–D09 and the confirmed constraints.
- `connector_feasibility.json` / `.md`: dated official sources, access conditions and review limitations.
- `deployment_parameters.example.json` / `.md`: unknown target values, owners and S08 checkpoint.
- `effective_baseline.json` and `../requirements/CR-001-Greek-frontend.md`: controlled requirement change.

Run `python3 tools/verify_s02.py` for the current S02 snapshot. The unchanged S01 verifier targets `s01-complete`; it intentionally expects the historical 84 requirements and pre-S02 step statuses. Run it from an isolated checkout of that tag when verifying S01, not against evolving S02 records.

These checks do not run Django, PostgreSQL, migrations, application tests, translation catalogs, live government APIs or deployment/recovery demonstrations. They pass no AT/QT business acceptance.

## Open inputs and next work

S03 can proceed now: clean dependencies and lock supported versions using official compatibility evidence. Read `prompts.json` for its full scope. One-office membership, Greek frontend, public GitHub and VM/DuckDNS hosting are confirmed; role details, client authority, financial policy, tax coverage, legacy ownership, scale, retention and operational ownership are not inferred as approved. Their exact blockers are in D01–D09.

AADE basic registry, myDATA and VIES have documentary routes, with registration/contract verification still needed. Full TAXISnet profile, AADE debt and e-EFKA retrieval remain conditional until approved private-application access is demonstrated. All six have unrun live tests and production disabled. S49 revalidates current contracts before implementation.

## Google Cloud VM checkpoint

**Create or select the VM at S08, after S02 and S07 are verified. No VM is needed for S03–S07.** At S08 collect the real project/billing, EU region/zone, existing-resource choice, administrator identity and DuckDNS hostname from the parameter sheet. Notify the user before that checkpoint. S09 deploys the HTTPS preview and S10 proves off-VM restore; live client data waits for the R1 gates.
