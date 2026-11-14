# Decision register

Recorded 2026-11-07 for S02. [Machine-readable register](decision_register.json) is the source for these records. Recommendations are implementation proposals, not domain approvals. Named role owners must be assigned to actual people before their acceptance gates.

## Confirmed constraints

- Each active accountant belongs to exactly one office. Source: User instruction; UR-OFF-01.
- Deploy initially on a Google Cloud VM with a DuckDNS hostname. Source: User deployment instruction.
- Use the public vtsakan/accounting_platform GitHub repository. Source: User-created repository and successful S01 push.
- All product-authored frontend content must be Greek, including staff and client experiences. Source: User instruction 2026-11-07; CR-001; UR-LOC-01.

S13 technical implementation (2026-11-10): Django auth plus django-otp, locally
generated QR and externally keyed seed encryption; owner/platform MFA, single-use
backup recovery, bounded sessions and PostgreSQL auth throttles. Recovery mail
is captured locally and disabled in production until provider/sender opt-in.
These are the selected S13 safeguards, not approval of the outstanding D01
capability/succession policy. S14 office invitations/regular onboarding and S16
integrated isolation remain Pending. See staff_authentication.md and S13 evidence.

S13 verification correction (2026-11-10): production-profile probes isolate
inherited authentication/mail environment settings as well as Django/database
settings. Explicit production HTTPS/origin validation is retained, including
negative tests. The six operator-reported configuration failures were reproduced;
the Docker retry is Pending. No domain-policy approval changes.

S14 follow-up (2026-11-10): the actual S13 Docker retry passed 218 checks
(192 passed plus 26 known financial failures), and s13-complete is pushed.
The earlier retry-Pending statements above are historical. D01 choices below
were then explicitly selected for current operations; unrelated decisions and
full requirement acceptance are unchanged.

## D01 — Office membership and permissions

Owner: Product owner (vtsakan). Status: **Current S14 operations confirmed; future capabilities pending**. Gate: G0; S14 technical gate and S16 boundary acceptance remain separate.

The product owner selected **Read and post** and **Colleague accepts** in the
S14 implementation conversation on 2026-11-10. Ordinary accountants may manage
all clients and current financial entries within their office. Office identity,
staff access and role administration are owner-only. An owner proposes handover
after password/recent MFA; the addressed same-office colleague accepts after
password/recent MFA, becomes owner, and the source becomes accountant. An
already-owned active office must retain an active owner. Unknown operations
are denied; there is no custom role editor.

Implementation evidence: `office_role_policy.json`, `office_settings_staff.md`,
`accounting/capabilities.py`, `accounting/tests_staff.py` and S14 verification.
Invitations are recipient/office-bound and single-use; acceptance creates an
inactive accountant profile and explicit owner approval activates access.
The 24-hour link, seven-day proposal and management-rate defaults are technical
choices, not separately asserted product-owner approvals.

Open inputs for later steps:

- Capabilities for attributable reversals, exports, connection secrets and jobs.
- Integrated S16 boundary acceptance and final financial/release acceptance.

Dependent steps: S11, S12, S14, S16, S17, S41, S50.
Evidence: UR-OFF-01, UR-OFF-03, UR-OFF-04, QR-01.
Approval evidence: **Explicit S14 conversation selections recorded in office_role_policy.json**.

## D02 — Client scope and portal grants

Owner: Product owner and participating office owner. Status: **Proposed; representative verification pending**. Gate: G0 before WP1; final grant policy before S43/S44.

Options:

- Independent client records per office, separate portal identities and explicit representative-approved grants.
- A shared global client directory with office relationships and a separate ownership model.

Recommendation: Keep client records office-scoped, allowing the same AFM in different offices. Separate staff membership, portal identity, representative verification and data grants. Revocation blocks the next protected action and queued job execution.

Open inputs:

- Evidence and reviewer needed to verify a business representative.
- Who can grant access, to which files/services, and for how long?
- Treatment of multiple representatives, disputes and staff reassignment.

Dependent steps: S15, S16, S43, S44, S45, S46, S50, S54.
Evidence: UR-CRM-06, UR-POR-02, UR-POR-05. Approval evidence: **not recorded**.

S15 implementation boundary (2026-11-12): UR-CRM-06 and the selected prompt
already require independent office identities/AFMs; the staff workspace uses
that scope without a global directory. Portal identity, representative proof
and grants remain S43/S44; those pending policies are not approved here. AFM
normalization/format checks are a technical input contract, not registry or
checksum proof. Legacy classification remains explicitly unreviewed until a
person chooses individual/business. Reversible archive preserves history and
does not decide statutory retention or authorize deletion under D07. See
client_supplier_workspace.md and counterparty_migration_map.json. All full
requirement acceptance statuses remain Pending.

