# ACC-FIN-001 — Office financial policy

Version 0.1 · S17 · **Draft for accountant and office-owner review** · 12 November 2026.

The prerequisite is the pushed S16 Docker-verification head
`e6fde507f634a0ccd2de80b197bfd883d0ab7ac9`: 382 tests, 356 passes and the same
26 exact known financial failures; all 652 office-boundary cases passed. This
policy does not fix those failures or approve current financial totals.

This document specifies the office's operational finance model. It is not a
statutory general ledger, invoice-issuance system or determination of tax
liability. It uses numbered rules, sources, explicit inputs/effects/corrections,
state transitions and acceptance examples. Original requirement baselines stay
immutable; all 85 full requirement acceptances remain Pending.

## Decision status and source of authority

`financial_policy.json` is the structured contract; its ten `D08-01`–`D08-10`
choices are **proposals**, with no selected option or approval recorded. Existing
requirement constraints `FIN-001`–`FIN-012` remain required, including one office
per accountant, strict positive ordinary amounts, exact decimal money, immutable
posted originals, same-counterparty settlement and transfer atomicity. Passing
the example arithmetic does not make the proposed money conventions approved.

The candidate files retain their preparation labels as the immutable reviewed snapshot; effective adoption is recorded in the bound S17 receipt and D08 register, without changing the bytes that were reviewed.

The Greek review sheet is `financial_policy_review_el.md`. The accountant and
office owner must review the choices, the examples and unsupported scope.
Alternative choices require updating this contract/examples and a fresh review;
a checker never silently substitutes an unreviewed alternative. References to
later implementation steps describe work to be done, not delivered features.

| Review ID | Proposed choice | Earliest affected implementation |
| --- | --- | --- |
| D08-01 | Opening at start of date; same-day movements included; signed opening requires approval; no movement before opening | S18/S19/S25 |
| D08-02 | Calendar-month source periods, explicit due rule, reviewed first/last amount; no inferred proration | S22/S27/S28 |
| D08-03 | Explicit confirmed allocations; oldest-due-first only as a preview | S18/S23 |
| D08-04 | Retain client credit and separate supplier advances; explicit source-linked refunds; no automatic cross-direction offset | S18/S23/S24 |
| D08-05 | Gross EUR office ledger; any net/VAT breakdown is an accountant-supplied snapshot; no inferred VAT/tax | S18/S22/S27 |
| D08-06 | Cents, reject over-precise ordinary input, HALF_UP once per derived line; sum rounded lines | S18 onward |
| D08-07 | Prospective term versions; cancellation stops future generation and retains posted debt | S22/S24/S28 |
| D08-08 | Full linked dated reversal, optional replacement, historical as-of preservation; explicit correction-date restrictions | S18/S24/S29 |
| D08-09 | Separate contract lifecycle and settlement; recurring paid-to-date is not an ended contract | S22/S23/S24 |
| D08-10 | Current read/post roles retained; propose owner-only corrections with recent MFA, reason and audit | S18/S19/S23/S24; D01 extension |

No tax rates, legal retention period, VAT exemption or statutory rounding rule
is selected here. If automatic VAT/invoice handling is required, the accountant
must first define its supported regimes, dates, calculation method and examples;
the first proposed scope does not infer them from the legacy amount field.

## Distinct concepts and record contract

| Concept | Minimum immutable posting/provenance data | Meaning |
| --- | --- | --- |
| Cash-account opening | Office, account, signed amount, effective date, reviewer/reference | Approved starting cash, not operating income and not client debt |
| Agreement/terms version | Office, counterparty, direction, amount/rate, effective period, version, reason | Contractual terms; not itself a cash movement or a duplicate charge |
| Charge | Office, counterparty, receivable/payable direction, gross amount, effective/due dates, source key, price/description snapshot | A dated obligation |
| Receipt/payment | Office, account, amount, direction/kind, business date, optional counterparty/category, actor, idempotency identity | Real cash; linking a client does not silently settle a charge |
| Allocation | Office, counterparty/direction, cash source, charge, amount, effective date, actor | Application of existing cash to an obligation; no cash movement |
| Credit/advance | Projection of each source receipt/payment, its allocations, releases and refunds | Unallocated money; never a second receipt or a free editable balance |
| Refund | Original source(s), amount, same counterparty/direction, cash account, date, reason, actor/proof | Explicit return of available source money |
| Reversal/release | Original ID, opposite/released effect, date, correction group, actor/reason, idempotency identity | Corrects an original without editing/deleting it |
| Audit | Office, actor, UTC recorded_at, operation, references, reason, approved before/after values | Attributable action; exclude passwords, seeds, tokens and raw secret payloads |

