# Implementation state

Updated 2026-11-13. Current step: **S19 Prepared — dated cash accounts and categories**. Next step: **Complete S19 Docker gate**.

## Current selected work

S17 is based on pushed S16 Docker/G1 head
`e6fde507f634a0ccd2de80b197bfd883d0ab7ac9`, with 382 tests (356 passes and
26 exact known financial failures) and 652 passing boundary cases. Its actual
verification/evidence remains unchanged.

Read [financial_policy.md](financial_policy.md), the structured policy and the
[Greek accountant review sheet](financial_policy_review_el.md). S17 defines
17 operation contracts, state transitions, 12 invariants, 10 proposed D08
choices, 20 worked examples and 16 future denied-case specifications. The
reference checker validates 65 exact-decimal calculations; it does not execute
financial operations or replace PostgreSQL/concurrency tests at later steps.

D08 choices D08-01–D08-10 are accepted by the product owner and the named
accountant/office-owner review is recorded against the unchanged policy,
examples and document hashes. Names remain in the ignored private review;
the public receipt records its digest and declared review status. S17 is
Verified for this policy scope. S18 may implement the approved operations.
All 85 full application acceptances and the 26 financial fixes remain
Pending; no application/database/VM change is made by this completion.

## Historical selected work through S16

S15 is pushed at `5fc66cb6161c76482501b31499e8745f79181a93` with actual Docker
verification: 344 tests, 318 passes and the same 26 exact known financial
failures. S16 audits the complete implemented office boundary from that base.
Read [office_boundary.md](office_boundary.md) and the reusable inventory in
`accounting/office_boundary_matrix.json`.

S16 adds a route/admin/autocomplete/SQL/operator/adapter matrix and independent
PostgreSQL revocation lock-wait tests. Undeclared business routes fail closed;
admin autocomplete validates its source; archived new-work choices are removed;
the save helper rechecks authority after locking the office/user. Business
calculations and ten existing migrations remain unchanged. Local owner/MFA,
private configuration and the working VM are retained. The S14A demonstration
remains operator-reported at the limits in `evidence/S14A-operator-report.json`;
S16 does not perform a new deployment or create human accounts.

Native proof is Prepared until `python3 tools/verify_s16.py --record` passes in
its disposable laptop Docker project. The G1 record covers technical foundation
checks only. Future jobs/files/exports/portal/connectors, manual Greek browser/
client acceptance and all 85 full requirements stay Pending. After the Docker
gate, S17 requires the accountant's financial policy decisions before posting
changes. Historical completion records follow.

## Historical repository position

