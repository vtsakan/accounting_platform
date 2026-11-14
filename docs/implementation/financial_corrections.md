# S24 — linked corrections, refunds and agreement lifecycle

Status: **Prepared, code-only**. The user runs the supplied tests/builds. No
agent execution, retained-demo migration, VM deployment, account/MFA/key action,
new policy approval or full acceptance is claimed. Historical S23 operator proof:
605/605 tests, 36 financial cases, 838 boundary cases, PostgreSQL 17.11 on
2026-11-14; see its unchanged receipt. This step implements UR-CSH-07,
UR-AGR-04/05, QR-04 and Greek UI UR-LOC-01 against the accepted D08 choices.

## Corrections and retained history

All sensitive operations require the current active office owner, the relevant
capability, the owner's password, recent verified MFA, a reason, date and request
identity. Fresh office/user authority is checked after the lock wait. Correction
history is scoped read-only finance.read. No submitted office ID supplies context.

| Action | Result |
| --- | --- |
| Cash reversal | Fully negate the retained ordinary/legacy cash entry and release each live allocation in the same atomic group. Explicit legacy transfer ambiguity is rejected for S25 review. |
| Cash replacement | The same reversal plus one new ordinary entry. New references are validated normally. Released cash allocations are not silently copied to the replacement; confirm new allocations separately. |
| Transfer reversal/replacement | Reverse both original legs together; optionally post two balanced replacement legs in the same group. Cash per account changes; operating income/expense does not. |
| Charge reversal/replacement | Release its allocations and add a full linked ChargeReversal, optionally a separately linked replacement Charge. Cash remains unchanged. The canonical original one-off/month source stays consumed, preventing accidental regeneration. |
| Credit/advance refund | Choose one explicit eligible ORDINARY source and active cash account; consume only its unallocated/unrefunded capacity. Create source-bound CashRefund and its opposite-direction cash entry. Customer credit and supplier advance stay distinct. |
| Refund reversal | Fully reverse its retained cash entry, restoring availability to that exact source. A later partial return is a separate refund, not an edit. |
| Source correction with refunds | Explicitly confirm exactly all active dependent refunds. Their full reversals, allocation releases and the original correction commit together. A correction cannot predate any retained allocation/release/refund/reversal. |

Exact retries return the same completed group with no duplicate money, releases,
versions or events. A changed payload under the same request key is denied; a
new key cannot reverse an already reversed original. Retained dependencies stay
visible. An injected failure rolls back the whole command, all new cash, releases
and links. Neither posted cash nor charge originals are edited or deleted.

Each group records office, actor, effective date, database timestamps, redacted
reason and source/command/event links. Commands and cash audit rows retain the
existing S18 attribution. New retained records are not generic admin, execution
adapter or worker models. Admin posted financial fields are read-only and link
to the same confirmed staff workflows. Accounts/MFA/recovery values never enter
the payload digests or source package.

## Dates, capacities and projections

Positive exact EUR cents are checked before writes and by PostgreSQL, including
raw numeric inputs; no silent fractional-cent rounding. Office/source/charge
locks serialize competing uses. SQL checks every affected historical change
point, including later refunds and refund reversals, so backdating cannot exceed
source cash or charge capacity. A source reversal is full; partial cash returns
use the explicit source-bound refund operation. Service checks and deferred SQL
member counts protect complete cash/audit/event groups, including both transfer
legs and exact refund dependencies.

Dated balances and settlement projections preserve the day before a reversal.
A charge reversal removes its obligation on its effective date while keeping the
original row and released allocation history. A cash reversal reopens the charge,
unless that charge has itself been reversed. Cash refunds reduce operating cash
in the original business direction: returning customer credit reduces income,
and receiving a supplier advance return reduces expense; neither is misclassified
as a new transaction in the other direction. Cash-flow listings still show the
actual direction and amount. Transfers and their reversals remain excluded from
operating/category totals. Office charge totals exclude reversed obligations.
These are office fee/cash projections, not tax/VAT calculations or a statutory
general ledger; the accepted gross office amounts are retained.

Modern settlement is always derived from posted obligations and allocations.
The narrow legacy Agreement.status bridge remains for old no-charge/no-amendment
records to preserve existing financial probes; it is skipped for posted-charge
or S24-versioned agreements and never changes an explicit CANCELLED record.

## Prospective terms, cancellation and closed periods

A reviewed agreement can receive a new immutable terms version with a reason and
an explicit effective date from today forward. Party, direction, billing mode and
start date stay fixed. Price/description changes affect only new obligations at
an applicable date; prior charge snapshots and cash are unchanged. Version
selection uses the highest applicable revision, not simply the last future date.
A newer cancellation can therefore supersede an older scheduled active version.

Cancellation or ending stops new charge generation from its cutoff. Existing
debt remains collectible/visible; reducing it needs a separate explicit charge
correction. No automatic cash refund, obligation deletion or status restoration
occurs. An ended/cancelled version cannot be silently reactivated; a new contract
requires the ordinary reviewed workflow. Stale expected revisions are rejected.
Until a scheduled cutoff, the prior active terms remain applicable. Completed
one-off/month source keys are never reset by changing terms.

