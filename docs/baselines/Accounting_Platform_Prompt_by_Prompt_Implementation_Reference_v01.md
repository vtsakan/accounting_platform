# Accounting platform prompt by prompt implementation

ACC-IMP-002 | Version 0.1 | 29 October 2026

Use this reference to implement the combined accounting-office platform one bounded step at a time. It turns the requirements and deployment pathway into 64 copyable prompts, with prerequisites, expected outputs and completion checks. Start with S01, carry the project instructions into each coding session, and keep progress and evidence in the repository.

This reference contains instructions only. All steps begin as **Not started**. The Word companion provides the same prompts for review and printing.

## How to use this reference

1. Keep this reference, ACC-URS-001, ACC-IMP-001 and the current repository available to the coding assistant. Paste the project instruction block at the beginning of a new implementation session, then paste one numbered step. The Markdown companion contains the same prompts in copyable code blocks.

2. Follow S01 to S64 by default. Dependencies identify the earlier verified work needed for a step; they are not a substitute for the baseline requirements. A cloud blocker in S08 to S10 does not prevent eligible local office/finance work. Preserve the original number when a step needs more than one implementation turn.

3. A prompt is a work unit, not a day or a promise that one assistant response completes the work. The relative weeks are inherited planning allowances: one experienced full-time developer, QA support and accountant review, plus 4 to 8 weeks of contingency. Update estimates from completed work.

4. Copy the complete step block, including its expected outputs and completion check. Review the resulting files and evidence, run the checks, and update the tracker before moving on. Persist the state in the repository so implementation does not depend on chat memory.

5. Use the original acceptance check for each mapped UR and QR in addition to the compact step check. The coverage matrix allocates work; it does not certify implementation or approval. Must requirements gate their assigned release. A Should deferral and any Must scope change need a recorded product-owner decision.

## Progress and evidence

Maintain `docs/implementation/state.md`, `decisions.md` and `traceability.csv`. Suggested step-register fields:

```csv
step_id,status,branch,commit,requirements,evidence,checks_run,checks_not_run,manual_acceptance,blocker,next_step
```

- **Not started:** No implementation has been attempted.
- **In progress:** Changes exist, but the step's completion evidence is incomplete.
- **Prepared:** Code or scripts are ready; required environment execution is outstanding.
- **Blocked:** A named input, decision or failed check prevents completion.
- **Verified:** The step's implementation and executable completion checks have passed.
- **Accepted:** Any required named domain/product/operating reviewer has also accepted it.
- **Deferred:** A recorded scope decision moves this requirement or step; it is not delivered.

## Project instructions for each session

Paste this once at the start of a new session, followed by one complete numbered step.

```text
Work on the accounting-office platform described by ACC-URS-001 and ACC-IMP-001. Apply this instruction block and the selected step S01 to S64. Read the current repository, its applicable instructions, docs/implementation/state.md, decisions.md and traceability.csv before changing anything. Use actual files and observed results as the source of truth. Preserve unrelated work and existing migration/table identities. Implement only the selected step and its necessary supporting changes.

Keep Django and PostgreSQL as the modular application, with templates and Bootstrap initially. The planning baseline uses Python 3.12, supported Django 5.2 LTS, PostgreSQL 17 and Docker Compose. Check official support/compatibility when locking versions; record a justified change rather than silently changing the stack. Deploy through Caddy and Gunicorn on one Google Cloud VM with a reserved static IPv4 address and an initial DuckDNS hostname. Use private Cloud Storage and workload identity. Add Redis, a worker and exactly one scheduler when S26 introduces them.

Enforce one office per active accountant; an office may contain several accountants. An active mandatory accountant profile supplies office context, never an untrusted submitted office identifier. Check office/client ownership on reads, writes, related choices, admin, exports, files and job execution. Keep portal identity and client grants separate from staff membership. Revocation must block the next protected action.

Keep agreement terms, charges, cash receipts/payments, allocations and reversals distinct. Use fixed decimal money and atomic services; transfers have zero operating income/expense effect. Preserve posted originals and correct them by attributable reversal. Keep office fee/cash data separate from client myDATA sources and tax forecast snapshots.

Use synthetic data until the R1 acceptance and restore gates pass. Protect secrets and private documents, mask credentials and keep keys separate from encrypted data. Use current official contracts for integrations and tax rules; simulated responses, an unavailable connector and an unrun test are not evidence of delivery. Track proposed policy approvals separately from code completion. Excluded scope remains excluded unless a recorded decision changes it.

Check the selected step's dependencies and required inputs. Use existing authorised values and proceed with reversible local work. If cloud access, credentials or a domain decision is missing, prepare the relevant code/configuration, record the exact blocker, and distinguish Prepared from Verified. Provision or change only the explicitly selected authorised environment; do not infer production targets. Send live client messages only through an explicitly confirmed product action or execution instruction.

Run meaningful checks for the change on PostgreSQL where financial or database behaviour matters. Include relevant denied-access and retry/concurrency cases. Report actual commands and results; label checks that could not run. Update implementation state, decisions and traceability with the step, requirement/test identifiers, evidence, actual commit when available and remaining blockers. Do not invent a commit or mark an approval on the reviewer's behalf.

Finish with a concise result: what changed; files/migrations and commands; checks passed/failed/not run; manual acceptance still needed; and the next eligible step. Stop after this selected step. If its scope needs subdivision, record SxxA and SxxB under the original identifier without renumbering later steps.
```

## Stage index

