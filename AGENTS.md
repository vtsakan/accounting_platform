# Accounting platform implementation instructions


## Selected CR005 — visible archive, open-contract veto and owner deletion

The product owner explicitly requests visible archive controls, denial when an
agreement is open, and deletion only by the office owner after archive. They
selected deletion ONLY WITHOUT financial history. Implement this scope, not S32.
Actual prior CR004/VM/GitHub is Verified: 965/36, current28 migrations, main
git:35a66ae24a40eb2bc8365a2e9530d08385513992, context sha256:b72e10ff53dcc5613beba5f0126f8bddede58860b023e051f48c4ba7a86322a9.
Preserve all actual operator receipts and old exclusive bindings byte-for-byte.
Do not reconstruct the actual Git history in this distinct preparation branch.

Add only0029/0030. Preserve all28 original migrations and financial services,
original assertions/36 cases, dependency pins, accounts/MFA/keys and current VM.
Archive uses posted unpaid obligations plus current/future contract terms:
fully settled ONE_OFF can close; active MONTHLY, pending/review/draft/future
terms or any unpaid charge blocks. Legacy COMPLETED alone is insufficient.
Use the same SQL decision in HTTP/service and a database veto, under the usual
office/user/entity locks with fresh authority and version checks.

Owner deletion requires clients.delete, active same-office owner, archived
identity, explicit POST/CSRF/version and NO financial history, including closed,
reversed, fully paid or audit-only history. Remove contact values and exclude
the retained anonymous identity from every workspace, detail, restore, note,
statement and export. Keep immutable note/audit anchors and an attributed
server-timed deletion marker. Do not cascade/delete money, notes or audit rows.
No UI undelete. Actual permission is rechecked after locks; flags cannot grant it.

Previously archived/open history remains valid. The old replay, reversal and
statement tests seed that authentic historical starting state only in a
restricted disposable-test-DB fixture. It may disable only the new archive veto
under an exclusive table lock, and restores it before returning; no app path
imports it. Keep every original assertion unchanged. New CR005 tests always use
the real service/SQL guard and never this legacy fixture. Boundary adaptation
adds the delete route/owner capability without removing earlier cases.

APPLY performs Git/files only and binds the actual seven receipts exclusively.
New source Prepared until the operator image/PG17/full-suite/real-worker gate.
Agent static syntax/source/hash/SQL/template/text checks only; NO agent tests,
Docker/build/migrations/app/browser/SSH/cloud/push. VM/GitHub rollout is separate
after the new gate, all85 full acceptances and human browser acceptance Pending.

## Selected CR004 VM/GitHub update —965-test gate Verified, 2026-11-21

The user explicitly requests the latest existing VM and GitHub once checks
pass. Their supplied console confirms CR004 Verified at2026-11-21T10:07:53+02:00,
965/965,36 finance,48newmethods,695bindings and real-worker/commit-before-ack.
Actual application source isedacf958f5dc427575b45725502b9048d2ca41bf,
contextb72e10ff53dcc5613beba5f0126f8bddede58860b023e051f48c4ba7a86322a9,
image2c9844e107af9690a4487ce17ef87a2ae6744ca05689008e06ca8b9e9d4f3d2d.
Read evidence/CR004-operator-completion.json and cr004_preview_upgrade_el.md.
Earlier failure stays retained; its correction gate now has actual proof.

This authorises the selected existing accounting-preview VM/GitHub update,
not real-client release or S32. Keep agent execution static/Git/files only;
the operator executes cloud/Docker/push. Reuse the exact passed308input image
without rebuilding or rerunning965. Preserve all695 old source bindings,
all28migrations, original assertions, app bytes, historical actual receipts,
accounts, MFA, keys, hostname, instance, disk and bounded resources. Bind the
actual five receipt/history files exclusively; runtime may not recapture.
Save only exact CR004 --record outputs before the clean-context guard.

Start from the CURRENT S31A26-migration database and clone26→28; never rewind
to an old snapshot. Stop existing worker/scheduler and HTTP writers, retain
Redis/scheduler volumes and queued intents, compare unchanged job code. Require
restricted migration, all original rows/passwords/MFA/sessions and same DB
container/process/material, encrypted before/after backups and both exact
off-VM restores using the existing independent key before activation. Never
restart/delete the DB or delete/flush queues. Candidate web cannot auto-start
on reboot. After jobs/HTTP may write, never auto-rollback the DB. Before then,
restore the exact source wrapper and all original services on abort. Public
proof includes the new journal CSS as a fourth immutable static asset.

Supply separate preview_cr004 tools; historical release scripts stay exact.
Ordinary fast-forward GitHub publication only; private ops files remain outside
Git. Full accountant/browser/workload/recovery/policy acceptance and all85 full
requirements remain Pending. No agent tests/build/Docker/migration/app/browser/
SSH/cloud/push; static AST/hash/source/text/SQL/template inspection only.

## CR-004 operator failure — restore ordinary fixture schema, 2026-11-21

The actual operator run applied CR004 and ran962 tests, ending with3errors.
Two retained diagnostics show a missing accounting_counterpartynote table in
old ownership and settlement card-read tests; the third detail is truncated.
Preserve evidence/CR004-initial-failure.json and the exact initial source lock.
Static inspection finds five ordinary setUpClass hooks pinned to22/24/26;
GenerationFixtures applies26 before later TestCase card reads need27/28.

Change only those ordinary setup hooks to a shared disposable-test-DB helper
that restores discovered graph leaves before class transactions. Historical
migration contracts keep their precise old targets. Do not hide missing tables,
skip tests, relax assertions or alter production selectors/notes/financial code.
All initial45 CR004 tests and all original962 test bodies stay exact. Supply
three further real old-schema→current→card/note/journal contracts (target965).
The earlier fixture-only adaptation limit is superseded for these five setup
hooks only. Keep all28 migrations and all historical actual receipts exact.

Retain the existing exclusive CR004 binding; never rebind during an upgrade.
The retry package must handle already-applied initial CR004 and fresh CR003,
check known source/context before mutation, preserve old reports and perform
Git/files only. New operator gate, accountant/browser and VM/GitHub Pending;
initial technical failure remains recorded. All85 full acceptances Pending.
Agent static syntax/source/hash/SQL/template/text checks only, no tests,
Docker/build/migrations/native app/browser/SSH/cloud/push.

## Selected CR-004 — counterparty card, notes and journal, 2026-11-21

The product owner requests a much richer client/supplier card, green incoming/
receivable entries, red outgoing/payable entries and blue attributable notes,
plus a client journal with all financial events and all notes. Implement this
selected feedback change; do not select S32 or deploy the VM. Read
docs/requirements/CR-004-Counterparty-card-journal.md and
docs/implementation/counterparty_journal_el.md.

Actual CR003 operator proof is Verified at 2026-11-21T08:07:18+02:00, source
git:bd541fb269343838e217c916cd7a83013baeb0c9,917/917,36 finance and real worker.
Its 292-input context is de928a2467826d60f2797c923ba46ee4c4cd908c6961cde1452e31e3fc8a22b0.
Agent preparation 5594575ae1f4a5cc792153e5f8f5bf63d80951e5 has identical
application bytes but a different Git lineage. Retain the genuine CR003 full
receipt, actual CR002 report and prior exclusive binding; never fabricate the
operator history. Bind all three before the new runtime gate. Commit only the
two exact known CR003 --record outputs before the clean image guard if needed.

Authorise two new additive note migrations 0027/0028. Capture server time,
fresh actor and username snapshot, same-office party, immutable row history,
retry key and office/user/entity lock order. Keep original financial services,
models fields,26 old migrations, dependencies and historical receipts exact.
The only old test adaptation is the boundary URL helper gaining two route
names; all prior assertions and other old test bodies remain exact. Add
operator PG/HTTP/concurrency/migration contracts; agent static checks only.

Use existing charge/debt/cash projections. A read-only paged SQL union includes
terms, charges, all cash, allocations/releases, charge reversals and notes;
every arm uses the same office/party. Use one read snapshot, dated filters,
Greek monthly calendar, real all-page counts, Athens note dates and escaped
plain text. A note or journal read never posts or reallocates money. Preserve
old card contexts, pages, account/MFA/key state and role capabilities.

APPLY performs Git/files only. New source Prepared; operator gate, browser/
accountant acceptance and VM/GitHub rollout Pending. All85 full acceptances
remain Pending. No agent tests, build, Docker, migrations, native app, browser,
SSH, cloud or push; static AST/template compilation/SQL grammar/source/hash/
text scan only. Earlier no-application-change/26-migration scope limits are
historical and superseded only for this explicitly selected CR-004 change.

## Selected CR-003 — agreement-scoped cash settlement, 2026-11-21

The user explicitly requests one-step receipts/payments against a selected
agreement, automatic reduction of posted unpaid charges, optional description
when agreement terms supply it, and party-dependent agreement choices. This
authorises the new composition flow, superseding earlier no-auto-allocation
creation/posting UI scope only for a new explicitly selected agreement receipt.
It does not authorise retrospective allocations or consumption of older credit.
Read CR-003-Agreement-cash-settlement.md and cash_agreement_settlement_el.md.

The actual CR002 operator gate is Verified at 2026-11-21T00:21:31+02:00,
source git:ee73318b2b1af1c02e419ff9c7d1d8d029764b80, 878/878, all36 finance,
30 new methods,659 bindings and real monthly worker. Preserve its genuine
CR002-verification.json and image/context exactly. Agent preparation reference
14547573babeb4cd6f38648e2a5eb4011fe5010b has identical application bytes but
is NOT the operator's Git lineage; use content guards and Git3way on their
actual branch, never reconstruct operator commits or replace actual receipts.

Compose unchanged post_cash and allocate_cash in one office/user-locked atomic
service. FIFO oldest due/effective/id only within the selected agreement. Use
the retained SQL used-at guard at all historical change points; excess remains
credit/advance. Replays of old cash-only entries or owner-released/corrected
allocations never add effects. Preserve legacy tokenless payload identity and
generate blank descriptions from effective terms/original retry text. Server
forms and the private GET lookup scope office, party and direction afresh.

