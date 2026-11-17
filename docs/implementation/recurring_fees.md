# S27 — service catalogue and monthly fee schedules

Status: **Prepared, source only**. The user runs tests, Docker builds and
migrations. S26 is operator-Verified from source
`5e583cf2d4aae0e2597084b5389bc7614edfeaf6`: 696/696, all 36 financial cases,
real Redis retry/duplicate/message-loss recovery, cancellation/revocation,
singleton scheduler/restart and cleanup. Its receipt is retained byte-for-byte.
S27 implements UR-BIL-01/02, with Greek frontend under UR-LOC-01. It stops at
configuration and preview. S28 owns automatic charge generation.

## Prices, authority and snapshots

`ServiceItem` is an immutable same-office code. Each `ServicePrice` is an
append-only description, positive fixed-decimal gross EUR amount, effective
date, availability, actor and reason. Same-day changes use the later revision;
future versions take effect only on their stated day. A new price cannot
precede today or an already scheduled later price. Retiring a service creates
a new unavailable price version; original quotes remain.

Owners maintain prices with `office.settings`. Both authorised roles may read
the catalogue and create monthly receivable agreements from a current quote
using `finance.write`. The Greek confirmation form copies the current price
and description, allows an explicitly confirmed negotiated fee, checks the
quote version again under the office lock and records catalogue provenance in
the immutable agreement-terms reason. This creates no charge or cash movement.
The catalogue never silently changes an existing agreed rate.

Existing S22 `AgreementTermsVersion` and `Charge` already store immutable
description/amount snapshots. S27 retains those models and all their guards.
Future changes to agreed fees use the existing S24 `amend_agreement` service,
owner `finance.amend`, password/recent MFA, effective date, reason and audit.
No new policy approval or financial-service bypass is inferred. Accepted D08
choices are bound by the original S17 acceptance receipts; bound policy files
and all old financial assertions remain unchanged.

## Monthly plan and effective preview

`FeeSchedule` references one active same-office customer and reviewed monthly
receivable agreement through that agreement's retained identity. A unique
one-to-one agreement link prevents overlapping plans for the same obligation,
even after a plan ends or is cancelled. Independent agreements remain explicit
separate obligations; no client-wide deduplication merges unrelated services.

The initial period cannot precede the agreement's start month. An initial
partial month requires an explicitly reviewed positive first amount and reason.
There is no day-count calculation. Other months use the approved terms effective
for that calendar period. The initial terms reference is retained for provenance;
preview resolves later approved S24 terms for each period without rewriting
that initial reference. First/last nonstandard periods are never silently prorated.

`FeeScheduleVersion` retains period, optional inclusive final month, due day
1–28, explicit same/following-month due rule, terms snapshot, actor and reason.
Future schedule revisions require owner/password/recent MFA, strictly increasing
effective months after the current month and an expected revision. Cancellation
is terminal for that plan. It stops future planned generation, retains old
configuration/charges/debt and does not claim to cancel the legal agreement.
The existing agreement lifecycle remains separately visible and authoritative.

Preview is a bounded, read-only 1–24-month projection. It shows dates, gross EUR
amount, description, approved terms revision and readiness/outside/review/closed/
blocked/posted/reversed state. Unsupported later mid-month changes and due dates
before the effective date require review; no amount is inferred for generation.
Closed periods and archived/inactive clients are not presented as ready.
Already posted or reversed sources show their original stored snapshot and dates.

Every occurrence uses the existing `agreement:<id>:month:<YYYY-MM>` source,
independent of schedule/terms/catalogue version. A posted/reversed occurrence
remains consumed. The S22 unique source constraint is unchanged. No schedule
save, rate preview or GET creates a Charge, Transaction or allocation. S28 must
reuse this identity and recheck live authority, cancellation, period close and
the approved terms before any real effect.

## Database and boundary

0023 adds four tables; 0024 adds fresh-actor/same-office/role/audit checks,
append-only identity/history, monotonic revision and period guards. SQL and
bulk writes cannot bypass those guards. All 22 earlier migrations and financial
service files remain unchanged. No generic records adapter or admin registration
is added for these tables. All eight new routes have explicit capabilities and
join the existing boundary inventory. The unchanged S16 HTTP assertions get only
additional synthetic setup/URL fixtures. Every retained test method's AST is
bound in S27-preserved-source.json along with exact retained file hashes.

