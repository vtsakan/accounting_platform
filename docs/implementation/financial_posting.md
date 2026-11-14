# S18 — financial posting foundation (ACC-FIN-IMPL-001)

This step implements the current cash posting/correction boundary required by
QR-03 and QR-04. The product owner accepted D08-01–D08-10, with the named
accountant/office-owner declaration bound to the unchanged S17 policy, examples
and documents. That declaration is private. Application, browser/client and
release acceptance remain separate.

## Implemented operations

| Entry point | Contract |
| --- | --- |
| `post_cash(user, idempotency_key, ...)` | Positive exact EUR cents; active same-office account, eligible counterparty, matching agreement/direction; one cash original and durable command, plus database-written audit in one transaction. |
| `post_transfer(user, ...)` | Current legacy transfer UI now calls one service; two equal opposite legs, distinct active accounts, one group/command. Deferred commit checks reject a half group or unequal pair. Full operating-report classification and paired transfer reversal remain S21/S24. |
| `reverse_cash(request, ..., password, reason)` | Owner only; real current password, confirmed authenticator and MFA within the existing five-minute proof window. Full opposite cash event linked to the retained original; optional independent replacement in the same transaction. Reject repeated/recursive reversal, foreign source, transfer leg and a reversal date before the original. |
| `save_master(instance, user)` | Current cash-account/category/agreement writes are attributed. Reject ordinary changes to a used opening or posted agreement identity/value/start/status. Existing cancelled agreements do not reactivate through posting. |
| `finance_history(user, target_model, target_id)` | Owner audit capability, exact office scope, bounded last 100 events. No global audit admin or HTTP endpoint is added. A later history/report UI can use this reader. |

The correction function is a core service, **not a new operator command or
self-service screen**. The full Greek correction/lifecycle workflow is S24.
No allocation/credit/refund/charge feature or closed-period administration is
claimed by S18. Current cash has no opening date until S19; closed-period and
dated-opening policy acceptance remains pending in its assigned steps. Do not
use this technical preview as an accepted statutory ledger.

The current `Agreement.total_amount` and its transaction link are explicitly a
**legacy settlement bridge**, not a charge or allocation model. A service
recomputes the legacy ACTIVE/COMPLETED projection from signed original/reversal
cash; cancellation is preserved. This is not the final contract lifecycle.
New charges/allocations will reference retained IDs and durable commands at
S22/S23; no legacy money or identifiers are rewritten here.

## Money and database boundary

`finance_money.money` rejects bool, binary float, nonfinite, zero/negative
ordinary money, values outside ±9,999,999,999.99 and over-precise ordinary inputs.
Signed exact opening values are structurally representable. `rounded_line`
uses decimal `ROUND_HALF_UP` once per derived line, with bounded inputs; callers
sum those rounded lines. S18 does not infer VAT, net amounts or tax rates.

Migrations 0011/0012 retain the model's 12-digit/two-place contract and add
explicit positivity/bounds/cent checks. Physical PostgreSQL columns are
unconstrained `numeric` with those checks: `numeric(12,2)` otherwise coerces
1.005 to 1.01 **before** a CHECK could reject over-precision. Raw SQL tests prove
that precision, NaN and infinities cannot bypass this boundary. Audited monetary
JSON values are decimal **strings** to prevent downstream floating-point decode.

References use the existing composite office foreign keys plus command/actor/
reversal/audit composite links. New SQL cash inserts also require a valid
cash direction, Greek business date, account and matching settlement target.
The SQL day is explicitly Europe/Athens, independently of the session timezone. Ordinary updates
and deletes of every cash row, including historical LEGACY rows and free text,
are denied by PostgreSQL. A harmless model re-save returns without a write;
it never re-runs a settlement side effect. Django admin displays posted rows
as read-only, rejects change/delete, and routes additions through the service.

## Retry and locking protocol

A command identity is `(office, operation, SHA256(caller_key))`; canonical
payload digests distinguish a retry from changed content. The raw key is not
stored. Free descriptions/remarks contribute only digests, never copies, to
command/audit payloads. Password/MFA proof never contributes to those digests.
A completed identical retry returns the original cash IDs without new audit;
a changed payload conflicts. Authority is rechecked even for replay.

Greek HTML cash/transfer forms and admin addition carry a hidden fresh UUID.
Use a fresh key for another legitimate posting, even with the same contents.
Legacy tokenless browser requests use a stable HMAC of the authenticated
session plus route and validated payload, so identical retries in that session
collapse. Identical intentional tokenless postings in the same session also
collapse; integrations must use the explicit key API, not this compatibility
fallback. The fallback stores neither a session key nor its HMAC in audit.