## D03 — Authorised government-service access

Owner: Service account owner with developer. Status: **Documentary feasibility reviewed; access not demonstrated**. Gate: G0 before connector commitment; S49 contract gate.

Options:

- Use documented service-specific interfaces after proving eligibility and client authority.
- Keep a connector unavailable pending approved access; allow separately reviewed manual document upload where the document module permits it.

Confirmed evidence: Use current official contracts; unavailable or unapproved retrieval is never represented as success.

Recommendation: Prioritise AADE basic registry, myDATA ERP retrieval and VIES documentary routes. Keep full TAXISnet profiles, AADE debt retrieval and e-EFKA retrieval conditional. Do not infer private-SaaS eligibility from a public-sector endpoint or portal login.

Open inputs:

- Service-specific account registrations, credentials and client delegation.
- Permitted production use and contract/schema versions at S49.
- Redacted response fixtures, negative cases, rate limits and document ownership checks.

Dependent steps: S49, S50, S51, S52, S53, S54, S60, S61, S62, S63.
Evidence: connector_feasibility.json, UR-INT-01, UR-INT-02, UR-INT-03, UR-INT-04, UR-INT-05, UR-INT-06, UR-INT-07. Approval evidence: **not recorded**.

## D04 — Tax forecast coverage and reference cases

Owner: Accountant reviewer (person to be assigned). Status: **Pending accountant review**. Gate: G0 outline; G5/S55 final approval.

Options:

- Release a named taxpayer/year subset backed by reviewed reference cases.
- Attempt all taxpayer types and years in the first forecast release.

Recommendation: Approve a narrow, explicit coverage matrix before coding calculation rules. Unsupported cases show a Greek explanation. Treat results as forecasts, retain rule/input snapshots and keep office fees separate from client tax sources.

Open inputs:

- Supported tax years, taxpayer types, VAT regimes and form versions.
- Rounding, code 401 provenance, corrections and missing-data handling.
- Accountant-approved ordinary, zero, credit and boundary examples for VAT, income tax and presumptive expenses.

Dependent steps: S49, S55, S56, S57, S58, S59, S63.
Evidence: UR-TAX-01, UR-TAX-02, UR-TAX-03, UR-TAX-04, UR-TAX-05, QR-13. Approval evidence: **not recorded**.

## D05 — Legacy ownership and cutover

Owner: Office owner with accountant reviewer. Status: **Pending; synthetic rehearsal may proceed later**. Gate: G2/S25 before live migration.

Options:

- Controlled migration with explicit ownership mappings, financial reconciliation and exception quarantine.
- Start a new office with approved opening balances and retain a restricted legacy archive.

Confirmed evidence: Preserve existing migration identities; no live client data before release and restore gates.

Recommendation: Prepare a repeatable dry run with source snapshot identity, user-to-office mapping, dated opening balances, paired transfers and an exception report. Do not silently repair ambiguous records.

Open inputs:

- Which legacy users and records belong to which office?
- Opening dates, reconciled cash totals, charges, allocations, credit and unmatched transfer pairs.
- Cutover freeze, reviewer sign-off and rollback owner.

Dependent steps: S11, S17, S25, S31.
Evidence: source_manifest.csv, known_issues.csv, QR-03, QR-09. Approval evidence: **not recorded**.

## D06 — Workload, service targets and sizing

Owner: Product owner and operator (operator to be assigned). Status: **Proposed targets; workload and budget pending**. Gate: G0 sizing; S08 parameters; S31/S63 load evidence.

Options:

- A standard non-Spot VM sized for a measured pilot; resize after observing memory and load.
- A smaller shared-core VM with lower cost and reduced headroom, subject to measured acceptance.

Confirmed evidence: Initial hosting is one Google Cloud VM.

Recommendation: Use e2-standard-2 (2 vCPU, 8 GB) as a provisional pilot candidate. Measure before accepting capacity; file scanning and S26 workers share resources. One VM is a single failure domain.

Open inputs:

- Office/accountant/client counts, concurrent sessions and annual transaction volume.
- Upload size/type/count limits, storage growth, task volume and retention.
- Monthly budget and EU region; confirm proposed p95 2-second list/detail and 10-second annual report at 50 sessions, 99.5% availability, RPO 24h/RTO 8h and WCAG 2.2 AA.

