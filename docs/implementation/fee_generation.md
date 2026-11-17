# S28 — monthly obligation generation

Status: **Prepared, source only**. The operator executes builds/tests/migrations.
The retained S27 receipt confirms 738/738, 36 financial cases, 327 exact-source
checks, four host contracts and actual Redis/worker/scheduler regression on
2026-11-17. Source git:e318bd9ef47d04026243d42373b590e8089ac3dc; application
sha256:0dd24ba422c85befbc29e12bbfb84edba0b920346b0b2ebc46d76d5e5722a721.
S28 implements UR-BIL-03/QR-06 and Greek staff controls under UR-LOC-01.

## Identity, effect and current authority

Every obligation uses the unchanged `agreement:<id>:month:<YYYY-MM>` source.
The existing database Charge uniqueness and one FeeSchedule per agreement
prevent a second obligation for the same schedule/month. A manual existing or
reversed charge consumes that source. Reconciliation preserves its stored amount,
description, terms revision and dates. Catalogue updates never reprice it.

`fee-occurrence.v1` is the only new S26 job adapter. Redis receives an opaque
job UUID; its immutable stored actor, entity, schedule, period, reason and optional
automation version establish the expected boundary. The worker freshly locks
office, actor, entity and job, checks finance.write and active customer membership,
then uses S27 preview and the unchanged S22 posting service. A current unexpired
lease fences its FeeGenerationRun pending-to-terminal transition. The charge,
run outcome and successful BackgroundJob receipt commit in the same transaction.
Failure before commit rolls everything back; loss after commit/before ack only
redelivers an already successful receipt. Bounded retry, recovery, revocation,
cancellation and the singleton scheduler retain the S26 contract.

Receipt uniqueness is one per job and one per automation-version/month. Distinct
explicit manual requests may retain separate receipts for the same occurrence;
all reference the same canonical charge. A fresh authorised actor can create a
new explicit request after a previous actor's intent was blocked. A consumed
source is never opened again by a new request or policy version.

Generation records obligations only: no receipt, payment, cash allocation,
transfer or cash-balance write. The charge effective day is the period's first
day or the reviewed first partial-period start; the separate payment due day
can be in this or the following month. Amount/description come from the terms
effective for that period. Closed periods, cancelled/ended programs, inactive
terms and unsupported mid-month changes are skipped with an explained outcome.
The first partial amount remains explicitly reviewed in S27; no VAT or proration.

## Activation and catch-up

The new tables start empty. `FEE_AUTOMATION_ENABLED=false` is the shared default
for web/worker/scheduler; `BACKGROUND_JOBS_ENABLED` must also be enabled for work.
Existing S27 plans do not become automatic merely by applying source/migrations.
The owner opens “Αυτόματη δημιουργία χρεώσεων” from the program, confirms a reason,
password and recent MFA. Append-only FeeAutomationVersion history records consent.
The controlled shared environment flag is set only during a separately authorised
deployment. This delivery does not change any environment or running process.

Discovery uses the current Europe/Athens month, current live owner and latest
enabled consent. A disabled/replaced policy invalidates queued work. The global
switch also prevents queued automatic effects; paused outcomes require an explicit
new request/consent review after re-enabling. Manual reviewed generation remains
available with background execution enabled even if automatic discovery is off.
Missed earlier months are never silently backfilled. The operator explicitly
previews and selects 1–24 calendar months, with a reason and stable request UUID.
The command accepts an expected office ID only to verify it against the actor's
fresh profile; it cannot grant another office. Scope is at most 100 schedules per
invocation; larger offices select individual schedules. A stopped batch can be
repeated with the same request UUID; committed intents and charges are retained.

Optional commands, in the correctly configured application container:

```bash
python manage.py generate_fees preview --user-id USER --office-id OFFICE \
  --start-period YYYY-MM --months 1
python manage.py generate_fees enqueue --user-id USER --office-id OFFICE \
  --start-period YYYY-MM --months 1 --request-key UUID --reason 'Ελεγμένη αναπλήρωση αμοιβών'
python manage.py generate_fees run --user-id USER --office-id OFFICE \
  --start-period YYYY-MM --months 1 --request-key UUID --reason 'Ελεγμένη αναπλήρωση αμοιβών'
python manage.py generate_fees reconcile --user-id USER --office-id OFFICE --start-period YYYY-MM
```

`preview` is the default. `--dry-run` on any action forces zero business/job writes.
`enqueue` uses the real worker; `run` calls the same fenced execution synchronously.
Both retain durable intents, failed/blocked/cancelled jobs and skipped outcomes.
Neither command prompts for credentials or changes human accounts/MFA. The Greek
office/month reconciliation screen is read-only; owner settings and ordinary
finance.read access remain separate. Internal JSON field names retain their schema.

## Delivery and verification

Only migrations 0025/0026 are new. The latter extends the registered S26 job
contract, retains its inert adapter and restores its exact previous function on
reverse. New model guards retain policy/run history, office links, monotonic
policy revisions and fenced terminal receipts. No old migration/service/lock is
edited. No generic admin/records registration exposes these models. The original
S16 HTTP assertions are unchanged; only its route-key fixture adapts.

APPLY_S28.sh performs Git/source/tracking only, preserves actual historical
receipts and all acceptance statuses, and records Prepared. It can retain an
already generated uncommitted S27 Verified receipt before creating the S28 branch.
The operator verification command is:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/verify_s28.py --record --host-dns
```

The gate requires a new exact committed-context image, unchanged retained sources,
all 738 previous tests plus 34 new PG methods (**772 target, not yet observed**),
all 36 financial cases and the full restricted-role/static/production delivery.
It retains every real S26 broker stage and adds actual scheduler-discovered charges,
an isolated Celery child SIGKILL after charge+receipt commit/before ack, observed
redelivery and one charge, next-month due dates and zero-cash office reconciliation.
Fault-injection tools mount only in a fresh owned project/database with explicit
identity checks; they are outside the production image. Only those resources are
removed. The previous S27 image cannot validate changed S28 application inputs.

Agent work is static only: AST/source/hash review, declaration comparison,
template compilation without setup/rendering, SQL parser and text-secret scan.
No agent tests/builds/Docker/migrations/native verification/browser/SSH/cloud/push.
S28 remains Prepared until the full operator command passes. Manual Greek/browser
acceptance, live VM rollout, D05/G2, workload recovery targets and all 85 full
requirement acceptances stay Pending. Stop after S28; S29 needs user selection.

References: Django 5.2 QuerySet select_for_update and transaction.on_commit;
Celery 5.7 tasks/acks_late/task_reject_on_worker_lost; PostgreSQL 17 unique
constraints and CREATE OR REPLACE FUNCTION. Existing version pins are unchanged.
