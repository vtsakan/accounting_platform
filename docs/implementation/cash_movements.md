# S20 — ordinary cash movements and typed historical search

Code-only delivery requested by the user. Status: **Prepared / not executed**.
No tests, builds, Docker containers, migrations or live deployments were run by
the implementation agent. The optional test source/verifier is for the operator.
The base is the supplied S19 package source; a published S19 branch was not
available when this implementation started. No prior operator result is inferred.

## Source changes

- `movement_views.py` implements income/expense requests using the unchanged
  atomic S18 `post_cash` service. Remarks are saved to the existing column;
  category/counterparty are optional. Cash account, classification and active
  references remain office-scoped and rechecked by the posting service.
- The form's UUID identifies an intended operation. Exact replay returns its
  original cash entry even after that entry's references retire or its linked
  agreement settles. Historical choices are restored only for that office's
  completed identity; a changed payload still fails in the service. A fresh
  form UUID permits a deliberate second identical financial movement. The
  existing tokenless session/payload fallback is retained for legacy clients.
- `movement_forms.py` parses dates, direction, related identifiers, description,
  page and page size. Dates combine inclusively; reversed intervals, duplicate
  parameter values, invalid choices/dates/numbers produce Greek field errors
  with no broad fallback results. Numeric foreign IDs retain the existing 404.
- `movement_selectors.py` is the shared list/report filter definition. Movement
  list pagination is 25/50/100 per page, deterministic by date then ID. Totals
  cover **all matching movements**, not just the page. Retired/archived references
  remain available when searching retained history.
- Existing URLs/capabilities remain the same. The report reuses typed filters
  without changing its legacy transfer/operating calculations. TRF-001 remains
  S21/S29. Ledger originals remain immutable; no edit/delete endpoint is added.
  The correction UI remains S24, with an explanatory history notice here.

All new product copy is Greek. CSRF, membership revocation, profile office,
S19 opening dates and database/category guards remain in force. No additional
runtime dependencies or migrations are needed; migrations 0001–0014 are intact.
The existing agreement selector remains a legacy settlement bridge for compatible
forms; this step does not create charges or replace S22/S23 allocations.

## Apply source only

The archive's `APPLY_S20.sh` creates `step/s20-cash-movements` from your current
S19 source and applies its patch. It does **not** run Docker, tests, builds,
backups or database commands, or stop/restart a service. It preserves private
files/accounts/MFA and previous receipts. Dynamic S19 verification timestamps and
CSV rows are not embedded in the patch: a metadata-only helper renders S20 on
top of your current records. An existing dirty Git tree or incomplete `git am`
is left for the operator to resolve; no user work is reset or discarded.

```bash
bash ~/Downloads/accounting-platform-S20/APPLY_S20.sh
```

Code may reload if your development server uses a live bind mount. Choose your
own stopping/restarting window. Your retained database must already have the
S19 migrations 0013/0014 before using these screens. No new S20 migration exists.
Do not recreate the office/users or reset MFA/recovery keys.

## Optional operator execution

These commands are provided only; none was run by the implementation agent.

```bash
python3 tools/verify_s20.py --record
```

The optional verifier builds a fresh random local Compose project, migrates its
synthetic PostgreSQL 17 database, runs the strict suite including all inherited
495 scenarios and the supplied S20 tests, and checks the same 784 boundary cases.
All nine FLT cases are expected to pass; **this is not observed evidence yet**.
TRF-001 remains the only registered expected failure. A failed test/build or
unrelated error prevents a Verified result. Cleanup removes only this verifier's
random test project, never the retained demo. Historical S19 evidence is not
rewritten or promoted; inherited scenarios are exercised against current S20.
After successful `--record`, commit the generated S20 receipt/state once.
Do not run the old context-pinned S19 verifier against the new S20 source.

All 85 full requirement acceptances, browser/client acceptance and any live VM
upgrade remain Pending. Stop after S20. S21 implements internal-transfer scope.