Every service locks office, then actor, rechecks fresh membership, and locks
money references in stable order inside one atomic transaction. The office
lock currently serializes all financial writes per office: this deliberately
favours correctness over throughput. Later allocation adapters must lock their
source/charge rows and recheck amounts/versions after waits; this step does not
claim allocation concurrency. Deferred constraints verify command completion,
entry/audit cardinality and paired transfer invariants at **real commit**.
A failed leg, replacement, authority proof or audit write rolls back all effects.

## Audit and operator trust

PostgreSQL writes audit in the same transaction as approved master changes or
cash insertion. Events identify office, actual user when a service context is
present, effective database role, recording time, business date, operation,
source/reversal/command references, sanitized reason and allowlisted financial
before/after values. Changed free-text fields are identified by field name,
without copying their content. Contact data, descriptions, remarks, passwords,
MFA seeds/codes, reset/invitation links and raw request bodies are excluded.
Configured secrets and recognizable credential syntax are redacted in reasons;
operators must write a business reason rather than paste arbitrary secrets.
This is an explicit allowlist and heuristic redaction, not a proof that every
possible unlabelled secret can be recognized.

Audit is append-only and direct ORM/SQL inserts are rejected; a triggering
business write is required. A trusted database/maintenance insertion has an
explicit `database` origin and effective SQL role, with no invented human user.
A historical baseline has `legacy` origin and says its original human is
unknown. Caller context is **not a cryptographic identity signature**. A schema
owner/superuser can disable triggers, change GUCs, TRUNCATE or alter DDL; such
privileged maintenance remains the separate S16 operator trust realm. Ordinary
staff have no SQL access. No SECURITY DEFINER/elevated migration role is needed.

## Migration, verification and remaining work

0011 preflights historical money before DDL. Invalid money stops the whole
migration for reviewed repair/import at S25; it never rounds, clamps, merges or
changes IDs automatically. 0012 creates baseline events and guards. Retrying a
completed migration does not duplicate history. Downgrade is refused after new
commands/postings, requiring a reviewed ledger/audit preservation plan.
The original migrations 0001–0010, keys/FKs, users, MFA and dependency locks
are unchanged. S12 mapping keeps its historical column contract; historical
rehearsals now use both historical Entity and Transaction models so later
metadata columns are not queried before they exist. Its rollback assertions
are retained and fault injection targets that historical manager.

Thirteen exact S06 defects become passing contracts: AMT-001–008, SET-001–002,
STA-001–002 and CAN-001. Correct expected values are unchanged. Only the two
STA diagnostic adapters change from mutating/deleting a receipt to the approved
owner/MFA reversal/replacement. Archived-history tests now assert stronger
posted immutability and read-only admin history. The other 13 known cases
(BAL-001–003, TRF-001, FLT-001–009) remain explicitly visible for S19/S21/S20/S29.
All existing test names and the 652-case S16 office boundary are retained.

Run once from clean committed candidate source:

```bash
python3 tools/verify_s18.py --record
```

Default verification creates/removes a **new disposable Docker** PostgreSQL 17
project. It does not touch the local demo, existing volumes or VM. Native PG17
proof is `Prepared`; the successful laptop Docker gate is `Verified`. Commit
only the four generated evidence/state files after success. Do not rerun just
to save them: that intentionally stops on their uncommitted output.

```bash
git add docs/implementation/evidence/S18-verification.json \
  docs/implementation/state.md docs/implementation/steps.csv \
  docs/implementation/traceability.csv
git commit -m "docs: record S18 Docker posting verification"
git push -u origin step/s18-financial-foundation
```

Only after that gate, reuse the existing stopped local demo (same .env,
`accounting-client-demo` project, port 8003), with its encrypted pre-upgrade
backup and recovery key already outside Git:

```bash
WEB_PORT=8003 docker compose -p accounting-client-demo build web
WEB_PORT=8003 docker compose -p accounting-client-demo run --rm --no-deps \
  --entrypoint python web manage.py migrate --noinput
WEB_PORT=8003 docker compose -p accounting-client-demo up -d web
```

Stop on a migration error and keep the original volume; never `down -v`, reset,
recreate the account or rerun owner bootstrap. Existing login/MFA continue.
Review synthetic posting/retry and read-only history in Greek. The VM remains
on its existing version; old S09/S14A context-pinned updaters must not be reused
for this upgrade. A separately tested deployment/backup restore path is needed
before changing its application/schema. No new cloud VM or GCP project is needed.

Next eligible implementation: **S19 dated cash accounts and balances**, after
the S18 Docker gate. All 85 full requirement acceptances remain Pending.

Primary technical references: [PostgreSQL 17 numeric types](https://www.postgresql.org/docs/17/datatype-numeric.html)
and [deferred constraint triggers](https://www.postgresql.org/docs/17/sql-createtrigger.html).