Dependent steps: S07, S08, S10, S26, S31, S38, S39, S47, S63.
Evidence: ACC-URS-001 section 5, QR-05, QR-08, QR-09, QR-12, deployment_parameters.md. Approval evidence: **not recorded**.

## D07 — Data retention, secrets and operational responsibility

Owner: Office owner and operator (people to be assigned). Status: **Pending policy and named operators**. Gate: S08 hosting inputs; before R1 live use and R2 portal use.

Options:

- Versioned per-category retention and access policy, off-VM backups and recoverable separately controlled keys.
- A blanket retention period for all records (not recommended; conflicts and holds must first be resolved).

Confirmed evidence: Private documents and credentials must be protected; public repository contains no live secrets.

Recommendation: Use an EU hosting location, a dedicated VM identity, least-privilege access and secret-version references. Approve retention by category and assign incident, restore, key recovery and client-request owners before live use.

Open inputs:

- Exact region and access administrators; key custodians and recovery rehearsal.
- Retention/archive/deletion/hold rules for financial records, files, messages, source data, audit logs and backups.
- Who handles incidents, restore tests, client exports/deletion requests and supplier account changes?

Dependent steps: S08, S10, S13, S31, S38, S41, S43, S46, S48, S50, S64.
Evidence: QR-02, QR-09, QR-11, QR-12, deployment_parameters.md. Approval evidence: **not recorded**.

## D08 — Office financial posting policy

Owner: Accountant reviewer and office owner. Status: **Approved for the bound ACC-FIN-001 v0.1 scope; implementation/release acceptance Pending**. Gate: G2/S17 before financial posting acceptance.

Options:

- Separate agreement terms, dated charges, cash, allocations, client credit and linked reversals.
- Treat agreement value as received/paid cash (rejected by the planned separation of obligations and settlement).

Recommendation: Implement the separate posting model in S17 onward with fixed decimal money, atomic transfer pairs and attributable reversals. Never infer paid status from agreement value alone.

Review topics resolved for the bound first scope:

- Fee due dates, proration, VAT treatment, recurrence and amount rounding.
- Allocation order, overpayments, refunds, client credit and payable settlement.
- Prospective agreement changes/cancellations, opening balances and report category treatment.

Dependent steps: S17, S18, S19, S20, S21, S22, S23, S24, S25, S27, S28, S29, S30, S31, S37.
Evidence: UR-CSH-01, UR-CSH-04, UR-AGR-01, UR-BIL-04, QR-03, QR-04. Approval evidence: bound S17 receipt in evidence/S17-verification.json; named review retained privately.

### S17 D08 review packet — Approved bound snapshot

Declared accountant/office-owner review recorded at 2026-11-12T16:58:37+02:00. The receipt binds the exact candidate policy, examples and documents. Names and source reference remain private. This records adoption of the reviewed contents, not application correctness or release acceptance.

## D09 — Release priorities and delivery capacity

Owner: Product owner (vtsakan). Status: **Implementation sequence authorised; release approval pending**. Gate: G0 and each release gate.

Options:

- R1 office/finance, R2 collaboration/portal, R3 authorised connectors/forecasts with explicit conditional exclusions.
- Bring conditional connectors forward, accepting additional access and policy dependencies.

Confirmed evidence: Proceed step by step from S01; Greek frontend is required from the first release.

Recommendation: Keep the 64-step sequence and deliver R1 first. Continue S03 locally while future policy inputs are collected. Keep unavailable connectors visible in release evidence; do not count them as delivered.

Open inputs:

- Final Must/Should release commitments and named acceptance reviewers.
- Developer/accountant/operator availability, budget and contingency.
- Explicit release disposition if a conditional connector cannot be authorised.

Dependent steps: S03, S31, S48, S49, S63, S64.
Evidence: steps.csv, CR-001, ACC-IMP-001. Approval evidence: **not recorded**.

## Work that can proceed

S05/S06 have successful Docker evidence pushed by the user. S07's complete production Docker gate is Verified in pushed commit a215beb91e2e49a5ffd1fa9ce8c751b8f3572234. S08's selected cloud foundation is Verified from operator execution as recorded below. S09 may proceed with actual DuckDNS control/contact; S10 must demonstrate off-VM restore. Resolve each policy at its dependent step. Greek remains confirmed in [CR-001](../requirements/CR-001-Greek-frontend.md). No government credentials or policy approvals are inferred from infrastructure completion.

## S03 technical selections

