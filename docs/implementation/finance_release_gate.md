# S31 — R1 finance release gate

Source status **Prepared**. Actual release decision **Blocked**. The supplied
2026-11-19 operator S31 run passed 848/848, all 36 financial cases, 40 host
contracts, the real S28 broker gate, the complete financial cycle and encrypted
recovery. Technical status is **Failed**: list/detail p95 exceed two seconds
at fifty sessions. The report target and recovery targets passed. See
[the exact operator summary](evidence/S31-operator-completion.json) and
[the diagnostic procedure](s31_performance_el.md). The actual Failed receipt,
all older receipts and both local-history bindings remain unchanged. The
operator diagnostic is now Observed at 2026-11-19T11:02:52+02:00: low Gunicorn
service times, high concurrent HTTP times and zero CPU quota throttling support
a worker-queue hypothesis. See [the supplied observation](evidence/S31-performance-observed.json)
and [the separate fixed 2/4/2 comparison](s31_workers_el.md). That experiment is
Prepared and Pending operator; no agent runtime result is claimed. Its four-worker
middle condition cannot promote the original formal two-worker profile or receipt.

The subsequent operator 2/4/2 result at 2026-11-19T11:36:54+02:00 is
Observed: four workers meet all timing targets (1.673/1.712/1.872 s), and both
two-worker controls still fail list/detail. All 1,350 requests, 39 business-table
comparisons and recovery/cleanup passed. A separate fixed schema-2 profile and
[explicit full workers4 retry](s31_workers4_el.md) are Prepared. The original
JSON/default remains legacy; D06 approval and the formal retry remain Pending.
The initial Failed receipt is exclusively retained before any new current result.

The effective R1 baseline has **33 Must user requirements**, including the
32 original requirements and CR-001/UR-LOC-01, plus **nine quality requirements**:
42 checks. [The matrix](r1_acceptance_matrix.json) retains the exact original
criteria and candidate evidence paths. [The Greek review](r1_review_el.md)
supplies a concrete manual procedure for every row. All full acceptance fields
in the 85-row traceability baseline remain Pending.

## Operator technical rehearsal

From clean committed source on the operator's local Docker Engine:

```sh
export PATH="$HOME/.local/bin:$PATH"
python3 tools/verify_s31.py --record --host-dns
```

The command defaults to the existing recovered age identity at
`~/.config/totalaccounting/recovered-backup-age.key`. Use `--identity` to select
another existing private, owner-only file outside Git. It does not generate,
rotate or overwrite an identity. Pinned age 1.3.2/age-keygen must already be
available, as for S25. Secrets/dumps/decrypted archives use private host tmpfs
under `/dev/shm`; the host must have at least 64 MiB free and enough for the
bounded synthetic dumps. No live database URL, existing Compose project or
VM/cloud target is accepted.

S31 introduces **no application image input**. All 284 S30 inputs, all 26
migrations, old tests, dependencies, pins and services remain exact. The
operator verifier first attempts guarded reuse of the S30 immutable image.
If it is unavailable, `--host-dns` uses the retained temporary-builder helper
to build the same committed application context. Image build provenance and
current verification source remain separately recorded. Reuse is never claimed
as a newly observed clean build.

The operator command performs these checks in order:

1. Exact SHA-256 checks for **485 unchanged source/policy files**,
   **35 enumerated operator results** and **71 supplementary historical
   metadata files** locked before APPLY, the original scanner-review prefix
   plus two exact non-secret Docker-name additions, all 42 R1 criteria and
   **40** stdlib host contracts (20 original, 12 receipt and eight history contracts). No AST serialization across Python
   versions and no silent re-hashing to accept changed source.
2. The unchanged full production-image delivery gate: all **848/848** tests,
   **36/36** financial cases, deploy checks, image/static audit, current
   source/history secret scan and actual Gunicorn/DB readiness outage/recovery.
3. The unchanged real S28 Redis/scheduler/worker gate: restricted-role
   migrations, retries/duplicates, message loss, cancellation/revocation,
   singleton/restart and actual fee generation. The worker child is killed
   after its charge/receipt commit and before acknowledgement; redelivery
   must retain one charge and zero cash.
4. Fresh, randomly named, internally networked S31 resources. A restricted
   `s31_app` role cannot create databases/roles or act as superuser. A synthetic
   baseline is migrated through accounting **0020**, with regular fixture
   people, password, encrypted TOTP seed and a verified fixture session.
5. An age-encrypted baseline custom dump is decrypted, integrity checked and
   restored into a separate empty candidate database. Genuine **0021–0026**
   migrations run there. Every old column/row, password/MFA/session and finance
   row must match; only additional migration/content-type/permission IDs are
   allowed. All newly added business tables must remain empty. The original
   database remains retained and unchanged throughout.
