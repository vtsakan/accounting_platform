# S26 — reliable background execution

Source status: **Prepared**. The user executes all tests, builds, Docker and
migrations. Applying this package performs only Git and source/metadata actions.
The previous S25 synthetic rehearsal is operator-Verified: 61 planner methods,
184 financial checks and encrypted source/target recovery. Its real-data D05/G2
and accepted workload recovery gates remain separate and Pending.

## Delivered boundary

Development and production definitions add an opt-in `jobs` profile with a
private digest-pinned Redis, one Celery worker and one separate scheduler.
Both processes use exactly the web application image. No worker embeds beat.
The existing app/database/proxy pins stay unchanged; Celery 5.7.0 and redis-py
8.1.0 extend the runtime lock while retaining all twelve previous package
versions and the complete maintenance lock. Redis is pinned to 8.2.11-bookworm
and its independently resolved linux/amd64 manifest; see docker/s26-image-pins.json.

Worker concurrency starts at **1**, prefetch at **1**, with a 512-MiB container
ceiling. The scheduler and broker each have a 192-MiB ceiling. These are cautious
technical defaults, not approved D06 capacity. The operator gate records an
actual resource sample and recovery duration; representative workload/load and
availability acceptance remain S31/S63. No VM action is performed by this step.

The sole registered business adapter is `client-probe.v1`. It writes one inert
`JobProbeEffect` row; it never changes a client, charge, agreement, cash or mail.
Existing `clients.read` authority is reused only for this harmless scoped probe.
No new broad job, export, financial correction or portal permission is invented.
Fee generation, task recurrence, mail submission, files and connectors are
registered only by their own steps with their own reviewed authority/effects.

## Database truth and retry protocol

`0021_background_jobs` creates four independent tables: BackgroundJob (also the
dispatch outbox), JobEvent, JobProbeEffect and BackgroundPulse. `0022` adds
same-office composite links, immutable input/identity/history and fenced effect
guards. The twenty existing migrations and every previous test file remain
unchanged. Existing human accounts, MFA, application volumes and VM are untouched
by source application and the disposable verification pathway.

Enqueue derives office from the active accountant, checks an active same-office
client, serializes under office/user/client locks and binds an occurrence UUID
to actor, client and exact payload. The intent/event commit before the
`transaction.on_commit` publisher runs. A changed payload using the same identity
is rejected; rollback removes intent and callback together.

Only the opaque job UUID crosses Redis. The worker reloads immutable context,
locks office, actor, client and job in that order, and checks fresh membership,
office/client activity and the registered capability. It commits a short running
claim with an unpredictable fencing token, then rechecks all guards before the
protected effect. The effect and success receipt commit atomically in one DB
transaction. Duplicate deliveries and acknowledgement loss therefore have one
database effect. This is not a claim of exactly-once network delivery.

Cancellation uses the same office/user/job locks. It blocks a queued or claimed
effect; an effect already holding the protected transaction's locks may commit
before cancellation, and its successful receipt is retained. Revocation blocks
the next protected action after the revocation transaction commits. The tests
observe an independent worker waiting behind the actual revocation lock.

Known transient failures roll back their effect and retry at 2 and 4 seconds,
with at most three attempts. Unexpected exceptions stop as failed. The database
stores only safe reason codes; protected logs include job/correlation IDs and
exception class, never exception text, client data, payload or credentials.
Publish failure retains the queued intent and backs off up to 60 seconds. The
periodic recovery task, every ten seconds, republishes due unfinished intents
and recovers expired 120-second claims with fresh fencing. A trusted operator can
also run `python manage.py background_jobs dispatch` after restoring the broker.
Dispatch recovery survives a send/commit gap and even a completely empty Redis.

Only short DB-transaction adapters are supported here. Future HTTP/SMTP or other
external side effects must supply durable intent/uncertain-outcome handling;
an SMTP timeout is never an excuse to blindly resend. No arbitrary Python name,
office, actor, capability, SQL or live connection can be supplied in a task.

## One scheduler and retained state

`core.job_scheduler.SingletonScheduler` claims a dedicated PostgreSQL session
advisory lock before opening PersistentScheduler's file. A second process using
the same DB is rejected, including one from another Compose project or release.
Celery's lazy introspection instance takes no lock. Each tick verifies its owned
connection and updates a heartbeat; losing that session stops scheduling instead
of silently reconnecting. One Compose replica is a convenience, not the lock.

The persistent `scheduler_state` volume owns `/app/run/beat`, initialized for UID
10001. Redis has its own AOF volume and `noeviction`; the DB still owns recovery.
No broker port is published and the broker joins only the internal jobs network.
That network is a trusted service boundary, not a multi-user broker service.
Only Caddy exposes public production ports; the worker/scheduler have no public
ingress. JSON is the only accepted task serializer; no Redis result backend
holds business states or secrets.