Keep all26 migrations, dependencies, original finance/settlement/correction/
charge services, old test bodies/assertions and36 financial cases exact. Add
the finance.write GET route to the existing boundary matrix. Supply new PG
atomicity/history/retry/access/concurrency and HTTP/dependent-choice contracts.

APPLY performs Git/files only. Validate/preserve and, if needed, commit only
the two exact CR002 --record outputs BEFORE the unchanged clean image guard.
Exclusively bind the actual old receipt; runtime never captures/rebinds it.
Do not mistake this agent's separate documentation closeout for installed
operator metadata. Source Prepared, operator gate/browser/VM rollout Pending;
all85 full acceptances Pending. No agent tests/builds/Docker/migrations/native
app/SSH/cloud/push. Static syntax/source/hash/archive/text scans only. No S32.

## Selected CR-002 — automatic initial agreement charge, 2026-11-20

The user explicitly selects implementation of the accountant's feedback:
saving a new agreement should automatically create its charge. This authorises
the creation workflow change after S31A, not S32 or an unrequested live rollout.
Start from the actual published operator history at
60a7d52db3250cfe35faed0c8321ee2e54323920. Read
docs/requirements/CR-002-Automatic-agreement-charge.md and
docs/implementation/automatic_agreement_charge_el.md.

Compose the unchanged save_terms/post_charge services atomically, under the
existing office/actor locks. New active ONE_OFF agreements charge once; MONTHLY
agreements charge the first calendar occurrence only, including catalogue
creation. Preserve explicit first-partial-month amounts, canonical sources,
fresh authority, closed periods and all later scheduler consent. Bind repeated
form submissions to the retained immutable initial charge/snapshot, including
after amendment or reversal. No cash, auto-allocation, retrospective existing
agreement posting or model-save side effects. Keep all 26 migrations/schema,
old financial services, dependency/runtime pins and actual historical receipts.

Only the two old HTTP tests which expressly required terms-only new agreement
creation are superseded by CR-002. Update them to require the charge while
retaining zero cash, immutable reviewed terms, amount, office and Greek checks.
Every other existing test body and all 36 financial cases remain unchanged.
Supply further meaningful operator-run atomicity/replay/concurrency/access
contracts. New verification uses current-source delivery and the retained real
S28 worker gate; do not rebind frozen historical S31/source manifests.

The user execution preference remains: agent static syntax/source/hash/text
checks only, no tests/builds/Docker/migrations/native app/SSH/cloud/push. Deliver
a complete Git/files-only installer and optional operator verifier. Source
Prepared, runtime/browser/VM rollout Pending, all 85 full acceptances Pending.
The historical S31A/S31 application-preservation limits below remain historical
for those completed scopes; they do not block this explicitly selected change.

## S31A follow-up — pending operator records before the clean image guard

The supplied operator retry stops in APPLY's committed_context before its
own commit of the known verify_s31 --record outputs. No build/push/VM operation
was reached. Preserve that actual failure. First audit the unchanged 284
application bytes with candidate_context, validate the exact successful S31
receipt/592 protections/four bindings and reject all dirty/untracked paths
outside the same four enumerated records. Then commit only those known records
and invoke the unchanged clean-only committed_context guard, checking the same
digest and file count. Apply this ordering in both installer and publication
checkpoint. Never weaken image.py, old guards, financial code/assertions,
historical receipts or VM/clone/recovery code. Preserve the original 20 new
S31A guard methods; supply two more real-Git source-only contracts, unexecuted
by the agent, for pending reports and denied application edits. Supply a complete
cumulative retry from the still-unapplied S31 workers4 source. Preview/GitHub
execution remains Pending operator; all 85 full acceptances stay Pending.

## Selected S31A — update the existing preview and GitHub

On 2026-11-19 the user explicitly requested the latest VM version and GitHub
update. This authorises the existing synthetic preview update and ordinary
GitHub publication, superseding earlier S31 no-SSH/no-cloud/no-push scope for
this selected work. Keep the operator-execution preference: the agent supplies
the complete package and performs static checks; the laptop operator executes
the guards, image publication, VM clone migration/recovery and push.

Read s31a_preview_upgrade_el.md. The only VM is accounting-514109 /
accounting-preview / europe-west1-b, existing instance and retained disk,
totalaccounting.duckdns.org. Reuse the exact successful S31/S30 cached image
and context, all 284 application inputs and 26 migrations. No rebuild,
new VM, machine resize, secret rotation, bootstrap/account/MFA reset,
financial import or volume deletion. Preserve all 592 old protections and the
operator's actual receipts, four local history/lineage files and initial failure.
Publish the actual operator Git history, never the agent's Prepared placeholders.

Use an untouched retained original database and a new 20→26 clone. Require
restricted-role migrations, all old columns/rows/passwords/MFA/sessions,
read-only existing MFA decryption, unchanged DB process and pinned material,
encrypted before/after GCS backups and both exact off-VM restores before
activation. Add four web workers, Redis, one worker process and exactly one
scheduler with bounded memory on this existing 4-GB shared-CPU preview. Actual
VM workload acceptance remains Pending; local S31 performance is not VM sizing.
Before activation a reboot cannot start the candidate. Once jobs/public writes
may begin, automatic rollback to the original database is forbidden.

Source/GitHub/preview completion are separate from R1 business acceptance.
Preserve all 85 Pending full acceptances and S31 real release Blocked. Empty
media remains required until document recovery. Supply operator-only stdlib
guards and resume/status commands. Stop after this preview update; no S32.

Work on the accounting-office platform described by ACC-URS-001 and ACC-IMP-001. Apply this instruction block and the selected step S01 to S64. Read the current repository, its applicable instructions, docs/implementation/state.md, decisions.md and traceability.csv before changing anything. Use actual files and observed results as the source of truth. Preserve unrelated work and existing migration/table identities. Implement only the selected step and its necessary supporting changes.

Keep Django and PostgreSQL as the modular application, with templates and Bootstrap initially. The planning baseline uses Python 3.12, supported Django 5.2 LTS, PostgreSQL 17 and Docker Compose. Check official support/compatibility when locking versions; record a justified change rather than silently changing the stack. Deploy through Caddy and Gunicorn on one Google Cloud VM with a reserved static IPv4 address and an initial DuckDNS hostname. Use private Cloud Storage and workload identity. Add Redis, a worker and exactly one scheduler when S26 introduces them.

All product-authored frontend content must be Greek under CR-001 / UR-LOC-01: staff screens, client portal, authentication/admin pages, accessible labels, validation, help/errors, notifications, user-facing email and report/export headings. Preserve original user/provider content, identifiers and brand names. Internal code and developer documentation may remain English. Read docs/implementation/frontend_language.md and docs/requirements/CR-001-Greek-frontend.md. Establish the Greek locale in S04 and include Greek copy in every later UI change; never claim the existing application is translated merely because the requirement is recorded. The effective baseline has 71 UR and 14 QR; keep original baseline documents immutable.

Enforce one office per active accountant; an office may contain several accountants. An active mandatory accountant profile supplies office context, never an untrusted submitted office identifier. Check office/client ownership on reads, writes, related choices, admin, exports, files and job execution. Keep portal identity and client grants separate from staff membership. Revocation must block the next protected action.

Keep agreement terms, charges, cash receipts/payments, allocations and reversals distinct. Use fixed decimal money and atomic services; transfers have zero operating income/expense effect. Preserve posted originals and correct them by attributable reversal. Keep office fee/cash data separate from client myDATA sources and tax forecast snapshots.

Use synthetic data until the R1 acceptance and restore gates pass. Protect secrets and private documents, mask credentials and keep keys separate from encrypted data. Use current official contracts for integrations and tax rules; simulated responses, an unavailable connector and an unrun test are not evidence of delivery. Track proposed policy approvals separately from code completion. Excluded scope remains excluded unless a recorded decision changes it.

Check the selected step's dependencies and required inputs. Use existing authorised values and proceed with reversible local work. If cloud access, credentials or a domain decision is missing, prepare the relevant code/configuration, record the exact blocker, and distinguish Prepared from Verified. Provision or change only the explicitly selected authorised environment; do not infer production targets. Send live client messages only through an explicitly confirmed product action or execution instruction.

Run meaningful checks for the change on PostgreSQL where financial or database behaviour matters. Include relevant denied-access and retry/concurrency cases. Report actual commands and results; label checks that could not run. Update implementation state, decisions and traceability with the step, requirement/test identifiers, evidence, actual commit when available and remaining blockers. Do not invent a commit or mark an approval on the reviewer's behalf.

Finish with a concise result: what changed; files/migrations and commands; checks passed/failed/not run; manual acceptance still needed; and the next eligible step. Stop after this selected step. If its scope needs subdivision, record SxxA and SxxB under the original identifier without renumbering later steps.

## User execution preference — effective from S20

The user explicitly requests code-only delivery and will execute tests/builds.
Do not run test suites, Docker builds/containers, database migrations or native
verification during implementation. Provide source/patch and optional operator
commands. Record unexecuted work as Prepared, never Verified. Do not block
code delivery on a missing operator receipt for the previous source step. This
explicit preference supersedes the historical agent-run verification workflow.
Preserve existing accounts, MFA, volumes, all prior migrations and historical
receipts. The S20 apply helper performs Git/source operations only.

## Selected S31 — finance release gate, source only

The user selected S31 after the actual S30 operator receipt at
2026-11-18T18:29:21+02:00: 848/848, all 36 financial cases, 40 export
methods, 381 retained files, four host contracts and the real S28 fee-worker
commit-before-ack gate. Preserve that exact receipt and all previous evidence.
Read finance_release_gate.md and the S31 prompt. The effective R1 baseline is
33 Must user requirements (32 original plus UR-LOC-01) and nine QR: 42 rows.