| Stage | Prompts | Planning allowance | Release |
|---|---|---|---|
| [P0 Establish the development baseline](#stage-p0) | S01 to S07 | Week 1 | Foundation |
| [P1 Deploy the foundation on Google Cloud](#stage-p1) | S08 to S10 | Weeks 1 to 2 | Foundation |
| [P2 Implement offices and client ownership](#stage-p2) | S11 to S16 | Weeks 3 to 5 | R1 |
| [P3 Implement the financial core](#stage-p3) | S17 to S25 | Weeks 6 to 9 | R1 |
| [P4 Deliver recurring fees and financial reporting](#stage-p4) | S26 to S31 | Weeks 10 to 12 | R1 |
| [P5 Implement daily office operations](#stage-p5) | S32 to S42 | Weeks 13 to 16 | R2 |
| [P6 Deliver the client portal](#stage-p6) | S43 to S48 | Weeks 17 to 19 | R2 |
| [P7 Implement authorised service connections](#stage-p7) | S49 to S54 | Weeks 20 to 22 | R3 |
| [P8 Implement forecasts and conditional retrieval](#stage-p8) | S55 to S62 | Weeks 23 to 26 | R3 |
| [P9 Complete the integrated pilot and handover](#stage-p9) | S63 to S64 | Weeks 27 to 28 | R3 |

The inherited allowance is 28 working weeks plus 4 to 8 weeks of contingency for one full-time experienced developer with QA/accountant input. External approvals may add waiting time. These are planning values, not per-prompt durations.

If cloud setup is blocked, eligible local work may continue from S11. R1 still needs executed deployment/recovery checks. A conditional connector remains unaccepted until delivered or explicitly removed through a recorded baseline change.

## Step checklist

- [ ] [S01 Inventory the source and establish implementation records](#s01)
- [ ] [S02 Record decisions and investigate connector feasibility](#s02)
- [ ] [S03 Clean the repository and lock application dependencies](#s03)
- [ ] [S04 Separate settings and establish Greek locale conventions](#s04)
- [ ] [S05 Build the local PostgreSQL environment](#s05)
- [ ] [S06 Capture the known financial defects as regressions](#s06)
- [ ] [S07 Build the production image and delivery checks](#s07)
- [ ] [S08 Prepare Google Cloud resources and persistent storage](#s08)
- [ ] [S09 Deploy the HTTPS preview using DuckDNS](#s09)
- [ ] [S10 Automate backups and establish operating checks](#s10)
- [ ] [S11 Introduce the office and accountant profile](#s11)
- [ ] [S12 Apply office ownership throughout the existing application](#s12)
- [ ] [S13 Complete authentication recovery and privileged MFA](#s13)
- [ ] [S14 Implement office settings and staff invitations](#s14)
- [ ] [S15 Implement the client and supplier workspace](#s15)
- [ ] [S16 Verify the complete office boundary](#s16)
- [ ] [S17 Specify the financial rules before changing posting logic](#s17)
- [ ] [S18 Create posting services constraints and audit history](#s18)
- [ ] [S19 Implement accounts categories and correct balances](#s19)
- [ ] [S20 Implement ordinary cash movements and validated filters](#s20)
- [ ] [S21 Implement atomic internal transfers](#s21)
- [ ] [S22 Separate agreement terms from charge obligations](#s22)
- [ ] [S23 Implement partial settlements allocations and client credit](#s23)
- [ ] [S24 Implement reversals and agreement lifecycle changes](#s24)
- [ ] [S25 Rehearse legacy migration and reconcile financial totals](#s25)
- [ ] [S26 Introduce reliable background execution](#s26)
- [ ] [S27 Implement price lists and monthly fee schedules](#s27)
- [ ] [S28 Generate recurring fees once per due occurrence](#s28)
- [ ] [S29 Implement dashboards and financial overviews](#s29)
- [ ] [S30 Export financial reports as PDF and structured data](#s30)
- [ ] [S31 Complete the finance release gate](#s31)
- [ ] [S32 Extend client records with office working information](#s32)
- [ ] [S33 Implement reviewed client and supplier imports](#s33)
- [ ] [S34 Implement tasks status settings and calendar views](#s34)
- [ ] [S35 Implement task recurrence and series changes](#s35)
- [ ] [S36 Implement deadline notifications and work counters](#s36)
- [ ] [S37 Create charges from completed billable tasks](#s37)
- [ ] [S38 Implement private document storage and version metadata](#s38)
- [ ] [S39 Validate scan and protect document downloads](#s39)
- [ ] [S40 Suggest client matches for PDF batches](#s40)
- [ ] [S41 Implement office mail settings templates and an outbox](#s41)
- [ ] [S42 Implement reviewed client email and submission history](#s42)
- [ ] [S43 Implement portal identity invitations and registration requests](#s43)
- [ ] [S44 Implement shared files and revocable accountant grants](#s44)
- [ ] [S45 Implement portal messages and service requests](#s45)
- [ ] [S46 Implement retention privacy export and deletion policy](#s46)
- [ ] [S47 Verify responsive and accessible office and portal workflows](#s47)
- [ ] [S48 Complete the collaboration release gate](#s48)
- [ ] [S49 Finalise current official connector contracts](#s49)
- [ ] [S50 Implement scoped encrypted connections and retrieval jobs](#s50)
- [ ] [S51 Implement reviewed AADE registry retrieval](#s51)
- [ ] [S52 Implement idempotent myDATA source ingestion](#s52)
- [ ] [S53 Implement VIES checks with explicit outcomes](#s53)
- [ ] [S54 Allow client representatives to configure their myDATA connection](#s54)
- [ ] [S55 Approve forecast contracts and accountant reference cases](#s55)
- [ ] [S56 Implement VAT forecasts and credit code 401](#s56)
- [ ] [S57 Implement supported income tax forecasts](#s57)
- [ ] [S58 Implement supported presumptive expense calculations](#s58)
- [ ] [S59 Retain forecast snapshots and expose permitted client summaries](#s59)
- [ ] [S60 Implement conditional TAXISnet profile retrieval](#s60)
- [ ] [S61 Implement conditional AADE debt statement retrieval](#s61)
- [ ] [S62 Implement conditional e EFKA notice retrieval](#s62)
- [ ] [S63 Complete the integrated pilot and release evidence](#s63)
- [ ] [S64 Complete operating handover and the maintenance backlog](#s64)

<a id="stage-p0"></a>

## P0 Establish the development baseline

Week 1 | Foundation

<a id="s01"></a>

### S01 Inventory the source and establish implementation records

```text
Apply the project instructions. Implement S01 Inventory the source and establish implementation records.
Dependencies: None.
Requirements: QR-14.
Required inputs: Current requirements and pathway documents; source archive or current repository.

Read ACC-URS-001, ACC-IMP-001 and the accountant_v6 source archive or its current repository. Inventory the models, migrations, routes, settings, dependency files and deployment files. Preserve an untouched reference copy and existing migration identities. Identify which advertised TaxPilot functions are requirements and which remain conditional on external access.

Create docs/implementation/state.md, decisions.md and traceability.csv. Register S01 to S64 as Not started and every UR and QR as pending. Record the actual starting commit, known defects and next eligible step. Produce a module map and a short README explaining local prerequisites. Make no business-model changes in this step.

Expected outputs: Source inventory, baseline references, migration inventory and implementation records.

Completion check: The inventory matches the repository; 70 UR and 14 QR records exist with pending evidence. Existing source files remain recoverable.
```

<a id="s02"></a>

### S02 Record decisions and investigate connector feasibility

```text
Apply the project instructions. Implement S02 Record decisions and investigate connector feasibility.
Dependencies: S01.
Requirements: QR-02, QR-09, QR-11, QR-12, QR-13.
Required inputs: Product owner and accountant input when available; no credentials needed to prepare the registers.

Translate D01 to D09 in the requirements baseline into decision records with an owner, options, current status and the step each decision blocks. Cover office permissions, client grants, financial policy, legacy ownership, tax cases, scale, retention and operational responsibility. Separate the confirmed one-office rule from proposed choices.

Create a connector feasibility register for AADE registry, myDATA, VIES, TAXISnet profiles, AADE debt statements and e-EFKA notices. Consult current official service information and record eligibility, authorised access, required accounts, sample evidence and unresolved questions. Prepare a deployment parameter sheet for Google Cloud and DuckDNS. Leave unknown values visibly unresolved and continue independent work.

Expected outputs: Decision register, connector evidence register and deployment parameter template.

Completion check: Every unresolved decision names its dependent steps. Unsupported connectors are recorded as blocked or conditional; no approval or successful connection is invented.
```

<a id="s03"></a>

### S03 Clean the repository and lock application dependencies

```text
Apply the project instructions. Implement S03 Clean the repository and lock application dependencies.
Dependencies: S01.
Requirements: QR-02, QR-14.
Required inputs: Existing repository and the current project records.

Create a clean working tree containing the application source and its migration history. Exclude bundled virtual environments, database dumps, sessions, private uploads and real secrets from version control and container build context. Add suitable ignore files. If a real secret was already committed, record the required rotation without copying its value into reports.

Replace the environment-wide dependency list and local wheel references with the application's direct dependencies and a reproducible lock. Use the planned Python 3.12 and a supported Django 5.2 LTS patch after checking official support information. Preserve compatibility with the legacy migrations. Add PostgreSQL and Gunicorn dependencies; defer optional libraries until their features arrive.

Expected outputs: Clean source tree, ignore files, minimal declared dependencies and dependency lock.

Completion check: A clean environment installs the lock without machine-specific paths. A secrets scan reports no committed secret values. No migration has been deleted or regenerated.
```

<a id="s04"></a>

### S04 Separate settings and establish Greek locale conventions

```text
Apply the project instructions. Implement S04 Separate settings and establish Greek locale conventions.
Dependencies: S03.
Requirements: QR-02, QR-07, QR-14.
Required inputs: Existing repository and the current project records.

Split Django configuration into common, local, test and production settings. Keep the existing authentication user model. Make database addresses, hostname and secret references explicit configuration. Production must reject missing required configuration, use DEBUG=False and avoid insecure secret defaults. Supply an example configuration containing placeholders only.

Use Europe/Athens for displayed deadlines and timezone-aware instants. Establish Greek text, day/month/year dates and euro formatting without converting money through floating point. Add focused checks for Greek round trips and daylight-saving boundaries. Introduce a redacted error/logging configuration. Document local secret loading and the future production Secret Manager interface.

Expected outputs: Settings modules, configuration example, locale helpers and configuration tests.

Completion check: Local and test settings load independently. Production fails clearly on missing required values; logs contain no secrets. Greek names and timezone boundary examples round trip correctly.
```

<a id="s05"></a>

### S05 Build the local PostgreSQL environment

```text
Apply the project instructions. Implement S05 Build the local PostgreSQL environment.
Dependencies: S03, S04.
Requirements: QR-14.
Required inputs: Existing repository and the current project records.

Create a local Docker Compose environment for Django and PostgreSQL using the planned PostgreSQL 17 major version. Use a fresh database volume and retain the original migration history. Provide repeatable commands for building, migrating, creating a development administrator and shutting down without deleting data. Restrict development port mappings to local access where possible.

Run the complete migration history against an empty PostgreSQL database and resolve compatibility issues with explicit migrations. Keep synthetic fixtures separate from real data. Document that the old PostgreSQL 15 data directory cannot simply become a version 17 volume; reserve the logical export/import rehearsal for S25.

Expected outputs: Development Compose definition, reproducible commands and empty-database migration evidence.

Completion check: A fresh checkout builds and migrates successfully. Restarting the stack retains synthetic records. No production dump is imported automatically.
```

<a id="s06"></a>

### S06 Capture the known financial defects as regressions

```text
Apply the project instructions. Implement S06 Capture the known financial defects as regressions.
Dependencies: S05.
Requirements: QR-03, QR-14.
Required inputs: Existing repository and the current project records.

Build a small PostgreSQL regression fixture from synthetic records. Capture the confirmed legacy failures: empty-side balance totals, transfers included in operating totals, cross-client agreement settlement, zero or negative amounts, stale agreement settlement status after correction, cancellation overwritten during save, and invalid filters causing server errors.

Write meaningful failing tests around observable financial behaviour. Record baseline results and link each failure to S19 to S24. Clearly mark known failures rather than weakening expected results. Include the intended balance and settlement examples from the requirements. Establish a test command suitable for later continuous integration.

Expected outputs: Synthetic regression fixture, failure inventory and repeatable PostgreSQL test command.

Completion check: Each listed defect is reproduced or explicitly documented as already fixed. Known failures remain visible and tracked; an unexpectedly passing case is investigated rather than silently ignored.
```

<a id="s07"></a>

### S07 Build the production image and delivery checks

```text
Apply the project instructions. Implement S07 Build the production image and delivery checks.
Dependencies: S04, S05, S06.
Requirements: QR-02, QR-12, QR-14.
Required inputs: Existing repository and the current project records.

Create a production Docker image that runs Django through Gunicorn and can later run the worker, scheduler and management commands. Use a non-root application process where practical, a controlled build context and pinned image identity. Add separate liveness and readiness endpoints containing no client data. Prepare static asset collection for Caddy's read-only static directory.

Add a repository verification workflow for dependency installation, empty-database migrations and PostgreSQL regression checks. Keep tracked legacy failures explicit until their corrective steps pass. Build an image once per commit and document how it is identified. Run Django deployment checks against production settings using safe test configuration.

Expected outputs: Dockerfile, health endpoints, static asset build path and CI or equivalent verification script.

Completion check: Gunicorn serves the image locally, readiness detects unavailable essential dependencies, and build output excludes private files. Migration and check results are recorded with the image identity.
```


<a id="stage-p1"></a>

## P1 Deploy the foundation on Google Cloud

Weeks 1 to 2 | Foundation

<a id="s08"></a>

### S08 Prepare Google Cloud resources and persistent storage

```text
Apply the project instructions. Implement S08 Prepare Google Cloud resources and persistent storage.
Dependencies: S02, S07.
Requirements: QR-02, QR-09, QR-12.
Required inputs: Confirmed Google Cloud project, billing, EU region and zone, administrator identity, existing VM details and authorised execution scope.

Using the confirmed deployment parameters, prepare idempotent provisioning commands for a regular Compute Engine VM in an EU region, a regional reserved static IPv4 address, a persistent data disk, private Cloud Storage, image registry and Secret Manager. Use the planned e2-standard-2 sizing and Ubuntu 24.04 LTS as initial candidates and record actual selections. Keep values configurable.

Configure a dedicated VM service identity with narrow secret, registry and bucket permissions. Use workload credentials rather than an exported service-account key. Restrict administrative access through IAP or the approved administrator source. Mount the data disk by stable identity and make Docker startup depend on that mount. Execute only against the explicitly selected project and authorised resource scope.

Expected outputs: Provisioning scripts, resource inventory, IAM definitions, mount guard and cost assumptions.

Completion check: If executed, disk mounting, restricted access and workload credentials are verified. If parameters or execution access are missing, scripts remain Prepared and the missing fields are listed; deployment is not claimed.
```

<a id="s09"></a>

### S09 Deploy the HTTPS preview using DuckDNS

```text
Apply the project instructions. Implement S09 Deploy the HTTPS preview using DuckDNS.
Dependencies: S08.
Requirements: QR-02, QR-12, QR-14.
Required inputs: Executed S08 resources, actual DuckDNS hostname and control of its DNS record.

Create the production Compose definition and Caddyfile. Deploy the application image, PostgreSQL and Caddy using the selected persistent paths. Publish only Caddy's application ports 80 and 443; keep Gunicorn and PostgreSQL private. Allow required outbound HTTPS and metadata access. Persist Caddy certificate state and collect static files into its read-only static directory.

Point the selected DuckDNS hostname to the reserved IPv4 address and remove any stale IPv6 target. Configure the exact ALLOWED_HOSTS and HTTPS CSRF origin, secure cookies and trusted proxy handling. Keep the DuckDNS token outside application settings and logs. Verify HTTP redirection, certificate trust, login POST, static assets and persistence after reboot. Use synthetic data only.

Expected outputs: Production Compose file, Caddyfile, image reference and HTTPS preview record.

Completion check: DNS resolves correctly; HTTPS and login work without redirect loops. Application/database ports are not public. Synthetic records and certificate state survive a controlled reboot.
```

<a id="s10"></a>

### S10 Automate backups and establish operating checks

```text
Apply the project instructions. Implement S10 Automate backups and establish operating checks.
Dependencies: S09.
Requirements: QR-09, QR-12.
Required inputs: Private backup storage, recovery destination, retention decision and operational alert destination.

Implement a scheduled PostgreSQL logical backup using compatible client tools, with timestamped manifests and upload to private storage outside the VM. Keep retention and backup-deletion authority separate from normal application writes. Record configuration and required secret/key version references for recovery without bundling decryption keys beside encrypted data.

Restore a synthetic backup into an isolated test destination and measure recovery time. Add monitoring for HTTPS, certificate expiry, VM disk and memory, backup age and readiness. Configure log rotation and identify an incident owner. Write an initial restore and release runbook, including the single-VM outage limitation. Add document restoration checks when document storage is introduced.

Expected outputs: Backup and restore scripts, scheduled backup, monitoring definitions and initial runbook.

Completion check: A backup restores successfully and measured results are recorded. Missing or stale backups are observable. RPO 24 hours and RTO 8 hours remain targets until demonstrated on the accepted dataset.
```


<a id="stage-p2"></a>

## P2 Implement offices and client ownership

Weeks 3 to 5 | R1

<a id="s11"></a>

### S11 Introduce the office and accountant profile

```text
Apply the project instructions. Implement S11 Introduce the office and accountant profile.
Dependencies: S02, S05.
Requirements: UR-OFF-01.
Required inputs: Approved role model and a mapping for any legacy users being migrated.

Add Office and AccountantProfile while retaining the existing Django user model. Each accountant has one profile with a mandatory office relationship and an owner or accountant role. Several accountants may belong to the same office. Use model/database constraints that prevent a second profile or simultaneous second office membership.

Provide a reviewed user-to-office mapping and a dry-run backfill command for legacy users. Reject missing, duplicate or ambiguous mappings instead of assigning everyone to a default office. Create synthetic Office A and Office B fixtures. Keep profile creation and membership changes in an explicit service so later invitations use the same rule.

Expected outputs: Office/profile schema, additive migrations, backfill command and two-office fixtures.

Completion check: Two accountants can share an office; a second office association for one accountant is rejected, including concurrent attempts. Unmapped legacy users receive no business access.
```

<a id="s12"></a>

### S12 Apply office ownership throughout the existing application

```text
Apply the project instructions. Implement S12 Apply office ownership throughout the existing application.
Dependencies: S11.
Requirements: UR-OFF-05, UR-OFF-07, QR-01.
Required inputs: Existing repository and the current project records.

Add office ownership to every existing office-controlled business table through nullable additions, reviewed backfill and non-null enforcement. Preserve table and migration identities. Centralise office context from the authenticated active accountant profile; never accept an ordinary request's office identifier as authority.

Replace global queries and unrestricted relationship choices in views, forms, selectors and Django admin. Validate parent/child ownership and deny inactive offices or missing profiles. Scope account-name and nonempty AFM uniqueness to the office. Add reusable permission checks for future exports, files and workers, with pending entry points listed for later coverage. Apply deny-by-default behaviour to unsupported access paths.

Expected outputs: Ownership migrations, office context, scoped selectors/forms/admin and relationship validation.

Completion check: Office B cannot list, open, modify or link Office A records. Forged identifiers and missing/inactive profiles are rejected at the server, not merely hidden in the interface.
```

<a id="s13"></a>

### S13 Complete authentication recovery and privileged MFA

```text
Apply the project instructions. Implement S13 Complete authentication recovery and privileged MFA.
Dependencies: S04, S12.
Requirements: UR-OFF-06, UR-OFF-07, QR-02.
Required inputs: Existing repository and the current project records.

Implement staff sign-in, sign-out and password recovery using maintained Django authentication components. Require an active profile and office for business access on every request. Enforce MFA for office owners and platform administrators, including recovery and enrolment rules. Keep platform support authority separate from routine office roles.

Add appropriate sign-in throttling, session expiry and secure token handling. Recovery links must expire and be single use. Verify logout invalidates the session and deactivation blocks an existing session's next business request. Use local email capture for development; prepare a controlled authentication-mail adapter for deployment without sending unrequested live messages.

Expected outputs: Authentication screens, recovery flow, privileged MFA and authentication permission checks.

Completion check: Anonymous, office-less and inactive users cannot access records. Recovery token reuse fails; privileged access requires MFA. An existing session cannot bypass deactivation or office checks.
```

<a id="s14"></a>

### S14 Implement office settings and staff invitations

```text
Apply the project instructions. Implement S14 Implement office settings and staff invitations.
Dependencies: S13.
Requirements: UR-OFF-02, UR-OFF-03, UR-OFF-04.
Required inputs: Approved office role matrix and ownership handover policy.

Implement owner-managed office identity and contact settings plus colleague invitation, approval and deactivation. Reuse the single-profile membership service. Bind invitations to the intended office and recipient and make them expiring and single use. Reject an accountant already affiliated with another office.

Apply the approved owner/accountant permission matrix to settings, clients, finance and delegated operations. Prevent an ordinary accountant from administering roles through direct requests. Provide a controlled ownership handover policy so deactivation cannot accidentally remove all authorised owners. Record actor and membership changes without leaking invitation secrets. Use captured mail until a live provider and sending scope are configured.

Expected outputs: Office settings, membership screens, invitation lifecycle and role enforcement.

Completion check: Allowed and denied role cases pass. Invitation reuse and cross-office membership fail; deactivation blocks the next request. Another office cannot read or change office settings.
```

<a id="s15"></a>

### S15 Implement the client and supplier workspace

```text
Apply the project instructions. Implement S15 Implement the client and supplier workspace.
Dependencies: S12, S14.
Requirements: UR-CRM-01, UR-CRM-02, UR-CRM-03, UR-CRM-06, UR-CRM-07, QR-07.
Required inputs: Existing repository and the current project records.

Extend the existing Entity record into an office-owned counterparty with independent client and supplier roles and individual/business classification. Preserve legacy identity mappings. Implement identity/contact validation, normalised nonempty AFM uniqueness within the office, search by AFM/name and a consolidated detail screen linking enabled modules.

Add archive and restore behaviour that retains financial history and excludes archived records from new work unless restored. Keep the same AFM in two offices independent. Use Greek text and agreed date/money conventions. Add office-scoped create/list/detail/edit/archive screens with server-side checks, pagination and useful empty/error states. Do not duplicate one identity merely because it has both commercial roles.

Expected outputs: Client/supplier schema, migration map, validated forms and consolidated workspace.

Completion check: A counterparty can have both roles. Duplicate normalised AFMs fail within one office and succeed independently in another. Archived records remain reportable and unavailable for new work.
```

<a id="s16"></a>

### S16 Verify the complete office boundary

```text
Apply the project instructions. Implement S16 Verify the complete office boundary.
Dependencies: S06, S14, S15.
Requirements: UR-OFF-01, UR-OFF-04, UR-OFF-05, UR-OFF-07, QR-01.
Required inputs: Existing repository and the current project records.

Audit every implemented entry point for office isolation, including detail URLs, create/edit POSTs, autocomplete choices, admin, management commands and current export routes. Run a two-office test matrix with anonymous, owner, accountant, inactive and missing-profile cases. Include guessed identifiers and cross-office related objects.

Verify database constraints and service checks for single-office membership and same-office relations. Fix discovered gaps in their owning layers. Record evidence by requirement and mark future modules as pending, not passed. Demonstrate the office-aware client workflow with synthetic records and update the foundation completion record. Reuse this matrix as each later entry point is introduced.

Expected outputs: Office-boundary test matrix, fixes and G1 acceptance evidence.

Completion check: All implemented cross-office cases are denied before returning data or committing a write. One accountant has one office; several colleagues share it. Pending future coverage is explicit.
```


<a id="stage-p3"></a>

## P3 Implement the financial core

Weeks 6 to 9 | R1

<a id="s17"></a>

### S17 Specify the financial rules before changing posting logic

```text
Apply the project instructions. Implement S17 Specify the financial rules before changing posting logic.
Dependencies: S02, S16.
Requirements: QR-03, QR-04.
Required inputs: Accountant review of D08 and legacy accounting conventions.

Translate D08 into an implementable financial policy covering opening balance dates, receivable/payable agreements, charges, cash movements, allocations, credit, refunds, reversals, cancellation and rounding. Keep office finances separate from client myDATA turnover. Define legal state transitions and the treatment of agreement changes and effective dates.

Prepare worked examples and expected totals, including obligation 100 with settlement 25, receipt 120 against charges 100, a two-account transfer and reversal of a completed agreement. Identify any unsupported operation explicitly. Obtain the accountant's decisions for unresolved money semantics before implementing them; do not infer a financial policy from the legacy defects.

Expected outputs: Financial policy, state transitions, posting invariants and reviewed examples.

Completion check: Each financial operation has explicit inputs, balance effects, permitted correction and expected result. Unresolved policy questions name the steps they block.
```

<a id="s18"></a>

### S18 Create posting services constraints and audit history

```text
Apply the project instructions. Implement S18 Create posting services constraints and audit history.
Dependencies: S17.
Requirements: QR-03, QR-04.
Required inputs: Resolved financial rules for the operations implemented.

Introduce explicit financial services for posting and correction instead of spreading business rules across forms and model save methods. Use fixed decimal money, approved rounding, database transactions and constraints for ordinary positive amounts and valid references. Define idempotency boundaries and row locking for later allocations and transfers.

Add attributable audit events containing office, actor, time, operation, reference, reason and approved change fields. Prevent ordinary interfaces and admin from silently editing or deleting posted originals. Keep secret values out of audit payloads. Establish a migration pattern that preserves legacy identifiers while later steps introduce charges and allocations. Verify transaction rollback and audit behaviour on PostgreSQL.

Expected outputs: Finance service structure, monetary constraints, audit model and posting protection.

Completion check: An invalid posting cannot leave partial effects. Posted originals cannot be changed through ordinary paths. Audit records identify the action and office without recording secrets.
```

<a id="s19"></a>

### S19 Implement accounts categories and correct balances

```text
Apply the project instructions. Implement S19 Implement accounts categories and correct balances.
Dependencies: S18.
Requirements: UR-CSH-01, UR-CSH-03, UR-CSH-05.
Required inputs: Existing repository and the current project records.

Implement office-owned cash account maintenance with opening balance, effective date and active state. Preserve history for used accounts and reject deletion of accounts referenced by posted records. Implement category hierarchy maintenance with same-office parents, cycle detection and safe retirement.

Correct balance aggregation for empty accounts and for accounts with only income or only expenses. Follow the approved opening-date interval so imported historical movements are not counted twice. Use shared selectors so dashboards and later reports use the same balance definition. Keep category renaming from changing posted monetary values. Re-run the relevant legacy regressions on PostgreSQL.

Expected outputs: Account/category screens, hierarchy constraints and corrected balance selectors.

Completion check: Opening 100 alone displays 100; adding income 50 displays 150 without any expense. Category cycles and cross-office parents fail. Account history survives deactivation.
```

<a id="s20"></a>

### S20 Implement ordinary cash movements and validated filters

```text
Apply the project instructions. Implement S20 Implement ordinary cash movements and validated filters.
Dependencies: S19.
Requirements: UR-CSH-02, UR-CSH-06.
Required inputs: Existing repository and the current project records.

Implement income and expense posting through the financial services with date, positive decimal amount, account, description, remarks and optional category/counterparty. Validate office ownership, active selections and permitted counterparty roles. Protect against double posting from repeated submission using the approved operation identity.

Implement paginated cash movement search combining date range, direction, account, category, counterparty and description. Parse filters through validated forms or equivalent typed validation so malformed dates, numbers and identifiers produce useful field errors. Keep totals aligned with the displayed scope. Retain posted history and expose a later correction action rather than unrestricted edit/delete.

Expected outputs: Cash posting screens, validated movement list and regression fixes.

Completion check: Zero, negative and invalid amounts fail without writes. Invalid filters return a validation message. Another office's account or counterparty cannot be submitted successfully.
```

<a id="s21"></a>

### S21 Implement atomic internal transfers

```text
Apply the project instructions. Implement S21 Implement atomic internal transfers.
Dependencies: S20.
Requirements: UR-CSH-04, QR-03.
Required inputs: Existing repository and the current project records.

Represent an internal transfer explicitly with two linked opposite movements and a single operation identity. Require different active cash accounts in the same office and a positive amount. Commit both legs atomically and make retries return the same operation rather than another transfer.

Update balance and operating-total selectors to recognise transfers and exclude both legs from income and expense totals. Retain an auditable transfer reference for reconciliation and future reversal. Add tests for a failed second leg, concurrent/repeated submission, same-account transfer and cross-office destinations. Avoid classifying all legacy UUID-bearing transactions as transfers; actual pairing is handled in S25.

Expected outputs: Transfer service, linked movement representation, transfer interface and atomicity tests.

Completion check: A transfer of 1000 reduces one balance and raises the other by 1000. Operating totals are unchanged; failure leaves neither leg and retries create no duplicate transfer.
```

<a id="s22"></a>

### S22 Separate agreement terms from charge obligations

```text
Apply the project instructions. Implement S22 Separate agreement terms from charge obligations.
Dependencies: S15, S18.
Requirements: UR-AGR-01.
Required inputs: Approved agreement-to-charge and recurring-fee overlap policy.

Preserve receivable and payable agreement terms while introducing explicit charge obligations with office, counterparty, direction, amount, dates, source and immutable posting details. Keep an agreement's agreed value distinct from cash received and from charges generated under it. Implement eligible-role validation and a clear agreement detail screen.

Define the source identity that prevents an agreement-derived obligation and a later fee schedule from charging the same obligation twice. Provide additive migrations preserving existing agreement identifiers and reviewable mappings. Do not trust stored legacy completed flags as the new settlement truth. Follow the reviewed policy for one-off and future scheduled obligations.

Expected outputs: Agreement/charge schema, additive migrations, agreement screens and source-identity rules.

Completion check: Receivable/payable agreements accept eligible counterparties only. An agreement, its charges and actual cash remain distinguishable. A repeated source cannot create a duplicate obligation.
```

<a id="s23"></a>

### S23 Implement partial settlements allocations and client credit

```text
Apply the project instructions. Implement S23 Implement partial settlements allocations and client credit.
Dependencies: S20, S22.
Requirements: UR-AGR-02, UR-AGR-03, UR-BIL-04, QR-03.
Required inputs: Existing repository and the current project records.

Implement allocation of cash receipts or payments to eligible charge obligations for the same office, counterparty and direction. Use transactions and appropriate row locks to prevent concurrent over-allocation. A receipt may settle several charges and retain unallocated credit; a charge may receive several partial settlements.

Expose receipt, allocation, remaining obligation and available credit together in the client/agreement workspace. Validate that a normal client receipt cannot settle a supplier payable or another client's charge. Use the reviewed refund/credit policy without inventing automatic cash activity. Add PostgreSQL concurrency tests and ensure aggregate values come from effective allocations rather than cached completion flags.

Expected outputs: Allocation services, settlement screens, credit calculation and concurrency tests.

Completion check: An obligation of 100 with settlement 25 leaves 75. A receipt of 120 against charges of 100 leaves credit 20. Concurrent requests cannot exceed cash or obligation balances.
```

<a id="s24"></a>

### S24 Implement reversals and agreement lifecycle changes

```text
Apply the project instructions. Implement S24 Implement reversals and agreement lifecycle changes.
Dependencies: S21, S23.
Requirements: UR-CSH-07, UR-AGR-04, UR-AGR-05, QR-04.
Required inputs: Existing repository and the current project records.

Implement corrections as linked reversals and, where required, replacement postings with actor, reason and date. Reverse allocations consistently when correcting receipts and reverse both legs when correcting a transfer. Make repeated reversal attempts safe and retain the original financial records.

Recompute agreement settlement after allocations and corrections. A reversed settlement reopens an unpaid balance; explicit cancellation remains cancelled. Implement versioned agreement term changes and cancellation, stopping future charges while preserving existing obligations or explicitly reversing them under policy. Apply these paths to forms, admin and service entry points and remove legacy save logic that overwrites cancellation.

Expected outputs: Reversal workflows, agreement change history and lifecycle regression fixes.

Completion check: All related legacy regressions pass. Corrections restore the expected cash and obligation balances, cancellation is preserved, and every original/reversal remains attributable.
```

<a id="s25"></a>

### S25 Rehearse legacy migration and reconcile financial totals

```text
Apply the project instructions. Implement S25 Rehearse legacy migration and reconcile financial totals.
Dependencies: S24.
Requirements: QR-03, QR-04, QR-09, QR-14.
Required inputs: Authorised legacy data copy, approved ownership mapping and accountant decisions on migration exceptions.

Build an idempotent migration or import command with dry-run mode, source-to-target identifiers and exception reports. Use an isolated copy of legacy data and the approved office mapping. Rehearse PostgreSQL 15 to 17 logical export/import with compatible tools and a fresh version 17 data volume.

Quarantine zero/negative movements, invalid settlement links, unmapped users and ambiguous transfer pairs for accountant review. A transaction UUID alone does not prove a transfer; match paired opposite legs and supporting evidence. Recalculate settlement instead of trusting legacy status. Reconcile every account balance, agreement obligation, receipt, allocation and transfer. Preserve a restorable source snapshot and document the cutover and recovery point.

Expected outputs: Migration command, mapping and exception reports, reconciliation report and rehearsal record.

Completion check: A rerun creates no duplicates. Reviewed source and target totals agree, all exceptions have recorded dispositions, and a restore can return to the rehearsal starting point.
```


<a id="stage-p4"></a>

## P4 Deliver recurring fees and financial reporting

Weeks 10 to 12 | R1

<a id="s26"></a>

### S26 Introduce reliable background execution

```text
Apply the project instructions. Implement S26 Introduce reliable background execution.
Dependencies: S07, S16.
Requirements: QR-01, QR-06, QR-12.
Required inputs: Existing repository and the current project records.

Add Redis, a Celery worker and exactly one scheduler to development and production definitions, using the same application image as the web service. Keep broker ports private, persist required scheduler state and start with measured low worker concurrency. Add observable job states, retry policy, correlation identifiers and queue health.

Build common execution guards that recheck office membership, client authority and cancellation when a job runs. Schedule work after database commit and provide a recovery mechanism for dispatch failures. Treat the database as the business source of truth; Redis loss or retry must not duplicate a business effect. Verify that release/restart procedures do not start a second scheduler.

Expected outputs: Worker/scheduler configuration, common job controls and operational visibility.

Completion check: A retried demonstration job has one database effect. Deactivated membership blocks protected execution, failures are visible, and only one scheduler is active.
```

<a id="s27"></a>

### S27 Implement price lists and monthly fee schedules

```text
Apply the project instructions. Implement S27 Implement price lists and monthly fee schedules.
Dependencies: S22, S24.
Requirements: UR-BIL-01, UR-BIL-02.
Required inputs: Existing repository and the current project records.

Implement owner-managed service prices and client monthly fee schedules with start/end periods and effective-dated changes. Use decimal amounts and immutable description/price snapshots for each posted charge. Preserve historical charges when a catalogue price or future fee changes.

Validate that schedules reference an active same-office client and do not overlap in a way that duplicates an agreement obligation. Present a preview of the periods and amounts a schedule will generate. Handle cancellation and future rate changes according to the reviewed financial policy, with an attributable history. Keep price maintenance permissions distinct from ordinary fee collection permissions.

Expected outputs: Service catalogue, fee schedule schema/screens and effective-date preview.

Completion check: A future rate affects only its stated periods. Existing posted prices remain unchanged and an overlapping source cannot charge the same obligation twice.
```

<a id="s28"></a>

### S28 Generate recurring fees once per due occurrence

```text
Apply the project instructions. Implement S28 Generate recurring fees once per due occurrence.
Dependencies: S26, S27.
Requirements: UR-BIL-03, QR-06.
Required inputs: Existing repository and the current project records.

Implement a period-based fee generation service invoked by the worker and a controlled manual command. Use database uniqueness for each schedule/source and due occurrence so retries and concurrent runs create one charge. Support reviewed catch-up behaviour and explain skipped, generated or failed periods.

Recheck office/client/schedule activity at execution time and honour effective price changes and cancellations. Generation creates obligations only and does not create cash receipts. Add preview/dry-run output and a reconciliation summary for an office/month. Test repeated runs, concurrent runs, month boundaries and a crash after charge commit but before task acknowledgement.

Expected outputs: Fee generation service, scheduled task, dry-run command and occurrence reconciliation.

Completion check: Running the same period twice or concurrently yields one charge per due occurrence. Fee generation changes no cash balance and produces no duplicate agreement obligation.
```

<a id="s29"></a>

### S29 Implement dashboards and financial overviews

```text
Apply the project instructions. Implement S29 Implement dashboards and financial overviews.
Dependencies: S23, S24, S28.
Requirements: UR-REP-01, UR-REP-02, UR-REP-03.
Required inputs: Existing repository and the current project records.

Implement the office dashboard, period financial report, client statement and twelve-month fees/settlement overview using shared scoped selectors. Reconcile opening balances, cash income/expenses, transfers, charges, allocations and unallocated credit. Exclude transfers from operating totals and label outstanding obligations with their as-of date.

Distinguish charges, receipts and remaining obligations in each monthly column. Keep client business tax turnover outside these office-finance totals. Apply the same validated filters to detail and aggregate views and use pagination where relevant. Reserve task counters for S36 rather than displaying fabricated values. Add representative reconciliation fixtures, including reversed and cancelled cases.

Expected outputs: Dashboard, financial reports, client statement and twelve-month overview.

Completion check: Every displayed total traces to detail records; transfers have zero operating effect. Monthly obligations and credit agree with the client statement and reviewed reconciliation examples.
```

<a id="s30"></a>

### S30 Export financial reports as PDF and structured data

```text
Apply the project instructions. Implement S30 Export financial reports as PDF and structured data.
Dependencies: S29.
Requirements: UR-REP-04, QR-01, QR-07.
Required inputs: Existing repository and the current project records.

Implement PDF and CSV exports for permitted financial reports and client statements. Reuse exactly the scoped selectors, filters, dates and as-of rules used by the screen. Render Greek text and euro values correctly and protect structured exports against spreadsheet formula execution from text fields.

Apply office and finance permissions at export request and, for queued exports, again at generation/download time. Store any generated private artefact behind authenticated access with expiry under policy. Add report headings identifying the office, period and report basis. Prepare an extension point for forecast provenance in S59 without mixing forecasts into cash reports.

Expected outputs: PDF/CSV exporters, protected download flow and reconciliation checks.

Completion check: Screen, PDF and CSV totals match for the same scope. Greek characters render correctly and another office cannot obtain or guess an export download.
```

<a id="s31"></a>

### S31 Complete the finance release gate

```text
Apply the project instructions. Implement S31 Complete the finance release gate.
Dependencies: S10, S13, S16, S25, S28, S30.
Requirements: QR-01, QR-02, QR-03, QR-04, QR-05, QR-07, QR-09, QR-12, QR-14.
Required inputs: R1 reviewer availability, approved workload/recovery targets and authorised live cutover scope when executing.

Run the R1 acceptance matrix for all 32 R1 user requirements and applicable quality requirements. Demonstrate a complete billing, collection, correction and reporting cycle. Recheck office boundaries, privileged MFA, migration reconciliation and PostgreSQL concurrency. Load-test the agreed envelope and measure the proposed p95 targets rather than assuming the initial VM size meets them.

Rehearse backup restoration and a controlled release with migration recovery. Prepare the first-office cutover checklist and record accountant/product-owner acceptance. Real-data migration requires the accepted ownership mapping and reconciled totals. If checks or approvals are missing, record the release as blocked; keep independent development work separate from any live cutover.

Expected outputs: R1 acceptance report, performance/recovery evidence and first-office cutover record.

Completion check: All R1 Must checks pass, known financial defects are resolved and restore is demonstrated. Record the actual release decision; a preview, passing unit tests or unexecuted scripts do not equal live acceptance.
```


<a id="stage-p5"></a>

## P5 Implement daily office operations

Weeks 13 to 16 | R2

<a id="s32"></a>

### S32 Extend client records with office working information

```text
Apply the project instructions. Implement S32 Extend client records with office working information.
Dependencies: S31.
Requirements: UR-CRM-04.
Required inputs: Existing repository and the current project records.

Add dated client notes, labels, business activities/KAD and related people with roles to the consolidated client workspace. Keep structured activity/contact data separate from free text and record the actor for changes. Apply office ownership and appropriate client permissions to every relation and lookup.

Make private staff notes private by default and ensure later portal serializers/templates cannot expose them. Extend client search/filtering only where it is useful for office work. Add focused tests for Greek text, archived clients, cross-office relations and note visibility. Retain the financial tabs and identifiers already delivered in R1.

Expected outputs: Client notes, labels, activities, related people and workspace integration.

Completion check: Information reloads with actor/date and correct client ownership. Private notes are absent from all client-facing outputs and another office cannot read or link the related records.
```

<a id="s33"></a>

### S33 Implement reviewed client and supplier imports

```text
Apply the project instructions. Implement S33 Implement reviewed client and supplier imports.
Dependencies: S32.
Requirements: UR-CRM-05.
Required inputs: Existing repository and the current project records.

Implement a controlled structured-file import for clients and suppliers with a documented template. Parse and normalise fields, validate roles and nonempty AFMs within the office, and preview valid rows, duplicate identities, invalid rows and proposed changes before confirmation.

Choose and document an explicit atomicity policy for confirmed valid rows; rejected rows must create no partial records. Preserve an import identity and row evidence so a retry is safe. Apply existing client validation and same-office rules rather than maintaining a second set of business rules. Produce a reviewable error report without exposing another office's matching records.

Expected outputs: Import template, preview/confirmation interface, importer and row error report.

Completion check: Duplicate AFMs and invalid rows are visible before confirmation. Rejected rows create no partial records and repeating an accepted import creates no unintended duplicates.
```

<a id="s34"></a>

### S34 Implement tasks status settings and calendar views

```text
Apply the project instructions. Implement S34 Implement tasks status settings and calendar views.
Dependencies: S32.
Requirements: UR-TSK-01, UR-TSK-02, UR-TSK-06.
Required inputs: Existing repository and the current project records.

Implement tasks linked to a same-office client and active accountable colleague, with title, description, deadline, priority and status. Add owner-managed status vocabulary and completion semantics; retire used statuses without destroying history. Keep task permissions consistent with the approved role matrix.

Provide list and monthly calendar views with identical filters for client, assignee, status and priority. Classify overdue, due-today and upcoming work consistently using Europe/Athens. Add paginated lists, keyboard-usable forms and clear empty/error states. Verify that an inactive assignee or archived client cannot be selected for new work unless the approved restoration flow is used.

Expected outputs: Task schema/screens, status settings, list and calendar views.

Completion check: Both views show the same filtered tasks and deadline classification. Cross-office/inactive references fail; retiring a status preserves historical tasks and completion reporting.
```

<a id="s35"></a>

### S35 Implement task recurrence and series changes

```text
Apply the project instructions. Implement S35 Implement task recurrence and series changes.
Dependencies: S26, S34.
Requirements: UR-TSK-03, UR-TSK-04, QR-06, QR-07.
Required inputs: Existing repository and the current project records.

Implement weekly, monthly, quarterly and yearly recurrence using stable series and occurrence identities. Materialise occurrences with database uniqueness and retry-safe background execution. Define month-end rules explicitly: a day-31 monthly series uses the last valid day in a short month while retaining the intended recurrence rule.

Support editing one occurrence or the future series without rewriting completed work. Record exceptions, effective changes and cancellation. Test leap years, daylight-saving boundaries, delayed scheduler catch-up, concurrent generation and retries after commit. Keep recurrence calculation separate from task completion and from fee charging so repeated scheduling cannot create money movements.

Expected outputs: Recurrence engine, series/exception model, edit controls and boundary tests.

Completion check: Retries generate one occurrence. A one-off edit leaves the rest unchanged, future-series changes preserve completed history, and month-end/DST examples match the approved local-time rule.
```

<a id="s36"></a>

### S36 Implement deadline notifications and work counters

```text
Apply the project instructions. Implement S36 Implement deadline notifications and work counters.
Dependencies: S35.
Requirements: UR-TSK-05, UR-REP-01, QR-06.
Required inputs: Existing repository and the current project records.

Add configurable upcoming and overdue task reminders as in-app notifications for the responsible accountant. Use stable notification occurrence keys so repeated scheduler execution creates one notification per configured reminder. Recheck current assignment and active office membership when generating or presenting notifications.

Implement acknowledgement while retaining a link to the task and its history. Add office dashboard work counters using the same task filters and deadline definitions as the list/calendar. Avoid sending live email reminders unless separately configured and confirmed in the product workflow. Add tests for reassignment, cancellation, acknowledged notifications, retries and inaccessible tasks.

Expected outputs: Reminder generation, notification list/acknowledgement and dashboard task counters.

Completion check: A configured reminder appears once per occurrence and remains linked after acknowledgement. Dashboard counters match task lists and users cannot follow notifications into another office.
```

<a id="s37"></a>

### S37 Create charges from completed billable tasks

```text
Apply the project instructions. Implement S37 Create charges from completed billable tasks.
Dependencies: S28, S34.
Requirements: UR-BIL-05, QR-03, QR-06.
Required inputs: Existing repository and the current project records.

Add an explicit reviewed action for charging a completed billable task. Bind the task, client, service and charge to the same office and capture the selected service description and price as a posting snapshot. Use the existing charge services and a unique task/source identity.

Keep completion and charging distinguishable so marking work complete does not silently charge an unreviewed amount. Repeated confirmation, job retry or reopening/completing the task must not create another charge. Correct a posted task charge through the existing reversal workflow and preserve its task reference. Add the charge link to task and client financial views.

Expected outputs: Billable-task review/confirmation, charge link and duplicate prevention.

Completion check: A confirmed completed task creates one correctly priced charge. Repeated completion/confirmation creates no duplicate and correction retains the original task and financial history.
```

<a id="s38"></a>

### S38 Implement private document storage and version metadata

```text
Apply the project instructions. Implement S38 Implement private document storage and version metadata.
Dependencies: S08, S26, S32.
Requirements: UR-DOC-01, UR-DOC-04, UR-DOC-05, QR-01, QR-09.
Required inputs: Private bucket access, permitted file/category policy and object retention/recovery configuration.

Implement a private Google Cloud Storage adapter and office/client-bound document metadata with period, category, immutable version identity, uploader and archive state. Store object references rather than public URLs. Enforce bucket public access prevention and narrow workload permissions. New staff uploads are private by default.

Add document lists and version/replace/archive operations. Keep uploads quarantined until S39 completes their checks; no direct download or attachment is enabled in this step. Introduce explicit portal-sharing metadata for a selected version, with actual portal grants enforced in S44. Extend backup manifests and recovery policy to preserve object generations throughout the database recovery window.

Expected outputs: Private storage adapter, document/version schema, client lists and recovery references.

Completion check: Documents are bound to one office/client and version history survives replacement. Quarantined content is inaccessible; object storage is not public and backup references can identify the required versions.
```

<a id="s39"></a>

### S39 Validate scan and protect document downloads

```text
Apply the project instructions. Implement S39 Validate scan and protect document downloads.
Dependencies: S38.
Requirements: UR-DOC-02, QR-01, QR-10.
Required inputs: Existing repository and the current project records.

Implement upload limits, content-based type validation and a malware scanning worker for permitted PDF, image and office-document types up to 25 MB. Model pending, clean, rejected and failed scan states. A scan failure or unavailable scanner must leave the file quarantined rather than treating it as clean.

Expose authenticated downloads only after checking current office/client permission, selected version and clean scan state. Proxy or stream through a route that rechecks access instead of leaving long-lived bearer links. Apply the same guard to email attachments and document moves. Measure scanning resource use on the VM and make limits configurable. Test extension spoofing and permission changes.

Expected outputs: Upload validation, scanning workflow, protected downloads and attachment guard.

Completion check: Oversized/disallowed content is rejected. Pending, failed or infected files cannot be downloaded or attached. A renamed extension and a guessed object identifier cannot bypass validation or authorisation.
```

<a id="s40"></a>

### S40 Suggest client matches for PDF batches

```text
Apply the project instructions. Implement S40 Suggest client matches for PDF batches.
Dependencies: S39.
Requirements: UR-DOC-03.
Required inputs: Existing repository and the current project records.

Implement a reviewed PDF batch assignment workflow for at most 100 files. Extract recognised AFMs or filename signals and suggest matches only among clients visible in the current office. Display the proposed client, confidence basis and unmatched or ambiguous cases without automatically assigning uncertain results.

Require explicit confirmation before changing client assignment, validate access to both source and destination, and retain actor and matching evidence. Keep content quarantined until its normal checks pass and handle per-file failures explicitly. Make repeated confirmation safe. Treat extracted content as untrusted input and preserve private file/version identities throughout reassignment.

Expected outputs: Batch suggestion interface, matching service, confirmation and assignment history.

Completion check: Ambiguous/unmatched files require a decision. No batch result reveals another office's client and a repeated confirmation cannot duplicate or misassign a document.
```

<a id="s41"></a>

### S41 Implement office mail settings templates and an outbox

```text
Apply the project instructions. Implement S41 Implement office mail settings templates and an outbox.
Dependencies: S26, S32.
Requirements: UR-COM-01, QR-02, QR-06.
Required inputs: Office mail provider configuration for deployment; captured transport is sufficient for development.

Implement office-owned SMTP configuration and Greek-language email templates with approved client fields and office signature. Use masked secret entry with a protected secret reference or approved encryption; never store a readable SMTP password in ordinary business fields or logs. Use the configured authenticated provider on its supported submission port, typically 587 or 465.

Add safe template rendering, missing-field reporting and markup sanitisation. Create a transactional outbox with stable submission intent identifiers and pending/submitted/failed/uncertain states. Use a captured mail transport in development. A timeout after possible SMTP acceptance must become uncertain and require review rather than automatic resend.

Expected outputs: Mail settings, template editor/preview, protected credential loading and outbox model.

Completion check: Greek previews render correctly; missing fields and unsafe markup are handled. An uncertain result is retained for review, and no SMTP credential appears in logs or rendered pages.
```

<a id="s42"></a>

### S42 Implement reviewed client email and submission history

```text
Apply the project instructions. Implement S42 Implement reviewed client email and submission history.
Dependencies: S39, S41.
Requirements: UR-COM-02, UR-COM-03, UR-COM-04, QR-01, QR-06, QR-10.
Required inputs: Live sending requires configured office mail and explicit confirmation within the implemented product workflow.

Implement single-client and individualised group email preparation with a review of recipient, subject, body and each client's permitted clean attachments before confirmation. At send time recheck office access, client association, attachment permissions and scan state. Use the outbox for one submission intent per confirmed message.

Display pending, submitted, failed and uncertain outcomes with actor/time and technical details safe for users. Label SMTP acceptance as submission, not confirmed delivery. For groups, create separate client messages without sharing address lists or another client's files. Add retry/review controls that cannot silently resubmit uncertain messages. Verify using a captured transport and synthetic recipients.

Expected outputs: Compose/review screens, outbox execution, client mail history and group preparation.

Completion check: Client A never receives Client B's attachments or address list. Repeated confirmation creates one intent, uncertain outcomes are reviewable, and submission history does not claim delivery.
```


<a id="stage-p6"></a>

## P6 Deliver the client portal

Weeks 17 to 19 | R2

<a id="s43"></a>

### S43 Implement portal identity invitations and registration requests

```text
Apply the project instructions. Implement S43 Implement portal identity invitations and registration requests.
Dependencies: S14, S39.
Requirements: UR-POR-01, UR-POR-02, QR-02.
Required inputs: Approved representative verification and client-linking policy.

Implement the client portal under /portal/ on the same hostname with an authorisation boundary separate from accountant membership. A portal account alone does not become an accountant. Bind an invitation to the intended client and verified representative, with expiry and single use.

Add pending registration/office-relationship requests that expose no existing client records and trigger no protected retrieval. Require office approval and verification of control before activation. Define the permitted relationship between one representative and its client records without implying access to other offices. Add sign-in/recovery, activation, rejection and revocation states using existing secure authentication components.

Expected outputs: Portal identity/client links, invitation activation and registration request approval.

Completion check: Expired, reused and incorrectly authenticated invitations cannot activate access. Pending requests see no existing records; portal identity cannot reach staff screens without a valid accountant profile.
```

<a id="s44"></a>

### S44 Implement shared files and revocable accountant grants

```text
Apply the project instructions. Implement S44 Implement shared files and revocable accountant grants.
Dependencies: S38, S39, S43.
Requirements: UR-POR-03, UR-POR-05, QR-01.
Required inputs: Existing repository and the current project records.

Implement portal file lists, uploads and downloads for explicitly linked clients. Show only versions explicitly shared by staff and eligible files uploaded by the client. Apply the clean-file guard and the current client permission at every download.

Add explicit approval/revocation of accountant access to portal-shared files and connected tax data. Keep these grants separate from office membership and from the office's retained financial history. Recheck grants for pending protected jobs and after reassignment. Avoid download links that remain valid after revocation. Add tests across two offices, two clients, multiple representatives, queued work and active sessions.

Expected outputs: Portal file exchange, grant model/screens and permission checks for downloads/jobs.

Completion check: Revocation denies the next protected download and pending protected execution for that accountant. Another client cannot enumerate files, while historical office charges and cash records remain retained.
```

<a id="s45"></a>

### S45 Implement portal messages and service requests

```text
Apply the project instructions. Implement S45 Implement portal messages and service requests.
Dependencies: S34, S43.
Requirements: UR-POR-04.
Required inputs: Existing repository and the current project records.

Implement client message threads and service requests with visible request status. Bind every thread and request to the correct office/client and authorised representatives. Allow staff to create or link an office task while retaining the original request reference.

Define clearly which messages are client-visible and which notes are staff-only. Apply the same file and scan guards to any supported attachments. Keep client status updates consistent with the linked task without exposing internal status configuration or private notes. Add permission checks to thread lists, detail routes, replies, status changes and notification links.

Expected outputs: Portal threads, request lifecycle, office inbox and task linkage.

Completion check: Both parties see the intended thread and request status. Private staff notes remain hidden and neither a forged task/thread identifier nor a notification link crosses client boundaries.
```

<a id="s46"></a>

### S46 Implement retention privacy export and deletion policy

```text
Apply the project instructions. Implement S46 Implement retention privacy export and deletion policy.
Dependencies: S44, S45.
Requirements: QR-11.
Required inputs: Approved D07 retention and privacy decisions for each data category.

Translate the approved data-category policy into retention, archive, eligible deletion, legal hold and authorised export controls. Cover office financial history, staff notes, portal content, document versions, external sources, forecasts, audit events and backup recovery windows. Preserve required posted financial records while removing only content eligible under the policy.

Implement reviewable dry-run reports and guarded background cleanup. Ensure document/object deletion stays consistent with database references and recovery requirements. Document how restored backups reapply deletion decisions where required. Add tests for a held record, expired eligible portal content and retained financial history. Do not invent statutory retention periods; use the recorded policy decision.

Expected outputs: Versioned retention policy, privacy/export controls, cleanup workflow and policy tests.

Completion check: Legal holds block removal, eligible expired content is removed under policy, and required financial/audit history remains. Policy changes and cleanup execution are attributable.
```

<a id="s47"></a>

### S47 Verify responsive and accessible office and portal workflows

```text
Apply the project instructions. Implement S47 Verify responsive and accessible office and portal workflows.
Dependencies: S42, S44, S45.
Requirements: QR-08, QR-07.
Required inputs: Existing repository and the current project records.

Audit the core staff and portal journeys against the proposed WCAG 2.2 AA target, combining automated checks with keyboard and manual review. Test at 375, 768 and 1440 CSS pixels. Include client search, financial posting, calendar/task editing, upload/download, message composition, invitation activation and grant revocation.

Fix labels, focus order/visibility, error association, contrast and responsive control loss. Check Greek text and long names, date input and euro values. Provide accessible alternatives for any calendar-only interaction. Record residual issues with affected requirements and severity. An automated scanner result alone must not be described as full accessibility conformance.

Expected outputs: Accessibility/responsive review, UI fixes and journey evidence.

Completion check: Core journeys are keyboard-completable with labelled controls. No task control disappears at the tested widths, and the evidence distinguishes automated checks from manual review.
```

<a id="s48"></a>

### S48 Complete the collaboration release gate

```text
Apply the project instructions. Implement S48 Complete the collaboration release gate.
Dependencies: S33, S36, S37, S40, S42, S46, S47.
Requirements: QR-01, QR-02, QR-06, QR-08, QR-09, QR-10, QR-11, QR-12.
Required inputs: Representative client and office reviewers; approved Should deferrals if any.

Run the R2 matrix and retained R1 regressions. Demonstrate month-end work generation, billable-task charging, document scan/sharing, reviewed email, client activation, file exchange, service request and grant revocation. Test retries and failures across worker and web paths.

Restore database plus required document versions into an isolated destination and verify current permissions after recovery. Confirm approved retention, responsive/accessibility evidence and operating limits for scanning on the VM. Resolve all R2 Must failures. Record any moved Should requirement through an explicit scope decision rather than dropping it from the tracker. Prepare and execute the R2 release only within the authorised environment.

Expected outputs: R2 acceptance report, combined data/document recovery evidence and release record.

Completion check: All R2 Must requirements and retained R1 controls pass. Revocation blocks pending access, retries create no duplicate effects, and the live release status reflects actual execution and acceptance.
```


<a id="stage-p7"></a>

## P7 Implement authorised service connections

Weeks 20 to 22 | R3

<a id="s49"></a>

### S49 Finalise current official connector contracts

```text
Apply the project instructions. Implement S49 Finalise current official connector contracts.
Dependencies: S02, S48.
Requirements: UR-INT-02, UR-INT-03, UR-INT-04, UR-INT-05, UR-INT-06, UR-INT-07.
Required inputs: Current official documentation, authorised service accounts/delegation and environment access when available.

Refresh the connector feasibility register against current official technical documentation. For each intended service record the authorised access method, eligibility/delegation, credential scope, versions/endpoints, request/response schema, pagination, rate limits, timeouts, retry rules and sample provenance. Keep real secrets outside the contracts and fixtures.

Distinguish documented, demonstrated, blocked and deferred connectors. Prepare sanitised contract fixtures and an authorised environment test plan. Where no supportable route exists, record the scope decision and keep the feature visibly unavailable. Do not substitute the public demo's simulated response for real evidence. Reconfirm tax-source completeness and cancellation semantics needed by later forecasts.

Expected outputs: Versioned contracts, sanitised fixtures and connector go or no-go evidence.

Completion check: Each connector has an explicit supported contract or a named blocker. Access eligibility is demonstrated before claiming an integration and any changed scope is recorded.
```

<a id="s50"></a>

### S50 Implement scoped encrypted connections and retrieval jobs

```text
Apply the project instructions. Implement S50 Implement scoped encrypted connections and retrieval jobs.
Dependencies: S26, S44, S49.
Requirements: UR-INT-01, UR-INT-08, QR-01, QR-02, QR-04.
Required inputs: Managed encryption key and secret access; approved connection/delegation model.

Implement connection records scoped by service, office and intended client, with delegated management permissions. Encrypt protected credentials using a separately managed key; store no key beside the encrypted database value. Load secrets through the workload identity and record key versions, rotation and recovery procedures. Mask secrets after entry and exclude them from logs/audit fields.

Implement retrieval job states: queued, running, succeeded, partial, failed, cancelled or needs-user-action. Recheck office and client grants when jobs run and before further protected retrieval. Use bounded retries, cancellation, provenance and dispatch recovery. Separate imported source datasets from office financial records. Add adapter interfaces and contract tests before live calls.

Expected outputs: Credential service, connection UI, encrypted storage, retrieval framework and adapter contracts.

Completion check: Cross-office/client use is rejected. Revocation/cancellation stops protected work, secrets remain masked, key rotation/recovery is demonstrable, and partial failure cannot masquerade as a successful empty result.
```

<a id="s51"></a>

### S51 Implement reviewed AADE registry retrieval

```text
Apply the project instructions. Implement S51 Implement reviewed AADE registry retrieval.
Dependencies: S50.
Requirements: UR-INT-02.
Required inputs: Approved AADE registry access and credentials for the selected environment.

Implement the approved AADE registry adapter using its versioned contract. Retrieve available data for the requested AFM, including supported business activities/KAD, and retain retrieval source and time. Validate office/client authority and response identity before making the data available.

Show existing and retrieved values side by side and let the accountant confirm individual field changes. Reuse client validation and audit approved updates. Handle invalid AFM, no result, unavailable service, permission failure and partial data distinctly. Test with contract fixtures, then demonstrate the authorised environment. Keep the integration disabled if the access contract is not proven.

Expected outputs: Registry adapter, comparison/selection UI, confirmed update audit and contract evidence.

Completion check: Only selected fields change; response identity, provenance and date are retained. Failure does not overwrite the client record and another client's credentials cannot be used.
```

<a id="s52"></a>

### S52 Implement idempotent myDATA source ingestion

```text
Apply the project instructions. Implement S52 Implement idempotent myDATA source ingestion.
Dependencies: S50.
Requirements: UR-INT-06, UR-INT-08.
Required inputs: Authorised myDATA connection, contract samples and a permitted client/period.

Implement authorised myDATA retrieval for a selected client and period using the approved contract. Handle pagination, stable source identifiers, updates, cancellations and credit records. Keep raw/provenance information and the effective source set distinct, with retrieval coverage and last successful progress explicitly recorded.

Make repeated and interrupted retrieval safe without duplicate source records. Distinguish complete, partial, failed and truly empty periods. Recheck client permission between protected operations and stop on revocation. Reconcile source counts/totals against sanitised examples and an authorised environment. Do not post imported client turnover into office cash accounts or fee reports.

Expected outputs: myDATA adapter, source dataset, update/cancellation logic and retrieval reconciliation.

Completion check: Repeated ingestion is idempotent; supported changes alter the effective set correctly. Interrupted/partial data remains visible as incomplete and client sources never alter office cash totals.
```

<a id="s53"></a>

### S53 Implement VIES checks with explicit outcomes

```text
Apply the project instructions. Implement S53 Implement VIES checks with explicit outcomes.
Dependencies: S50.
Requirements: UR-INT-07.
Required inputs: Current approved VIES contract and outbound service access.

Implement the approved VIES adapter with country and VAT-number validation. Bind the request to the visible client/workspace, record timestamp and returned evidence, and distinguish valid, invalid and service-unavailable outcomes. Use the common job, timeout and bounded retry controls.

Present the latest result and its age without replacing an earlier successful result with an apparently invalid registration during an outage. Add fixtures for valid, invalid, malformed, unavailable and timeout cases. Demonstrate against the authorised public service route without embedding assumptions about undocumented interfaces. Keep the optional requirement visible in the tracker if deferred by a recorded decision.

Expected outputs: VIES adapter, result history, user feedback and service contract tests.

Completion check: An outage is displayed as unavailable rather than invalid. Country, number, time and returned result remain attributable to the requested client.
```

<a id="s54"></a>

### S54 Allow client representatives to configure their myDATA connection

```text
Apply the project instructions. Implement S54 Allow client representatives to configure their myDATA connection.
Dependencies: S43, S50, S52.
Requirements: UR-POR-07, QR-02.
Required inputs: Verified client representative and authorised myDATA credentials.

Add portal connection setup for an authorised representative's own client-bound myDATA account. Verify the representative-to-client link before saving or testing credentials and use the encrypted connection service. Mask secrets after entry and keep them out of rendered forms, logs and ordinary API responses.

Apply the client's accountant grants to protected retrieval separately from the representative's ability to manage its own connection. Provide connection validation/status, credential replacement and disconnect flows without exposing secret values. Test forged client identifiers, multiple linked representatives, revoked grants and a queued retrieval after credential replacement. Reuse the same adapter and source ownership rules as staff retrieval.

Expected outputs: Portal myDATA setup/status, protected credential changes and connection tests.

Completion check: A representative can configure only its permitted client. Credentials cannot be used for another office/client, and revoked accountant authority blocks protected retrieval without exposing the secret.
```


<a id="stage-p8"></a>

## P8 Implement forecasts and conditional retrieval

Weeks 23 to 26 | R3

<a id="s55"></a>

### S55 Approve forecast contracts and accountant reference cases

```text
Apply the project instructions. Implement S55 Approve forecast contracts and accountant reference cases.
Dependencies: S49, S52.
Requirements: QR-13.
Required inputs: Accountant approval of D04, supported tax years/types and official reference material.

Define the supported taxpayer types, tax years, period rules, F2 mappings, rounding and required inputs for VAT, income tax and presumptive expenses. Consult current official tax/service sources for the selected year and record their versions. Name unsupported cases and incomplete-source conditions explicitly.

Prepare accountant-reviewed golden cases covering ordinary, zero, credit, missing-data and boundary inputs, with expected intermediate values and final amounts. Define source coverage, manual adjustment, review and snapshot requirements. Obtain approval of the cases before coding the corresponding rule. Keep this specification independent of hardcoded current-year constants so later rule versions can coexist.

Expected outputs: Forecast contracts, approved tax-year rules and golden datasets with expected results.

Completion check: Every supported case has reviewed inputs and expected outputs. Unsupported cases and missing assumptions prevent an apparently complete forecast; approval is recorded rather than inferred.
```

<a id="s56"></a>

### S56 Implement VAT forecasts and credit code 401

```text
Apply the project instructions. Implement S56 Implement VAT forecasts and credit code 401.
Dependencies: S55.
Requirements: UR-TAX-01, UR-TAX-02, QR-13.
Required inputs: Existing repository and the current project records.

Implement the approved monthly/quarterly VAT calculation as a versioned rule using the effective myDATA source set and reviewed F2 box mappings. Show the source records and adjustments contributing to each displayed box. Keep cancellation/credit treatment consistent with the ingestion contract.

Allow a VAT credit carried forward in code 401 to be supplied or confirmed with amount, source and applicable period. Distinguish manual from retrieved values and flag missing credit or incomplete source coverage. Run all approved VAT golden cases and boundary checks. Produce a reviewable estimate without filing a tax return or treating an unsupported period as complete.

Expected outputs: Versioned VAT engine, F2-mapped view, code 401 input/provenance and case evidence.

Completion check: Displayed boxes reconcile to included sources; code 401 provenance is visible. All approved VAT cases pass and missing/unreviewed inputs remain clearly flagged.
```

<a id="s57"></a>

### S57 Implement supported income tax forecasts

```text
Apply the project instructions. Implement S57 Implement supported income tax forecasts.
Dependencies: S55.
Requirements: UR-TAX-03, QR-13.
Required inputs: Existing repository and the current project records.

Implement income-tax estimation only for the approved taxpayer types and tax-year rule versions. Expose the reviewed income basis, applicable bands, prepayment, withholdings and other approved adjustments with their sources. Use exact decimal arithmetic and approved rounding.

Validate required inputs and reject unsupported combinations before calculation. Keep source data, manual assumptions and rule constants distinguishable. Run the accountant's ordinary, zero, missing-data and boundary examples, including approved band transitions. Present intermediate and final values as an estimate for review, with an extension point for the immutable snapshot in S59.

Expected outputs: Versioned income-tax engine, input/review screen and golden-case results.

Completion check: Every supported reference case matches the approved result and intermediate values. Unsupported taxpayer/year combinations cannot produce an apparently complete forecast.
```

<a id="s58"></a>

### S58 Implement supported presumptive expense calculations

```text
Apply the project instructions. Implement S58 Implement supported presumptive expense calculations.
Dependencies: S55.
Requirements: UR-TAX-04, QR-13.
Required inputs: Existing repository and the current project records.

Implement the approved individual presumptive-expense calculations from declared household and asset inputs for the supported tax years. Preserve each input's meaning, applicable period and source. Validate missing or inconsistent information and keep unimplemented scenarios visibly unsupported.

Apply the reviewed tax-year formulas and rounding using versioned rule definitions. Show how each supported component contributes to the total and retain manual assumptions for review. Run all approved ordinary, zero, missing-data and boundary cases. Keep these estimates separate from cash expenses and from imported myDATA expense records.

Expected outputs: Versioned presumptive-expense engine, input/component view and approved case results.

Completion check: Reference scenarios match the accountant's expected values. Missing inputs block or explicitly qualify the result, and the calculation does not change office cash or client source records.
```

<a id="s59"></a>

### S59 Retain forecast snapshots and expose permitted client summaries

```text
Apply the project instructions. Implement S59 Retain forecast snapshots and expose permitted client summaries.
Dependencies: S54, S56, S57, S58.
Requirements: UR-TAX-05, UR-POR-06, UR-REP-04, QR-13.
Required inputs: Existing repository and the current project records.

Create immutable forecast snapshots containing client/period, effective included sources, retrieval coverage, manual inputs, adjustments, rule version, calculation time and reviewer status. Ensure a snapshot can be reproduced after source data or current rules change. Label incomplete and unreviewed estimates clearly.

Add authorised portal myDATA income/expense/VAT summaries with period, source and last successful retrieval. Keep office fees distinct from client business turnover. Extend PDF/structured exports with estimate status, source dates and rule provenance. Recheck current client/grant permissions at view/export/download time and include reviewed forecast examples in the client workspace.

Expected outputs: Snapshot model, review history, portal summaries and provenance-aware exports.

Completion check: A stored result reproduces from its retained inputs/rules. Revoked users cannot read/export protected data; summaries show completeness and do not mix office fees with business turnover.
```

<a id="s60"></a>

### S60 Implement conditional TAXISnet profile retrieval

```text
Apply the project instructions. Implement S60 Implement conditional TAXISnet profile retrieval.
Dependencies: S49, S50.
Requirements: UR-INT-03.
Required inputs: Demonstrated authorised TAXISnet access route; otherwise this connector remains blocked.

Implement TAXISnet individual/entity profile retrieval only if the connector register demonstrates an authorised supportable access route. Validate the delegated client identity, credential scope and contract before making protected calls. Record provenance and show the retrieved profile for review without silently overwriting the client register.

Use the common job, grant, cancellation and failure controls. Demonstrate the authorised environment with sanitised evidence. If access is not proven, retain an explicit unavailable state and document the exact blocker and baseline scope decision. A manually entered or simulated profile must not be presented as a completed live integration.

Expected outputs: Authorised profile adapter and evidence, or explicit blocked-connector record/UI.

Completion check: A delivered adapter retrieves the intended client's profile and honours revocation. Otherwise the feature is visibly blocked and UR-INT-03 remains unaccepted until a recorded scope change.
```

<a id="s61"></a>

### S61 Implement conditional AADE debt statement retrieval

```text
Apply the project instructions. Implement S61 Implement conditional AADE debt statement retrieval.
Dependencies: S49, S50.
Requirements: UR-INT-04.
Required inputs: Approved AADE debt access and client delegation; clean document workflow from S39.

Implement AADE debt statement retrieval only through the approved access route. Verify the requested client identity and required authorisation, retrieve the statement, and bind the result to the correct office/client with retrieval date and source evidence.

Store the statement through the private document validation/scanning workflow, then allow review before any attachment to a message. Recheck grants at execution and download/attachment time. Handle no statement, unavailable service and permission failure distinctly. If no authorised route has been demonstrated, retain a blocked status and scope record instead of a simulated successful document.

Expected outputs: Debt retrieval adapter, protected document integration and evidence or blocker record.

Completion check: A retrieved statement belongs to the requested client, retains retrieval provenance and is reviewed before attachment. Missing access never results in a claimed successful integration.
```

<a id="s62"></a>

### S62 Implement conditional e EFKA notice retrieval

```text
Apply the project instructions. Implement S62 Implement conditional e EFKA notice retrieval.
Dependencies: S49, S50.
Requirements: UR-INT-05.
Required inputs: Approved e-EFKA access, required client identifiers and permitted period; document workflow from S39.

Implement non-salaried e-EFKA contribution-notice retrieval only where the approved contract and access route have been demonstrated. Validate client identity, required identifiers, authorisation and notice period. Bind the returned notice to the correct office/client/period and retain source and retrieval date.

Use the private document validation/scanning workflow and current grant checks before review, download or attachment. Show missing identifiers, missing notices, permission failures and service failures explicitly. Run contract fixtures and the authorised environment check. If access is unavailable, keep the connector visibly blocked and record the scope consequence rather than claiming parity.

Expected outputs: Notice adapter, protected document integration and authorised evidence or blocker record.

Completion check: The notice matches the requested client and period; missing-input and retrieval errors are distinct. Protected access stops on revocation and unsupported access remains unaccepted.
```


<a id="stage-p9"></a>

## P9 Complete the integrated pilot and handover

Weeks 27 to 28 | R3

<a id="s63"></a>

### S63 Complete the integrated pilot and release evidence

```text
Apply the project instructions. Implement S63 Complete the integrated pilot and release evidence.
Dependencies: S48, S53, S59, S60, S61, S62.
Requirements: QR-01, QR-02, QR-03, QR-05, QR-06, QR-08, QR-09, QR-10, QR-11, QR-12, QR-13, QR-14.
Required inputs: Pilot office/client reviewers, accepted release scope and authorised recovery/release environment.

Run the complete current acceptance matrix across office onboarding, finance, recurring work, document/email exchange, portal grants, authorised retrieval and reviewed forecasts. Repeat isolation, concurrency, retry, revocation, malformed-input and accessibility checks across the integrated flows. Reconcile every one of the 70 UR and 14 QR records with real evidence.

Load-test the accepted workload on the actual VM and adjust capacity from measurements. Restore onto an isolated replacement VM, recover documents/key references, and rehearse reserved-IP reassignment, release rollback and failed-migration recovery. Record blocked connectors honestly. A Must connector can leave release scope only through an explicit baseline change; retain the resulting acceptance limitation. Prepare the R3 decision and pilot issue list.

Expected outputs: Integrated pilot report, full traceability, measured recovery/performance and R3 decision.

Completion check: All Must requirements in the accepted release scope pass and serious access, money or data-loss defects are resolved. Unexecuted/blocked checks remain explicit; no deferred connector is reported as delivered.
```

<a id="s64"></a>

### S64 Complete operating handover and the maintenance backlog

```text
Apply the project instructions. Implement S64 Complete operating handover and the maintenance backlog.
Dependencies: S63.
Requirements: QR-09, QR-12, QR-14.
Required inputs: Named operator, incident contact and accepted release record.

Finalise the operating runbook for the Google Cloud VM and DuckDNS service. Cover image-based releases, controlled migrations, static collection, a single scheduler, backup/restore, certificate/DNS faults, disk growth, failed/uncertain jobs, secret rotation, access revocation and incident ownership. Keep staging data/storage separate from live resources.

Demonstrate a compatible application rollback and document when a schema/data restore or forward fix is required instead. Add repeatable health, backup-age and release checks to the delivery workflow. Record remaining issues and evidence-based triggers for a larger VM, separate workers or managed PostgreSQL. Explain future custom-domain configuration changes. Update the state file with the accepted commit, release, blockers and next backlog items.

Expected outputs: Operating/user guidance, handover checklist, release workflow and maintenance backlog.

Completion check: The named operator can deploy, diagnose and restore from the runbook. Accepted scope and remaining limitations are recorded; a single VM is not described as providing automatic failover.
```

## Requirement coverage

These mappings allocate work; they are not evidence that a requirement is implemented or accepted. Use the original baseline acceptance checks.

| User requirement | Release | Implementation prompts | Acceptance |
|---|---|---|---|
| UR-OFF-01 | R1 | S11, S16 | AT-OFF-01 |
| UR-OFF-02 | R1 | S14 | AT-OFF-02 |
| UR-OFF-03 | R1 | S14 | AT-OFF-03 |
| UR-OFF-04 | R1 | S14, S16 | AT-OFF-04 |
| UR-OFF-05 | R1 | S12, S16 | AT-OFF-05 |
| UR-OFF-06 | R1 | S13 | AT-OFF-06 |
| UR-OFF-07 | R1 | S12, S13, S16 | AT-OFF-07 |
| UR-CRM-01 | R1 | S15 | AT-CRM-01 |
| UR-CRM-02 | R1 | S15 | AT-CRM-02 |
| UR-CRM-03 | R1 | S15 | AT-CRM-03 |
| UR-CRM-04 | R2 | S32 | AT-CRM-04 |
| UR-CRM-05 | R2 | S33 | AT-CRM-05 |
| UR-CRM-06 | R1 | S15 | AT-CRM-06 |
| UR-CRM-07 | R1 | S15 | AT-CRM-07 |
| UR-CSH-01 | R1 | S19 | AT-CSH-01 |
| UR-CSH-02 | R1 | S20 | AT-CSH-02 |
| UR-CSH-03 | R1 | S19 | AT-CSH-03 |
| UR-CSH-04 | R1 | S21 | AT-CSH-04 |
| UR-CSH-05 | R1 | S19 | AT-CSH-05 |
| UR-CSH-06 | R1 | S20 | AT-CSH-06 |
| UR-CSH-07 | R1 | S24 | AT-CSH-07 |
| UR-AGR-01 | R1 | S22 | AT-AGR-01 |
| UR-AGR-02 | R1 | S23 | AT-AGR-02 |
| UR-AGR-03 | R1 | S23 | AT-AGR-03 |
| UR-AGR-04 | R1 | S24 | AT-AGR-04 |
| UR-AGR-05 | R1 | S24 | AT-AGR-05 |
| UR-BIL-01 | R1 | S27 | AT-BIL-01 |
| UR-BIL-02 | R1 | S27 | AT-BIL-02 |
| UR-BIL-03 | R1 | S28 | AT-BIL-03 |
| UR-BIL-04 | R1 | S23 | AT-BIL-04 |
| UR-BIL-05 | R2 | S37 | AT-BIL-05 |
| UR-TSK-01 | R2 | S34 | AT-TSK-01 |
| UR-TSK-02 | R2 | S34 | AT-TSK-02 |
| UR-TSK-03 | R2 | S35 | AT-TSK-03 |
| UR-TSK-04 | R2 | S35 | AT-TSK-04 |
| UR-TSK-05 | R2 | S36 | AT-TSK-05 |
| UR-TSK-06 | R2 | S34 | AT-TSK-06 |
| UR-DOC-01 | R2 | S38 | AT-DOC-01 |
| UR-DOC-02 | R2 | S39 | AT-DOC-02 |
| UR-DOC-03 | R2 | S40 | AT-DOC-03 |
| UR-DOC-04 | R2 | S38 | AT-DOC-04 |
| UR-DOC-05 | R2 | S38 | AT-DOC-05 |
| UR-COM-01 | R2 | S41 | AT-COM-01 |
| UR-COM-02 | R2 | S42 | AT-COM-02 |
| UR-COM-03 | R2 | S42 | AT-COM-03 |
| UR-COM-04 | R2 | S42 | AT-COM-04 |
| UR-POR-01 | R2 | S43 | AT-POR-01 |
| UR-POR-02 | R2 | S43 | AT-POR-02 |
| UR-POR-03 | R2 | S44 | AT-POR-03 |
| UR-POR-04 | R2 | S45 | AT-POR-04 |
| UR-POR-05 | R2 | S44 | AT-POR-05 |
| UR-POR-06 | R3 | S59 | AT-POR-06 |
| UR-POR-07 | R3 | S54 | AT-POR-07 |
| UR-INT-01 | R3 | S50 | AT-INT-01 |
| UR-INT-02 | R3 | S49, S51 | AT-INT-02 |
| UR-INT-03 | R3 | S49, S60 | AT-INT-03 |
| UR-INT-04 | R3 | S49, S61 | AT-INT-04 |
| UR-INT-05 | R3 | S49, S62 | AT-INT-05 |
| UR-INT-06 | R3 | S49, S52 | AT-INT-06 |
| UR-INT-07 | R3 | S49, S53 | AT-INT-07 |
| UR-INT-08 | R3 | S50, S52 | AT-INT-08 |
| UR-TAX-01 | R3 | S56 | AT-TAX-01 |
| UR-TAX-02 | R3 | S56 | AT-TAX-02 |
| UR-TAX-03 | R3 | S57 | AT-TAX-03 |
| UR-TAX-04 | R3 | S58 | AT-TAX-04 |
| UR-TAX-05 | R3 | S59 | AT-TAX-05 |
| UR-REP-01 | R1 | S29, S36 | AT-REP-01 |
| UR-REP-02 | R1 | S29 | AT-REP-02 |
| UR-REP-03 | R1 | S29 | AT-REP-03 |
| UR-REP-04 | R1 | S30, S59 | AT-REP-04 |

| Quality requirement | Implementation prompts | Acceptance |
|---|---|---|
| QR-01 Office isolation | S12, S16, S26, S30, S31, S38, S39, S42, S44, S48, S50, S63 | QT-01 |
| QR-02 Authentication and secrets | S02, S03, S04, S07, S08, S09, S13, S31, S41, S43, S48, S50, S54, S63 | QT-02 |
| QR-03 Financial integrity | S06, S17, S18, S21, S23, S25, S31, S37, S63 | QT-03 |
| QR-04 Audit history | S17, S18, S24, S25, S31, S50 | QT-04 |
| QR-05 Response time | S31, S63 | QT-05 |
| QR-06 Job idempotency | S26, S28, S35, S36, S37, S41, S42, S48, S63 | QT-06 |
| QR-07 Greek locale | S04, S15, S30, S31, S35, S47 | QT-07 |
| QR-08 Accessible responsive use | S47, S48, S63 | QT-08 |
| QR-09 Backup and recovery | S02, S08, S10, S25, S31, S38, S48, S63, S64 | QT-09 |
| QR-10 Safe file handling | S39, S42, S48, S63 | QT-10 |
| QR-11 Retention and privacy controls | S02, S46, S48, S63 | QT-11 |
| QR-12 Operational readiness | S02, S07, S08, S09, S10, S26, S31, S48, S63, S64 | QT-12 |
| QR-13 Calculation verification | S02, S55, S56, S57, S58, S59, S63 | QT-13 |
| QR-14 Reproducible delivery | S01, S03, S04, S05, S06, S07, S09, S25, S31, S63, S64 | QT-14 |

## Reusable prompts

### Resume an implementation session

```text
Apply the project instructions. Read the current repository, applicable repository instructions, implementation state, decisions and traceability. Reconcile the actual branch/commit and implemented code with the tracker. Summarise the last verified step, unfinished changes, blockers and the next eligible numbered step. Do not repeat completed work. If I name a step, execute only that step after checking its prerequisites; otherwise prepare the next-step prompt without changing business logic.
```

### Repair a failed step

```text
Apply the project instructions. Diagnose the failure in step <STEP_ID> using the attached error and repository evidence. Reproduce it with the smallest meaningful case. Fix the cause while preserving the step's scope and all business/office invariants. Run the affected checks and relevant regressions. Update the step's evidence and state, explain the cause and result, and leave unrelated scope for later numbered steps. Do not weaken an expected result to make a check pass.
```

### Review a completed step

```text
Review step <STEP_ID> against its complete prompt, mapped requirements and original acceptance checks. Inspect the code/migration diff and test evidence. Check ownership, permission denial, financial integrity and retry behaviour where relevant. Identify concrete defects or missing evidence by severity and file location. Distinguish code review from checks you actually executed. Fix authorised reversible defects within this step and update the tracker; do not claim manual approval or deployment that has not happened.
```

### Prepare a release

```text
Apply the project instructions and prepare release <RELEASE_ID> for <ENVIRONMENT>. Verify the accepted scope, image/commit identity and requirement evidence. Rehearse migrations and recovery; identify the backup and rollback point. Produce an exact release checklist including stopping relevant writers, controlled migration/static collection, web/worker start and one scheduler, smoke checks and post-release monitoring. If execution is authorised for this exact environment, execute and record results; otherwise leave it Prepared with the concrete missing inputs.
```

### Record a requirement or scope change

```text
Record change <CHANGE_DESCRIPTION> against the current requirements baseline. Identify affected UR/QR, numbered steps, schema/data, permissions, exports, jobs and acceptance evidence. Preserve stable identifiers, propose the smallest consistent change and name any new requirement. Record product-owner approval separately. Update the implementation sequence and regression expectations only after the applicable decision; do not silently remove a Must requirement or report an unavailable connector as delivered.
```

## Scope and source references

One office per active accountant is mandatory. Excluded scope remains statutory general-ledger bookkeeping, invoice issuance, payroll, automatic tax filing, bank-payment execution, native mobile apps and subscription billing.

- ACC-URS-001 v0.1: `Accounting_Platform_User_Requirements_and_Implementation_Plan_v01.docx`, 29 October 2026. Requirements, acceptance checks, decisions and releases.
- ACC-IMP-001 v0.1: `Accounting_Platform_Implementation_Pathway_GCP_DuckDNS_v01.docx`, 29 October 2026. Deployment choices, stages and operating constraints.

This is a companion to the ISO/IEC/IEEE 29148:2018-aligned requirements baseline. It allocates implementation work and does not imply certification. Changing runtime/service/tax information is rechecked in the relevant implementation step.