Greek screens: `/fees/services/`, service history/new-agreement confirmation,
`/fees/schedules/`, schedule creation, detail/preview/history and prospective
change/cancellation. Existing Material workspace, CSRF, private response caching,
office-derived choices and server-side validation remain in use. Browser review,
responsive/accessibility acceptance and real VM rollout remain separate.

## Optional operator verification

APPLY_S27.sh performs Git/source/tracking only. It preserves actual historical
receipts and current private/demo/VM resources. From the clean applied branch:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/verify_s27.py --record --host-dns
```

A new application image is required. The old S26 image cannot match this changed
context. `--host-dns` uses the observed working host resolver in a new temporary
digest-pinned BuildKit builder, first proves Debian/PyPI access, builds the exact
committed allowlisted source and removes only that builder/cache. It does not
edit/restart Docker or change the selected default builder. A successful matching
cached image is validated and reused on retry; `--image sha256:...` also requires
the existing exact-context/source/nonroot/architecture guards.

The gate runs the complete unchanged 696-test baseline plus 42 new S27 methods
(**738 target, unobserved**), all 36 financial cases and the full existing
production lock/catalogue/secret/static/HTTP/readiness checks. The same image
then runs the existing actual Redis regression in fresh isolated resources,
including restricted-role migration and `makemigrations --check`, duplicate
delivery, retry, broker/message loss, cancellation/revocation and singleton
scheduler/restart/state/health. Historical receipts and source are checked
before recording Verified. No gate or assertion is waived.

Agent checks are static only: Python/SQL syntax, template/route/source review,
model-migration declaration comparison and hashes. Tests, builds, migrations and
native application execution are not run by the agent. S27 stays Prepared until
the full operator command passes. On failure share `S27-DIAG` and the error.
All 85 full acceptances, D05/G2, accepted workload targets and VM rollout remain
Pending. Stop after S27; S28 is separately selected.

On success, record the generated receipt/tracking changes:

```bash
git add docs/implementation/evidence/S27-verification.json \
  docs/implementation/state.md docs/implementation/steps.csv \
  docs/implementation/traceability.csv
git commit -m "docs: record verified S27 fee catalogue and schedules"
git push -u origin step/s27-price-lists-fees
```

## Portable source-preflight correction — Prepared

The first S27 operator attempt applies all source commits and reaches
source-preflight, then rejects an AST assertion fingerprint. All 326 exact-byte
checks precede that error and pass. The agent prepared AST hashes on Python
3.12; Python's AST/debug dump is not a stable interchange format across releases.
The newer dump omits optional empty fields by default. This is a verifier defect,
not evidence of a changed agreement-charge assertion in the supplied log.

The original S27-preserved-source.json and its historical AST hashes remain
unchanged. S27-test-source-bindings.json takes all 23 original test-file hashes
from the already published S27 preflight, cross-checks the 22 existing canonical
file bindings, and includes the exact published tests_boundary.py fixture-only
extension. Verification now checks 327 unique retained files, with no AST
serialization comparison or unguarded fixture. Missing, malformed, contradictory
or changed files still stop before Docker. No digest is recalculated from
unknown operator changes to accept them.

Four stdlib host contracts are supplied and run by the operator verifier before
Docker. They are separate from the 42 application methods and the 738/36 target.
The new method count uses AST node names without serializing them. The complete
delivery, application, financial and real Redis gates remain mandatory. No
application input, migration, financial rule or existing test body changes.

Apply accounting-platform-S27-source-check-fix.zip using
APPLY_S27_SOURCE_CHECK_FIX.sh, then retry:

```bash
python3 tools/verify_s27.py --record --host-dns
```

The prior attempt stopped before building the S27 image; the normal new-image
path remains required. Agent checks are static only; all runtime verification,
S27 completion, D05/G2, VM rollout and full acceptance remain Pending.

Primary references:

- https://docs.djangoproject.com/en/5.2/ref/models/constraints/
- https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- https://www.postgresql.org/docs/17/plpgsql-declarations.html
- https://docs.docker.com/build/buildkit/toml-configuration/
- https://docs.docker.com/build/builders/drivers/docker-container/
- https://docs.python.org/3.14/library/ast.html#ast.dump
