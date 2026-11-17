# S29 — dashboard, dated statements and financial overviews

Status: **Prepared, source only**. The operator runs all tests/builds/migrations.
S28 is operator-Verified from git:9b24a52217545c5a2ecf13a5c1fadb1d9b9e1443,
image sha256:23fa49adebb0a3b06ff170bb2f81239fedc00a5f8278f5554cc32cbf298d1067:
772/772, all 36 financial cases, 343 exact-source bindings, four host contracts,
actual scheduler-created obligations and two deliveries/one charge after a
worker child died after commit/before acknowledgement. The receipt is retained.
S29 implements UR-REP-01/02/03 and Greek frontend under UR-LOC-01.

## Screen bases and reconciliation

The office dashboard keeps its S24A Material workspace, active cash balances,
current-month operating cash and six recent movements. It now adds actual
dated receivable/payable debt, separate unallocated customer credit and up to
ten clients with unpaid posted charges. No task counter or sample metric.

The period report at the existing `/report/` uses PeriodReportForm and the
same filtered movement queryset for operating totals, category groups and
paged detail. Existing business-direction rules retain refunds/reversals with
their proper sign. Internal transfers and their reversals contribute zero
operating income/expense even when filtering just one account. Cash receipts
are separate from contract terms and posted obligations; no tax-profit claim.

The full selected-account bridge independently reconciles opening cash plus
all physical inflows minus all outflows plus dated opening adjustments to the
closing balance. It includes transfers and both corrective cash directions.
If the account opened during the period, its reviewed opening amount enters
once. If an opening date is missing or after the end date, the balance stays
unknown and the subtotal is explicitly only the known accounts. Category,
counterparty, direction and text filters cannot allocate opening account cash
to a client, so those restrictions do not apply to the full account bridge.
The account selection and period end do apply, and the distinction is labelled.

Posted charge/settlement/credit cards use the same office and optional entity,
with a separately displayed as-of date. This defaults to the chosen period
end, otherwise today; it cannot precede the period end or exceed today. Cash
period start does not erase earlier open obligations. Cash account/category/
direction/text filters do not change the client-wide debt/credit position;
the cards and detail tables explicitly explain this different reporting basis.
Every card traces to its full dated charge or source-cash detail before paging.

The counterparty statement `/reports/clients/<id>/` works for own current and
archived clients, suppliers and dual-role counterparties. It fixes the selected
entity, shows both debt directions and separate credit/advances, and lists cash,
charges, original receipt credit and allocation/release events. A release of an
older allocation appears on its own effective date. Refunded/reversed originals
stay visible; their dated net/available amounts come from the retained selectors.
Cancellation does not hide a posted obligation. An entity input cannot change
the route's statement to another entity. Revocation blocks the next request.

The twelve-month `/reports/fees/` table includes all posted client obligations,
including one-off charges in their effective month. For each month it separates
original charges, reversals, net charges, operating receipts after refunds,
active allocations to that month's charges, remaining debt, and unused credit
from original receipts in that month. All balances use one as-of date. A later
receipt allocated to an earlier charge remains in the receipt's month while
settlement reduces the earlier charge cohort. Cash and charge cohorts are not
summed together or silently offset. Future months contain no invented fees.

Annual totals plus the explicitly displayed outside-year bucket equal the whole
dated statement's net charges, allocated amount, remaining debt and credit.
The outside bucket includes every other year's cohort visible as of the cutoff,
including later cohorts when inspecting an earlier year with a later as-of.
Month links expose the exact selected charge/receipt/credit detail; pagination
preserves entity, date, year and other page filters. Supplier debt remains a
separate dated statement/report basis rather than client fee turnover.

Legacy unreviewed movements can contribute their retained cash semantics but
are not fabricated as allocatable credit. A notice identifies such cash rows;
the original S23 eligibility rule is unchanged. Historical report context aliases
needed by older S12 probes remain available but are not rendered as product debt.

## Authority, consistency and exclusions

All screens require finance.read and derive the office from live membership.
Model-choice filters include only that office, including inactive/archived
references for history. Foreign IDs produce 404; malformed/duplicate/invalid
dates return Greek field errors and empty scope, never broader aggregates.
Every source query has office/entity/date bounds. Source detail is paginated
25/50/100 rows; totals are calculated before paging. No new admin/records model.

Normal top-level report reads use a PostgreSQL REPEATABLE READ, READ ONLY
transaction. Financial aggregates and paged objects are materialised before
leaving it. This keeps one committed snapshot across queries without locking
financial writers. Nested callers, including existing TestCase fixtures, retain
their existing transaction isolation; callers requiring a new snapshot must
start a top-level report request. Forms' rendered choices may load outside the
money snapshot, but financial rows and totals are already materialised. The
pages are private/no-store and accept GET only. They never post a charge, cash
entry, allocation, refund, agreement change or background task.

All existing financial write services and financial selectors are unchanged,
as are all 26 migrations, schemas, dependencies, pins and S28 automatic opt-in.
Only the old S16 URL adapter adds the statement route key; every prior test
method/assertion is unchanged. The new finance.read routes join the boundary
inventory. No export, task counter, tax connector, client business turnover,
forecast, VAT calculation or new domain-policy approval is introduced.

## Optional operator verification

APPLY_S29.sh performs only Git/source/tracking and can retain the four already
generated S28 Verified tracking files before making the S29 branch. All historical
receipt bytes and all acceptance statuses are retained. No VM action occurs.

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/verify_s29.py --record --host-dns
```

A new exact committed-context image is required. The gate must pass all 772
retained tests plus 36 new report/snapshot methods (**808 target, unobserved**),
all 36 financial cases, exact-source/host contracts and the unchanged full S28
real Redis/scheduler/worker/commit-before-ack gate on the new image. New contracts
cover physical cash reconciliation, unknown openings, partial dates, reversals,
refunds, dated allocation releases, cancellation, annual outside-year buckets,
source detail/pagination, two-office denial, Greek/no-store/no-writes, and an
actual concurrent cash commit during a repeatable read-only report snapshot.

Agent checks are static AST/source/hash/route/template checks and text scanning.
Templates may be compiled without setup or rendering. No agent tests/builds/
Docker/migrations/native application verification/browser/SSH/cloud/push.
S29 Prepared until the full operator command succeeds. Greek browser/manual
acceptance, VM rollout, D05/G2 and all 85 full requirement acceptances stay Pending.
Stop after S29. PDF/CSV export is S30 when separately selected.

Primary references:
- https://www.postgresql.org/docs/17/transaction-iso.html
- https://www.postgresql.org/docs/17/sql-set-transaction.html
- https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- https://docs.djangoproject.com/en/5.2/ref/models/querysets/