- Repository: [vtsakan/accounting_platform](https://github.com/vtsakan/accounting_platform), public by user choice.
- S07 branch: `step/s07-production-delivery`; resolve its implementation commit with `git rev-parse HEAD` after applying the patch.
- Pushed S06 baseline: `53e453b59bda9e2a21cbea59a086ed7ae26a45bb` on `origin/step/s06-financial-regressions`, including successful Docker verification (78 tests: 52 passed, 26 known failures).
- Pushed S05 baseline: `5a65a72906f7d3a5fccdcfd8aad0d0362a2bd7fa` on `origin/step/s05-local-postgresql`, including Docker build/migration/recreation persistence.
- Pushed S04/S03 baselines: `aae1250c441f76b804c532711bc00edc3258943e` and `1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718`.
- S02: `a6a251b434bce295ec04240a63e33a656dc7f92e`, tagged `s02-complete`; S01: `86d01abaf76fbbed669ae39a12b41ff4d47b831a`, tagged `s01-complete`.
- Original source: `3bb4c0240a48ee31ddbb19a26698bc25b3c79486`.
- Pushed S07 verification baseline: `a215beb91e2e49a5ffd1fa9ce8c751b8f3572234` on `origin/step/s07-production-delivery`; read through GitHub and fetched before S08. No successful CI run is inferred from that push.
- S08 is pushed at `git:e64861e0673e7c051d8aeb2c8ae79ef5fccf8aac` on `origin/step/s08-google-cloud`; fetched before S09 implementation.
- S09 is pushed/tagged at `s09-complete`, `git:eced8ea70e26f410ce2d234e41169d3fc05f529b`, with actual public/reboot verification. App commit is `git:70cf0d3dbc601163f33ae9c6f927605be50841aa`; S09 operator commit is `git:1968cd67424a368359c44cbddc055868ecf74d0a`.
- S10 uses `step/s10-backup-restore` from that exact tag. The actual operations commit is captured by the installer; the tested app image is reused.

## Completed foundation and selected scope

S01/S02 preserve provenance, decisions, connector evidence, deployment parameters and the confirmed Greek requirement. S03 locks CPython 3.12.16, Django 5.2.19, Psycopg 3.3.8 binary and Gunicorn 26.2.0; seven runtime packages remain. S04 supplies settings/secrets/redaction and Greek locale/templates/catalog. S05's actual Docker environment/migrations/persistence and S06's financial baseline are independently Verified in the pushed records.

S07 adds the root production Dockerfile, Gunicorn configuration, command-only entrypoint, live/ready endpoints, manifest static build/export, committed-source image helper, disposable delivery Compose/verifier and pinned GitHub workflow. Twelve health/configuration tests extend the strict suite to 90 cases. Existing development Compose, local .env/port 8001 and its PostgreSQL volume are preserved.

Original business models, forms, views, app routes, migrations and dependency locks remain unchanged from S06. Core URLs gain only health routes. No new migration/dependency or financial fix is introduced. The 26 known failures remain Open at S18–S24/S29; legacy English generated transfer descriptions remain S21. No new human-facing UI is added; health responses are machine schema keys.

## Current completion gate

<!-- S07-RESULT -->
The production Docker image, explicit migrations, strict PostgreSQL suite, non-root/private-file audit, static export and Gunicorn readiness outage/recovery are Verified. See evidence/S07-verification.json for the immutable image identity. S08 is eligible: create/select the Google Cloud VM and supply the deployment parameters.
<!-- /S07-RESULT -->

## Evidence and commands

- `evidence/S01-verification.json` through `evidence/S06-verification.json`: historical step snapshots; S05/S06 current records include the user's Docker verification.
- `evidence/S07-verification.json`: successful real Docker gate, immutable image/context identity, migrations and 90-test outcomes (64 passed, 26 exact known failures), health/static/log/configuration proof. Earlier failed attempts are historical.
- `evidence/S08-verification.json`, `cloud_inventory.json`, `google_cloud.md`: operator-executed cloud/host/access evidence, actual resources, commands, cost assumptions and limitations.
- `evidence/S07-configuration-checks.json`: observed Compose/YAML configuration-only checks; no Engine execution.
- `evidence/S07-static-export-fix.json`: reported Docker export failure, host regression results and guarded existing-image retry.
- `production_delivery.md`: image identity, explicit migrations, probes, static export, CI artifacts, warnings and next gate.
- `docker/image-pins.json`, `docker/ci-pins.json`: runtime/base image and immutable official action identities.
- `financial_regressions.md`, `evidence/S06-regression-baseline.csv`, `accounting/regression_cases.json`: unchanged financial failure contracts and fix mapping.

```bash
python3 tools/verify_s07.py --record
```

Use a committed checkout and local Docker Engine/Compose. Verification builds/reuses one full-commit image, uses its immutable ID throughout, explicitly migrates an empty PostgreSQL 17 database, tests the image, checks real outage/recovery and exports static from that same image. A random project/unused loopback port separates it from normal local services. Only its temporary containers/network/volume are removed; the tested image remains. Successful --record updates this state, steps and evidence, then announces the S08 VM checkpoint. Commit those evidence/state changes afterwards; the recorded image revision remains the code commit that was actually built.

For the already built user image, append `--image sha256:68e1e362af3d7d22e59f57ed7b0c3014093737ab621009044964fcb3c9b9af2f` after applying the static-export fix. The helper refuses application-context mismatches; the host-only fix does not change that context. See production_delivery.md for the full retry command and identity checks.

For daily tests use `python3 tools/dev.py test`. Earlier verifiers remain historical snapshots, including S06's exact 78-test count. The CI workflow uses tools/verify_delivery.py to discover all current tests and follow reviewed registry outcomes as future features change models/migrations; it saves evidence/tested image artifacts and cannot rewrite historical step records. No live deployment or credentials are configured.

## Limits and open inputs

Django production checks show zero errors and reviewed warnings W005/W021: HSTS includeSubDomains/preload remain disabled pending S09 hostname/TLS verification. Other warnings fail delivery verification. Actual Caddy/static/TLS serving is S09; restore/incident operations are S10. Two Gunicorn workers are a provisional default, not workload evidence.

All 71 user and 14 quality acceptance statuses remain Pending. D01–D09 unresolved domain/operator approvals remain open. S08 cloud resources are actually provisioned; no real client data, live messages/connectors, application deployment, off-VM restore or full financial/office/Greek frontend acceptance is claimed.

## Google Cloud VM checkpoint

**S08 is complete from operator execution; another VM purchase is not needed.** The user selected the new accounting-only project accounting-514109 and accounting-preview in europe-west1-b. See cloud_inventory.json for the exact retained disk, Premium static IPv4, private buckets, IAM and secret metadata. The biomedical/research project is outside this scope. S09 deploys HTTPS; S10 proves off-VM restore before live data. Legacy PostgreSQL 15 logical migration remains S25.

## S08 execution and repository tools

The actual lower-cost selection is regular e2-medium (4 GB RAM/shared core) with
Ubuntu 26.04.1 LTS amd64. Host Docker 29.9.3, Compose 5.7.0 and containerd 2.4.2
use the retained 50-GiB ext4 data disk at /srv/accounting. Mount dependencies/UUID
guards were configured, and mount/runtime startup plus cached network-disabled
hello-world passed after reboot. A physical missing-disk boot test was not run.

IAP SSH works from Cloud Shell and laptop. Effective public ingress is TCP 80/443;
TCP 22 is limited to IAP. Metadata-key SSH was observed; OS Login was not independently
verified. The dedicated accounting-vm service account has cloud-platform scope and
resource-specific roles. The final project IAM query returned no VM project-role
rows. Pinned signing/database secret version-1 reads passed without printing values;
project-wide secret listing was denied. No service-account JSON key was used.

Document CRUD/listing passed. Backup upload passed while VM reads/listing/overwrite/
delete returned 403. Anonymous requests returned 401, correctly allowed by the
fixed 401/403 expectation. The administrator removed the exact backup probe object.
Registry listing and reported read permissions passed; a real image pull is S09
proof after publishing an image. Seven-day soft deletion is not retention approval
or immutable-backup acceptance. Automated encrypted backup/key recovery/restore
remain S10 work.

The implementation workspace reviewed the user's output rather than executing GCP
itself. New configurable cloud/host/access replay tools have offline safeguards;
their own live execution is not claimed. Actual configuration is Git-ignored under
private/gcp.json. See google_cloud.md for init/inspect/reference provisioning and
evidence/S08-verification.json for exact local check counts/code commit.

```bash
python3 tools/verify_s08.py
```

Run from a clean committed checkout. This verifies the offline safeguards and
unchanged S07 application build context, not live cloud availability. No new app/
database suite, migration or financial fix was run by S08; all 26 known defects
remain scheduled. Application code, dependencies and Greek frontend are unchanged.
Monthly budget/alerts, measured workload and incident/restore/key custodians remain
open D06/D07 inputs. S09 still needs actual DuckDNS control and ACME contact, then
must prove Caddy/Compose/secret loading, HTTPS/login/static/reboot behaviour. The
app is not deployed yet. Redis/worker/exactly-one scheduler arrive only at S26.

## S09 selected HTTPS preview — 2026-11-09

<!-- S09-RESULT -->
Public DNS/TLS/login/static/isolation and actual reboot persistence are Verified. S10 is eligible; full release acceptance remains Pending.
<!-- /S09-RESULT -->

The user selected `totalaccounting.duckdns.org`. Public DNS observed on 09/11/2026
resolves exactly to reserved IPv4 `207.175.136.231` with no AAAA record. DuckDNS
account ownership/control and a real ACME contact are operator inputs; the public
DNS observation does not establish account ownership. Manual static DNS and Caddy
HTTP/TLS challenges need no DuckDNS token in the application or deployment.

Production Compose deploys the pinned app, PostgreSQL 17.11 and Caddy 2.11.9. Only
Caddy publishes 80/443; application/database networks are internal. Code, static,
private media and certificates use explicit separate paths. The host loads pinned
Secret Manager versions into tmpfs before Docker startup; container metadata access
is denied. The app database role is restricted. Installation explicitly migrates;
boot only resumes. Exact hosts/origin, secure cookies, a one-hour host-only HSTS
policy, overwritten proxy headers and Greek proxy errors are configured.

The only application-setting change is a persistent private MEDIA_ROOT; models,
views, migrations, locks and the 26 open financial regressions are preserved.
All newly authored product-facing proxy responses are Greek. No client messages,
real records, credential values or DuckDNS token are created or committed.

Read [HTTPS preview instructions](https_preview.md) and [S09 evidence](evidence/S09-verification.json).
Offline safeguards and native Caddy/Gunicorn/PostgreSQL TLS checks pass. The strict
90-test suite remains 64 passed / 26 known failures / zero unexpected outcomes.
Native proof uses a local internal CA and process restart; public ACME, Docker
execution, actual VM reboot and off-VM restore are not established by that proof.
The laptop must run current-source tools/verify_delivery.py, publish and ship the
immutable image, then tools/verify_s09.py --live --record before and after a real
reboot. Only the latter marks S09 Verified. All 85 acceptance statuses stay Pending.
S10 follows the completed S09 gate and must prove encrypted off-VM backup/restore
before real data. Redis/worker/one scheduler remain S26.

## S09 operator image gate and first deployment attempt

The current-source Docker gate is now operator-Verified for git:70cf0d3dbc601163f33ae9c6f927605be50841aa
(64 passed / 26 known failures / zero unexpected outcomes). Artifact Registry
publication succeeded. The initial ship failed with its underlying error hidden.
A subsequent operator read-only probe verified SSH/sudo, staged inputs and data
UUID; it listed no accounting containers. See evidence/S09-deployment-retry.json.

A confirmed Compose tmpfs parsing defect is fixed separately from the unconfirmed
original deployment failure. Safe stage diagnostics and a distinct clean operator
revision support retrying the unchanged, already published image. Apply the
follow-up patch, check the repository, push, then run preview.py ship --current-tools.
Actual VM image pull/setup, public HTTPS/login and reboot still require proof;
S09 is Prepared. Application code, locks, migrations and all 85 acceptance states
are unchanged. Read the retry section of https_preview.md before continuing.

## S09 confirmed image-store identity difference — 2026-11-10

The operator pushed the first deployment fix at git:8f16ea5a57c218411707c6fdcbd73626378d2063.
Its retry passed VM setup through registry pull and stopped at image-identity.
The read-only probe confirmed the containerd snapshotter, daemon image ID equal
to the recorded registry digest, the exact pinned RepoDigests reference, amd64,
UID 10001:10001, application revision 70cf0d3 and the unchanged source context.
The check had incorrectly required the laptop's build image ID on every store.

The new operator-only fix accepts only the recorded build ID or the recorded
registry digest, additionally requiring the exact registry reference, matching
optional descriptor, Linux/amd64, runtime UID, source URL, revision and context.
Running-container checks retain the pinned reference and validated IDs. Both build
and VM identities are retained in runtime evidence; no expected value is learned
from an untrusted VM response. Apply the follow-up identity patch and retry
preview.py ship --current-tools. App image, code, locks, migrations and all 26
financial failures are unchanged. The application context is still identical.
Actual app startup, public HTTPS/login and reboot proof remain Pending; S09 stays
Prepared. See evidence/S09-image-identity.json and the HTTPS retry guide.

## S10 selected backup and operating checks — 2026-11-10

Current S09 HTTPS/login/isolation and actual reboot proof are Verified. Earlier
Prepared statements above are historical step/retry notes. S10 is Prepared until
its own operator gate passes; see [backup/recovery instructions](backup_restore.md)
and evidence/S10-verification.json. No new VM, application image or human account
is required. The user elected to create a regular application account through
the office/accountant workflow at S13–S14.

S10 uses a consistent PostgreSQL 17 snapshot and custom dump, streaming age 1.3.2
encryption to an off-VM object and a non-secret recovery receipt. Decryption
identities stay on the laptop and in independently controlled recovery storage.
VM upload-only access is retained. Laptop recovery discovers an exact generation
without the source VM, authenticates/decrypts it and restores into a temporary
network-disabled PostgreSQL 17 container. No preview restore/migration occurs.

The source supplies two systemd timers, eight host metrics, external readiness,
nine Greek alert policies and bounded journal logs. S10 explicitly adds the VM's
Monitoring metric-writer project role; S08's earlier no-project-role observation
is historical. Preview retention and named incident/restore/key owners are entered
by the operator. Business retention, workload, availability and accepted-data RPO/
RTO approvals remain Pending. Nonempty private media stops backup; S38 must add
document recovery. Redis/worker/scheduler remain S26.

Native PG17/age proof restored all 16 public tables and 76 rows, including Greek
text and exact decimals, with the primary key removed. Concurrent writes after
snapshot export were excluded. Wrong keys, tampered ciphertext, changed restored
rows and oversized dumps were rejected; snapshot transactions and plaintext were
removed. These are local native checks, not actual GCS/Docker/timer/email proof.
All 85 release acceptances and 26 known financial defects retain their status.

Install from committed source; then run the actual isolated restore and explicit
alert test. Only `tools/verify_s10.py --live --confirm-alert-received --record`
may mark S10 Verified and make S11 eligible. Do not create s10-complete before
that gate. Application code, migration/table identities, runtime/maintenance
locks and production Compose are unchanged.

## S10 first cloud retry — 2026-11-10

The operator pushed S10 at git:40fad8974aed810811a10f27e351701c124a7f86.
Configuration completed with an independently stored key copy and seven-day
synthetic cleanup retention. Named operator/contact details remain private.
The first cloud action returned only HTTP 400, without a request identifier;
its exact failed operation is unproven from that output.

The follow-up aligns metric lookup URLs with Monitoring's reserved resource
expansion and adds bounded operation/RPC status/field-name diagnostics. It
provides read-only cloud-status for partial setup. Provider messages and all
request/contact/credential values are omitted. Retrying preserves the existing
private key and policy configuration and reuses exact existing resources.
Application image context, models, migrations, locks and Compose are unchanged.
S10 remains Prepared pending actual cloud retry, timer/upload, off-VM restore
and observed alert proof. See evidence/S10-cloud-request-fix.json.

## S10 systemd status compatibility — 2026-11-10

The operator's cloud retry completed: seven-day lifecycle, one notification
channel, one uptime check and nine alert policies were configured. Operations
installed at git:d3031b251a80f94c337b1943a3a78d27c868c5a1 without restarting
the app or migrating/restoring its database. The subsequent status report failed
when systemctl returned LastTriggerUSecMonotonic as `9h 5min 11.812969s`;
our integer-only conversion caused the confirmed ValueError. This status failure
does not establish the underlying backup/restore/alert outcomes.

The parser now accepts raw numeric microseconds and finite systemd time spans.
Zero/empty/unset values remain untriggered; malformed, negative, non-finite or
unknown values fail closed. Full status-report regressions retain the create-only
VM permission check and actual denied reads/listing. The status action now emits
its own stage checkpoint. App code, image context, locks, migrations, timer units,
private configuration, key identity and selected retention are unchanged.

Apply the status fix, verify and push it, then rerun `tools/operations.py install`
to select the new immutable operator release on the VM. Rerun status afterward.
No cloud reconfiguration or app publication is required. S10 remains Prepared
until the actual scheduled backup, off-VM recovery and observed alert gate pass.
See evidence/S10-systemd-status-fix.json and backup_restore.md.

<!-- S11-RESULT -->
Verified: 30 membership/backfill/access/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. Docker execution: True. Full office ownership, policy and release acceptance remain Pending.
<!-- /S11-RESULT -->

## S11 office/profile foundation — 2026-11-10

Based on pushed s10-complete (06cb37d3342115aebf53dd47e36b7900c3918fcd),
whose live backup/restore/monitoring gate is Verified. The selected S11 scope is
the Office/AccountantProfile schema, locked service, explicit reviewed mapping
and minimum missing/inactive-profile gate. See office_profiles.md. The old
business model definitions, tables, views, forms, first two migrations and
financial assertions remain intact; only synthetic auth fixtures gain explicit
membership. Current-source delivery discovers the new tests. The S11 exact
synthetic fixture is deliberately included in image context; private mappings
are not. No new human account, live mapping, VM change or production deployment.

Native PostgreSQL 17.11 upgrade/reversal rehearsal and 120 tests pass: 94 passed,
26 exact known financial failures, no unexpected outcomes. S11 is Prepared until
the local Docker verifier completes. Full row ownership is S12, authentication
S13 and owner office settings/invitations S14. D01 capability/handover and actual
legacy ownership approvals remain Pending. AT-OFF-01 full boundary and AT-LOC-01
full Greek release acceptance are not claimed by the S11 schema tests.

<!-- S12-RESULT -->
Verified: 37 ownership/backfill/access/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. Docker execution: True. Future entry-point coverage, policy and full release acceptance remain Pending.
<!-- /S12-RESULT -->

## S12 office ownership — 2026-11-10

Pushed S11 Docker verification is Verified at s11-complete
(e314645a4c6decc701fc0dca928d52d6f9b76491). Earlier S11 Prepared notes
are historical. Selected S12 adds nullable office columns at 0004, a complete
reviewed backfill, then guarded non-null/composite-key enforcement at 0005.
Original tables, PKs, first three migrations and S11 membership schema remain.
The five existing business models now validate ownership; views/forms/admin use
a fresh actor profile and scope every record/related choice. Six composite FKs
and five immutable-owner triggers protect raw/bulk writes. Cash names and
nonempty AFMs are unique per office; detailed AFM normalisation remains S15.

Native PostgreSQL 17.11 checks pass: 157 tests, 131 passed and 26 exact known
financial failures, no unexpected outcomes. The new 37 tests include actual
concurrency, staged legacy migration/dry run/apply/retry/rollback and source-row
fingerprint preservation. Existing assertions, registry and financial calculations
are retained. Malformed-filter/date failures remain S29; no assertion was changed
to turn an unrelated failure into a pass.

The admin's unscoped historical recent-action widget is omitted, retaining audit
entries and scoped individual history. Unsupported bulk actions and office
lookup overrides are denied. records/execution_record helpers are foundations
for future exports/files/workers, not delivered adapters. Greek access/ownership
errors and private no-store responses are tested. Full boundary acceptance is
S16; auth/MFA is S13 and capability/settings/invitations are S14.

S12 remains Prepared until local Docker reproduction with verify_s12.py. No human
account, actual legacy mapping, real import, cloud change or VM deployment occurs.
The running preview and its backup binding remain at their verified release.
See office_ownership.md before applying schema changes to any existing database.

## S13 staff authentication and privileged MFA — 2026-11-10

S12 is now operator-Verified at s12-complete (13ef2a1c8c96984da88c4cf73e695d128023555b):
157 tests, 131 passed, 26 exact known financial failures. Earlier S12 Prepared
statements above are historical. S13 adds Greek Django sign-in/out/password
recovery, owner/platform mandatory MFA, local private QR enrolment, single-use
backup-code recovery, server session bounds/revocation and shared PostgreSQL
rate budgets. Platform authority gives no office-record bypass. Recovery keeps
MFA enabled; code reuse and concurrent activation/reset are rejected.

Read staff_authentication.md. Migration 0006 adds authentication metadata only;
first five migrations, office/business definitions, money calculations and
financial assertions are preserved. The additional maintained OTP/encryption/QR
libraries retain all previous framework versions. Authored mail templates are
included explicitly in the production context; captured mail is excluded.
Production SMTP is disabled by default, while local recovery uses private capture.

Only isolated native PostgreSQL proof is available in this workspace; S13 remains
Prepared until the laptop runs tools/verify_s13.py --record on Docker. The gate
never opens the existing development database or VM. All 85 release acceptances
remain Pending, including staged Greek/accessibility and full security review.
Human account onboarding/settings/invitations are S14, after S13's Docker gate.
No human account, live email, production migration, cloud change or deployment is
made. Keep the verified VM release and S10 recovery binding unchanged.

## S13 Docker profile-environment retry — 2026-11-10

The operator's first local Docker run reached the 216-test suite, reproducing
26 known financial failures plus six unexpected production-configuration
failures. The test helper had inherited Compose's development AUTH_PUBLIC_ORIGIN
into synthetic production settings; the production HTTPS/allowed-origin guard
correctly rejected it. All six failures were reproduced independently with
AUTH_PUBLIC_ORIGIN=http://localhost:0. This is a profile-test isolation defect.

The follow-up strips inherited authentication/mail/SMTP configuration before
applying each test's explicit values. Production origin validation and auth
implementation remain unchanged. Original configuration and financial assertions
are preserved; two new cases cover credential isolation and explicit valid/
invalid origin overrides. The current suite has 218 tests, including 61 S13
checks. See evidence/S13-environment-fix.json and staff_authentication.md.
S13 remains Prepared until the operator's Docker retry passes. No completion
tag, human account, cloud change, live mail or VM deployment is made by this fix.

<!-- S13-RESULT -->
Verified: 61 authentication/MFA/recovery/session/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. Docker execution: True. Live mail/deployment, S14 onboarding and full release acceptance remain Pending.
<!-- /S13-RESULT -->

The committed-source native retry with the Compose HTTP origin inherited passed
218 tests: 192 passed, the same 26 registered financial failures, and zero
unexpected outcomes. Hash-lock/catalog/secret checks and restricted-role DDL also
passed. This remains native evidence; the operator's Docker retry is Pending.

## S14 current handoff

The actual pushed s13-complete baseline is
16501f4ffeafc15f7361bce1ef790e8e19031f77. Its operator Docker retry is Verified:
218 tests, 192 passed plus the same 26 known financial failures. Earlier S13
retry-Pending text describes historical preparation and is superseded by that
pushed evidence.

S14 implements Greek office identity/contact settings, expiring single-use
recipient/office invitations, approval, deactivation, the selected owner/accountant
capabilities, mutual password/MFA handover, last-owner database guards and an
append-only office-scoped staff audit. The product owner explicitly selected Read
and post and Colleague accepts; office_role_policy.json records that scope.
Future capabilities and all 85 full requirement acceptances remain Pending.

Use tools/verify_s14.py --record on laptop Docker from committed source. Native
PostgreSQL proof is Prepared. See office_settings_staff.md for a regular first
owner after that gate, in a separate empty local project with no admin flags.
No human account, live email, client import or VM deployment has been performed.
The running S09 image/S10 recovery binding is preserved. S15 follows the Docker
gate; a reviewed S11–S14 deployment is a separate operation.

<!-- S14-RESULT -->
Verified: 60 office/settings/invitation/role/handover/concurrency checks pass on PostgreSQL 17; the strict suite retains 26 known financial failures. Docker execution: True. Live mail/deployment and full release acceptance remain Pending.
<!-- /S14-RESULT -->

## S14 referrer/CSRF follow-up — 2026-11-12

The pushed S14 Docker result remains historical Verified evidence. The owner
account bootstrap succeeded, but actual browser login exposed Origin:null caused
by blanket no-referrer response headers. The follow-up changes normal form
responses to same-origin, retains no-referrer on bearer-link redirects/errors,
and fixes the proxy default. No CSRF/origin checks, office/MFA controls, accounts,
passwords, migrations, locks or financial assertions are removed or reset.
Read referrer_csrf_fix.md and evidence/S14-referrer-fix.json. The new native
PostgreSQL proof remains Prepared until the operator's Docker and browser retry.
The client demo stays in accounting-client-demo on port 8003; reuse the existing
vtsakan owner. VM migration/image inspection and demo deployment are still pending.

## S14A selected VM demo follow-up — 2026-11-12

The operator has now reported the corrected S14 Docker gate: 287 tests, 261
passes, 26 registered financial failures and no unexpected outcomes. Actual
local owner login also succeeded; recovery downloads were moved outside Git.
These observations supersede the retry-Pending text immediately above.

Selected work prepares the requested sample office/accounts on the existing VM.
Read vm_demo_upgrade.md and evidence/S14A-demo-preparation.json. The inspected VM
still runs S09 and accounting migrations 0001/0002 with working S10 operations.
The prepared operator flow rejects users/non-marker business data, preserves the
source database, clones/migrates only the selected synthetic database, requires
an explicit two-record ownership plan, updates backup binding and proves the
new backup off-VM before interactive regular-owner bootstrap. It also supports
password/TOTP-verified captured staff invitations without live SMTP.

Native PG17 restricted-role migration, source preservation, invitation and
current production smoke proof is Prepared. Actual Docker image delivery,
publication, VM cutover, new backup/restore and browser MFA/accountant approval
remain Pending. No VM change, human account or live message is made while
preparing this follow-up. Original S10–S14 evidence, completion tags, migrations,
dependency locks and financial assertions remain intact; all full requirement
acceptances stay Pending. S15 is unchanged.

<!-- S15-RESULT -->
Verified: 57 workspace/migration/archival/concurrency checks; 344 total tests with 26 known financial failures and no unexpected outcomes. Docker execution: True. Greek browser and full requirement acceptance remain Pending.
<!-- /S15-RESULT -->

<!-- S16-RESULT -->
Verified: 38 integrated tests; 652 explicit boundary cases; 382 total tests with 26 exact known financial failures and no unexpected outcomes. Docker execution: True. G1 technical evidence is recorded; browser/client, future modules and full requirement acceptance remain Pending.
<!-- /S16-RESULT -->

<!-- S17-RESULT -->
Verified: 17 operation contracts, 10 explicit D08 decisions, 20 worked examples and 65 exact-decimal arithmetic checks; 16 denied specifications are for future application tests. Application/database/cloud execution this step: none. D08 review: Approved. All full requirement acceptances remain Pending.
<!-- /S17-RESULT -->

<!-- S18-RESULT -->
Verified: 46 S18 tests; 428 total; 13 corrected known cases, 13 still reproduced, no unexpected outcomes. The 652-case office boundary is retained. Docker execution: True. Core correction uses owner/password/recent MFA; correction UI, dated opening/balance/report/allocation work remain later steps. No existing demo/VM migration performed.
<!-- /S18-RESULT -->

<!-- S19-RESULT -->
Prepared: 67 S19 tests; 495 total; BAL-001–003 corrected, 10 known failures still reproduced, no unexpected outcomes. All 784 current boundary cases passed, retaining the original 652. Docker execution: False. Legacy amounts and history remain; opening dates require explicit owner/password/recent-MFA review. Signed adjustments are immutable and do not create operating cash. No existing demo/VM migration performed by verification.
<!-- /S19-RESULT -->