Only operator tools, acceptance/recovery/load procedures, docs and tracking
change. Preserve all 284 S30 application inputs, all 26 migrations, every old
test/assertion, financial service/form/selector, locks, runtime/image pins,
historical receipts, accounts/MFA, demo/VM/cloud/key configuration. Reuse the
exact S30 immutable image only through its unchanged context guard. No agent
tests/builds/Docker/migrations/native application/PDF/browser/SSH/cloud/push.
Static syntax/AST/source/hash and secret text scans are permitted. The only
append to existing security metadata is two precisely bound non-secret Docker
container-name reviews from the actual S30 receipt; preserve every old review
byte and the receipt itself. Read evidence/S31-static-secret-review.json.

Supply an operator-only full 848/36 and unchanged real S28 broker regression,
a real synthetic billing/collection/refund/correction/report/export cycle,
50 distinct HTTP sessions and a 365-day financial report, restricted-role
20→26 clone migration with old-column/row checks, encrypted baseline/current
PG17.11 recovery and MFA key proof, all-table reconciliation and owned cleanup.
The synthetic workload and proposed p95/RPO/RTO are unapproved candidates;
measure and report failures, never reduce targets or infer VM capacity.

S31 source stays Prepared and actual release Blocked even after technical
Verified. Accountant/product-owner full application review, D05 real ownership/
opening/exception reconciliation or approved new-office scope, accepted D06/
D07 workload/recovery/owners/retention, Greek visual/browser/email/HTTPS/MFA,
authorised real first-office/window/backup/cutover and G2 remain Pending.
No live deploy command is authorised or supplied for an unknown target.
S17 policy approval is not R1 application acceptance. All 85 full acceptance
statuses remain Pending. Source-only APPLY performs Git/files only. Stop S31;
S32 independent source work requires separate selection and cannot unblock live use.

### S31 operator follow-up — actual historical receipts, source only

The operator APPLY stops before any S31 patch/test/Docker work because the
manifest pins the agent Prepared S25-verification.json while the operator has
the successful generated S25 result already reported in this conversation.
Read evidence/S31-receipt-fix.json. Never replace the local receipt with the
agent template or re-hash a changed financial source to make a guard pass.

Classify only the 35 enumerated historical operator JSON/CSV outputs separately
from 556 exact old source/static-evidence files and one exact append-only scan
review. Capture their actual bytes before APPLY, validate receipt identity and
claimed S25/S30 Verified results, then exclusively create an S31 hash-only
binding. Keep every original byte/status; runtime verification must require
that binding and reject changes without capturing or refreshing hashes.
Preserve all 592 original protections, 284 image inputs, 26 migrations, old
848/36, every old source assertion and all twenty original S31 host methods.
Supply twelve additional stdlib operator contracts (32 total), unexecuted by
the agent, and a corrected complete source-only ZIP for the unchanged S30
branch. Reuse the same context-guarded S30 image. No agent tests/builds/Docker/
migrations/native app/SSH/cloud/push. S31 stays Prepared; technical retry,
D05/G2 and all full acceptances Pending; actual release Blocked. No S32 work.

### Latest S31 follow-up — supplementary historical evidence, source only

The corrected complete APPLY again stops before source application, now at
S26-hash-fix.json. The earlier 35-output correction omitted preparation/fix/
provenance metadata from the local-history category. Their operator-local
values must be preserved without requiring the agent's draft bytes.
Read evidence/S31-history-fix.json. This supersedes the previous 556-source
categorisation: 485 exact source/policy files, the same 35 operator outputs,
71 additional explicitly enumerated historical metadata files, and one exact
append-only scan-review file retain all original 592 protections.

Keep s31_receipts.py and its twelve contracts byte-identical. Add a separate
71-path supplementary binding with structural JSON/CSV validation, exclusive
creation from actual pre-APPLY bytes, strict post-binding hashes, no runtime
capture/rebind, and no new status/approval claim. Historical manifest values
must never set current source/test expectations. Keep all 284 image inputs,
26 migrations, financial services/selectors/forms, 848/36 and original twenty
S31 host methods unchanged. Add eight stdlib operator contracts (40 total),
unexecuted by the agent. Report all remaining immutable-source mismatches
at once. Supply a complete source-only retry from the unchanged S30 branch.
No agent tests/builds/Docker/migrations/native app/SSH/cloud/push, no S32.
S31 Prepared; operator retry and full acceptance Pending; release Blocked.

### S31 actual latency failure — diagnostic follow-up, source only

The supplied 2026-11-19 operator log confirms successful S31 APPLY, all 106
historical files and both exclusive bindings retained, 848/848, 36/36 finance
cases, 40 host contracts, real S28 broker recovery, 20-to-26 clone migration,
the complete financial cycle and encrypted baseline/current recovery. The
actual S31 technical result is Failed: list p95 2.613222578999739 seconds and
detail p95 2.6956580339997345 seconds exceed the unchanged two-second target.
The 365-day report is 2.7540532670000175 seconds against ten; HTTP errors zero,
450 attempts. Recovery passed: 51 public tables, 7,593 rows and 7.397 seconds.
Read evidence/S31-operator-completion.json and S31-performance-diagnostics.json.

Keep the actual Failed receipt, historical receipts/bindings and all 592
protected paths. Do not change targets, sessions, dataset, two sync
workers, resource caps, application inputs, services, tests or dependencies.
The old CPU sample was taken after the load; it does not identify a bottleneck.
Supply a separate operator-only diagnostic using the unchanged isolated S31
rehearsal and immutable S30 image. Collect all 151 per-operation Gunicorn
durations including one warmup (not paired with client samples), CPU/throttling counter deltas over the
benchmark, and subsequent single-session HTTP and instrumented in-process
SQL/application profiles. Do not subtract unpaired p95 distributions to claim
queue time. Never save SQL/parameters, cookies, bodies or profile locals.

The only existing source-policy extension in this follow-up appends one exact
review for the public rehearsal.nonce in the supplied actual Failed receipt.
Read evidence/S31-performance-secret-review.json. Preserve all 195,117 old
scanner-review bytes (including both previous S30 reviews); the S31 append-only
manifest fixes that entire prior prefix and the one published suffix. All 485
retained source hashes, both historical binding policies and all existing guard
code/tests stay exact. No wildcard exclusion, receipt rewrite or financial
source rebind. The previous two-review-only scope is extended solely for this
newly observed non-secret identifier; no other review change is authorised.

New operator diagnostic tools/docs accompany that exact review. The diagnostic does not repeat
848/36 or real Redis and cannot mark the formal gate Verified. Keep its output
in ignored private/s31, preserve the actual official Failed record and all 85
Pending acceptances, and remove only its owned synthetic resources/plaintext.
No agent tests/builds/Docker/migrations/native app/SSH/cloud/push. Static AST,
source/hash/archive checks and secret text scans only. Release Blocked; no S32.

### S31 observed diagnosis — bounded worker comparison, source only

The user supplied successful diagnostic output at 2026-11-19T11:02:52+02:00.
Read evidence/S31-performance-observed.json. Concurrent list/detail p95 is
2.904/3.038 s; Gunicorn logged p95 is 0.062/0.074 s and subsequent single-session
HTTP is 0.052/0.065 s. All 450 requests succeeded; cgroup CPU throttling and
memory event deltas are zero, web/DB interval averages about 1.13/0.77 CPU.
Recovery and owned/plaintext cleanup passed. Formal technical Failed remains.

This supports worker-queue contention as an inference, not a paired queue-time
measurement or a proven sole cause. Prepare a separate fixed 2 → 4 → 2 sync
worker experiment on one fresh nonce-owned synthetic database/image/dataset.
Only the temporary owned web service's GUNICORN_WORKERS may change, only to
four in the middle condition; keep two CPU, 1 GiB, 50 sessions, 450 attempts
per condition, original targets, all other services and full original profile.
Recreate the web in every condition, verify actual process counts and resource
limits, compare all accounting business tables before/after each run, retain
both controls/all failures, then finish at two workers before encrypted recovery.
The earlier two-worker-only diagnostic rule remains for the formal gate and
original diagnostic; this separate exploratory experiment is the sole extension.

Keep every previous operator/diagnostic tool, 485 source hashes, 106 historical
files, both exclusive bindings, exact scanner prefix/suffix, all 592 protections,
284 image inputs, 26 migrations, 848/36, 40 old contracts and the formal Failed
receipt unchanged. No new scanner review or app/runtime-default/dependency change.
Record the supplied observation separately and the new experiment Prepared;
update only the S31 follow-up note, S31 step source/evidence and QR-05 notes/
evidence/date while keeping every acceptance criterion and all 85 statuses.
No automatic candidate promotion or formal Verified, VM/deploy/workload approval.
No agent tests/builds/Docker/migrations/native app/browser/SSH/cloud/push; static
AST/JSON/source/hash/archive and text scans only. Stop S31; no S32.

### S31 measured workers4 candidate — explicit full retry, source only

The supplied operator 2/4/2 comparison at 2026-11-19T11:36:54+02:00 is Observed:
four-worker p95 1.673/1.712/1.872 s meets unchanged 2/2/10 s targets; controls
at two workers fail again (list/detail about 2.68–2.81 s). All 1,350 HTTP
requests succeeded, 39 business tables stayed unchanged, recovery/cleanup
passed, actual CPU/memory caps remained two CPU/1 GiB per service. Four-worker
web CPU averaged 1.84 with throttling in 131/165 periods; do not infer capacity
margin, accepted real workload or absence of contention. Record the actual
comparison separately; no automatic formal Verified or live promotion.

Prepare an explicitly selected `--profile workers4` full S31 retry. Preserve
the original r1_workload.json and default legacy selection byte for byte.
The new schema-2 candidate is an exact published copy with only web_workers=4
plus version/provenance fields; every target/load/CPU/memory/approval remains.
The measured candidate is sufficient to prepare this separate technical retry;
it does not authorise production tuning. This extends the earlier temporary-
trial-only rule solely for the named, explicit synthetic profile. No live change.