An owner can explicitly close the office's financial dates through a chosen day.
Cutoffs only move forward; there is no reopening action. New cash, obligations,
allocations, releases, refunds, corrections, opening approval and signed opening
adjustments on/before the cutoff are denied at service and SQL boundaries. Use a
later open date for a correction while retaining its original source reference.
Exact completed retries remain safe after a later close. This is an application
financial cutoff, not a legal/statutory year-end certification. No cutoff is
inferred during migration. Closing a synthetic demo is optional and should be
reviewed first because it is intentionally irreversible through the application.

## Schema and compatibility

Only new migrations **0019_financial_corrections / 0020_financial_correction_guards**
are added. Seven new tables: FinanceCorrection, CorrectionRelease, CashRefund,
ChargeReversal, ChargeReplacement, AgreementChange, FinancePeriodClose. Existing
cash/command choices are extended; existing columns/identities and the original
18 migration files are retained. No historical correction/closure is inferred.
0019 defines the retained records; 0020 adds same-office composite foreign keys,
immutable/date/actor guards and deferred group checks. New cash operations must
be bound by the database to one pending correction. Downgrade is denied once
retained S24 history exists. No dependency lock changes.

Original migration rehearsals intentionally use old schemas. Source-only table/
function existence probes let those historical tests use their original fields;
no settings/user flag disables installed S24 guards. Direct database/schema-owner
access remains the explicit operator trust realm; no SECURITY DEFINER privilege
or staff-accessible raw SQL bypass is introduced. Restricted-role migration
execution remains a separate operator check, not a claimed observed result.

## Operator verification and local use

APPLY_S24.sh performs Git/source/metadata operations only. It may commit only the
four generated S23 receipt/state files when those are the only outstanding edits;
it refuses other dirty files or an interrupted Git operation. It never runs the
application, Docker, tests or migrations. No dependency on a remote S23 push/tag
or missing old operator receipt blocks source delivery.

Optional after apply, from the repository root:

```bash
python3 tools/verify_s24.py --record
```

This command explicitly builds/runs a fresh random local Docker project with
PostgreSQL 17, applies migrations there, checks drift/system checks and executes
the strict full suite. It removes only that fresh project. Supplied **51** new
methods target **656** passes, **36** unchanged financial cases and **922** boundary
cases (every previous case plus 84 new route/persona/inventory cases), zero known
failures/errors/skips. These are targets, not execution results. The new contracts
cover atomic rollback, idempotency, source-bound refund amounts/history, explicit
refund dependencies, signed operating totals, both transfer legs, terms/cutoffs,
closed dates, office/CSRF/admin denials, migration preservation and independent
PostgreSQL races. The verifier records only its own S24 receipt plus state,
steps.csv and traceability.csv. Commit those four generated files once after a
successful run; do not reapply the package to save results.

The retained demo uses a source bind mount and auto-reload. Stop its web service
before applying if it is running. After successful operator checks, use an
independent backup and explicitly rebuild/restart its web service; the development
entrypoint applies 0019/0020. Do not delete/recreate its database volume or seed/
bootstrap people. The ZIP's START_HERE.txt gives the commands. The VM needs a
separate reviewed migration/deployment plan; old context-pinned S09/S14 installers
must not be reused. No deployment is performed by this step.

Greek browser/client acceptance remains Pending: correct a fully allocated
synthetic receipt, inspect reopened debt/history, separately allocate replacement
cash, refund a surplus then reverse it, correct a transfer, schedule a terms
change/cancellation, review before/after dates and test keyboard/validation/error
states as owner and accountant. All 85 full acceptances remain Pending. **S25**
legacy migration/import and reconciliation is next and is not implemented here.


## Operator-failure follow-up: locking and CSRF fixture

The operator's 2026-11-14 log reports 656 tests, 20 errors and one failure.
Its supplied tail shows PostgreSQL refusing FOR UPDATE on the nullable release
side of the allocation query. release_targets now explicitly locks only the
CashAllocation rows with `of=('self',)`. Office/source serialization, release
selection/order and database protections remain in place. The CSRF test now
copies a real MFA-verified synthetic session into a CSRF-enforcing client,
proves the protected GET succeeds, and still requires the tokenless correction
POST to return 403. The shared authentication helper and runtime security
checks remain unchanged. No test method or financial assertion is removed.

The fix is Prepared, with unchanged targets of 656 passes/36 finance/922 boundary
cases. No corrected run was executed by the agent. The provided log is a tail,
so omitted errors are not claimed to be resolved until the operator runs the
full verifier again. No migration, dependency, local demo/VM or account/MFA/key
change. See evidence/S24-locking-csrf-fix.json. The package's apply helper runs
only Git/source/metadata operations and commits the four generated S24 metadata
files before the optional `python3 tools/verify_s24.py --record` command.
