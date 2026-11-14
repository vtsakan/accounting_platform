# S19 — dated cash accounts and category workspace

Scope: UR-CSH-01/03/05, UR-LOC-01, QR-03/04. The actual verified S18 source is
`22dbd3a12816cfaceb62958ad45e19231669f3be`. No new dependencies, live messages,
cloud changes, human accounts or automatic demo migrations are introduced.

## Behaviour and balance contract

`cash_selectors.cash_accounts(user, as_of=day, include_inactive=...)` derives the
office from a fresh active staff profile. It returns a reviewed opening plus
income minus expense plus signed opening adjustments in the inclusive interval
`opening_date <= business_date <= as_of`. Each aggregate has an exact Decimal
zero; independent correlated subqueries prevent a cash/adjustment join from
multiplying amounts. Dashboard and account detail use this selector, which is
the shared contract for later balance reports. Operating report/transfer/filter
changes remain S20/S21/S29; the remaining ten known defects stay explicit.

| Example | Displayed balance |
| --- | --- |
| Opening 100, no cash | 100.00 |
| Opening 100, same-day income 50, no expense | 150.00 |
| Opening 100, expense 20, no income | 80.00 |
| Opening 100 on 15 January, older income 30 and same-day income 50 | 150.00; the older 30 remains in history |
| No reviewed opening date, or viewing before that date | Awaiting approval / no established balance; never an invented zero |
| Opening 100, cash income 50, signed adjustment 7 and inverse -7 | 150.00 after the inverse's effective date |

Transfers still move money between accounts and have zero aggregate office-cash
effect. A future reversal changes the balance only from its effective date.
Opening adjustments do not create income, expense, charges or settlements.

## Greek staff journeys

- **Ταμεία** (`/cash/`): active/inactive/pending filters, 25-row pagination,
  create pending account, edit name/status and inspect all retained history.
- Detail (`/cash/<id>/`): exact dated components, validated date and retained
  movements marked before/within/after the calculation interval.
- **Έλεγχος και έγκριση αρχικού υπολοίπου**: owner-only preview shows the amount,
  date and prior-movement counts/net. It binds an immutable history fingerprint,
  account version and office to a signed 15-minute token. Confirm requires a
  reason, evidence reference, explicit cutoff acknowledgement, real password
  and MFA in the last five minutes. Exact retries return the same approval;
  changed inputs, expired/tampered tokens and intervening metadata changes fail.
- **Τεκμηριωμένη προσαρμογή αρχικού υπολοίπου**: owner proof records a signed
  nonzero delta and evidence. Ordinary staff adjustments use today's Athens
  business date. Correct one by its single linked exact inverse, preserving
  both originals. Full period/cash-correction screens remain S24.
- **Κατηγορίες** (`/categories/`): create, rename/reparent, retire and restore.
  Foreign-office/self/descendant parents fail, including direct SQL and races.
  Retire or move active children before the parent. Retired categories and cash
  accounts disappear from new-work choices but remain on original records.

Owner/accountant retain `finance.write` for reference metadata. Owner-only
`finance.opening` is based on accepted D08 correction authority. All requests
resolve office from membership, never POST data. Existing CSRF, same-origin
referrer policy, session revocation and rate budgets remain enabled. Passwords
and review tokens are marked sensitive; audit snapshots use allowlisted fields,
exact monetary strings and actor/date/reference identity, without secret values.

## Migrations and operator boundary

Original migrations 0001–0012 are immutable.

- `0013_cash_accounts_categories` adds nullable opening metadata, legacy flags,
  versions, category state/root uniqueness, the signed adjustment table and
  office structure guard. Existing account amounts/IDs and movement columns are
  preserved; all existing dates remain unknown. Invalid legacy category cycles,
  excessive depth or duplicate roots stop **before** new schema changes. There
  is no auto-merge, deletion, inferred date or unreviewed financial rewrite.
- `0014_cash_workspace_guards` adds same-office foreign keys, immutable approved
  openings/adjustments, hierarchy and retirement guards, extended append-only
  audit and deferred adjustment/audit completeness. A writable office guard
  serializes raw SQL cross-row decisions; stale Repeatable Read writers abort
  rather than creating a category cycle. Audit failure rolls back the event.
  Unsafe downgrade after approved openings/category changes/adjustments stops
  for a separately reviewed preservation plan.

Trusted operator SQL remains the S16/S18 database/DDL realm. It can restore an
explicit synthetic opening/date or dated adjustment, with `origin=database`
and no invented human actor. A holder of schema/DDL rights can disable guards;
that is not a staff API. Normal UI/services always enforce owner proof. No new
unscoped endpoint, admin model, worker, file or export is introduced.