Change only current S31 operator helpers/verifier/docs. Keep every application
input (284), 26 migrations, old 848/36, real S28 gate, all 40 old host test
methods, 485 protected source hashes, 106 historical files, both history bindings,
592 protections and exact scanner metadata unchanged. Supply eight additional
stdlib profile/lineage/resource denial contracts (48 total), unrun by the agent.
Pin both original/new profile file and canonical digests. Prove actual selected
worker counts, image and fixed caps before/after HTTP and recovery. Full retry
must execute retained 848/36, all 48 host contracts, real broker and original
cycle/migration/encrypted restore/cleanup; never substitute the comparison.

Before APPLY changes Git/source, capture the actual initial Failed report.
Exclusively create S31-initial-failure.json from those exact local bytes and a
hash-only S31-profile-lineage.json after source apply. Preserve current Failed
through APPLY. Runtime verifies that archive/binding without creating or rebinding;
only a completed operator --record may replace the current result. Keep a private
full copy of each new attempt beside its review template. Qualify public run IDs
as run:<nonce>; internal raw ownership nonces remain unchanged, no scanner bypass.

Record prepared retry in S31/QR-05 tracking without accepting any requirement.
Source Prepared, new formal retry Pending, actual prior technical Failed,
release Blocked; all D05/D06/D07/G2/human inputs and 85 full acceptances Pending.
No agent tests/builds/Docker/migrations/native app/PDF/browser/SSH/cloud/push.
Only static syntax/AST/JSON/source/hash/archive/text scans. No S32 work.

### S31 current operator checkpoint — workers4 technical Verified

The user supplied the complete successful full-gate output at
2026-11-19T12:29:37+02:00. Read S31-verification.json and
evidence/S31-workers4-operator-completion.json. Actual operator source is
git:39a088ab36970ebe839624b28521adaf9f72d9fb, with the published profile
implementation from git:f652d7428571f248458c6468f50aa499273e9b76.

All 848 application tests, 36 financial cases, 48 host contracts, 592 original
protections, real S28 broker/commit-before-ack, complete cycle/migration and
encrypted recovery passed. At 50 sessions, 450 successful HTTP requests yielded
p95 1.627/1.608/1.767 s against unchanged 2/2/10 s. Actual four sync workers,
same image/two-CPU/1-GiB caps and recovered runtime were proven. Restore matched
51 tables/7,593 rows in 7.561 s; initial failure/history and cleanup were retained.

This is operator evidence, not agent runtime execution. Do not rerun passing
tests without a relevant change. Keep all application inputs/migrations/operator
code and historical evidence unchanged. The operator's exclusive initial-failure
archive and lineage binding exist on their machine; only their actual hashes
are supplied here. Never fabricate binding contents or captured Git provenance.

Source remains Prepared, isolated workers4 technical status Verified, actual
release Blocked and all 85 full acceptances Pending. Named R1 application review,
D05/D06/D07/G2, Greek visual/HTTPS/real recovery and authorised first-office
decisions remain. No live deployment or automatic human approval. Stop S31;
S32 independent source work requires separate user selection.

## Historical S30 — PDF/CSV exports, source only

The user selected S30 after the actual S29 operator receipt at
2026-11-17T21:24:53+02:00: 808/808, all 36 financial cases, 360 retained
sources, four host contracts and the real scheduler/Redis/worker/ack-loss
gate. Preserve that exact receipt and all previous evidence. Verified source
is git:e40485f760d28e9149d1ed86e5f2b1f027db69d7; its immutable image is
sha256:08367b193ad6458272e8b87bed16b994a3ddbe341cdd278f44ca3178c1a15448.
Read report_exports.md and S30 in prompts.json. Implement only UR-REP-04,
QR-01/07 and Greek export/UI content under UR-LOC-01. Stop after S30.

Export the existing period report, fixed-counterparty statement and annual
fee overview as real PDF and UTF-8 CSV. Call the unchanged S29 selectors in
an outer read-only repeatable-read snapshot and materialise their exact
unpaged source querysets, preserving every filter/as-of/cohort distinction.
Do not recalculate debt or infer forecasts. Greek headings identify office,
period, filters and reporting basis. Embed licensed Greek/euro fonts; quote
CSV cells and protect untrusted text from spreadsheet formula interpretation.
Keep money typed Decimal and identifiers/leading-zero AFMs as text.

Downloads are synchronous authenticated attachments held only in memory,
with no stored artifact, token, public link or queue. Recheck live membership
and the expected office after rendering, before releasing bytes. No-store
responses and bounded row/output limits; reject oversized scopes in Greek
without partial totals. Add a typed provenance extension for separately
labelled S59 estimates; S30 always exports posted actuals.

ReportLab 5.1.0 and its required wheel-only dependencies are intentional S30
runtime additions. pypdf 7.1.0 supports actual PDF text/font/structure readback
inside the existing production-image test gate, which already ships tests.
Keep every existing dependency version, maintenance lock, runtime/image pin,
26 migrations, financial service/selector/form and prior assertion unchanged.
Only the existing boundary URL adapter adds format/statement export keys.
No model, migration, generic admin, worker/VM/account/MFA or cloud change.

Supply meaningful operator-run export/reconciliation/Greek/PDF/CSV/denied-
access contracts, the retained full suite/36 financial cases and unchanged
real S28 broker gate on a fresh committed image. Agent checks are static
AST/source/hash, template compilation without setup/rendering, font cmap/
license inspection, dependency resolution and text scans only. No agent
tests/builds/Docker/migrations/native app or PDF generation/verification.
S30 Prepared until operator verification; browser/PDF visual acceptance,
D05/G2, VM rollout and all 85 full acceptances remain Pending. S31 separate.

## Historical S29 — dashboard and financial reports, source only

The user selected S29 after the actual S28 receipt on 2026-11-17 at
17:55:18 Europe/Athens: 772/772, all 36 financial cases, 343 retained files,
four host contracts and actual scheduler/worker/Redis/commit-before-ack recovery.
Preserve S28-verification.json exactly. Verified source is
git:9b24a52217545c5a2ecf13a5c1fadb1d9b9e1443; image is
sha256:23fa49adebb0a3b06ff170bb2f81239fedc00a5f8278f5554cc32cbf298d1067.
Read financial_reports.md and the S29 prompt. Implement UR-REP-01/02/03 and
Greek copy under UR-LOC-01. No exports/S30 or task counters/S36.

Deliver a real unpaid-obligation dashboard, filtered operating cash report,
full selected-account opening/cash/transfer/adjustment/closing reconciliation,
dated client/counterparty statement and a twelve-month charge/receipt/settlement/
credit overview. Reuse all existing financial selectors; never derive debt
from contract amounts or subtract unallocated credit automatically. Distinguish
cash period, debt as-of, charge cohort and receipt cohort. Outside-year buckets
reconcile monthly totals to the whole dated statement. Unknown openings stay
unknown. Cancelled contracts retain posted debt; reversals/refunds/releases
use retained effective dates. Keep tax turnover/forecasts outside office totals.

Use shared typed office-owned forms and the same source querysets for aggregates
and paged detail. Materialise money/rows in a read-only repeatable-read snapshot
for normal top-level requests; nested callers retain their transaction context.
Keep all financial write services, old selectors, 26 migrations, dependencies,
worker settings and previous test methods/assertions unchanged. Only the S16
URL fixture adds the new statement route. Legacy report probe aliases remain
available but are not product debt totals. No generic model/admin change.

Supply 36 PG reporting/snapshot contracts (808 is an unobserved target), four
host source contracts and an optional verifier with the full retained 772 tests,
all 36 finance cases and the unchanged S28 real-broker generation/ack-loss gate.
No agent tests/builds/Docker/migrations/native application/browser/SSH/cloud/push.
Static AST/source/hash, template compilation without rendering/setup and text
scans only. No new migration. S29 Prepared until operator verification; VM,
D05/G2, full Greek/browser acceptance and all 85 full acceptances remain Pending.
Stop after S29; S30 requires separate user selection.

### S29 operator follow-up — current-day adjustment fixture

The supplied operator log builds image
sha256:10200edb5e1473883f2ba7fa377ebde8d00f7bc183c3e7029efdb34963635f96
and runs all 808 tests with one error in the new signed-adjustment report
contract. The retained adjust_opening service requires today's local date;
the fixture wrongly supplies historical DAY. Set only this new fixture's
effective date to timezone.localdate() and its report end/as-of to the same
day. Preserve every assertion, all 36 new methods, 360 retained bindings,
all 26 migrations, financial services/selectors, locks and historical receipts.
No additional test is needed: the existing case covers the corrected path.

The fixture is an application-image input, so rebuild the committed image
and repeat the full 808/36 and real S28 broker gate. Do not reuse the failed
image. No agent tests/builds/Docker/migrations/native app verification.
Static AST/source/hash/text checks only. Read
evidence/S29-adjustment-date-fix.json. S29 stays Prepared until operator retry;
browser/full acceptance, D05/G2, VM and all 85 full acceptances stay Pending.

## Historical S28 — recurring obligation generation, source only

The user selected S28 after the actual S27 receipt on 2026-11-17 at
16:52:17 Europe/Athens: 738/738, all 36 financial cases, 327 retained files,
four host contracts and the real Redis/worker/scheduler gate. Preserve that
exact S27-verification.json and all historical receipts. Its source is
git:e318bd9ef47d04026243d42373b590e8089ac3dc and its immutable image is
sha256:0dd24ba422c85befbc29e12bbfb84edba0b920346b0b2ebc46d76d5e5722a721.
Read fee_generation.md and the selected S28 prompt; implement UR-BIL-03,
QR-06 and Greek copy under UR-LOC-01. Stop after S28.