A dual-role counterparty can have both receivable credit and a supplier advance.
Their sources/directions remain independent. Neither shared AFM nor a submitted
office ID supplies authority. Archival prevents new work; retained historical
corrections require the approved correction capability. A replacement/new charge
for an archived identity requires restoration and the normal new-work checks.

## Dates, openings and derived balances

**Proposed D08-01/08:** an opening on 15/01 is the balance at the beginning of
15/01. Include movements effective on 15/01. Before that date, the account has no
established balance; do not invent zero. Reject a cash posting earlier than its
opening. A reviewed negative opening is a signed starting position, not an
exception allowing negative ordinary receipts/payments. Permitted overdrafts
must be confirmed with this convention; no overdraft/credit-limit engine is
currently delivered.

`effective_date` is the business date, interpreted in the office's agreed Greek
date convention. `recorded_at` is an immutable UTC instant identifying when the
operation was recorded. Backdating needs a reason and cannot enter a declared
closed period or precede opening. Future cash is unavailable in the initial
proposal. Closed-period administration is not implemented by S17; S18/S24 must
supply its guard before claiming it. Due dates and service periods are distinct
from cash dates and timestamps.

For a report date `t`, take only posted events effective on or before `t`:

- `account_cash(t) = approved_opening + sum(signed_cash_effects_through_t)`.
- `charge_outstanding(t) = net_posted_charge(t) - net_effective_allocations(t)`.
- `source_available(t) = source_face - source_full_reversal - net_allocations - net_refunds`.

An allocation release reduces net allocations; refund reversal reduces net
refunds. The first two formulas are per account/charge; source availability is
per original receipt/payment, not an arbitrary client-wide float. Validate that
outstanding and source availability do not become negative; do not clamp a
broken result to zero. Aggregate client totals from those checked sources.
Opening receivables/payables/credit require separate reviewed migration items
with provenance at S25, not another cash opening. Do not import both a closing
cash total and the same historical movements into its balance.

An original receipt on 15/01 reversed on 16/01 remains visible on 15/01; the
opposite effect appears on 16/01. Never globally exclude an original merely
because its current metadata says REVERSED. The same dated treatment applies
to charge reversals, allocations/releases and refunds. EX-006 demonstrates it.

## Operation inputs, effects and corrections

All operations require fresh office/action authority and same-office references.
`financial_policy.json` gives the complete inputs, preconditions, invariant IDs,
decision dependencies, balance effects and permitted correction for these
17 operations:

| Operation | Immediate balance effect | Correction |
| --- | --- | --- |
| OP-OPEN | Establish account cash; no operating total or client settlement | Attributable opening adjustment after use |
| OP-ADJUST_OPENING | Apply a reviewed signed delta on its own date; no operating/client effect | Linked opposite adjustment; preserve prior as-of reports |
| OP-AGREEMENT | Terms only; no cash/charge | New prospective version or explicit cancellation |
| OP-CHARGE | Increase receivable/payable outstanding; no cash | Linked charge reversal; release its allocations |
| OP-RECEIPT | Increase cash and client source credit when linked | Linked full receipt reversal after explicit handling of dependent refunds |
| OP-PAYMENT | Decrease cash; supplier-linked payment is an advance until allocated | Linked full payment reversal |
| OP-ALLOCATE | Reduce source credit/advance and outstanding equally; no cash | Dated linked release |
| OP-RELEASE | Restore source credit/advance and outstanding; no cash | New explicit allocation if needed |
| OP-REFUND | Client: cash and credit decrease; supplier: cash increases, advance decreases | Linked refund reversal restores its original source availability |
| OP-TRANSFER | Equal opposite cash effects between two accounts; office cash unchanged | Reverse both legs together; replace explicitly |
| OP-REVERSE_REFUND | Opposite refund cash effect and restore original source availability; no charge change | A new explicit refund if subsequently needed |
| OP-REVERSE_CASH | Opposite original cash effect; release allocations; remove its own source credit/advance | New explicit replacement with retained correction chain |
| OP-REVERSE_CHARGE | Reduce net obligation; cash unchanged; allocated cash becomes unallocated | New linked replacement charge when approved |
| OP-AMEND | Only future unposted occurrences use new terms | Another dated terms version; existing postings remain immutable |
| OP-CANCEL | Stop future generation; retain posted cash/debt/allocations | No implicit reactivation/refund; explicit replacement/correction |
| OP-RECURRING | One charge per due period, never cash | Link reversal/waiver/replacement to retained source identity |
| OP-TASK_CHARGE | One confirmed task charge; task completion alone has no cash effect | Linked charge reversal preserving task/source |