S03 selects CPython 3.12.16, Django 5.2.19 LTS, Psycopg 3.3.8 binary and Gunicorn 26.2.0 within the authorised architecture. [Dependency policy](dependency_policy.json) records the official evidence, target platform and deferred optional libraries; [dependencies.md](dependencies.md) records installation and update procedures. Runtime and maintenance dependencies have separate hashed locks. These technical choices do not approve or close any open D01–D09 domain policy. The selected runtime versions are retained through S04.

## S04 configuration and locale selections

S04 separates local/test/production settings, uses explicit environment or mounted-file secret inputs and masks configured log/error output. Greek locale, Decimal presentation and explicit DST conversion are implemented. [Settings and locale instructions](settings_and_locale.md) record supported inputs, verified scope and future Secret Manager/proxy checks. Full financial, office-boundary, admin and frontend release acceptance remains Pending. D01–D09 approvals are unchanged.

## S05 local environment selections

S05 uses digest-pinned official Python 3.12.16 slim-bookworm and PostgreSQL 17.11 bookworm images on linux/amd64. A new project-scoped `postgres17_data` volume separates PostgreSQL 17 from the legacy PostgreSQL 15 directory; logical legacy migration remains S25. Development startup applies migrations explicitly before Django's development server, without data imports or default users. The web port is loopback-only and the database has no published host port. The existing runtime lock and original models/views/migrations remain unchanged.

[Local development instructions](local_development.md) document the commands and [S05 evidence](evidence/S05-verification.json) distinguishes native PostgreSQL proof from the Docker completion gate. The initial implementation workspace lacked a Docker Engine. The user subsequently completed local Docker build/migration, 35 tests, Greek HTTP and container recreation/persistence checks and pushed commit `5a65a72906f7d3a5fccdcfd8aad0d0362a2bd7fa` on 08/11/2026. S05 is Verified. Native mode did not substitute for that gate. These implementation selections do not approve D01–D09 or complete QT-14 release acceptance.

## S06 regression tracking selections

S06 uses Django/unittest with a small strict result adapter, avoiding a new dependency. The canonical registry links 36 financial cases to seven source defects, requirements and corrective steps. Only an explicitly matched legacy financial assertion is recorded as an expected failure; ordinary assertions, runtime errors, tracked skips and unexpected successes fail the command. Seven guard tests verify these distinctions. The ordinary Django runner still fails the 26 unfixed assertions.

The S06 snapshot runs 78 tests on real PostgreSQL 17.11: 52 passed, 26 known failures reproduced and no unexpected outcomes. The user subsequently pushed Docker verification at `53e453b59bda9e2a21cbea59a086ed7ae26a45bb`. [Financial regression instructions](financial_regressions.md) and [S06 evidence](evidence/S06-verification.json) describe the commands and observations. Mutable legacy probes remain diagnostics; S24 must replace their adapters with attributable reversals/replacements while retaining the contract. D01–D09 and all 85 acceptance statuses remain unchanged.

## S07 production delivery selections

S07 retains the pinned runtime/images and adds a non-root Gunicorn image, explicit migration interface, data-free live/ready endpoints, hashed static assets and a CI workflow. Production contexts contain only allowlisted regular files from a clean commit; private/untracked inputs and selected symlinks are rejected. Full commit tags, context digests and immutable image IDs connect build, migration, tests and static export. Existing matching commit images are reused. The continuing tools/verify_delivery.py CI entrypoint discovers current tests and reviewed registry outcomes without freezing future models or rewriting historical S07 records.

Native Gunicorn/PostgreSQL 17.11 proof runs 90 tests: 64 passed, the same 26 financial failures reproduced and no unexpected outcomes. Real database outage/recovery, Greek login, admin manifest references and query-log exclusion pass. Static collection produces 255 files with 127 manifest entries. Deployment checks have zero errors and the reviewed W005/W021 warnings for HSTS subdomain/preload settings pending S09. These warnings are not suppressed; other warnings fail the gate.

The [delivery guide](production_delivery.md) and [S07 evidence](evidence/S07-verification.json) distinguish Prepared native proof from actual Docker execution. A local Engine must verify image UID/private-file exclusion, the same-image static export and container health before S08. CI execution is also unrun until push. No VM, proxy/TLS, restore, worker/scheduler, government integration or domain approval is claimed.

The user's first local S07 image build reached locked dependency installation but timed out downloading psycopg-binary from PyPI. The follow-up transport fix sets pip's socket timeout to 120 seconds and explicitly keeps five new-connection attempts in both Dockerfiles. Hash checks, HTTPS, binary-only installs and package locks remain unchanged. This is not a financial change or evidence of a successful Docker build; S07 stays Prepared until the same verifier passes. See evidence/S07-download-timeout-fix.json and the retry instructions in the delivery guide.