Old migration tests use historical models/columns rather than querying today's
new columns before they exist. Financial fixtures explicitly declare synthetic
opening dates; this is not a legacy backfill. Correct financial expected-value
assertions and all 428 old test names are retained. Only BAL-001–003 change from
known failure to passing. Remaining known failures: TRF-001 and FLT-001–009.

## Apply on the laptop

Download/extract `accounting-platform-S19.zip`, then from any directory:

```bash
bash ~/Downloads/accounting-platform-S19/APPLY_S19.sh </dev/null
cd ~/accountant_cloud/accounting_v5/accounting-platform
python3 tools/verify_s19.py --record
```

The installer starts an existing stopped demo database, stops only the demo web
before source/migration changes and creates an age-encrypted database/environment
backup outside Git using the configured public recipient. It keeps the database
volume, users, MFA and recovery keys. Docker child commands have closed stdin so
pasting a shell block cannot consume the next verification command. If a required
prerequisite fails, its named stage stops with a useful message. It does not
create a replacement demo or change the VM. A completed installation is not
reapplied. Source/evidence must be committed before the recording verifier runs.

The verifier creates its **own disposable Compose project**, reproduces pinned
locks/catalog, scans Git history/candidate text, runs PostgreSQL 17 migrations,
checks migration drift, the complete strict regression suite and the extended
office boundary matrix. It does not inspect or change the retained demo.
Native PostgreSQL proof is **Prepared**; actual laptop Docker yields **Verified**.
After a successful `--record`, commit generated evidence once:

```bash
git add docs/implementation/evidence/S19-verification.json \
  docs/implementation/evidence/S19-office-boundary.csv \
  docs/implementation/state.md docs/implementation/steps.csv \
  docs/implementation/traceability.csv
git commit -m "docs: record S19 Docker verification"
git push -u origin step/s19-cash-accounts
```

Do not reapply the package or rerun verification just to save its output. The
verifier's generated working-tree changes are expected, not lost source.

## Explicit retained-demo migration after Verified

Use the same `.env`, Compose project and port; do not delete volumes or rerun
bootstrap. The installation backup is retained under
`~/.config/totalaccounting/local-demo-backups/s18-before-s19.*`.

```bash
bash <<'SH'
set -euo pipefail
cd ~/accountant_cloud/accounting_v5/accounting-platform
python3 - <<'PY'
import json
from pathlib import Path
r=json.loads(Path('docs/implementation/evidence/S19-verification.json').read_text())
assert r['status']=='Verified' and r['docker_execution'], 'Complete the S19 Docker gate first'
PY
WEB_PORT=8003 docker compose -p accounting-client-demo build web </dev/null
WEB_PORT=8003 docker compose -p accounting-client-demo run --rm --no-deps \
  --entrypoint python web manage.py migrate --noinput </dev/null
WEB_PORT=8003 docker compose -p accounting-client-demo up -d --no-deps web </dev/null
WEB_PORT=8003 docker compose -p accounting-client-demo ps </dev/null
SH
```

Sign in with the existing owner at `http://localhost:8003/`. For each old cash
account, inspect its original amount/history and **approve its actual cutoff**
in **Ταμεία** using password/recent MFA. Do not choose a date merely to clear a
warning. Earlier cash stays visible but is excluded because the reviewed base
already includes it. Pending accounts cannot receive new cash. New accounts can
approve zero explicitly. The VM upgrade is a separate future operation; old S09
ship/S14A empty-database tooling must not be used for this populated demo.

## Acceptance and next step

Evidence: `evidence/S19-verification.json`, `evidence/S19-office-boundary.csv`,
`accounting/tests_cash_workspace.py`. Native and Docker reports distinguish
actual execution. The installer/control-flow checks do not claim an actual
Docker backup, browser session, client sign-off or live VM migration here.

Manual Greek desktop/mobile/keyboard acceptance, real dataset financial and
recovery targets, complete closed-period administration and all 85 full
requirements remain **Pending**. S20 is eligible after the laptop Docker S19
gate. Stop after S19; do not fix unrelated report/filter defects in this step.

For implementation environments with slow temporary filesystem sync, native
verification accepts `--native-fast-io` **only** alongside `--native-bin`. It
changes fsync/synchronous_commit only in the newly created disposable synthetic
cluster, records `native_io` explicitly and still runs real PostgreSQL commits,
constraints, independent connections and the full suite. It does not establish
power-loss/crash durability. The default native and laptop Docker modes retain
their normal durability settings; no retained database is configured by this
option. S09/S10 recovery evidence remains unchanged.