6. A complete synthetic real-service cycle: charge 100; receipt 120; allocate
   25; refund 20; reverse the refund; correct the receipt and release its
   allocation; separately receive/allocate 50; transfer 5 between cash accounts.
   Final debt is 50, credit zero, cash accounts 145 and 5, operating income 50
   and expense zero. Originals stay immutable. Role/password/expired recent-MFA
   failures write no finance. Authenticated Greek screens and real PDF/CSV
   bytes reconcile, with foreign detail/export/filter denials.
7. The explicitly **unapproved** [synthetic workload](r1_workload.json): 200
   additional clients/charges and 2,000 ordinary movements through real
   unchanged services. Fifty distinct authenticated DB sessions belong to one
   synthetic ordinary accountant. After three separately reported warmups,
   50 simultaneous closed-loop sessions each run three list/detail/report
   cycles: **150 attempts per operation, 450 total**. The report covers a
   rolling 365-day period ending today, not a monthly slice. Dates never
   precede the synthetic cash opening.
8. Complete-body loopback HTTP timing through actual production Gunicorn,
   including waiting in the server queue. p95 uses nearest rank
   `ceil(0.95*N)`; failed and timed-out attempts retain their elapsed time.
   Proposed limits are list/detail ≤2 seconds and annual financial report
   ≤10 seconds. Two sync workers, local container CPU/memory caps, actual
   request/error counts, all elapsed samples and a resource sample are recorded.
9. Stop the candidate web to freeze sessions and create a current-schema
   encrypted dump with required generated signing/MFA/password material. Start
   a separate new pinned PG17.11 recovery cluster. Intentionally reject the
   candidate before any public exposure, restore the encrypted 20-migration
   baseline into an empty rollback database, then the encrypted current
   26-migration snapshot into another empty database. Compare **all public
   tables** before any new login. Restore sessions, exact financial totals,
   owner password and actual synthetic OTP verification; the wrong signing key
   must fail to decrypt the MFA seed. A real restored Gunicorn HTTP report
   must return 200 in Greek.
10. Measure recovery from archive decryption through new recovery-cluster
    startup/roles, baseline rollback, current restore, all-table checks, keys
    and HTTP. Record snapshot age at completion separately. Compare with the
    proposed 24-hour/8-hour limits without accepting a production backup cadence.
    Check the original baseline and candidate snapshots again. Remove only
    owned containers/volumes/networks and host plaintext. Keep only encrypted
    archives outside Git under
    `~/.config/totalaccounting/finance-release-rehearsals/<run>/`.

