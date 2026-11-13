# S21 — Atomic internal transfers

Code-only delivery selected by the user. **Prepared**, with no S21 tests,
builds, containers, databases or cloud operations executed by the implementation
agent. The operator's unchanged S20 receipt at `8871e76c20c20dd912b55861da5209f72a17978c`
records 511 tests: 510 passes and TRF-001 reproduced. It is not S21 evidence.

Requirements: UR-CSH-04, QR-03, UR-LOC-01; the operating-report correction also
supports UR-REP-02. Approved S17 D08 choices and OP-TRANSFER remain unchanged.

## Representation and write boundary

Reuse the S18 schema and all fourteen existing migrations. A new transfer has
one completed `FinanceCommand(operation='cash.transfer')`, two immutable
`Transaction(posting_kind='TRANSFER')` legs, a shared `command_id` and a shared
`transfer_id`. Source is EXPENSE, destination INCOME. Each leg has the same
positive exact-cent EUR amount and business date; neither has a category,
counterparty, agreement or allocation. The database appends two attributable
audit events linked to the command. User text is escaped in the frontend.

The service locks office then user, rechecks active authority, normalizes account
IDs and compares the command's canonical payload. New work locks distinct,
active same-office accounts in increasing numeric ID order. Both openings must
be reviewed and no later than the transfer date. Future dates, floats, booleans,
nonpositive/overprecise money and malformed account IDs fail. A completed exact
retry returns the original pair; a changed payload with the same identity fails.
Two submissions with different identities are intentionally different operations.

One `transaction.atomic` encloses command, both legs, both audit events and
completion. The existing deferred SQL command/pair guards reject incomplete,
unequal, same-account or otherwise inconsistent pairs at the real commit.
Exceptions roll back the entire group. No model/table/guard migration is needed.

## Greek entry and history

The existing `add-transfer` route delegates to a decorated transfer view;
`finance.write`, CSRF, session/MFA policy and route inventory stay in force.
The form supplies today's date and a new UUID operation identity. A validation
error retains that identity. A completed operation can restore only its own
retired account choices for an exact retry; the service still compares the full
payload and fresh authority before returning it. New or changed work cannot
use this to bypass retirement. The historical tokenless compatibility path is
retained for pre-existing callers; rendered forms always carry a UUID.

Both history rows show the same command reference and pair reference. The
confirmation also names the command; each account's retained history shows it.
No new route is introduced, so the existing 784-case boundary inventory remains
applicable. No edit/delete or single-leg reversal action is added.

## Selector contract

| Projection | Transfer treatment |
| --- | --- |
| Dated account balance | Includes each leg on its own account and date |
| Movement history and cash inflow/outflow totals | Includes both legs, subject to the user's cash filters |
| Operating income, expense and category totals | Excludes explicit transfers before aggregation, even when a filter selects one leg |
| New account projections | `transfer_in/out` identify transfer cash; `operating_income/expense` exclude it |
| Legacy UUID-bearing rows | Retain their existing classification; a UUID or apparent shared UUID does not prove a transfer |

`operating_movements()` excludes explicit TRANSFER rows and future linked
transfer reversals. Current services/SQL still deny single-leg transfer reversal;
paired correction administration belongs to S24. S25 must review legacy pairing
and reconciliation explicitly; this step neither rewrites nor guesses it.

For reviewed openings 2000 and 100, a transfer of 1000 produces balances 1000
and 1100. With ordinary receipt 50 and payment 20, operating totals stay
50 / 20 / 30; cash movement totals are 1050 / 1020 / 30. These are required
outcomes, **not observed S21 results**. S29 still owns the fuller report scope,
including later charge/settlement projections. This cash-basis view is not a tax
calculation or a statutory profit statement.

## Supplied operator checks

`accounting/tests_internal_transfers.py` supplies 22 tests: Greek entry and
references, retry/retirement/revocation, exact validation, two-office denial,
legacy UUID distinction, dated balances and operating/category totals, genuine
independent PostgreSQL connection races, failed second leg, real-commit SQL
rejection and immutable history. All 511 earlier tests and all original
financial assertions remain unchanged. TRF-001 is now an expected-pass target;
the strict runner will fail if it is still broken. No known failure is waived.

When desired, run from a clean committed candidate:

```bash
python3 tools/verify_s21.py --record
```

This optional command builds and tests a fresh random local Docker project on
PostgreSQL 17, expects 533 total passes, all 36 financial cases and the unchanged
784 boundary cases. It does not touch the retained `accounting-client-demo`,
people/MFA/keys or VM. Only a successful actual run writes Verified evidence.
Commit its four changed metadata files once; do not reapply the package to save
verification output. The apply helper itself only changes Git/source/metadata.

Local demo rebuild/restart and any VM release are separate explicit operator
actions. Applying source does not update a running container. Preserve existing
volumes/accounts and do not run the historical context-pinned deploy installers.
Browser/client Greek acceptance and all 85 full requirement acceptances remain
Pending. Stop at S21; S22 is the next source step when selected.