Release order when a later deployment is explicitly selected: quiesce dispatch,
stop the old scheduler, let the bounded worker drain and stop, explicitly apply
the new versioned migrations after backup, set the **same pinned image** for web,
worker and scheduler, then start worker and the single scheduler. Do not use
`worker -B`, start an additional beat on boot or launch overlapping old workers.
Retain the scheduler volume; check DB/Redis/worker/scheduler health before
resuming. An attempted second scheduler must fail and the old process must
release its DB session before replacement. The current VM is not upgraded here;
historical context-pinned deployment tools must reject this new image.

## Operational visibility

The trusted operator CLI supports `background_jobs health --strict`,
`health --component worker --strict`, `health --component scheduler --strict`,
`dispatch`, and scoped `list --user-id ID`, `enqueue-demo --user-id ID
--entity-id ID --key UUID`, and `cancel --user-id ID --job-id UUID`.
List/cancellation services still enforce current authority; colleagues cannot
implicitly cancel another actor's probe. No new HTTP/admin route is introduced.
Product-authored status labels and command errors are Greek; interchange keys
remain stable machine identifiers. Queue health exposes only counts, boolean
components, expired leases and oldest-due age. It flags a due backlog older than
120 seconds, and stale worker/scheduler heartbeats after 45 seconds. This is
local observability, not a new external Monitoring alert or accepted SLA.

## Optional operator gate

From clean committed source on a local Docker Engine:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/verify_s26.py --record
```

The current-source production delivery gate builds one new image, reproduces
hashed dependency locks, checks the Greek catalog and secret scan, executes
all retained tests plus the 35 new methods (target **696**, not yet observed),
keeps all 36 finance cases and verifies actual Gunicorn/static/readiness behavior.
No assertion or known-failure result is waived. An exact matching cached S26
image may be supplied with `--image sha256:...`; the S24A image cannot satisfy
the changed context and must not be reused for this new application feature.

The same image then starts in fresh random labelled resources, with no published
ports and a new non-superuser DB role. It verifies restricted-role migrations,
real Redis retry and duplicate delivery, dispatch after broker outage, DB recovery
after Redis FLUSHDB, cancellation/revocation, attempted second beat, scheduler
restart/state persistence and queue health. FLUSHDB is confined to this new
isolated broker. The real runtime probes require the matching fresh DB identity.
Cleanup is checked before a Verified report is produced. No retained local demo,
VM, human account, MFA or key is selected. The image is retained for reuse.

If this command fails, it prints `S26-DIAG` with the stage and a bounded redacted
error. S26 remains Prepared; share that output. On success, commit only:

```bash
git add docs/implementation/evidence/S26-verification.json \
  docs/implementation/state.md docs/implementation/steps.csv \
  docs/implementation/traceability.csv
git commit -m "docs: record S26 isolated background execution"
git push -u origin step/s26-background-execution
```

Full acceptance of QR-01/06/12, all 85 requirements, manual Greek browser review,
actual VM rollout, D05/G2 and workload/incident-owner approvals remain Pending.
Stop after S26. S27 recurring fee schedules is the next planned step when selected.

## Operator preflight correction — Prepared, 2026-11-16

The supplied operator log applies S26 successfully, then fails in
`ensure_preserved` before any Docker/build action. Reapplying the original ZIP
correctly reports already applied and does not repair this verifier defect.

The recorded manifest and installer both use `sha256:<64 lowercase hex>`.
The original verifier compared a bare hexdigest to that prefixed value, so even
identical bytes failed on the first entry, accounting/account_services.py. The
follow-up compares the same canonical representation and rejects malformed or
empty metadata. A genuine changed file still stops the gate with expected and
actual public hashes; no stored digest is recalculated or replaced to accept it.

Four supplied stdlib host contracts exercise the real retained manifest, a
matching prefixed digest, a real changed-file rejection without manifest writes,
and malformed/empty metadata. The operator's existing `verify_s26.py --record`
command now runs them before checking Docker. They are separate from the 35
application methods; target 696 application tests and all 36 financial cases
remain unchanged and unexecuted by the agent. No app image input changes.

Apply only accounting-platform-S26-hash-fix.zip with APPLY_S26_HASH_FIX.sh, then
retry the same verifier command. The fix is Git/source/metadata only and remains
Prepared. See evidence/S26-hash-fix.json. D05/G2, VM rollout and all full
acceptances stay Pending. Do not reapply the original S26 ZIP to repair this issue.

## Primary references

- https://docs.celeryq.dev/en/stable/django/first-steps-with-django.html
- https://docs.celeryq.dev/en/stable/userguide/tasks.html
- https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html
- https://docs.celeryq.dev/en/stable/_modules/celery/beat.html
- https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html
- https://www.postgresql.org/docs/17/explicit-locking.html#ADVISORY-LOCKS
- https://docs.djangoproject.com/en/5.2/topics/db/transactions/#performing-actions-after-commit
- https://raw.githubusercontent.com/docker-library/official-images/master/library/redis
