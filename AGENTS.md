# Accounting platform implementation instructions

Work on the accounting-office platform described by ACC-URS-001 and ACC-IMP-001. Apply this instruction block and the selected step S01 to S64. Read the current repository, its applicable instructions, docs/implementation/state.md, decisions.md and traceability.csv before changing anything. Use actual files and observed results as the source of truth. Preserve unrelated work and existing migration/table identities. Implement only the selected step and its necessary supporting changes.

Keep Django and PostgreSQL as the modular application, with templates and Bootstrap initially. The planning baseline uses Python 3.12, supported Django 5.2 LTS, PostgreSQL 17 and Docker Compose. Check official support/compatibility when locking versions; record a justified change rather than silently changing the stack. Deploy through Caddy and Gunicorn on one Google Cloud VM with a reserved static IPv4 address and an initial DuckDNS hostname. Use private Cloud Storage and workload identity. Add Redis, a worker and exactly one scheduler when S26 introduces them.

All product-authored frontend content must be Greek under CR-001 / UR-LOC-01: staff screens, client portal, authentication/admin pages, accessible labels, validation, help/errors, notifications, user-facing email and report/export headings. Preserve original user/provider content, identifiers and brand names. Internal code and developer documentation may remain English. Read docs/implementation/frontend_language.md and docs/requirements/CR-001-Greek-frontend.md. Establish the Greek locale in S04 and include Greek copy in every later UI change; never claim the existing application is translated merely because the requirement is recorded. The effective baseline has 71 UR and 14 QR; keep original baseline documents immutable.

Enforce one office per active accountant; an office may contain several accountants. An active mandatory accountant profile supplies office context, never an untrusted submitted office identifier. Check office/client ownership on reads, writes, related choices, admin, exports, files and job execution. Keep portal identity and client grants separate from staff membership. Revocation must block the next protected action.

Keep agreement terms, charges, cash receipts/payments, allocations and reversals distinct. Use fixed decimal money and atomic services; transfers have zero operating income/expense effect. Preserve posted originals and correct them by attributable reversal. Keep office fee/cash data separate from client myDATA sources and tax forecast snapshots.

Use synthetic data until the R1 acceptance and restore gates pass. Protect secrets and private documents, mask credentials and keep keys separate from encrypted data. Use current official contracts for integrations and tax rules; simulated responses, an unavailable connector and an unrun test are not evidence of delivery. Track proposed policy approvals separately from code completion. Excluded scope remains excluded unless a recorded decision changes it.

Check the selected step's dependencies and required inputs. Use existing authorised values and proceed with reversible local work. If cloud access, credentials or a domain decision is missing, prepare the relevant code/configuration, record the exact blocker, and distinguish Prepared from Verified. Provision or change only the explicitly selected authorised environment; do not infer production targets. Send live client messages only through an explicitly confirmed product action or execution instruction.

Run meaningful checks for the change on PostgreSQL where financial or database behaviour matters. Include relevant denied-access and retry/concurrency cases. Report actual commands and results; label checks that could not run. Update implementation state, decisions and traceability with the step, requirement/test identifiers, evidence, actual commit when available and remaining blockers. Do not invent a commit or mark an approval on the reviewer's behalf.

Finish with a concise result: what changed; files/migrations and commands; checks passed/failed/not run; manual acceptance still needed; and the next eligible step. Stop after this selected step. If its scope needs subdivision, record SxxA and SxxB under the original identifier without renumbering later steps.

## User execution preference — effective from S20

The user explicitly requests code-only delivery and will execute tests/builds.
Do not run test suites, Docker builds/containers, database migrations or native
verification during implementation. Provide source/patch and optional operator
commands. Record unexecuted work as Prepared, never Verified. Do not block
code delivery on a missing operator receipt for the previous source step. This
explicit preference supersedes the historical agent-run verification workflow.
Preserve existing accounts, MFA, volumes, fourteen migrations and historical
receipts. The S20 apply helper performs Git/source operations only.

## Current checkpoint — S21

Deliver S21 as code only; the operator owns all test/build execution. Start from
pushed S20 head 8871e76c20c20dd912b55861da5209f72a17978c, whose operator receipt
records 511 tests, 510 passes and only TRF-001 reproduced. Keep that historical
receipt unchanged. Read internal_transfers.md. Reuse S18 command/pair/audit SQL
and all fourteen migrations. Normalize transfer account IDs, preserve stable
retry identity including retired-reference replay, and expose a common audit
reference in the Greek interface. Cash balances/history include both legs;
operating totals/categories exclude explicit transfers before filtering totals.
Legacy UUIDs alone never classify transfers; reviewed legacy pairing is S25.
Single-leg correction stays denied; paired correction administration remains
S24. Preserve all 511 previous test names/assertions, the 784 boundary cases,
auth/MFA/referrer policies and locks. TRF-001 is now an expected-pass target,
not an observed pass. New optional S21 tests are supplied but unexecuted.
Source is Prepared until the operator runs tools/verify_s21.py --record. The
apply script must only change Git/source/metadata. Do not touch Docker, local
demo, accounts, keys, databases or VM on apply. Stop after S21.