Two subsequent user runs successfully built one immutable image but failed at static export. The old docker cp helper hid its captured stderr; the underlying Docker cause is unconfirmed. Export now streams a bounded tar archive from a network-disabled, read-only temporary container and writes validated regular files with host ownership/modes before publishing the directory. Redacted process diagnostics survive failed export/cleanup. The host-only change leaves the production context unchanged. A verification-only --image option accepts an existing local image only when its context digest, source/revision labels, architecture and runtime UID match; original image and current verifier revisions remain distinct. Default build/CI identity policy is unchanged. Seventeen host regressions pass; real Docker execution of the fix, full S07 verification and S08 eligibility remain pending. See evidence/S07-static-export-fix.json.

## S07 gate completion and S08 actual selections — 2026-11-09

The preceding S07 Prepared/failure paragraphs are historical. The user subsequently
completed the Docker gate and pushed the successful evidence at
`a215beb91e2e49a5ffd1fa9ce8c751b8f3572234` on `step/s07-production-delivery`.
S08 was based on that actual pushed commit, not the stale native-only workspace.

The user selected a new accounting-only project, a regular e2-medium shared-core
VM in Belgium, Ubuntu 26.04.1 LTS and 30/50-GiB boot/data disks. This supersedes the
earlier e2-standard-2/Ubuntu24.04 candidates without changing the app's pinned
runtime. Premium-tier regional static IPv4, IAP-limited metadata-key SSH, retained
ext4 data storage and Docker/containerd mount guards were actually configured.
OS Login and a physical missing-disk boot test are not claimed. Host persistence
passed across reboot. Measured workload/availability acceptance remains separate.

Private EU object buckets use uniform IAM and enforced public access prevention.
The VM receives document object-user and backup object-creator permissions; the
registry grants reader and each runtime secret grants accessor. The attached
dedicated identity uses cloud-platform scope/metadata tokens. The operator's final
project IAM query returned no VM project roles. Pinned generated signing/database
secrets use version 1 with payload replication in Belgium. No service-account JSON
key was used; no new user-managed-key inventory execution is invented.

The real denied-access probe confirmed anonymous 401 and authenticated 403 outcomes.
The overly narrow anonymous 403-only expectation was corrected without weakening
authenticated denials. Document operations and backup upload/restrictions passed;
the exact backup test object was removed by the administrator. Registry listing
and reported read permissions passed; a real image pull is S09 proof.

The versioned provisioner/host replay/access probe are configurable reference tools
with local safeguards. Their new code was not executed against GCP here; operator
output proves the deployed infrastructure. Public inventory/evidence record metadata,
never secret payloads. Operative parameters and secret references remain in ignored
private/gcp.json. No app/dependency/migration/Greek UI change was introduced by S08.

D06/D07 still need budget/alerts, workload, named operators/key custodians, business
retention and recovery approval. Seven-day soft deletion and upload-only VM IAM
are infrastructure choices, not immutable-backup or retention-policy acceptance.
S09 deploys only synthetic preview data; S10 must establish encrypted automated
backup and restore. All 85 full acceptance statuses remain Pending. See
[S08 instructions](google_cloud.md), [inventory](cloud_inventory.json) and
[evidence](evidence/S08-verification.json).

## S09 HTTPS deployment selections — 2026-11-09

The user requested `totalaccounting.duckdns.org` for the existing S08 preview.
Observed public A/AAAA results match the reserved IPv4/no-IPv6 configuration.
Manual static DNS avoids a persistent DuckDNS token. Certificate issuance uses
Caddy's standard public HTTP/TLS challenges; renewal is configured, not observed.
The real ACME contact is entered only in ignored/private operator configuration.

Digest-pinned Caddy 2.11.9 adds no Python dependency. Separate certificate/static/
media roots, read-only application files, internal app/database networks and only
public TCP 80/443 preserve the S07 image boundary. Host metadata retrieves pinned
runtime materials into mode-0400 tmpfs binds; DOCKER-USER denies workload metadata.
PostgreSQL uses a non-superuser app role and local peer administration, with the
initialization-only admin password disabled. Explicit install migrations remain
separate from automatic boot resume. Secret rotation is never an implicit retry.

The native TLS/PostgreSQL test and offline safeguards are observed local evidence;
Docker publication/pull, public trusted ACME and controlled VM reboot remain the
operator gate. The implementation is Prepared. No D01–D09 policy, real-data release,
availability target or full QR/Greek frontend acceptance is approved. Refer to
[runbook](https_preview.md), [pins](../../docker/preview-pins.json) and
[S09 evidence](evidence/S09-verification.json) for actual commands and limits.