A receipt reversal cannot consume refunded money twice. Effective dependent
refunds must be explicitly reversed first, within the reviewed correction group
where requested. Release allocations and remove source availability together;
EX-018 shows why releasing a fully allocated receipt must not leave phantom
credit. Full reversal is the initial proposal. Partial returns are refunds;
partial arbitrary cash reversals and recursive un-reversal are unsupported.

A convenience form combining a new cash entry with confirmed allocations must
commit the cash, allocations and audit atomically. Rejecting an allocation
against an already existing receipt leaves that existing receipt unchanged.
Neither operation may leave a new partial effect or erase pre-existing money.

## Money, rounding and operating reports

Finite decimal strings are the interchange format. Ordinary input uses Greek
presentation, e.g. `1.234,56 €`; parsing must reject ambiguity, floats, NaN,
Infinity, overflows and amounts with more than two non-zero fractional digits.
Posted cents fit the existing amount envelope until an explicitly reviewed
migration changes it. Derived intermediate arithmetic may use greater exact
decimal precision. Never perform arithmetic on display text.

**Candidate D08-06:** `ROUND_HALF_UP` once per derived posted line; total the
rounded lines. Three lines of 0.335 become 0.34 each, total 1.02; rounding the
unrounded total gives 1.01 instead. EX-013 deliberately exposes this choice.
Do not apply either convention as an approved tax rule. A residual allocation
or manual proration must remain visible for explicit resolution, not disappear
in rounding. Cash/allocations already in cents are not rounded again.

The management views show distinct quantities: **Χρεώσεις**, **Εισπράξεις**,
**Πληρωμές**, **Επιστροφές**, **Αντιλογισμοί**, **Πιστωτικό**, **Ανεξόφλητα**.
Opening balances, internal transfer legs and allocations are not ordinary
operating receipts/payments. Customer refunds and receipt reversals reduce net
incoming operating cash in separate visible columns; they are not reclassified
as supplier expenses. Supplier refunds/payment reversals symmetrically reduce
net outgoing operating cash. Keep original and correction amounts visible for
their respective date ranges.

A 120 receipt against 100 charges is 120 cash collected, 100 billed and 20
credit; it is not a claim of 120 earned revenue/profit or client myDATA turnover.
Statutory reporting, VAT determination and tax forecasts require their own
approved rules and source data in their assigned modules.

## Contract and settlement states

| Record | Legal transitions | Rule |
| --- | --- | --- |
| Terms | DRAFT → ACTIVE; DRAFT → CANCELLED; ACTIVE → ENDED/CANCELLED | Amendments produce versions, not edits of posted history |
| Charge | DRAFT → POSTED → REVERSED | OPEN/PARTIAL/SETTLED is a derived dated projection |
| Cash/refund/transfer group | DRAFT → POSTED → REVERSED | Reversal of a transfer acts on the whole pair |
| Allocation | POSTED → RELEASED | Release is a linked event; never delete the original |

The complete finite-state definitions are in the JSON contract. An agreement
with no effective positive obligations is **NO_OBLIGATIONS**, not paid. Positive
outstanding with no effective allocation is OPEN; with some allocation it is
PARTIAL; zero outstanding against posted positive obligations is SETTLED.
For a one-off agreement, all planned obligations must be posted and settled
before displaying COMPLETED. For recurring terms, SETTLED_TO_DATE does not stop
future due charges while ACTIVE. A cancellation remains CANCELLED even if the
retained charges are fully settled or a later correction creates an unpaid
balance. Display its balance separately instead of overwriting cancellation.

