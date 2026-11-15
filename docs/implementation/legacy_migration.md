# S25 — Legacy migration rehearsal and financial reconciliation

Status: **Prepared**. This source-only delivery has not run tests, images,
containers, migrations, imports or cloud commands. Preserve the actual S24A
661-test/36-finance-case production receipt and successful VM/off-VM restore.
This step changes operator tooling and documentation only. The existing
application image, all twenty migrations, dependency locks, local demo,
human accounts/MFA and VM are unchanged.

## Scope and approval boundary

S25 supplies a read-only analyser for a canonical legacy JSON projection and
an executable, synthetic PostgreSQL 15→17 migration rehearsal. The importer
uses the verified S24A image in new, marked databases and normal application
services. It is not a route, production management command or deployment.

No authorised real legacy dump, accepted office mapping or migration-exception
review was supplied with this request. D05 and G2 remain **Pending**. The S17
financial-policy approval does not approve a new dataset, identity correction,
opening inventory, transfer pairing or cutover. The fixture references are
explicitly synthetic; no person's approval is invented. An operator passing
the synthetic technical gate does not complete real migration acceptance.

The analyser can inspect an authorised real JSON copy. Live/staging execution
of that dataset needs a later explicitly selected D05-reviewed run, a bound
mapping/snapshot, named cutover/recovery owners and accepted exceptions. The
executable rehearsal deliberately takes no live database URL, VM target,
existing Docker project or arbitrary SQL dump as an argument.

## Operator commands

Apply the Git-only package, then optionally run the fast planner contracts:

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
python3 -m unittest discover -s tools -p test_s25.py -v
```

Generate a private dry-run report, without Docker or any database:

```bash
python3 tools/legacy_migration.py analyse \
  --source docs/implementation/fixtures/s25-source.json \
  --review docs/implementation/fixtures/s25-review.json \
  --report private/s25-analysis.json
```

Run the complete optional synthetic gate. It runs the new planner tests,
reuses the already verified local S24A image, and creates only new disposable
resources. It does not rebuild or rerun the 661 production tests:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/verify_s25.py --record \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
```

If the verified local image ID was removed, use the existing pinned S24A
registry image; current Docker registry authentication is reused:

```bash
python3 tools/verify_s25.py --record \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key" \
  --image europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:08cf99dc5ab117b08db3739600e4f6486611a6c63238cb4a2b9efba141b115b1
```

Host prerequisites: Linux, Python 3.10+, local Docker Engine, `/dev/shm`, the
existing pinned age installation and an existing external private identity
file matching `private/operations.json` if that configuration exists. No new
key or service account is created. Images may need downloading. The application
image revision, context label, user and architecture are checked before use.
The official `postgres:15-bookworm` legacy-test image is resolved once to an
immutable registry digest and recorded; only that digest starts containers.
The production PostgreSQL 17.11 lock is retained unchanged.

To repeat the exact legacy image from a previous receipt, add
`--source-image postgres@sha256:<the recorded source_postgres15 digest>`.
There is no PostgreSQL production dependency update in this step.

On success, commit the generated four-file evidence set once. A second gate
run is not needed just to save its output:

```bash
git add docs/implementation/evidence/S25-verification.json \
  docs/implementation/state.md docs/implementation/steps.csv \
  docs/implementation/traceability.csv
git commit -m "docs: record S25 synthetic migration rehearsal"
git push -u origin step/s25-legacy-rehearsal
```

## Canonical source and reviewed mapping

The two JSON fixtures are the executable schema example. Source `schema: 1`
contains an immutable `lineage` and ordered rows for `users`, `cash_accounts`,
`entities`, `categories`, `agreements`, `transactions`, using the original
0001/0002 column names. IDs are positive integers, EUR values are finite exact
strings with two decimal places, dates are ISO dates. Every row of each group
has the same projected fields; rows are sorted by original ID. Source timestamps
are retained verbatim in the archive/ID ledger. Credentials are not exported
into this JSON; the native logical snapshot preserves the complete source DB.

Review `source_sha256` binds the canonical sorted-key JSON, not file whitespace.
`lineage` is a stable snapshot identity, not an idempotency key to change in
order to force a retry. Every `records["model:id"]` decision contains a reviewed
office key, responsible source-user ID, action, reference and reason. An
archived source-user decision must map to the same office. There is no default
office, implicit administrator promotion or copied/activated human password.

Masters use `action: import`. Parties require explicit `legal_kind`, customer
and supplier booleans; AFM syntax follows S15, without inventing a checksum or
registry claim. Accounts require reviewed opening amount/date/reference. A
positive/negative pre-opening movement is never automatically repaired: only
accepted positive directional source rows become explicit opening components.
Their signed sum plus the original source opening must equal the approved
opening exactly. These old rows are archived, not posted a second time.

