# S23 — Partial settlements, allocations and separate credit

Status: **Prepared, code-only delivery**. No tests, builds, migrations, Docker,
local demo or VM operations were executed by the agent. Optional operator gate:
`python3 tools/verify_s23.py --record`. S22's existing receipt remains unchanged:
560 passes, 36 finance cases, 799 office-boundary cases on PostgreSQL 17.

Operator follow-up (14 November 2026): the supplied run reached 605 tests with
one error in the fractional-cent negative test: `amount` was passed twice to
the raw SQL fixture. The fixture now supplies one explicit amount per case.
Every denial assertion and the 605/36/838 targets remain unchanged. No product
code or migration changed; the agent has not rerun the suite. See
`evidence/S23-test-fix.json`; S23 remains Prepared until the operator reruns
`python3 tools/verify_s23.py --record` successfully.

## Behaviour and reviewed scope

An ordinary receipt/payment is retained cash, not automatic settlement. A staff
member explicitly selects one source, one or more eligible obligations and the
exact amount for each. A source may cover several agreements belonging to that
same counterparty; a charge may receive several partial settlements. The
original optional cash agreement reference does not restrict or create these
allocations. Each batch commits completely or has no effect. No FIFO allocation
or cross-direction offset runs on save.

| Example | Effective allocated | Charge outstanding | Unallocated source |
| --- | ---: | ---: | ---: |
| Charge 100; receipt 25; confirm 25 | 25 | 75 | 0 |
| Charge 100; receipt 120; confirm 100 | 100 | 0 | 20 |
| Charge 100; receipt 120; no confirmation | 0 | 100 | 120 |
| Release an allocation of 25 | decreases by 25 | increases by 25 | increases by 25 |

Customer receipts settle RECEIVABLE charges only. Supplier payments settle
PAYABLE charges only. The party, office and EUR direction must match. A dual-role
party keeps customer credit and supplier advance separately; totals never net
those two directions or invent an automatic refund. New allocation requires an
active eligible party and fresh staff authority. Retained debt on a cancelled
agreement can still be settled; its cancellation is not overwritten.

Only explicit `ORDINARY` cash with a counterparty is eligible. Transfers,
reversals, reversed sources, partyless movements and `LEGACY` cash are excluded.
Legacy review remains S25; the migration creates no inferred historical links.
Already retired cash accounts do not invalidate an earlier eligible receipt.

## Retained records and transactional boundary

Migrations **0017/0018** add three tables; all sixteen preceding migrations and
all existing cash/charge/person IDs and financial assertions remain unchanged.

| Record | Purpose |
| --- | --- |
| SettlementCommand | Source, actor, operation, date/reason, hashed request/payload, expected row count, completed state |
| CashAllocation | Original cash, original charge, positive exact amount and effective/recording dates |
| AllocationRelease | One full dated release per original allocation, through a distinct owner command |

Allocation amounts use unrestricted PostgreSQL numeric plus an exact-cent guard; raw SQL cannot silently round a fractional cent.

Commands start pending and complete once. Deferred database constraints reject
empty, incomplete, mixed or uncompleted groups at commit. Allocation/release
rows cannot update/delete, even through direct SQL; completed commands cannot
change. Composite foreign keys bind every source, actor and related row to the
same office. A downgrade stops once settlement history exists.

Services lock office, user and fresh authority before business rows. Sources and
sorted charge UUIDs are locked; the database also writes the existing finance
serialization root before capacity checks, including raw SQL paths. Capacity is
checked at the candidate date **and every affected later allocation/release
change point**. Thus backdating after a later release cannot overuse historical
cash or debt. Exact request retries return the same completed group; changing
payload under the same request identity is rejected. Retry still checks current
membership. No raw password or submitted free text is copied into hashes beyond
the cleaned reason's digest; the reason itself is retained for accountability.

The trusted database operator can of course disable triggers; this is not a
separate untrusted SQL-user security realm. Password/MFA proof belongs to the
HTTP/service boundary. SQL additionally checks an active same-office actor and
owner role for releases.

## Release and cash correction boundary

A release needs `finance.release` (owner), the owner's password, recent verified
MFA, date and reason. It releases the whole original allocation once, retains it
and restores debt/credit on the selected effective date. It can correct archived
history. A second identical request is safe; a different second release fails.
Past dated views retain the original effect until the release date.

Releasing does not move cash. The existing S18 cash reversal now refuses a source
with active allocations, and cannot predate any retained allocation/release.
Release explicitly first; full grouped corrections, refunds and their screens
remain S24. S23 does not add a cash refund action or automatic money movement.

## Greek screens and derived totals

- Counterparty card → **Εξοφλήσεις και αδιάθετα ποσά**.
- A dated workspace displays source cash, remaining charge debt, active/released
  allocation history, customer credit and supplier advance together.
- Each source's **Αντιστοίχιση** opens explicit charge/amount rows and reason/date.
  Leave unused rows blank. The standard form offers six rows per confirmation;
  another confirmation can use the remaining source. The service supports up
  to 100 rows and the bounded formset accepts up to 20 submitted rows.
- Owner-only release confirmation appears with the allocation's retained history.
- Agreement details/lists display allocated and remaining obligation amounts.
  Monthly settlement means **Εξοφλημένη έως τώρα**, without claiming future months.
- Report debt totals derive from effective allocations. Credit/debt cards are
  current whole-office values; movement filters still control operating cash
  totals separately. Full financial reporting/export remains S29/S30.

GET routes never write events. The three new routes are declared in the existing
boundary manifest; there is no new generic admin, records or worker adapter.
All authored labels/help/errors are Greek; source descriptions remain original.
Deprecated `remaining_balance`/`total_payments` compatibility contexts stay only
for unchanged legacy financial probes, not the settlement UI's source of truth.

## Operator verification and application

45 new test methods are supplied. Targets, **not observed results**, are 605
passes, all 36 original financial cases, zero failures/skips and all 838 boundary
case IDs (799 retained plus 39 for the new routes). Tests include partial/multiple
payments, direction/office denials, exact retry, full rollback, dated releases,
historical capacity, direct SQL immutability/commit guards, distinct PostgreSQL
backends, real revocation lock waits and migration/downgrade preservation.

Apply changes Git/source/metadata only. The operator may run:

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
python3 tools/verify_s23.py --record
```

After one successful run, commit the generated four S23 evidence/state files;
do not rerun just to save output. A dirty tree is intentionally refused before
verification, so private MFA downloads stay outside Git.

The standard development Compose file bind-mounts source. A running web process
may reload new code before its schema exists. The operator can stop only that
web service before applying source, retaining the database/volume:

```bash
WEB_PORT=8003 docker compose -p accounting-client-demo stop web
```

For the retained local demo, only after its backup and verification are reviewed,
explicitly rebuilding/restarting its existing web service is a separate action:

```bash
WEB_PORT=8003 docker compose -p accounting-client-demo up -d --build web
```

Its development entrypoint applies the two additive migrations. Existing volume,
office/accounts and MFA are retained; do not use `down --volumes`, seed/import,
bootstrap a second owner or delete previous data. The apply helper does not run
this command. Existing production/VM deployment tooling is not reused here.

Manual Greek browser/keyboard/accessibility and restricted-role DDL remain
Pending. All 85 full requirement acceptances remain Pending. Requirements:
UR-AGR-02, UR-AGR-03, UR-BIL-04, QR-03, UR-LOC-01. Next selected work may be S24;
this package stops at S23.