Custom dump and logical fingerprints share a PostgreSQL exported snapshot;
restores use the matching pinned 17.11 tools, a seekable private tmpfs file,
`--no-owner --no-acl --exit-on-error --single-transaction`. No privilege
promotion, disabled trigger, SQL filtering, backward migration, `docker cp`
into tmpfs or physical PG15 volume reuse is used. Table MD5s are only logical
comparison fingerprints; age authenticates encryption and SHA-256 binds the
dump/archive bytes. The retained native helpers follow official
[pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[snapshot](https://www.postgresql.org/docs/17/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION)
and [pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html) contracts.

## What the observations mean

`technical_status: Verified` requires the full retained gates, actual complete
cycle, measured candidate performance and encrypted data/key/rollback recovery.
If measured performance/recovery misses its proposed limits, the command writes
the measurements with `technical_status: Failed`, keeps release Blocked and
exits nonzero. It does not lower a target, discard a slow sample, resize the VM
or waive a financial assertion. A source/runtime failure stops at its explicit
`S31-DIAG`, `S31-REHEARSAL-DIAG` or `S31-PROBE-DIAG` stage, and must not be
interpreted as a completed gate. No partial execution receives Verified.

This fixed local workload is a candidate measurement, **not an agreed operating
envelope** or a claim that the current preview VM can handle it. It excludes
TLS/WAN, external providers, distinct-user login load, sustained open-loop
arrivals, concurrent financial write load and worker contention. The separate
real-worker test is a correctness/recovery proof, not a simultaneous capacity
test. Actual office/user volumes, history, request mix, database size, CPU/RAM,
worker traffic and duration need D06 approval and a corresponding measured run
before capacity acceptance. No monthly availability percentage is inferred from
one successful rehearsal.

The local encrypted recovery is not an off-VM restore of a real authorised
dataset or proof of independent human key custody. It covers DB/signing/MFA
material and **empty media only**; document storage/recovery is S38 before
documents may be used. The 20→26 exercise starts from a synthetic current-code
baseline schema; it does not certify an arbitrary old database. Rejecting the
candidate after real migrations rehearses pre-public-exposure recovery. It does
not test the historical application image at schema20, a deliberately failing
DDL migration or a public cutover/image rollback. A selected real release must
rehearse its exact starting image/schema, freeze, migration and post-write
recovery behavior. Never discard new public writes by restoring an old snapshot.

## First receipt correction — previous inventory

The first operator APPLY stopped at `S25-verification.json` before changing
S31 source or running any tests. Its original manifest incorrectly pinned the
agent's Prepared source template. The operator has a successful generated S25
receipt; that file must remain exactly as recorded.

The first receipt correction classified all 592 protections as 556 exact
source/static-evidence bindings, 35 explicit operator-output bindings and one
exact append-only scanner-review binding. It reads those actual JSON/CSV
results before making any Git/source change, validates their step identity,
and checks claimed S25/S30 Verified results against the known technical
contracts. It never writes, converts or replaces a historical report.

After its source patch it exclusively creates
`evidence/S31-operator-receipts.json`, containing only the original SHA-256
values, fixed path inventory, policy digest and pre-APPLY Git reference. This
new S31 record is committed with the four existing S31 tracking files. An
already present binding is checked and left unchanged. Runtime guards require
it and reject any modified receipt or policy; missing bindings are not created
by the verifier. Existing Prepared/failed history is preserved with its actual
status and is not promoted. All old evidence remains in the current secret
scan and before/after preservation checks.

The new twelve operator-run stdlib contracts cover successful versus Prepared
S25 input, exact non-mutating capture, claimed-result conflicts, missing and
malformed JSON/CSV/policy, exclusive/idempotent creation, symlinks and strict
post-binding change rejection. The twenty original S31 methods, 848 application
tests and 36 financial cases are unchanged. The agent did not run them.

## Complete supplementary-history correction

The first correction retained the 35 primary verifier outputs, but the next
operator APPLY stopped at `S26-hash-fix.json`, still before source application.
Supplementary preparation/fix/provenance documents also have operator-local
history. The exact changed fields were not collected; the installer must not
invent them, overwrite them, or claim an approval from a different draft.

The current policy retains every original path as 485 published exact source/
policy hashes, the unchanged 35-output inventory, 71 explicitly listed
supplementary historical JSON/CSV documents, and the exact append-only scanner
review. Code, migrations, tests, financial policy, dependency/runtime pins and
operator tools remain in the source group. No source/test hash is taken from
an operator-local historical manifest. The active hashes remain the published
S31 source expectations, even if an old metadata record contains other hashes.

A second exclusive S31 record, `evidence/S31-historical-evidence.json`, binds
all 71 supplementary documents before any source/Git change. Both S31 binding
records contain only exact original hashes, fixed inventory/policy digests and
the pre-APPLY Git reference. Neither changes or promotes a historical status.
The previous helper and twelve tests remain exact. Eight new supplied stdlib
contracts cover local preparation stamps, complete inventories, exclusive/
idempotent binding, changed/missing/malformed documents, policy/code-path
rejection, symlinks, and the independence of current source hashes from old
historical manifest values. All source mismatches are reported together.

The existing Git-clean guard is retained: older history edits cannot be
auto-committed. Only the four already generated S30 tracking changes may be
committed automatically after their successful result is checked. Capture
does not authorise a new uncommitted edit to historical records.

The corrected complete bundle applies directly from the unchanged S30 branch;
no older failed S31 ZIP must be applied first. This remains source-only and
unexecuted by the agent. All previous history stays in the full secret scan
and must match its captured bytes after APPLY and throughout verification.

## Human acceptance and first-office decision

The public S31 receipt stays `status: Prepared`, `release_decision: Blocked`
even after technical success. The missing required inputs are explicit:

- Named accountant/product-owner review and observed acceptance of all 42 R1
  rows, including Greek browser/email/PDF visual review and actual public
  HTTPS/privileged MFA. The earlier S17 approval accepts financial policy for
  its bound snapshot, not this application/release.
- D06 approved actual dataset/workload, response/availability/recovery targets
  and operating budget. D07 real-release incident/restore/key custodians,
  retention and recovery evidence. Earlier S10 preview approvals/evidence are
  retained for their original scope.
- D05 real ownership mapping, opening dates, cash/charges/allocations/credit,
  transfer pairs and exception dispositions with exact reconciled totals, or
  an explicitly reviewed new-office/start-with-openings scope. S25 remains
  synthetic evidence and cannot approve real client data.
- Exact first-office/environment/window, freeze and restore owners, current
  bound real backup/off-VM restore and cutover authorisation, followed by the
  observed controlled release and actual G2 decision.

After a completed rehearsal, the verifier writes a private blank
`private/s31/<run>/R1-review.json`, bound to source/context/report/matrix/workload
digests. Only humans fill names, dated actual observations and approval
references. Evaluate declared completeness without writes with:

```sh
python3 tools/review_s31.py --review private/s31/<run>/R1-review.json
```

The evaluator reports only blocker categories, never names or private evidence.
It cannot authenticate human identity or turn a self-declared cutover flag into
an observed release. It does not update any acceptance field or run deployment.
The [first-office record](r1_first_office.json) and
[Greek cutover checklist](r1_cutover_el.md) remain Blocked until those exact
inputs and a separately selected execution are present.

Agent work in this delivery is source/AST/hash/text inspection only: no tests,
builds, Docker, migrations, Django setup, app/PDF/browser/native verification,
SSH/cloud action or push. Stop after S31. S32 independent source development
can be separately selected while the real release remains Blocked.