## S09 first deployment attempt and operator-tool retry

The operator verified and published application commit git:70cf0d3dbc601163f33ae9c6f927605be50841aa.
The image ID/context/registry digest are recorded in evidence/S09-deployment-retry.json.
The first ship command returned only a suppressed gcloud failure. A read-only check
confirmed IAP SSH, sudo, staged files and the expected mounted disk, with no listed
accounting containers. The failing original setup stage is not established.

Local inspection separately reproduced malformed web/Caddy tmpfs flow lists; block
lists and option validation correct that defect. Typed, bounded stage diagnostics
replace opaque VM errors without forwarding credential-bearing stderr. A clean
operator-tool revision may deploy the already published image only after exact
application-context comparison. Both source identities remain explicit; no image
label is rewritten and no previous release is modified in place. Boot configuration
uses the operator revision, and actual reboot proof includes it. Existing identity,
secret, PostgreSQL-version and explicit-migration guards remain. This host-only fix
adds no runtime dependency, model, migration, product copy or financial assertion.
S09 remains Prepared until the operator retry/public/reboot gate succeeds.

## S09 image identity across Docker stores — 2026-11-10

The VM's read-only image probe confirmed that its containerd store reports the
published manifest digest as Id, whereas the publication receipt retains the
laptop build ID. Both values already belong to the same recorded publication.
This is consistent with Docker's containerd ImageInspect implementation, which
sets Id from the target descriptor, and Docker's storage documentation. The first
comparison incorrectly assumed all stores use the same Id representation.

The correction requires an exact RepoDigests binding to the immutable selected
repository reference and accepts Id only from the two already trusted publication
anchors. Any present descriptor must match the pinned digest. Linux/amd64, UID,
source URL, application commit and context checks remain mandatory. Runtime
containers must retain the exact pinned reference and a validated image identity.
The original build ID is never replaced with whatever the VM reports. This is an
operator-only compatibility fix, with no registry tag move or image rebuild.
Actual startup/public/reboot proof remains separate. See S09-image-identity.json.

Official references:
- https://docs.docker.com/engine/storage/containerd/
- https://github.com/moby/moby/blob/master/daemon/containerd/image_inspect.go

## S10 backup and operations selections — 2026-11-10

S09 public/reboot proof is pushed at s09-complete (eced8ea70e26f410ce2d234e41169d3fc05f529b).
The user authorised S10 and elected to wait for S13–S14 to create a regular
application account. This step creates no human account.

The implementation reuses the same synthetic VM, UUID-mounted disk and private
EU backup bucket. A consistent exported PG17 snapshot binds table fingerprints
and pg_dump. A checksum-pinned age 1.3.2 binary encrypts to a public recipient;
only the laptop/recovery custodian holds the private identity. A completed
non-secret receipt in private storage allows off-VM recovery without SSH access
to the original VM. Unique create-only uploads, generation binding, CRC32C, SHA-256
and age authentication are checked; the original VM gets no backup read/delete
permission. Recovery is a bounded, isolated local Docker PG17 database drill.

The operator explicitly chooses synthetic cleanup retention (7–90 days; proposed
30), incident/restore/key custodians and alert email during configuration. No
business retention or SLA approval is inferred. Lifecycle deletion is limited
to s10/v1/ and seven-day soft deletion remains additional. No bucket lock is set.

Systemd schedules twice-daily backups and five-minute observations. Cloud
Monitoring adds one external HTTPS check, eight custom measurements and nine
Greek alert policies, including missing telemetry. Only the selected VM receives
roles/monitoring.metricWriter. A separate namespaced journal is capped at 16 MiB
with 14-day retention. Monitoring configuration and explicit alert receipt are
separate evidence; no notification delivery or GCP execution is claimed locally.

Native PostgreSQL 17.11/age proof passes all-table recovery and concurrent-write,
wrong-key, ciphertext-tamper, changed-row, size-limit and transaction cleanup
cases. Systemd syntax is checked in an isolated fixture root. Actual cloud
uploads, source-VM timers, laptop Docker recovery and the configured email
notification remain the operator's S10 completion gate. D01–D09 business approvals,
all full acceptance statuses and the 26 financial defects are unchanged. No
application image, model, migration, lock or existing production Compose changes.

