# S22 — Agreement terms and explicit charge obligations

**Prepared, code-only delivery.** The implementation agent has not run tests,
builds, containers, migrations, native PostgreSQL checks or cloud operations.
The unchanged S21 operator receipt at `6f67b4c8c079f6cbdc299db623966fe3f4e222d9`
records 533/533 passes, 36 financial cases and 784 boundary cases. It is historical
evidence, not verification of this step.

Scope: UR-AGR-01, UR-LOC-01 and supporting QR-03. Use the accepted S17 D08-02,
D08-05, D08-07 and D08-09 choices bound by the existing review receipt. The
immutable original policy/example documents and named private review remain
unchanged. Source identity also implements the OP-CHARGE/OP-RECURRING overlap
contract. S23 allocations, S24 correction workflows and S27/S28 generation are
not implemented here.

## Separate representations

| Record | Meaning and effects |
| --- | --- |
| Existing `Agreement` | Retains the original identifier and current master terms, amount, direction, party and start date |
| `AgreementTermsVersion` | Database-written immutable snapshot of those terms, billing mode, independent lifecycle, actor/reason/time and revision |
| `Charge` | Immutable positive gross EUR obligation, with effective/due dates, source identity, exact terms snapshot and posting actor/reason/time |
| Existing `Transaction` | Actual cash receipt/payment; creating terms or a charge never inserts cash or a cash command |

The obligation is the posted charge. Agreed value is not added again as another
debt. Cash is displayed separately and does not automatically settle a charge.
Allocation, unallocated-credit/refund projections and reversals are later work.
An empty charge set means **no obligations**, never paid. Legacy `COMPLETED`
flags are retained as history and are not new settlement truth. S18's legacy
cash/status bridge remains compatible with all existing financial assertions.

## Additive upgrade and reviewable mapping

Migrations `0015_agreement_charge_foundation` and `0016_agreement_charge_guards`
add two tables and their guards. Original migrations 0001–0014, agreement IDs,
cash IDs, values, users/MFA and historical receipts are unchanged.

| Existing data | New mapping |
| --- | --- |
| Agreement ID `a` | Same Agreement ID `a`; revision-0 snapshot linked by `agreement_id` and office |
| Party, direction, description, amount, start date | Exact baseline snapshot of stored values |
| Legacy ACTIVE / COMPLETED / CANCELLED | Retained old field; new lifecycle UNREVIEWED, without guessing contractual or paid status |
| Unknown billing overlap | Billing mode UNREVIEWED; no one-off/monthly choice invented |
| Unknown historical human | Baseline actor NULL and origin legacy, with database recording time |
| Existing receipts/payments | Same rows/links and signed legacy projection; no allocation or synthetic obligation inferred |
| New charges during migration | None |

The mapping is reviewable in agreement list/detail and the snapshot table.
The user explicitly chooses ONE_OFF or MONTHLY, independent lifecycle, reason
and expected revision in the Greek terms form. Approved snapshots retain their
actor and reason. A stale revision fails. Rendered forms always carry a revision;
historical tokenless form clients may update an unreviewed revision-0 record,
but cannot omit the revision for a reviewed record.

Material term changes before posting append another snapshot. After a charge
is posted, repricing/reclassification/party changes are denied pending the
prospective correction workflow; originals are not edited. Existing S18 cash
history restrictions also remain. Raw operator master changes are recorded as
unreviewed snapshots rather than silently inheriting a prior approval. Status-only
legacy settlement updates do not change contractual lifecycle or create charges.

## Shared obligation source

| Billing mode | Canonical source | Rules |
| --- | --- | --- |
| ONE_OFF | `agreement:<id>:one-off` | One charge for the reviewed agreed amount; no calendar period |
| MONTHLY | `agreement:<id>:month:YYYY-MM` | One charge per calendar month, independent of version and future schedule ID |
| UNREVIEWED | None | Explicit review required before posting |

The database enforces `(office, source_key)` uniqueness and validates the key
against agreement/mode/period. A different scheduler ID or terms version cannot
create another source for the same occurrence. Changing billing mode after a
posted obligation is prohibited. A future scheduler must use `post_charge` and
the same source contract; creating another model-specific key is not an escape.

ONE_OFF charges equal the reviewed amount. MONTHLY charges use the reviewed
monthly amount; the first partial month may use a positive explicitly confirmed
amount/reason. No automatic proration, tax/VAT rate or invoice is inferred.
The monthly effective date belongs to its source month and cannot precede the
agreement start. Effective dates are no later than today in Europe/Athens; due
dates are explicit and no earlier than the effective date. Later periods are
posted explicitly here; no scheduler or worker is deployed.