## Historical S20 checkpoint

S20 was verified by the operator on PostgreSQL 17: 511 tests, 510 passes and
TRF-001 as the sole expected failure. The S20 receipt is historical evidence;
S21 code delivery must not overwrite it. Greek ordinary entry, remarks,
optional references, typed combined filters, full-scope cash totals and
pagination are retained. The template-link correction preserves the S04
presentation fixture and real ORM links. No S20 test assertions are relaxed.

## Historical S19 checkpoint

## Current checkpoint

S19 is selected from the actual pushed/verified S18 head
22dbd3a12816cfaceb62958ad45e19231669f3be (428 tests, 415 passed, 13 exact
known failures). Read docs/implementation/cash_accounts_categories.md.
Preserve original migrations 0001–0012, all historical evidence, approved S17
policy/review, exact-money guards, every old test name and financial assertion.
S19 adds migrations 0013/0014, Greek cash/category screens, one dated cash
selector, explicit owner/password/recent-MFA opening approval and immutable
signed adjustments outside operating cash. Existing opening amounts are retained
with an unknown date until their owner reviews the cutoff; never infer it or
silently rewrite a legacy amount. Human adjustments are effective today; wider
closed-period/correction UI remains S24. Categories cannot cycle, cross offices
or delete history. New work excludes retired references; original-linked
reversals retain them. Retain all 652 old boundary cases and cover every new
route. BAL-001–003 now pass; the other 10 known defects remain for their steps.
Native PostgreSQL proof is Prepared. Complete tools/verify_s19.py --record on
laptop Docker, commit the generated evidence/state once, then explicitly migrate
and restart the retained local demo. Keep the VM, people, MFA/keys/volumes and
all 85 full acceptances unchanged. Do not reuse old context-pinned deployment
installers. Stop after S19; S20 follows its Docker gate. Below is history.

## Historical S18 checkpoint

S18 is Verified in the operator's Docker proof: 428 tests, 415 passed and 13
exact known failures. The retained demo was explicitly migrated through 0012
and restarted successfully. Core correction requires owner/password/recent MFA;
its full UI is S24. See docs/implementation/financial_posting.md and the
unchanged S18 verification evidence. This history is not a new VM deployment.

<!-- S17-REVIEW-CLOSED -->
S17 financial-policy choices D08-01–D08-10 are accepted by the product owner.
The named accountant/office-owner review was supplied in the project
conversation and recorded privately against the unchanged ACC-FIN-001
v0.1 policy/example/document digests. Read evidence/S17-verification.json
and evidence/S17-product-owner-acceptance.json. This is a declared human
review, not independent identity verification or application acceptance.
S17 is Verified for this scope; S18 is next when selected. D08-10 records
owner correction rights with recent MFA; actual capabilities/services
remain to be implemented at S18/S24. All 26 known financial failures,
85 full acceptances, original migrations/locks and S16/G1 proof remain
unchanged. Keep the local demo, accounts/MFA and VM intact. Names stay
in ignored private/; never add the named review file to Git.
<!-- /S17-REVIEW-CLOSED -->
The checkpoints below are historical.

S17 is selected from the actual pushed S16 Docker/G1 head
e6fde507f634a0ccd2de80b197bfd883d0ab7ac9. S16 is Verified: 382 tests,
356 passes, 26 exact known financial failures and 652 passing boundary cases.
Read docs/implementation/financial_policy.md and financial_policy.json, the
Greek review sheet and all 20 worked examples. S17 specifies 17 operations and
10 unresolved D08 choices; tools/verify_s17.py checks 65 exact-decimal example
results and rejects stale/incomplete human-review records. This is document/
reference arithmetic, not production finance, database or concurrency execution.
Keep application code, 10 migrations, dependency locks, all 382 tests/26 known
failures, S16/G1/history evidence, accounts, MFA, local demo and VM unchanged.
S17 remains Prepared until the accountant/office owner review the exact policy,
examples and documents. An optional private review file records their actual
names/roles, time, reference and selections; do not invent them or interpret
passing arithmetic as business approval. An alternative choice needs revised
policy/examples and a new bound review. No S18 posting behaviour changes before
its required D08 decisions are recorded. All 85 full acceptances remain Pending.
The checkpoints below are historical.

