# Decision register

Recorded 2026-11-07 for S02. [Machine-readable register](decision_register.json) is the source for these records. Recommendations are implementation proposals, not domain approvals. Named role owners must be assigned to actual people before their acceptance gates.

## Confirmed constraints

- Each active accountant belongs to exactly one office. Source: User instruction; UR-OFF-01.
- Deploy initially on a Google Cloud VM with a DuckDNS hostname. Source: User deployment instruction.
- Use the public vtsakan/accounting_platform GitHub repository. Source: User-created repository and successful S01 push.
- All product-authored frontend content must be Greek, including staff and client experiences. Source: User instruction 2026-11-07; CR-001; UR-LOC-01.

## D01 — Office membership and permissions

Owner: Product owner (vtsakan). Status: **Partly confirmed; permission policy pending**. Gate: G0; before S11/S14/S16 acceptance.

Options:

- Office owner and accountant roles, with explicit capabilities for finances, exports, invitations and connections.
- Owner plus custom roles with a configurable capability editor.

Confirmed evidence: One active office per accountant; UR-OFF-01 acceptance allows several accountants in the same office.

Recommendation: Start with owner/accountant roles and explicit server-side capabilities; defer a custom role editor. Deny protected operations unless a capability is granted.

Open inputs:

- May ordinary accountants view all office finances or only assigned clients?
- Who may post, reverse, export and manage connection secrets?
- Define ownership succession and the last-owner deactivation rule.

Dependent steps: S11, S12, S14, S16, S17, S41, S50.
Evidence: UR-OFF-01, UR-OFF-03, UR-OFF-04, QR-01. Approval evidence: **not recorded**.

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

Owner: Accountant reviewer and office owner. Status: **Pending accountant approval**. Gate: G2/S17 before financial posting acceptance.

Options:

- Separate agreement terms, dated charges, cash, allocations, client credit and linked reversals.
- Treat agreement value as received/paid cash (rejected by the planned separation of obligations and settlement).

Recommendation: Implement the separate posting model in S17 onward with fixed decimal money, atomic transfer pairs and attributable reversals. Never infer paid status from agreement value alone.

Open inputs:

- Fee due dates, proration, VAT treatment, recurrence and amount rounding.
- Allocation order, overpayments, refunds, client credit and payable settlement.
- Prospective agreement changes/cancellations, opening balances and report category treatment.

Dependent steps: S17, S18, S19, S20, S21, S22, S23, S24, S25, S27, S28, S29, S30, S31, S37.
Evidence: UR-CSH-01, UR-CSH-04, UR-AGR-01, UR-BIL-04, QR-03, QR-04. Approval evidence: **not recorded**.

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