Use the unchanged S22 canonical agreement/month Charge uniqueness and S27
preview/effective terms; never generate cash or reopen a reversed source.
Register only fee-occurrence.v1 alongside the retained S26 inert adapter,
under the same fresh office/actor/entity locks and lease/atomic receipt.
Add only 0025/0026; keep all 24 existing migrations, financial services,
runtime/dependency/image pins and all old test methods/assertions unchanged.
Only the S16 URL fixture adapter adds the new automation route key.

Owner/password/recent-MFA consent is append-only and opt-in per schedule.
FEE_AUTOMATION_ENABLED defaults false in shared production configuration;
no VM or running environment is changed. Automatic discovery covers only the
current Athens calendar month. Missed historical months require explicit
preview and a controlled office/actor/request/reason CLI range of 1–24 months.
The worker rechecks live authority, policy, cancellation, client, terms and
period close. Every job has an immutable canonical-source reconciliation row;
pending becomes generated/existing/skipped only under its current S26 fence.

Supply 34 meaningful PG contracts (772 is an unobserved target) and an optional
full production-image gate with all 36 financial cases, all retained S26 real
Redis stages, actual scheduler-discovered fee generation and a strictly isolated
worker-child SIGKILL after charge/receipt commit but before acknowledgement.
The fault harness stays outside the application image. No agent tests/builds/
Docker/migrations/native application verification/browser/SSH/cloud/push.
Static AST, template compilation without rendering/setup, SQL parsing, source
and hash scans only. S28 Prepared until operator retry. D05/G2, VM rollout,
accepted workload recovery targets and all 85 full acceptances remain Pending.

### S28 operator follow-up — office UUID and operator-command inventory

The supplied operator log applies S28, passes its source preflight and builds
sha256:4cdd7e9bf33ac1c7124afd50a8b9532d0e54492f6d1a9fef6d58eb6110179718.
The full suite runs 772 tests with one error and one failure: --office-id uses
int although Office.id is UUID; generate_fees is missing from operator_commands.
Use uuid.UUID for that argument and declare only the missing command in the
existing inventory. Keep the fresh profile-to-expected-office comparison and
all scopes, capabilities, tests/assertions, 26 migrations, financial services,
source manifests, runtime locks, automatic opt-in and historical receipts.
No new test is needed: the existing dry-run and boundary contracts expose both
defects. A new committed application image is required for these two inputs.
Source-only APPLY plus full --record --host-dns retry. No agent tests/builds/
Docker/migrations/native application verification; static AST/source/hash only.
Read evidence/S28-cli-boundary-fix.json. Prepared until the full 772/36 and
actual scheduler/worker/Redis/ack-loss operator gate completes. S29 is separate.

## Historical S27 — catalogue and monthly fee plans, source only

The user selected S27 on 2026-11-17 after the supplied S26 Verified receipt:
696/696, all 36 finance cases, real Redis duplicate/retry/loss recovery,
cancellation/revocation and singleton scheduler. Preserve that exact local
receipt and all historical evidence. Read recurring_fees.md and S27 in
prompts.json. Implement UR-BIL-01/02 and Greek copy under UR-LOC-01.

Deliver owner-managed immutable service-price versions, client monthly plan
schema/screens and a read-only effective-period preview. Catalogue defaults
copy into explicitly confirmed monthly agreements. Agreed future rates use
the existing S24 owner/password/recent-MFA amendment, not silent repricing.
Use finance.write for initial schedules and office.settings for price
maintenance; changes/cancellation of an existing schedule use finance.amend
with the existing proof. One schedule per agreement and the S22 canonical
agreement/month source prevent a second obligation after version or reversal.
Store a reviewed first partial-month amount; never infer proration or VAT.
Period ends are inclusive calendar months, due days 1–28, explicitly in the
same or following month. Mid-month later term changes require manual review.

Add only migrations 0023/0024. Preserve all 22 older migrations, financial
service code, dependencies, S26 runtime tools and every old test method/assertion.
The S16 HTTP fixture's setup/URL adapter may add synthetic S27 records so its
unchanged role/scope assertions also cover the new routes. Keep the new models
out of generic records/admin. No scheduler task or charge/cash generator is
introduced: S28 is separately selected. Optional verify_s27.py executes the
full retained suite plus 42 supplied methods (738 is an unobserved target),
all 36 finance cases, restricted-role migration and actual Redis regression.
The --host-dns option owns only a temporary builder and preserves the daemon,
active default builder and source pins. No agent tests/builds/Docker/migrations,
browser/SSH/cloud/push/local-demo/VM/account/MFA/key action. Static syntax,
template/source/hash/SQL-parser checks are permitted. S27 remains Prepared
until operator verification; D05/G2 and all 85 full acceptances remain Pending.

### S27 source-preflight follow-up — portable exact test sources

The supplied operator log applies S27 and stops before build at a retained
AST assertion fingerprint. The original 326 exact-file SHA-256 checks pass
first. ast.dump output is a debugging representation and differs between
Python releases (including optional empty fields from 3.13). Keep the original
retained manifest and historical AST map unchanged. Bind all 23 old test files
to their exact original published S27 source bytes: 22 retain the existing
canonical digests; tests_boundary.py uses the published S27 preflight after
digest for the authorised fixture-only extension. This is stricter than AST
comparison and checks 327 unique retained files without interpreter formatting.
Do not derive new accepted hashes from unknown operator changes.

Supply four stdlib host contracts for the real bindings, no AST serialization,
changed original/fixture rejection and malformed/missing/conflicting bindings.
The operator runs them before Docker. Keep all application inputs, 24 migrations,
42 S27 test bodies, the 738/36 gate and all old receipts unchanged. No agent
tests/builds/Docker/migrations or native application execution. Read
evidence/S27-source-check-fix.json. S27 Prepared until the full operator retry.

### S27 operator follow-up — Greek quote input fixture

The latest operator log passes the portable source preflight and builds image
sha256:3863daa8bd76fe1b82fb76ae76bbcd20364ebd2e912ece6c863e7a95ba68ca0d.
It executes all 738 tests with one failure: the new catalogue quote HTTP
contract submits total_amount='100.00' to the existing GreekMoneyField, which
deliberately requires Greek decimal text. Correct only that new S27 HTTP
fixture literal to '100,00'. Preserve every assertion, the 42 method count,
all 327 retained sources, all 24 migrations and all production services/forms/
locale rules. Do not change service/API decimal fixtures or relax the parser.
No additional tests are needed for this fixture correction.

The test file belongs to the immutable application image context, so a fresh
committed image is required even though no production behaviour changes.
Supply the source-only APPLY and the same full --record --host-dns command.
Record the actual failed 738-test run, keep the financial/Redis completion
Pending and preserve all historical receipts. No agent runtime/test/build/
Docker/migration/native application execution. Static AST/source/hash checks
only. Read evidence/S27-quote-input-fix.json. S27 remains Prepared until retry.

## Historical S26 — reliable background execution, source only

The user selected continuation after the actual successful S25 rehearsal on
2026-11-16: 61 planner tests, 184 reconciliation checks and encrypted source/target
recovery. See evidence/S25-operator-completion.json. Preserve the operator's
existing S25-verification.json and every historical receipt; real D05/G2 and all
85 full acceptances remain Pending.

Read background_jobs.md. Implement only S26 from prompts.json: private Redis,
same-image Celery worker at concurrency one and exactly one separate persistent
scheduler, durable DB/outbox state, execution-time office/client/cancellation
checks, bounded retry/recovery and data-free queue health. Use the existing
clients.read capability only for the inert client probe; no broad future job or
external-effect authority is inferred. Add only 0021/0022, preserve all twenty
old migrations, all previous test files, financial services and existing runtime
versions. Celery/Redis dependencies are now intentionally introduced under S26.
No generic admin/records adapter for new event/effect models. No HTTP route is
needed for this operational foundation.

Deliver source and optional tools/verify_s26.py --record. No agent tests/builds/
Docker/migrations/native verification/browser/SSH/cloud/push or local demo/VM/
account/MFA/key actions. Static syntax/YAML/source/hash checks are allowed. The
operator gate must execute the unchanged 661-test baseline plus 35 supplied
methods (696 is an unobserved target), all 36 finance cases and actual Redis,
restricted-role migration, duplicate/cancellation/revocation/scheduler/restart/
cleanup proofs before recording Verified. A new production image is required;
never reuse S24A for changed application context. Worker/beat definitions are
opt-in and are not a live VM rollout. Stop after S26; S27 is separately selected.

### S26 operator follow-up — digest prefix, source only

The operator applied S26 twice; the first application succeeded and the second
correctly reported already applied. Both verifier attempts stop before Docker
at accounting/account_services.py. The manifest and installer use sha256:<hex>,
but ensure_preserved compared a bare hexdigest to that prefixed string. Correct
the comparison and validate the canonical format; do not rewrite recorded hashes,
alter retained source or skip the guard. Supply four stdlib host contracts for
the real manifest, matching bytes, changed bytes and malformed metadata. The
operator verifier runs these before Docker; all 35 application test bodies and
the 696/36 targets stay unchanged. Read evidence/S26-hash-fix.json. No agent
tests/builds/Docker/migrations or application execution. Prepared until retry;
old receipts, local demo/VM, people/MFA and all acceptance states are retained.

### S26 operator follow-up — attempt-counter SQL, source only

The host-DNS helper built the new production image successfully. The operator
then passed all 145 retained-file checks and four host contracts, but the
delivery gate stopped while compiling 0022_background_job_guards, before the
application suite and real Redis gate. Parenthesize only the SQL CASE expression
inside the attempt-counter IF so its inner THEN is not read as the IF delimiter.
Keep the attempt rule, constraint identity, reverse SQL, all other guards,
0021 and the twenty older migrations, all 35 application test bodies and every
retained digest unchanged. No extra migration or checksum replacement is needed:
the supplied failing migration ran only in the disposable verification database.
Read evidence/S26-migration-fix.json. Require a new committed-context image via
the existing host-DNS helper, then the complete 696/36 and real Redis gate.
Agent work remains static only; S26 Prepared and all full acceptances Pending.