## Authority, atomicity and audit

`post_charge` locks office then user and rechecks fresh authority before any
retry. It locks the agreement and active eligible same-office counterparty.
Receivable needs customer role; payable needs supplier role. The selected
snapshot must be current, ACTIVE and reviewed. The cancelled legacy flag is
also respected; a legacy COMPLETED flag is not treated as settlement proof.

A UUID form identity binds the complete canonical payload, exact cents, dates,
revision and reason digest. An exact retry returns the same Charge ID, even if
the reference was subsequently archived. Revocation still denies replay. A
changed payload conflicts. A new identity targeting the same source is denied
with the existing same-office reference; it never creates another obligation.

One atomic service encloses posting. Charge rows retain actor, reason, source,
price snapshot and UTC recording time, with business effective dates separate.
SQL triggers reject update/delete, mismatched snapshots, altered source shapes,
wrong role/office/actor and invalid occurrence prices. Composite foreign keys
bind office, agreement, snapshot, counterparty and actor. Snapshot writes only
come from the agreement trigger, and update/delete is denied. DDL/table-owner
operations retain the explicitly documented S16 operator trust boundary.

No new model is registered in admin or exposed through the generic records/job
adapter. The new `agreement-charge-add` GET/POST route requires finance.write
and is explicitly in the boundary matrix. Foreign agreement IDs return 404.
Later workers must call the authorized posting service, not an unscoped manager.

## Greek screens and compatibility

Agreement list/detail and counterparty agreement tables separate agreed amount
from posted charges. Detail shows charge source/reference, dates and versions,
plus retained cash history. Summary report charge panels show gross posted
receivable/payable obligations across the office, independently of cash filters.
They do not claim allocated outstanding balances before S23. Terms alone are
not displayed as another obligation. Historical unreviewed records remain
visible for review and are not silently billed.

The old `remaining_balance` and `accounts_receivable/payable` context aliases
remain only for the unchanged legacy regression assertions. Product panes use
the new charge projections and do not present those aliases as charge truth.
S29 retains the fuller as-of/report scope. All product copy and validation is
Greek, including field errors for malformed money/months. Existing CSRF,
same-origin referrer policy, authentication and MFA remain unchanged.

## Supplied checks — unexecuted

`accounting/tests_agreement_charges.py` supplies 27 new test methods for terms/
charge/cash separation, legacy completed flags, customer/supplier roles,
calendar source overlap, precise money/dates/prices, retry conflicts, archive/
revocation, stale review, immutable ORM/SQL writes, foreign offices, independent
PostgreSQL races, additive upgrade preservation and unsafe downgrade denial.

All 533 existing test names and financial assertions remain. Two historical
migration-test teardowns now restore the actual graph leaves, while their tested
old/current targets and every assertion are unchanged. The boundary URL helper
recognizes the new route; all 784 old case IDs remain and 15 new generic route
cases are required (8 GET personas, 6 invalid-membership POSTs and inventory).

Optional operator command, from a clean committed candidate:

```bash
python3 tools/verify_s22.py --record
```

This explicitly builds and migrates a fresh disposable Docker/PostgreSQL 17
project, checks migration drift, and expects **560 passes**, all 36 financial
cases and **799** boundary cases with no skips/known failures. These are targets,
not observed results. Restricted production-role DDL execution and Greek
browser/client acceptance remain unexecuted. Only a successful operator run
records Verified. Commit its four generated evidence/state files once.

## Applying source versus updating a running demo

`APPLY_S22.sh` only changes Git/source/metadata. It does not stop/build/restart
containers, migrate databases, push, change cloud resources or create accounts.
The current development container bind-mounts source; the new screens need the
new schema. Update the retained demo explicitly after review/testing and the
usual private backup, then open it. A source apply alone is not a database upgrade.

For the existing local demo only, its normal startup applies committed additive
migrations before starting Django:

```bash
WEB_PORT=8003 docker compose -p accounting-client-demo up -d --build web
```

Keep the existing volume, login, MFA and recovery keys. Do not recreate accounts
or use `down --volumes`. This is not a VM deployment instruction. Paired finance
corrections and reviewed histories deny unsafe schema downgrades; a rollback
must follow a reviewed restore plan. All 85 full requirement acceptances stay
Pending. Stop after S22; S23 follows when selected.