S16 is selected from actual pushed S15 Docker head
5fc66cb6161c76482501b31499e8745f79181a93 (344 tests: 318 passes and 26 exact
known failures). Read docs/implementation/office_boundary.md and the reusable
accounting/office_boundary_matrix.json. Run tools/verify_s16.py --record in a
disposable local Docker project to complete the G1 technical gate; native PG17
proof is Prepared. Retain all ten migrations and original 344 tests, money
calculations, locks, auth/MFA/referrer policy, accounts and recovery material.
New business routes need a declared capability and matrix coverage; identity
exceptions bind exact module/name and admin uses its dedicated permissions.
Write authority is checked after the office/user lock wait. Maintenance CLI is
an operator/database trust realm, not an unscoped staff API. Files, actual jobs,
exports, portal and connectors stay Pending until implemented and added to the
matrix. All 85 full acceptances and manual Greek browser/client review remain
Pending. Keep the working VM unchanged by this step. Do not rerun the old S14A
updater against existing people/office data. After a successful --record, commit
the six generated evidence/state files once; do not reapply or rerun solely to
save their output. Next is S17 accountant review of D08, not financial changes.
The checkpoints below are historical.

S15 is now selected. Start from the actual pushed S14 demo head
ab9602592cb699684450bc4ee70438f80d30351f, not the older s14-complete tag.
The user reports the VM demo working after apply/restore/bootstrap/login;
record that as operator-reported, without inventing missing stage receipts.
Read docs/implementation/client_supplier_workspace.md, counterparty_migration_map.json
and S15 evidence. Add independent roles, explicit classification, normalized
office AFM, Greek workspace and archive/restore retaining financial history.
Migrations 0009/0010 preserve IDs and all eight prior files; invalid/duplicate
legacy AFMs stop for review rather than merge or overwrite. Keep existing
accounts, keys and recovery binding intact. The local Docker completion gate
is tools/verify_s15.py --record; native PG proof is Prepared. Browser/keyboard
acceptance remains Pending. Do not rerun the S14A S09-only updater against a
database with people or deploy S15 as part of this implementation. S16 follows
the S15 Docker gate. The checkpoints below describe earlier handoffs.

Selected S14A follow-up: the user requests a sample office and regular accounts
both locally and on the existing VM. The corrected S14 Docker gate was reported
Verified on 2026-11-12: 287 tests, 261 passes and the same 26 known financial
failures; actual local owner login now works. Reuse that local demo/owner.
Read docs/implementation/vm_demo_upgrade.md. The VM remains S09/0001–0002.
The new operator flow accepts only its exact two markers with no users, clones
the original database, applies an explicitly reviewed ownership map, and binds
the new image/database to S10 backups. Keep the original database unchanged.
Native proof is Prepared; actual Docker publication/VM cutover/new off-VM
restore/browser MFA are operator gates. No human VM account is made by apply.
Do not use the old context-pinned ship/installer to bypass the staged migration,
nor alter existing completion tags, original migrations/locks or financial
assertions. Captured invitations do not send live mail or implicitly approve
staff. Stop after this S14A follow-up; S15 has not been selected.

The following S14 checkpoint text records the earlier handoff.

S14's operator Docker gate is Verified at s14-complete (dc4cdc5). Its browser
login subsequently exposed the no-referrer/Origin:null defect. The selected
S14 follow-up uses same-origin on forms and no-referrer only on bearer-link
redirects, including proxy errors. Read referrer_csrf_fix.md and its evidence.
Do not trust null origins or disable CSRF. Existing accounts/volumes and the
original eight migrations are preserved. The correction is Prepared pending
its own local Docker/browser retry; keep the existing completion tag immutable.

S13 is operator-Verified and pushed/tagged at s13-complete
(16501f4ffeafc15f7361bce1ef790e8e19031f77), with 218 tests: 192 passed and
26 exact known financial failures. Selected S14 adds Greek office settings,
recipient-bound invitations/approval/deactivation, explicit capabilities,
mutually verified ownership handover and an append-only scoped staff audit.
The product owner selected Read and post and Colleague accepts; read
staff_authentication.md, office_settings_staff.md and office_role_policy.json.
D01 is resolved for these current operations only. Future reversal/export/
connector/job capabilities and full release acceptance remain Pending.
Use tools/verify_s14.py --record for the disposable local Docker completion
gate; native PG17 proof remains Prepared. Bootstrap the first regular owner
only after that gate, using the documented separate empty local project and
bootstrap_office_owner command, not a Django administrator. No human account,
live SMTP, VM/database change or deployment is performed by implementation.
S14 adds migrations 0007/0008 without changing the original six, money models,
financial test assertions or dependency locks. Keep the running preview and
its recovery binding unchanged; do not run old context-pinned installers.

The following earlier preparation checkpoints are historical.