### S26 operator follow-up — missing redelivery interval, source only

The 2026-11-17 operator run builds the corrected image and passes migrations,
145 retained-file checks and four preservation contracts. It executes 696 tests
but fails two S26 recovery contracts because BACKGROUND_REDELIVERY_SECONDS is
read by dispatch_job without a base setting. Add the shared 30-second dispatch
redelivery interval in core/settings/base.py; all four settings profiles inherit
it. Keep service code, all 35 S26 methods, all 22 migrations, financial contracts,
dependency locks and historical receipts unchanged. Statically audit referenced
BACKGROUND_/CELERY_ settings without importing or executing the application.
Read evidence/S26-redelivery-fix.json. Rebuild through the existing host-DNS
helper and rerun the full gate. Agent tests/builds/Docker/migrations remain
unexecuted; S26 Prepared, real Redis verification and all full acceptances Pending.

### S26 operator follow-up — isolated probe import path, source only

The latest 2026-11-17 delivery receipt confirms 696/696 tests, all 36 finance
cases, 22 accounting migrations and zero unreviewed text-secret findings for
image b4a9d0676043246a22feef446178d7383b7d6577785996c9f384e005625b0b9e.
The real-broker gate stops at start-worker-scheduler because a root-mounted
/probe.py cannot import core from /app. Mount the unchanged operator probe at
/app/s26_runtime_probe.py and execute that same path. Preserve its isolated-DB
identity guard, all gate stages, historical receipts, source hashes, tests,
migrations and application files. The application image context is unchanged;
reuse the exact image only through the existing --image context/identity guard.
Read evidence/S26-probe-path-fix.json. No agent tests/builds/Docker/migrations;
S26 remains Prepared until the full operator real Redis gate completes.

## Historical S25 — legacy rehearsal, source only

The user now selects S25. Read legacy_migration.md and legacy_review_el.md.
Keep the actual operator S24A 661-test/36-case receipt and successful local/VM
deployment evidence. Supply a strict exact-decimal read-only planner, private
reports, snapshot/office/decision binding, source-ID ledger and an idempotent
isolated PG15→17 import/reconciliation/recovery pathway. Only operator tooling,
synthetic fixtures and documentation change; all application source, twenty
migrations, dependencies, human accounts/MFA and local demo/VM stay intact.
Use the already verified S24A image in fresh labelled local resources. Native
PG15 source rollback and PG17 forward/target backups are separate. The required
synthetic signing/MFA material belongs in the encrypted archive; the age
private identity remains external. No live DB URL, arbitrary SQL dump or VM
target is accepted by the synthetic execution command. Real authorised JSON
analysis is read-only; D05 mapping/exception/cutover and G2 acceptance stay
Pending. Existing S17 approval does not approve real migration. Do not execute
tests/builds/Docker/migrations/SSH/cloud/push; user executes supplied commands.
All new tests/runtime are Prepared, and all 85 full acceptances remain Pending.
Stop after S25; S26 queue/scheduler is a separately selected step.

S25 operator follow-up: the supplied log reaches logical-15-to-17 and stops on
docker exit 1. The old wrapper discarded pg_restore stderr, so the underlying
SQL/archive/connection cause is unconfirmed. Read S25-restore-fix.json. Supply
safe first-failure diagnostics, exact client/archive/empty-writable-server
metadata and a private seekable tmpfs restore file with an explicit loopback
connection. Keep atomic/exit-on-error and every source/financial/restore check.
No DB privilege promotion, SQL filtering, trigger suppression, dependency change
or existing demo/VM action. The source fix and twelve additional guard contracts
are Prepared and unexecuted. Preserve the 34 original planner assertions and
the actual S24A receipts; only operator retry can establish completion.

Latest operator retry on 2026-11-16 reaches logical-15-to-17/archive-copy.
Server 17, expected role/database, writable mode and empty target all pass;
docker cp fails before pg_restore. Docker documents cp limitations for tmpfs
and user-created mounts. Replace that transfer with a fixed-script, positional-
path docker exec writer, verify exact SHA-256 inside tmpfs, and keep the seekable
file restore and every existing assertion. Preserve all 46 prior test methods;
four additional contracts are source-only. S25 remains Prepared until retry.

Latest restore retry passes the tmpfs SHA-256/TOC checks and reaches CREATE TABLE,
which rejects the internal pg_attver parameter. The configured 17.11 dump/restore
tools predate the November 2026 attribute-version metadata; the floating PG15
image allowed a newer source. Pin only the disposable S25 pair to official
15.20/17.12 immutable images in fixtures/s25-image-pins.json. Check full server,
pg_dump and pg_restore versions before creating/seeding rehearsal databases.
Read evidence/S25-postgres-pair-fix.json and retain all 50 earlier test bodies;
eight additional contracts are unexecuted. Do not strip SQL, bypass checks or
change production/VM image pins, application dependencies or twenty migrations.
The actual source minor version was not supplied in the operator diagnostic;
do not turn an inferred floating-image version into an observed receipt.
No agent runtime execution. S25, D05/G2 and all full acceptances stay Pending
for their respective operator/acceptance gates; source status is Prepared.

The next operator retry confirms all six 15.20/17.12 versions and reaches
concurrent-idempotent-import after logical restore and earlier gates. It stops
in apply_plan at legacy_worker.py:299 because an integer charge position has
overwritten the canonical agreement/charge key in the planner's dictionary
unpacking. Put the copied review metadata first and the computed cash/charge
identities last. Keep reviewed JSON and all financial services unchanged.
Preserve all 58 prior test methods; three new contracts cover canonical keys,
nonzero charge positions and metadata collisions. Read S25-allocation-key-fix.json.
Agent checks remain static only. The full concurrent/reconciliation/recovery
gate and D05/G2 acceptance remain Pending; do not infer completion from progress.

## Historical S24A — Material-inspired office workspace

The product owner explicitly selected S24A now, before S25, and requested an
impressive Material-style interface. Read material_workspace.md. Keep Django
templates/Bootstrap and all Greek frontend/security/financial conventions. Add
only presentation assets, shell/auth/list styling and a read-only dashboard
composition of the existing scoped cash/operating selectors. Preserve every
old assertion, all 20 migrations, financial services, dependency locks, users,
MFA and recovery setup. No chart/sample amounts in the live app; unknown openings
remain unknown. The standalone design preview is explicitly illustrative.
No agent tests/builds/Docker/browser verification/migrations/VM actions. Supply
five focused overview/search contracts. The operator has now passed 661/661
production-image tests and all 36 finance cases on 2026-11-15; preserve that
recorded S24A receipt and S24's historical receipt. Do not rebuild or rerun the
suite just for the operator-only local-preview helper fix. Its container-local
psql authentication and staged diagnostics remain Prepared until operator use;
see evidence/S24A-local-preview-fix.json. No production-context input changes.
Manual responsive/keyboard/dark theme/client and full S47 acceptance remain
Pending. New local preview command requires the existing S24/0020 schema and
starts web without migrating or resetting accounts. Historical S14-to-S24 tools
must not deploy S24A. No S25 implementation. The separately selected VM
image-only release below is operator-executed; no agent cloud action.
The preview --inspect option reads only migration/version metadata and may start
the already existing demo database; it never builds/replaces web. An old local
schema is separate from the disposable production-test database and upgraded VM.

The operator retry now reaches the schema guard successfully and reports twelve
applied local migrations. Prepare the explicit local-only S18/0012 -> S24/0020
path in tools/upgrade_local_s24a.py; read local_s24a_upgrade.md. It backs up the
retained database and .env with the existing age recipient outside Git, checks
decryption, applies only versioned forward migrations and compares all original
columns/rows including account/password/MFA/session tables before starting the
Material preview. No bootstrap/reset, volume removal, .env/key rewrite, cloud
or VM operation. Preserve the successful 661-test receipt. This operator helper
has now been operator-executed successfully: twenty migrations, 27 old tables,
all retained rows/accounts/MFA/sessions and checked encrypted backup. See
evidence/S24A-local-deployment.json. No agent execution is authorised.

## Historical follow-up — S24A VM and GitHub, operator commands only

The user explicitly requests the existing VM upgrade and a GitHub update in
parallel. Supply the Git-only patch and operator commands on step/s24a-material-ui.
Read s24a_vm_release.md. Reuse the existing 661-test production receipt/image;
operator commits get a separate deployment identity. Do not rebuild or rerun the
production suite. The VM is already S24/0020: replace only image/static on the
same active DB. Never migrate/bootstrap/restore on the VM or use old installers.
Preserve pinned secrets, PG container, users/MFA, certificates, IAM and domain.
Require encrypted backups, all-table equality before public activation, and an
exact off-VM restore with the independent key copy. Image rollback retains this
same current database, including any new public writes. GitHub receives code
first and the successful public evidence afterwards. New tools and 15 release-
guard tests are Prepared, not agent-executed. No agent tests/builds/Docker/SSH/
GCP/GitHub push or S25 work in this scope.

The actual operator VM log is now deployed_and_restored: through 0020, 24 old
tables preserved, restricted role, matching off-VM restore and HTTPS/CSRF checks.
See evidence/S24-VM-deployment.json; actual browser/MFA acceptance stays Pending.
The historical notes below describe earlier attempts, not the current VM state.

## Historical S24 VM follow-up — operator execution only

The user explicitly requests commands to update GitHub and the already selected
VM before S25. This authorizes preparing this deployment pathway; the user will
execute commands. No agent tests/builds/Docker/SSH/cloud/migrations. Read
s24_vm_upgrade.md. The operator S24 proof is 656/656, all 36 finance cases and
922 boundary cases; preserve it. Actual VM report: S14 image/schema through
0008, existing people/MFA, healthy S10 backups and monitoring. Use vm_upgrade.py
and its host/clone-only helper. Do not use S09/S14 installers or bootstrap people.
Require production-image delivery proof, exact source/target/secret/disk/registry
identity, pre-change encrypted backup, retained original database, restricted-
role migrations of a clone with original-column/people/MFA checks, a newly bound
backup and an independent off-VM restore before public activation. Preserve the
old DB/image and refuse automatic rollback after new public writes may exist.
New tooling is Prepared until the operator executes it. Existing S24 application
Verified receipt and all migrations/financial source/assertions/locks remain
unchanged. No new resources/credentials/key rotation or S25 implementation.

