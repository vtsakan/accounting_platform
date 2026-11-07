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

S03 dependency cleanup is complete; S04 settings and Greek locale work can proceed locally. The open decisions above do not require a VM or government credentials for that work. Resolve each specific policy at its dependent step. The Greek requirement is confirmed in [CR-001](../requirements/CR-001-Greek-frontend.md). Cloud target values are collected at S08 after S07.

## S03 technical selections

S03 selects CPython 3.12.16, Django 5.2.19 LTS, Psycopg 3.3.8 binary and Gunicorn 26.2.0 within the authorised architecture. [Dependency policy](dependency_policy.json) records the official evidence, target platform and deferred optional libraries; [dependencies.md](dependencies.md) records installation and update procedures. Runtime and maintenance dependencies have separate hashed locks. These technical choices do not approve or close any open D01–D09 domain policy. S04 is the next implementation step.