S11 is now Verified and pushed/tagged at s11-complete
(e314645a4c6decc701fc0dca928d52d6f9b76491), including the actual Docker
120-test gate. Selected S12 adds ownership to all five old business tables.
Read office_ownership.md and evidence/S12-verification.json. Keep this work local
and synthetic. Migration 0004 is nullable; 0005 refuses unreviewed records before
non-null/composite-key enforcement. Never fill a default office or alter original
row identities. Use the dry-run backfill_office_records command with an actual
reviewed mapping when migrating a selected existing database. Current tests use
synthetic mappings only. Use tools/verify_s12.py for the disposable PG17 gate;
native proof is Prepared, local Docker proof completes the step. Keep all 26
financial failures and original financial assertions/calculations. Full boundary
coverage is S16, authentication/MFA S13, and capability/settings/invitations S14.
No human account, VM change, live-data import or production deployment is made.

S10 is now Verified and pushed/tagged at s10-complete
(06cb37d3342115aebf53dd47e36b7900c3918fcd). Read its live evidence: actual
timer/upload, independent-key laptop Docker restore and received alert passed.
Earlier S10 Prepared statements below describe its historical implementation.
Selected S11 adds Office/AccountantProfile and a minimum missing/inactive-profile
gate. Read office_profiles.md and evidence/S11-verification.json. Keep this step
local and synthetic: full record ownership is S12 and authentication/MFA is S13.
Office settings/invitations are S14, not S11. No automatic memberships, default
office, real legacy mapping, human account, cloud change or new app deployment.
Use tools/verify_s11.py for the disposable PG17 gate; native proof is Prepared,
local Docker proof completes S11. Preserve the 26 financial failures and S10's
verified app/bucket/key/timer configuration. Do not run its old context-pinned
operations installer after the S11 application context changes.

S09 is Verified from the operator's public checks and actual changed-boot-ID
verification, pushed/tagged at s09-complete (eced8ea70e26f410ce2d234e41169d3fc05f529b).
S10 adds operator-only encrypted backups, isolated laptop recovery and Monitoring;
read docs/implementation/backup_restore.md and evidence/S10-verification.json.
Keep S10 Prepared until its actual GCS upload, timer, off-VM Docker restore with
the independently recovered key, and observed alert gate passes. Native PG/age
proof is not that gate. No application account is needed for S10; the user elected
to wait until the regular office/accountant onboarding at S13–S14. Do not create
an administrator as a substitute. Preserve the verified S09 app image and existing
cloud resources; the only new VM project role is Monitoring metric writer.

S08 cloud foundation is Verified from the user's Cloud Shell/VM execution and reboot/access probes. Read docs/implementation/google_cloud.md, cloud_inventory.json and evidence/S08-verification.json. The selected accounting-514109/accounting-preview environment already exists: e2-medium, Ubuntu 26.04.1, Premium static IPv4, retained 50-GiB data disk, IAP SSH and metadata-authenticated resource IAM. New replay utilities have local safeguards; their own GCP execution is not claimed. Do not recreate/reformat existing resources or infer another project. Keep actual deployment configuration under ignored private/gcp.json; no secret values or service-account JSON keys. S09 targets user-selected totalaccounting.duckdns.org; read docs/implementation/https_preview.md and the current state/S09-verification.json for its gate status. DNS matches the reserved IPv4 with no AAAA, and its completion gate requires actual image publication/pull, public TLS/login and VM reboot proof. Use the current-source verify_delivery.py gate because S09 deliberately changes production MEDIA_ROOT; preserve historical S07/S08 evidence. Do not recreate cloud resources or mark S09 Verified from native proof. S10 must prove off-VM restore before live data. Cost/budget/retention/operational approvals remain separate.

Read docs/implementation/state.md before editing. S05 and S06 have pushed Docker verification. S07 supplies the production image and delivery checks; read docs/implementation/production_delivery.md and require successful tools/verify_s07.py --record on a local Docker Engine before S08. Native Gunicorn/PostgreSQL proof remains Prepared and cannot complete the image gate. Build from clean committed source with tools/image.py; reuse its immutable image identity for migration, tests, static export and deployment. Keep migrations explicit; production startup never imports data or migrates automatically. Read docs/implementation/financial_regressions.md and use the strict accounting test runner through tools/dev.py test. Preserve correct assertions and the 26 known failures until their corrective steps; unrelated errors, tracked skips and unexpected passes fail. Read docs/implementation/local_development.md; preserve the PostgreSQL 17 volume and never attach the old PostgreSQL 15 data directory to it. Keep local WEB_PORT choices in .env; disposable verification selects an unused loopback port. Use explicit settings profiles and read docs/implementation/settings_and_locale.md; core.settings.build is static-collection-only. Keep the compiled Greek catalog in sync with its PO source. Use the unchanged hashed runtime/maintenance locks and read docs/implementation/dependencies.md before updates. Use docs/implementation/prompts.json with the original prompt reference. Notify the user to create/select the Google Cloud VM at S08 only after the S07 Docker gate passes. Do not treat build/health checks or regression capture as passed business, TLS, backup/restore or release acceptance.