S24 VM retry follow-up: the operator production-image suite passed 656/656,
all 36 finance cases and zero unreviewed secret findings; publication succeeded.
Clone migration correctly stopped on entity 2 invalid_afm, restored S14 with
original_database_unchanged true, public_cutover_started false and hold false.
Read evidence/S24-VM-retry.json and the retry section of s24_vm_upgrade.md.
Require the operator's explicit identity review in the existing S14 UI; never
invent, clear or automatically repair an AFM or edit frozen migration guards.
Archive only the completed unexposed rollback journal, retain its failed clone,
choose a fresh clone and preflight source identities read-only before downtime.
Operator-only tools may reuse the exact already verified image via a separately
bound deployment_commit and unchanged production-context/receipt checks. No
agent runtime execution; new retry tooling is Prepared. Stop before S25.

## Historical S24 source checkpoint

Deliver source only. No agent-run tests/builds/Docker/migrations or local demo/VM/
account/MFA/key actions. Read financial_corrections.md. Actual S23 operator proof
on 2026-11-14: 605 passes, all 36 financial cases and 838 boundary cases, source
9f10f4f9e6f3fe66eebb5590f6392bcf505df757; preserved source context
sha256:ae4c2a7be2ef5f7213b8a213407e8878c484c96a88d45cfd521fd72b9562e182.
Keep its receipt, original 18 migrations, all previous assertions, accepted D08
policy and dependency locks. Add only 0019/0020, seven retained correction/event
models, owner password/recent-MFA grouped corrections, explicit source-bound
credit/advance refunds, both transfer legs, prospective agreement terms and
cancellation, and forward-only closed-period cutoffs. Replacement cash requires
separate explicit allocation; cancellation retains posted debt and never refunds
automatically. Check every affected historical allocation/refund change point.
New event models stay outside generic admin/records/workers. The narrow legacy
no-charge/no-amendment status bridge remains for the original probes; modern
settlement/lifecycle are separate. Preserve all 605 tests/36 finance assertions;
extend every previous route case. Supplied 51 new methods target 656 passes and
922 boundary cases, NOT observed results. Prepared until the optional operator
runs tools/verify_s24.py --record. APPLY only merges Git/source/metadata; generated
S23 receipt files may be committed only as an exact four-file set with no other
outstanding edits. Greek browser/client acceptance, restricted-role DDL and all
85 full acceptances remain Pending. Stop after S24; S25 import/reconciliation
is separate and no deployment is authorised by this implementation step.

### S24 operator-failure follow-up — Prepared

The operator reported 656 tests, 20 errors and one failure. Read
S24-locking-csrf-fix.json: the supplied tail identifies nullable outer-join row
locking in release_targets and a CSRF test fixture failing before its protected
request. Restrict allocation locks to self; retain office/source locking and
all SQL safeguards. Use a real MFA-verified synthetic session in the strict
CSRF client, assert its protected GET succeeds, then keep the tokenless POST
403 assertion. No application CSRF/MFA bypass, weakened financial assertion or
migration change. No agent-run tests/builds/migrations. Fresh operator S24 suite
and full acceptance remain Pending; stop after this S24 follow-up.

## Historical S23 source checkpoint

Deliver code only; no agent-run tests, builds, Docker or migrations. Start from
actual pushed S22 head f8e9b92f470765c1411067c14e06f625c0b13d91: its operator
receipt records 560 passes, all 36 finance cases and 799 boundary cases. Preserve
all sixteen existing migrations, every previous assertion and historical receipt,
locks and accepted S17 policy. Read settlements_credit.md. S23 adds only
0017/0018: immutable cash allocations, dated owner releases and completed
idempotent settlement groups. Cash, charges, settlement and credit remain
separate. Lock the office/user, fresh authority, source and ordered charge IDs;
SQL also serializes capacity, same-office links and every affected historical
change point. Customer credit and supplier advance never net automatically.
Only explicit ORDINARY party cash is eligible; legacy review stays S25. An
existing agreement reference never settles a charge by itself. Release needs
finance.release (owner), password, recent MFA, reason and date. Existing cash
reversal rejects effective allocations and predating their retained releases;
full grouped correction/refund UI stays S24. New models are not added to generic
admin/records/worker adapters. Extend the route matrix without removing old
case IDs/assertions. Supply 45 new methods: targets are 605 passes, all 36
finance cases and 838 boundary cases, NOT observed results. Prepared until the
operator executes tools/verify_s23.py --record. APPLY performs Git/source/metadata
only; no local demo, VM, account, MFA or key actions. Browser, restricted-role
DDL and all 85 full acceptances remain Pending. Stop after S23.

## Historical S22 checkpoint

S22 is operator-Verified on PostgreSQL 17: 560/560 tests, zero known or unexpected
failures, 36 passing financial cases and 799 boundary cases. Source receipt
47173b8bfc143de804ecae4d0ddafc7b916987cc was recorded and pushed in f8e9b92.
Keep S22-verification.json unchanged. Migrations 0015/0016 retain terms snapshots
and separate source-bound ONE_OFF/calendar-month obligations. UNREVIEWED legacy
terms create no automatic charges or paid state. Existing audit contexts retain
the original SQL error across savepoint rollback. This is historical technical
evidence, not full product/browser acceptance or a deployment instruction.

## Historical S21 checkpoint

S21 is Verified by the operator's PostgreSQL 17 run: 533 tests all passed,
zero known/unexpected failures and 784 office-boundary cases. Both retirement
fixture actions refresh database-written approval metadata. The receipt remains
unchanged. Explicit transfer pairs, retries, references, dated balances and
operating exclusion remain intact; no financial assertion is waived.

## Historical S20 checkpoint

S20 was verified by the operator on PostgreSQL 17: 511 tests, 510 passes and
TRF-001 as the sole expected failure. The S20 receipt is historical evidence;
S21 code delivery must not overwrite it. Greek ordinary entry, remarks,
optional references, typed combined filters, full-scope cash totals and
pagination are retained. The template-link correction preserves the S04
presentation fixture and real ORM links. No S20 test assertions are relaxed.

## Historical S19 checkpoint

## Current checkpoint

S19 is selected from the actual pushed/verified S18 head
22dbd3a12816cfaceb62958ad45e19231669f3be (428 tests, 415 passed, 13 exact
known failures). Read docs/implementation/cash_accounts_categories.md.
Preserve original migrations 0001–0012, all historical evidence, approved S17
policy/review, exact-money guards, every old test name and financial assertion.
S19 adds migrations 0013/0014, Greek cash/category screens, one dated cash
selector, explicit owner/password/recent-MFA opening approval and immutable
signed adjustments outside operating cash. Existing opening amounts are retained
with an unknown date until their owner reviews the cutoff; never infer it or
silently rewrite a legacy amount. Human adjustments are effective today; wider
closed-period/correction UI remains S24. Categories cannot cycle, cross offices
or delete history. New work excludes retired references; original-linked
reversals retain them. Retain all 652 old boundary cases and cover every new
route. BAL-001–003 now pass; the other 10 known defects remain for their steps.
Native PostgreSQL proof is Prepared. Complete tools/verify_s19.py --record on
laptop Docker, commit the generated evidence/state once, then explicitly migrate
and restart the retained local demo. Keep the VM, people, MFA/keys/volumes and
all 85 full acceptances unchanged. Do not reuse old context-pinned deployment
installers. Stop after S19; S20 follows its Docker gate. Below is history.

## Historical S18 checkpoint

S18 is Verified in the operator's Docker proof: 428 tests, 415 passed and 13
exact known failures. The retained demo was explicitly migrated through 0012
and restarted successfully. Core correction requires owner/password/recent MFA;
its full UI is S24. See docs/implementation/financial_posting.md and the
unchanged S18 verification evidence. This history is not a new VM deployment.

<!-- S17-REVIEW-CLOSED -->
S17 financial-policy choices D08-01–D08-10 are accepted by the product owner.
The named accountant/office-owner review was supplied in the project
conversation and recorded privately against the unchanged ACC-FIN-001
v0.1 policy/example/document digests. Read evidence/S17-verification.json
and evidence/S17-product-owner-acceptance.json. This is a declared human
review, not independent identity verification or application acceptance.
S17 is Verified for this scope; S18 is next when selected. D08-10 records
owner correction rights with recent MFA; actual capabilities/services
remain to be implemented at S18/S24. All 26 known financial failures,
85 full acceptances, original migrations/locks and S16/G1 proof remain
unchanged. Keep the local demo, accounts/MFA and VM intact. Names stay
in ignored private/; never add the named review file to Git.
<!-- /S17-REVIEW-CLOSED -->
The checkpoints below are historical.

S17 is selected from the actual pushed S16 Docker/G1 head
e6fde507f634a0ccd2de80b197bfd883d0ab7ac9. S16 is Verified: 382 tests,
356 passes, 26 exact known financial failures and 652 passing boundary cases.
Read docs/implementation/financial_policy.md and financial_policy.json, the
Greek review sheet and all 20 worked examples. S17 specifies 17 operations and
10 unresolved D08 choices; tools/verify_s17.py checks 65 exact-decimal example
results and rejects stale/incomplete human-review records. This is document/
reference arithmetic, not production finance, database or concurrency execution.
Keep application code, 10 migrations, dependency locks, all 382 tests/26 known
failures, S16/G1/history evidence, accounts, MFA, local demo and VM unchanged.
S17 remains Prepared until the accountant/office owner review the exact policy,
examples and documents. An optional private review file records their actual
names/roles, time, reference and selections; do not invent them or interpret
passing arithmetic as business approval. An alternative choice needs revised
policy/examples and a new bound review. No S18 posting behaviour changes before
its required D08 decisions are recorded. All 85 full acceptances remain Pending.
The checkpoints below are historical.

