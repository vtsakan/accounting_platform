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

## Current checkpoint

S12 is operator-Verified and pushed/tagged at s12-complete
(13ef2a1c8c96984da88c4cf73e695d128023555b), with 157 tests: 131 passed and
26 exact known financial failures. Selected S13 adds Greek staff authentication,
password recovery, privileged MFA and bounded sessions/shared PostgreSQL limits.
Read staff_authentication.md and evidence/S13-verification.json. Use
tools/verify_s13.py --record for the disposable Docker completion gate; native
PG17 proof remains Prepared. No human account, live SMTP, VM/database change or
deployment occurs. S14 handles regular office onboarding/invitations and D01
capabilities. Preserve original migrations/calculations and the 26 financial
failure assertions. S13 adds migration 0006 and five runtime packages, retaining
all seven previous versions and the maintenance lock. Keep the running preview
and its recovery binding unchanged; do not run old context-pinned installers.

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
