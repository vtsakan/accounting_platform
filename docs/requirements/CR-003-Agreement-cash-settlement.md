# CR-003 — Agreement-scoped receipt/payment and dependent choices

Selected by the product owner on 2026-11-21 following accountant feedback.
Saving an income/expense entry with a selected agreement must also reduce its
posted unpaid obligations without a second allocation screen. A description
need not be typed when an agreement supplies it. Choosing a client must list
only that client's agreements; payments use the equivalent supplier boundary.

Source **Prepared**. Operator runtime verification, browser/accountant acceptance
and VM rollout remain Pending. This is a change request for UR-CSH-02,
UR-AGR-02/03 and supporting UR-LOC-01/QR-01/03, not an S32 selection or a change
to original requirement/policy baseline documents.

1. A new same-office receipt/payment may explicitly select one eligible
   agreement. Its cash command and all new allocations commit atomically or
   leave no new cash, command, allocation or audit when any part fails.
2. Match only that agreement's posted charges in oldest-due-date order, then
   effective date and immutable charge ID. Never consume other agreements or
   earlier unallocated receipts automatically. Excess is retained as ordinary
   customer credit/supplier advance, separately from debt.
3. Respect the selected cash date and every later retained allocation/release
   change point. A later release cannot justify earlier over-allocation. Do not
   allocate to charges posted after the cash date or reopen a reversed source.
4. Repeating a completed cash intent returns its original without allocating
   again, including pre-change cash-only entries, released allocations or owner
   corrections. Changed payloads under one key remain denied by the existing
   cash service. Preserve legacy tokenless retry identity.
5. A blank description with a selected agreement copies the effective terms'
   description and the receipt/payment direction; retries retain original text.
   User-entered descriptions and remarks remain intact. Without an agreement,
   the existing short-description requirement remains.
6. Show only the actor's office, selected party and correct agreement direction.
   Validate the relationship again in the bound form and locked write service.
   The dependent GET lookup is private, read-only and capability-classified.
   Client-side manipulation or stale options cannot grant a foreign choice.
7. An agreement with no eligible posted charges produces unallocated credit,
   not an invented charge. Existing cash and balances are not backfilled.

Keep the financial representations distinct: selection is explicit permission
to compose existing cash and allocation actions, not a new calculated debt or
paid flag. Preserve all 26 migrations, fixed-decimal arithmetic, original
financial services and prior test assertions. All 85 full acceptance statuses
stay Pending until their separate acceptance gates pass.