Agreements require explicit `ONE_OFF` or `MONTHLY`, `lifecycle: ACTIVE` and a
finite list of reviewed charge amounts, effective/due dates and periods.
No charge is generated beyond this list. A first partial month uses an explicit
reviewed amount; no automatic proration/tax rule is added. Legacy COMPLETED
does not settle a charge. Allocation lines identify source cash, agreement,
charge index, positive amount, effective date and review reference. Capacity,
party, direction, office and date are checked again by the normal SQL/services.

| Source finding | Rehearsal treatment |
|---|---|
| Zero/negative movement | Quarantine unchanged; never abs/round/delete |
| Missing office/user or foreign-office FK | Quarantine; no default owner |
| Duplicate identity, invalid AFM or category cycle | Quarantine; no merge/repair |
| Ordinary UUID singleton | Ordinary cash, because old UUIDs defaulted on every row |
| Candidate internal transfer | Exactly two equal opposite legs, same day/office, distinct accounts, no party/agreement/category and explicit supporting leg/reference proof |
| Missing/ambiguous/three-leg transfer | Hold every leg; no half transfer or netting |
| Invalid old settlement reference | Genuine cash may be explicitly held unallocated; no invented settlement |
| Legacy COMPLETED agreement | Retain source status; derive outstanding from reviewed charges/allocations |
| Unreviewed exception | Report it and refuse import until a disposition/reference exists |
| Already completed identical snapshot | Return the original target IDs without writes |
| Same lineage with changed source/review | Refuse; never update posted originals |

Quarantine/archive decisions explain exclusions; they do not assert that the
whole raw legacy total equals the accepted financial subset. Coverage reports
account for **every** raw identity as imported, opening component, archived,
held unallocated or quarantined. The accountant must review these differences
before real financial acceptance. Dated source cash can settle a different
agreement only through its explicit reviewed allocation; the old FK alone is
never proof. Cash without a valid party is excluded from credit/advance claims.

## Database, audit and reconciliation design

1. Create a new PostgreSQL 15 source in tmpfs with the original 0001/0002 schema,
   auth dependencies and synthetic data. Freeze it read-only after seeding.
2. Use **native pg_dump 15** for a source rollback archive. Separately use
   **pg_dump 17** against source 15 for the forward custom-format archive, with
   quoted identifiers and no role/privilege ownership import. Restore only
   into a new PostgreSQL 17 raw-copy database; compare all logical table hashes.
   Never mount the PostgreSQL 15 data directory as a PostgreSQL 17 volume.
3. Create a separate empty target database, current twenty migrations under a
   restricted role, and synthetic owners with no Django admin flags. The new
   PostgreSQL 17 named volume has this run's random ownership label. No port is
   published; the network is internal. Source rows are never migrated in place.
4. Capture the target starting point. Encrypt source-native15, source-forward17,
   target-start, JSON mapping/source, manifest and **required synthetic Django
   signing/MFA key material** with the existing age recipient. The decryption
   identity stays external. Decrypt into tmpfs and check every member digest.
5. Run a read-only plan, inject a failure after cash posting and prove every
   table rolled back. Import concurrently from independent worker processes;
   an advisory transaction lock and unique source ledger serialize completion.
   The successful batch is atomic; replay returns the same IDs without login,
   session, audit, balance or allocation writes. A third retry must also match.
6. Use normal counterparty, account, opening, agreement/charge, cash/transfer
   and allocation services. Opening approval uses a real CSRF-protected login,
   TOTP enrollment, recent verified MFA and password for the synthetic owner.
   No service guard is disabled and no human source user is autoactivated.
7. Retain each original source row, digest, decision/reference and target ID in
   append-only `s25_import` tables in the isolated target. Ordinary financial
   audit records attribute the actual migration actor/time; they do not pretend
   that a historical user performed a new posting. This operator-only ledger
   does not add a production migration/model or staff route.
8. Independently compare each account's approved opening, operating receipts,
   payments, transfer legs and final balance; each explicit charge amount,
   allocated amount and outstanding; each original cash amount/type/credit or
   supplier advance; every allocation's source/charge/amount/date; source ID
   coverage and retained digest; and attributable financial audit. The expected
   arithmetic is stdlib Decimal, the actual values are existing scoped selectors.
9. Restore the encrypted native archive into a separate source PostgreSQL 15
   database and compare it with the original. Restore the target starting
   snapshot, compare all tables including auth/ledger, then repeat import and
   reconciliation. Verify original source hashes again before cleanup.