S16 is selected from actual pushed S15 Docker head
5fc66cb6161c76482501b31499e8745f79181a93 (344 tests: 318 passes and 26 exact
known failures). Read docs/implementation/office_boundary.md and the reusable
accounting/office_boundary_matrix.json. Run tools/verify_s16.py --record in a
disposable local Docker project to complete the G1 technical gate; native PG17
proof is Prepared. Retain all ten migrations and original 344 tests, money
calculations, locks, auth/MFA/referrer policy, accounts and recovery material.
New business routes need a declared capability and matrix coverage; identity
exceptions bind exact module/name and admin uses its dedicated permissions.
Write authority is checked after the office/user lock wait. Maintenance CLI is
an operator/database trust realm, not an unscoped staff API. Files, actual jobs,
exports, portal and connectors stay Pending until implemented and added to the
matrix. All 85 full acceptances and manual Greek browser/client review remain
Pending. Keep the working VM unchanged by this step. Do not rerun the old S14A
updater against existing people/office data. After a successful --record, commit
the six generated evidence/state files once; do not reapply or rerun solely to
save their output. Next is S17 accountant review of D08, not financial changes.
The checkpoints below are historical.

S15 is now selected. Start from the actual pushed S14 demo head
ab9602592cb699684450bc4ee70438f80d30351f, not the older s14-complete tag.
The user reports the VM demo working after apply/restore/bootstrap/login;
record that as operator-reported, without inventing missing stage receipts.
Read docs/implementation/client_supplier_workspace.md, counterparty_migration_map.json
and S15 evidence. Add independent roles, explicit classification, normalized
office AFM, Greek workspace and archive/restore retaining financial history.
Migrations 0009/0010 preserve IDs and all eight prior files; invalid/duplicate
legacy AFMs stop for review rather than merge or overwrite. Keep existing
accounts, keys and recovery binding intact. The local Docker completion gate
is tools/verify_s15.py --record; native PG proof is Prepared. Browser/keyboard
acceptance remains Pending. Do not rerun the S14A S09-only updater against a
database with people or deploy S15 as part of this implementation. S16 follows
the S15 Docker gate. The checkpoints below describe earlier handoffs.

Selected S14A follow-up: the user requests a sample office and regular accounts
both locally and on the existing VM. The corrected S14 Docker gate was reported
Verified on 2026-11-12: 287 tests, 261 passes and the same 26 known financial
failures; actual local owner login now works. Reuse that local demo/owner.
Read docs/implementation/vm_demo_upgrade.md. The VM remains S09/0001–0002.
The new operator flow accepts only its exact two markers with no users, clones
the original database, applies an explicitly reviewed ownership map, and binds
the new image/database to S10 backups. Keep the original database unchanged.
Native proof is Prepared; actual Docker publication/VM cutover/new off-VM
restore/browser MFA are operator gates. No human VM account is made by apply.
Do not use the old context-pinned ship/installer to bypass the staged migration,
nor alter existing completion tags, original migrations/locks or financial
assertions. Captured invitations do not send live mail or implicitly approve
staff. Stop after this S14A follow-up; S15 has not been selected.

The following S14 checkpoint text records the earlier handoff.

S14's operator Docker gate is Verified at s14-complete (dc4cdc5). Its browser
login subsequently exposed the no-referrer/Origin:null defect. The selected
S14 follow-up uses same-origin on forms and no-referrer only on bearer-link
redirects, including proxy errors. Read referrer_csrf_fix.md and its evidence.
Do not trust null origins or disable CSRF. Existing accounts/volumes and the
original eight migrations are preserved. The correction is Prepared pending
its own local Docker/browser retry; keep the existing completion tag immutable.

S13 is operator-Verified and pushed/tagged at s13-complete
(16501f4ffeafc15f7361bce1ef790e8e19031f77), with 218 tests: 192 passed and
26 exact known financial failures. Selected S14 adds Greek office settings,
recipient-bound invitations/approval/deactivation, explicit capabilities,
mutually verified ownership handover and an append-only scoped staff audit.
The product owner selected Read and post and Colleague accepts; read
staff_authentication.md, office_settings_staff.md and office_role_policy.json.
D01 is resolved for these current operations only. Future reversal/export/
connector/job capabilities and full release acceptance remain Pending.
Use tools/verify_s14.py --record for the disposable local Docker completion
gate; native PG17 proof remains Prepared. Bootstrap the first regular owner
only after that gate, using the documented separate empty local project and
bootstrap_office_owner command, not a Django administrator. No human account,
live SMTP, VM/database change or deployment is performed by implementation.
S14 adds migrations 0007/0008 without changing the original six, money models,
financial test assertions or dependency locks. Keep the running preview and
its recovery binding unchanged; do not run old context-pinned installers.

The following earlier preparation checkpoints are historical.

S11 is now Verified and pushed/tagged at s11-complete
(e314645a4c6decc701fc0dca928d52d6f9b76491), including the actual Docker
120-test gate. Selected S12 adds ownership to all five old business tables.
Read office_ownership.md and evidence/S12-verification.json. Keep this work local
and synthetic. Migration 0004 is nullable; 0005 refuses unreviewed records before
non-null/composite-key enforcement. Never fill a default office or alter original
row identities. Use the dry-run backfill_office_records command with an actual
reviewed mapping when migrating a selected existing database. Current tests use
synthetic mappings only. Use tools/verify_s12.py for the disposable PG17 gate;
native proof is Prepared, local Docker proof completes the step. Keep all 26
financial failures and original financial assertions/calculations. Full boundary
coverage is S16, authentication/MFA S13, and capability/settings/invitations S14.
No human account, VM change, live-data import or production deployment is made.

S10 is now Verified and pushed/tagged at s10-complete
(06cb37d3342115aebf53dd47e36b7900c3918fcd). Read its live evidence: actual
timer/upload, independent-key laptop Docker restore and received alert passed.
Earlier S10 Prepared statements below describe its historical implementation.
Selected S11 adds Office/AccountantProfile and a minimum missing/inactive-profile
gate. Read office_profiles.md and evidence/S11-verification.json. Keep this step
local and synthetic: full record ownership is S12 and authentication/MFA is S13.
Office settings/invitations are S14, not S11. No automatic memberships, default
office, real legacy mapping, human account, cloud change or new app deployment.
Use tools/verify_s11.py for the disposable PG17 gate; native proof is Prepared,
local Docker proof completes S11. Preserve the 26 financial failures and S10's
verified app/bucket/key/timer configuration. Do not run its old context-pinned
operations installer after the S11 application context changes.

S09 is Verified from the operator's public checks and actual changed-boot-ID
verification, pushed/tagged at s09-complete (eced8ea70e26f410ce2d234e41169d3fc05f529b).
S10 adds operator-only encrypted backups, isolated laptop recovery and Monitoring;
read docs/implementation/backup_restore.md and evidence/S10-verification.json.
Keep S10 Prepared until its actual GCS upload, timer, off-VM Docker restore with
the independently recovered key, and observed alert gate passes. Native PG/age
proof is not that gate. No application account is needed for S10; the user elected
to wait until the regular office/accountant onboarding at S13–S14. Do not create
an administrator as a substitute. Preserve the verified S09 app image and existing
cloud resources; the only new VM project role is Monitoring metric writer.

S08 cloud foundation is Verified from the user's Cloud Shell/VM execution and reboot/access probes. Read docs/implementation/google_cloud.md, cloud_inventory.json and evidence/S08-verification.json. The selected accounting-514109/accounting-preview environment already exists: e2-medium, Ubuntu 26.04.1, Premium static IPv4, retained 50-GiB data disk, IAP SSH and metadata-authenticated resource IAM. New replay utilities have local safeguards; their own GCP execution is not claimed. Do not recreate/reformat existing resources or infer another project. Keep actual deployment configuration under ignored private/gcp.json; no secret values or service-account JSON keys. S09 targets user-selected totalaccounting.duckdns.org; read docs/implementation/https_preview.md and the current state/S09-verification.json for its gate status. DNS matches the reserved IPv4 with no AAAA, and its completion gate requires actual image publication/pull, public TLS/login and VM reboot proof. Use the current-source verify_delivery.py gate because S09 deliberately changes production MEDIA_ROOT; preserve historical S07/S08 evidence. Do not recreate cloud resources or mark S09 Verified from native proof. S10 must prove off-VM restore before live data. Cost/budget/retention/operational approvals remain separate.

Read docs/implementation/state.md before editing. S05 and S06 have pushed Docker verification. S07 supplies the production image and delivery checks; read docs/implementation/production_delivery.md and require successful tools/verify_s07.py --record on a local Docker Engine before S08. Native Gunicorn/PostgreSQL proof remains Prepared and cannot complete the image gate. Build from clean committed source with tools/image.py; reuse its immutable image identity for migration, tests, static export and deployment. Keep migrations explicit; production startup never imports data or migrates automatically. Read docs/implementation/financial_regressions.md and use the strict accounting test runner through tools/dev.py test. Preserve correct assertions and the 26 known failures until their corrective steps; unrelated errors, tracked skips and unexpected passes fail. Read docs/implementation/local_development.md; preserve the PostgreSQL 17 volume and never attach the old PostgreSQL 15 data directory to it. Keep local WEB_PORT choices in .env; disposable verification selects an unused loopback port. Use explicit settings profiles and read docs/implementation/settings_and_locale.md; core.settings.build is static-collection-only. Keep the compiled Greek catalog in sync with its PO source. Use the unchanged hashed runtime/maintenance locks and read docs/implementation/dependencies.md before updates. Use docs/implementation/prompts.json with the original prompt reference. Notify the user to create/select the Google Cloud VM at S08 only after the S07 Docker gate passes. Do not treat build/health checks or regression capture as passed business, TLS, backup/restore or release acceptance.