See backup_restore.md and evidence/S10-verification.json. Keys/real credentials
are not in the patch or public evidence. Document recovery is deferred to S38,
and nonempty private media is refused until that consumer is implemented.

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

## S11 implementation boundary — 2026-11-10

The authorised S11 prompt explicitly selects one retained Django user, one
mandatory-office profile and owner/accountant role values. Implementing this
schema does not approve D01's unresolved capability matrix or ownership
succession. Membership services are trusted internal operations, with no new
public endpoint or admin registration; S14 must enforce actor capabilities and
last-owner/handover rules before exposing them. Implicit office transfer is
rejected. Profile/office inactivity denies the next protected request.

D05 remains Pending for real legacy ownership. Complete reviewed mappings are
validated against the actual ID/username/active-flag inventory and explicit
existing office UUIDs; no fallback office is created. Tests review synthetic
mappings only. The original VM was previously observed without human users;
this is not a current inventory or permission to manufacture a real mapping.
No legacy/VM mapping is applied here. Each future real inventory needs its own
reviewer and reviewed SHA-256. See office_profiles.md and its synthetic example.

S10 live proof at s10-complete is preserved. S11 changes the application source
context locally; its deployment and corresponding S10 backup binding update are
not part of this step. Keep the working preview and existing resources as they
are while completing S12 ownership and S13 authentication.

## S12 ownership enforcement — 2026-11-10

The selected step adds an immutable mandatory office to all five existing
business tables. Actor context comes from the active user/profile/office,
independent of submitted office IDs or superuser flags. Explicit query/saving
helpers guard current HTTP/admin paths; PostgreSQL composite foreign keys and
immutable-owner triggers protect linked writes that bypass forms. Table/PK and
prior migration identities are preserved. No new all-office permission is granted.

The migration is deliberately staged: 0004 adds nullable columns; 0005 rejects
unassigned/conflicting rows before enforcement. A private complete reviewer-bound
mapping fills only null offices atomically and preserves original financial row
values/timestamps. No ownership is inferred from one user, a record name, a
default office or an arbitrary request ID. Real legacy ownership remains D05
review work; tests use explicitly synthetic identities/assignments only.

Cash names/nonempty AFMs become office-scoped; S15 retains detailed AFM validation.
The admin recent-action sidebar is omitted because its historical labels have
no office context; audit data is not deleted. Existing finance semantics and all
26 exact known regressions remain scheduled. D01 capability/last-owner policy is
still not approved by this technical step. Current helpers do not grant portal
authority or complete future job/file/export integration. See office_ownership.md.

Native PostgreSQL proof is Prepared pending operator Docker reproduction. Schema
reversal is not an automatic data rollback after names/AFMs are reused across
offices. Future VM deployment needs a new image and matching S10 backup binding;
S12 does not change the existing preview or create application accounts.

### S16 implementation review — existing D01 policy retained

The S16 matrix applies the owner/accountant capabilities and mutual handover
already selected for S14. It adds no role, cross-office grant, platform-to-office
bypass or membership transfer policy. The global auth administrator and trusted
maintenance process are separate operator realms; neither supplies staff office
authority. D02 portal/grants and D08 financial semantics retain their existing
Pending decisions. G1 is recorded as a scoped technical foundation check;
client/browser and full requirement acceptance are not inferred from it.


### S18 implementation of the accepted D08 scope

The S17 product-owner acceptance and declared named accountant/owner review
already authorize D08-06/08/10 for the current cash foundation. S18 adds the
owner-only `finance.reverse` capability with password and recent real MFA,
exact cents and reason, retained originals and atomic database audit. Read/post
roles remain as selected at S14. No public human name or secret is introduced.
This is the core service boundary; opening-date administration, allocations,
paired transfer correction, closed-period management and the complete
lifecycle/correction UI remain their S19/S21–S24 steps. The historical S14 role
snapshot remains unchanged; the current implementation extension is recorded
here and in financial_posting.md. Full release acceptance is still Pending.


## S19 cash-account and category implementation — 2026-11-13

Selected from actual S18 Docker head `22dbd3a12816cfaceb62958ad45e19231669f3be`.
This implements the already accepted D08 opening/decimal/correction boundaries;
it does not manufacture a new accountant approval or tax rule.

- An opening is a signed amount at the **start** of its approved business date.
  Same-day cash is included; older cash is retained and excluded. All old amounts
  remain byte-for-value equivalent and their new date is NULL until explicit
  owner review. New staff-created accounts also await review, including zero.