## Idempotency, locking, recurring work and audit

The later services must atomically lock office, actor/user and protected money
sources/targets in stable order, then recheck authority, state, availability and
expected version after waits. A concurrent allocation cannot over-settle a
charge or over-consume a receipt. Use database uniqueness/checks plus service
validation; form validation alone is insufficient.

A repeated idempotency identity with identical semantic payload returns the
original result. A changed payload conflicts. Identity includes office,
operation, durable caller key and a canonical payload fingerprint. Protect the
whole correction or transfer group, including audit. Do not include raw
secrets in fingerprints or audit data.

Recurring charge identity is `(office, agreement/schedule-source, calendar
period, charge kind)`, independent of the terms version; a changed version
cannot re-charge the same occurrence. An explicit waiver/reversal outcome is
retained so retry does not silently recreate it. Billable tasks use one durable
task/source identity plus price confirmation. Dispatch occurs after commit and
execution rechecks authority/cancellation at S26/S28/S37; S17 creates no worker.

Audit identifies office, actor, recording instant, business date, operation,
original/replacement/source references, reason and authorised before/after
fields. Money originals and audit events remain append-only. No posted-record
edit/delete becomes an ordinary admin shortcut. D08-10 must be reviewed before
new correction capabilities are added to D01/S18/S24.

## Examples, denied cases and review gate

`examples/S17-financial-examples.json` contains 20 synthetic scenarios and 16
expected denied cases. The Greek rendered examples are
`examples/S17-financial-examples_el.md`. Required cases include 100/25 partial
settlement, 120/100/20 credit, two-account transfer and completed-settlement
reversal. EX-007 additionally separates contract cancellation, charge reversal
and refund. Each scenario identifies the decisions and future implementation
steps it depends on.

`tools/verify_s17.py` validates the contract, safe exact-decimal expressions,
example results, review bindings, unchanged application context/migrations/tests,
and S16's actual evidence. It does not run new application/database/concurrency
checks or count the 16 expected denials as executed application tests. The
S16 PostgreSQL suite remains prior evidence. It rejects incomplete/duplicate
cases, invalid numeric types and stale/incomplete review records.

```bash
python3 tools/verify_s17.py --record
```

This produces **Prepared** while accountant review is pending. Commit the
resulting evidence/state files once; a repeat record run requires clean source.
Prepare the private review template without overwriting an existing file:

```bash
python3 tools/verify_s17.py \
  --make-review-template private/S17-financial-review.json
```

Fill it only after actual accountant/office-owner review: names/roles, timestamp,
review reference, all ten selected proposed options, examples reviewed and no
unresolved conditions. It binds policy, example and document digests. Keep the
filled review in ignored `private/` or outside Git. It is a recorded human
attestation, not identity verification or a digital signature. To record it:

```bash
python3 tools/verify_s17.py \
  --review-file private/S17-financial-review.json \
  --require-approved --record
```

A changed alternative/condition leaves S17 Prepared and calls for revising the
contract/examples, then reviewing new digests. A malformed or stale record is
rejected. Verified requires the actual S16 gate and the bound declared review;
it does not approve application money behaviour, tax treatment beyond scope or
full requirement acceptance. No S18 posting code is implemented by this step.

## Unsupported and blocked work

Initial proposal exclusions include multi-currency/FX, bank reconciliation,
statutory general ledger, tax invoice/credit-note issuance, automatic tax/VAT/
withholding computation, automatic cross-direction offset, unreviewed proration,
due days 29–31, future cash, partial arbitrary cash reversal and silent
reactivation of cancelled terms. The JSON contract lists them explicitly.
An unsupported case must stop with a Greek explanation, never a silent fallback.

Every unresolved D08 choice names its blocked steps in the contract. D08-01/06/
08/10 affect the S18/S19 service foundation; allocation/credit/VAT choices affect
S23, recurrence choices S27/S28, cancellation/corrections S24, and reconciliation/
report semantics S25/S29–S31. Real-data cutover remains gated by S25/S31 and
recovery evidence. The 26 exact known financial failures and their correct
assertions remain unchanged. **S18 is the next implementation step only after
S17's required accountant decisions have been recorded.**