PostgreSQL's primary references:
[cross-version pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html),
[major-version upgrades](https://www.postgresql.org/docs/17/upgrading.html),
[official image sources](https://github.com/docker-library/postgres).
The forward pg_dump 17 archive is **not** represented as a PostgreSQL 15
rollback archive; the separate native dump is what proves that recovery.

## Reports, recovery and acceptance

Detailed JSON/Greek CSV reports and source→target IDs stay in
`private/s25/<run>/` (ignored by Git). The retained recovery archive is
`~/.config/totalaccounting/legacy-rehearsals/<run>/rehearsal.tar.age`, outside
Git. Keep the existing independent recovery identity copy separately.
Plaintext dumps, recovered members and ephemeral credentials live only in
`/dev/shm` and are removed when the command ends. Only newly labelled containers,
network and volume are removed. A cleanup failure records the exact owned
resource names privately and leaves the technical gate incomplete.
The `dry-run-source-balances.csv` report separately shows each raw legacy
balance, accepted balance, signed excluded amounts and any unexplained delta.
Unpriceable source rows remain explicitly identified; they are never zeroed.

The public receipt has only digests/counts/technical results. It does not copy
source names, source→target IDs, passwords, MFA seeds, private key paths or raw
provider errors. Safe failures include stage/function/line/SQLSTATE metadata.
The tool manifest binds the exact operator scripts used, in addition to the
source Git reference. A full S25 secret scan is not claimed by retaining the
historical S24A scan. Actual tests/runtime are Pending until the operator runs
the optional gate.

The restore timing measures this small synthetic snapshot only. It does not
accept production workload sizing, the 24h/8h RPO/RTO targets, private documents,
external connector secrets or S38 document/full-environment recovery. All 85
full requirement acceptances remain Pending. G2 additionally needs approved
D05 decisions against the real snapshot, reviewed exception/account/obligation/
allocation/transfer totals and a named freeze, cutover and rollback plan.
S26 is selected separately; no Redis/worker/scheduler is introduced by S25.

## Operator restore failure follow-up — Prepared

The reported attempt stops at `logical-15-to-17: docker exit 1`. The original
wrapper discarded pg_restore's stderr, so its archive/SQL/connection cause is
**unconfirmed**. Reaching this stage implies that the original planner gate,
source seeding/read-only export and dump commands returned successfully; it
does not prove the forward restore or financial/recovery acceptance.

The follow-up keeps the original 34 planner methods and supplies twelve new
restore/diagnostic contracts. The optional operator command remains
`python3 tools/verify_s25.py --record`; it starts fresh owned resources.
No new application image, dependency update or rebuild is required.

Before restoration it now checks the custom archive header, the exact owned
database name/role, server major/port/read-write mode and empty target, then
checks the destination pg_restore version and archive TOC source/dumper
versions. It copies only this run's bounded private dump to a **regular file
in an additional container tmpfs**, reads its TOC, and restores using explicit
loopback/5432 credentials. This removes stream/implicit-connection ambiguity;
it is not a claim that either was the original root cause. The original
`--single-transaction`, `--exit-on-error`, no-owner/no-privileges and every
row/financial/restore assertion remain in effect. No SQL is edited or skipped.

A command failure prints `S25-DIAG` with phase, operation, exit code, classified
error headers and version metadata, and retains the first failure across
cleanup. `private/s25/<run>/failure-summary.json` is the small redacted report
to share. `failure-private.json` retains bounded, credential-redacted stderr
for local inspection; do not paste that larger private file. No command input,
SQL dump, credentials or recovery identity contents are logged. If a disk-full
condition prevents writing the files, the safe console diagnostic is retained.
The temporary container restore file is removed after the attempt and the
original run-owned resource cleanup still applies.

Agent validation is static syntax/source preservation only. New tests, actual
restore and the full S25 operator gate remain Pending. Primary references:
[pg_restore](https://www.postgresql.org/docs/17/app-pgrestore.html) and
[pg_dump](https://www.postgresql.org/docs/17/app-pgdump.html).

## Tmpfs transfer follow-up — Prepared, 2026-11-16

The latest operator diagnostic specifically reports `logical-15-to-17/archive-copy`:
PostgreSQL 17, expected database/role, writable mode and zero user tables all
passed; the failing command is the Docker archive copy, before pg_restore.
The previous adapter incorrectly used `docker cp` to a user-created tmpfs mount,
a documented Docker cp corner case. The exact raw Docker error text was not
shared, so the full operator retry is still required.

The transfer now runs a fixed `sh`/`cat` writer through `docker exec -i` inside
the owned container mount namespace. A positional argument supplies only the
generated private path; binary dump bytes are stdin data, never shell text.
Noclobber, umask 077 and mode 0600 retain a private regular file in tmpfs.
An in-container SHA-256 must match the original dump before TOC/SQL processing.
pg_restore still reads that seekable file, with the existing atomic/exit-on-error
flags and all ownership, version, reconciliation and recovery assertions.

All 46 previous test method bodies remain unchanged; four extra contracts cover
binary transport/no-tty/no-docker-cp, write failure cleanup, hash mismatch denial,
and safe Docker/shell error headers. They are supplied but not agent-executed.
Safe diagnostics now retain Docker/shell headers as well as PostgreSQL headers.
The same optional command starts fresh owned resources:

```bash
python3 tools/verify_s25.py --record
```

See [Docker cp corner cases](https://docs.docker.com/reference/cli/docker/container/cp/#corner-cases)
and [Docker exec](https://docs.docker.com/reference/cli/docker/container/exec/).
No application source, dependency, schema, retained demo or VM change is included.