- Metadata maintenance remains `finance.write` for owner/accountant. Financial
  opening approval/correction uses owner-only `finance.opening`, real password,
  MFA within five minutes, office/user lock and an exact operation identity.
  Approval binds a 15-minute signed amount/date/version/history preview and an
  acknowledgement. A legacy amount cannot change while establishing its date.
- Approved base amount/date cannot be edited. Signed, attributable, immutable
  adjustments and their exact linked inverses are separate from operating cash.
  Human adjustments use today's Athens business date to preserve prior daily
  balances. Backdating/closed-period administration remains S24; no automatic
  period inference is introduced.
- Used and unused references are retained, with deactivate/retire actions and
  optimistic versions. Category parent must belong to the same office, with no
  cycles, a 64-level ceiling and unique sibling/root names. Retire or move active
  children first. Category changes do not change posted cash amounts or links.
- A writable per-office PostgreSQL structure guard prevents raw-SQL write skew
  under both Read Committed and Repeatable Read. The existing operator/DDL trust
  realm remains explicit; database-role audit never invents a human actor.
- Native proof is Prepared; laptop Docker is the S19 completion gate. Preserve
  the actual S18 evidence, original twelve migrations, existing accounts, local
  encrypted backup policy and live VM. All 85 full acceptances remain Pending.


## S20 code-only delivery — 2026-11-13

The user will run tests/builds; agent execution is explicitly disabled. Deliver
Prepared source without inferring S19 operator completion or new acceptance.
Reuse S18 posting/identity/audit services and S19 opening/category safeguards.
Ordinary forms add remarks and optional category; all submitted references remain
scoped/active with service revalidation. UUID retries recover only their stored
references when these later retire or settle; payload/authority checks remain in
the atomic service. Legacy tokenless session fallback remains for compatibility;
a fresh UI form UUID distinguishes an intentional second identical movement.
Typed historical filters are shared by list/report, with 25/50/100 paging and
full matching-scope cash totals. History includes retired/archived references.
Foreign numeric keys retain 404, malformed values become Greek field errors.
No posted edit/delete API or new migration/dependency is added. All nine FLT
cases are switched to expected-pass targets, with execution explicitly Pending.
TRF-001 and report/transfer semantics remain S21/S29. All full acceptances remain
Pending. The apply helper does not run tests, builds, Docker or database actions.

## S23 implementation of approved D08 choices — Prepared

The accepted S17 snapshot remains unchanged. D08-03/D08-04 are implemented as
explicit same-party/direction allocations, separate customer credit/supplier
advance and no automatic cash/refund/offset. D08-09 settlement is derived from
retained charges and effective allocations; cancellation is a separate state.
D08-10 supplies named owner capability `finance.release` with password and recent
MFA for full dated allocation release. Each action retains actor, reason,
request/payload digests, source IDs and database recording time. SQL capacity is
checked at every affected historical change point under a serialization root;
a release on a later day does not authorize an earlier over-allocation. Refund
and full grouped correction screens remain S24; legacy interpretation remains
S25. No new policy approval is inferred or requested. Code is Prepared; operator
PostgreSQL verification, Greek browser review and release acceptance are Pending.
See settlements_credit.md and evidence/S23-verification.json.


## S24 implementation of the accepted D08 choices — Prepared

S24 source adds owner-confirmed full cash/charge/transfer corrections with
retained originals, grouped allocation releases and explicit dependent-refund
confirmation. Replacement cash requires a separate allocation action. Source-
bound credit/advance refunds never offset directions automatically. Prospective
immutable terms/cancellation stop new obligations at the cutoff while retaining
posted debt. Explicit forward-only closed-period protection enforces later open
correction dates. No new accountant approval is inferred; the unchanged S17
snapshot remains the policy reference. See financial_corrections.md. Code-only
user preference: no agent tests/builds/database/VM/demo execution. Supplied 51
new methods target 656 passes/36 finance/922 boundary cases; not observations.
Historical S23 operator result is retained: 605/605, 36 finance, 838 boundary.
All full/browser acceptances remain Pending; S25 is outside this selected step.


### S24 locking/CSRF follow-up — Prepared

Operator failure: 656 tests, 20 errors, one failure (uploaded tail, 2026-11-14).
Use PostgreSQL FOR UPDATE OF the existing allocation table only when filtering
an absent release through a nullable join. The owner/office/source locks and
immutable release guards remain. Prepare the CSRF fixture with its real verified
MFA session, then enforce CSRF on the actual protected GET/POST. No policy change,
security bypass or test waiver. Source fix is unexecuted; the full corrected
operator PostgreSQL gate remains Pending. See S24-locking-csrf-fix.json.
