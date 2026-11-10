# S12 — office ownership and isolation

Based on the pushed `s11-complete` commit
`e314645a4c6decc701fc0dca928d52d6f9b76491`. S11 is operator-Verified on Docker /
PostgreSQL 17.11: 120 tests, 94 passes and 26 exact known financial failures.

S12 scopes the five existing business tables: Entity, CashAccount, Category,
Agreement and Transaction. It retains their table/primary-key identities, the
first three migrations, existing Django user/profile schema, dependency locks,
financial assertions and financial calculations. The current preview remains
the previously verified S09/S10 release; this step runs locally with synthetic data.

## Ownership and access

Each business record has a mandatory protected office foreign key, hidden from
editable forms. `office_access.records`, `record` and `save_for_user` resolve the
actor's active profile and active office from the database at each action.
Submitted office IDs, cached reverse relations, staff flags and superuser status
do not choose or override that context. Missing/inactive membership denies access.
Successful protected responses also use `Cache-Control: no-store, private`.

Every existing view, aggregate, filter/dropdown, detail/edit lookup and creation
path uses that context. A well-formed foreign-office identifier receives 404 or
a scoped form-field error, indistinguishable from an unavailable record. Forms
constructed without an actor have no related choices and cannot validate. Form
saves recheck profile activity. The separately tracked malformed-filter/date
defects remain S29: S12 does not alter their assertions or count their generic
failure responses as successful filter handling.

PostgreSQL enforces non-null ownership and six composite `(related_id, office_id)`
foreign keys: Category.parent, Agreement.entity, and Transaction's cash account,
category, entity and agreement. Five database triggers reject ownership changes
after assignment. Model validation also rejects cross-office links/moves. The
database guards cover raw ORM updates/bulk operations that bypass model forms.
Money, agreement settlement and transfer classification remain in their assigned
financial steps. Same-office entity/agreement financial semantics are not changed.

Cash-account names and nonempty AFMs are unique per office, allowing the same
value in independent offices. Null/empty AFMs remain repeatable. Category child
uniqueness includes the office; root-null semantics are retained. Detailed AFM
normalisation/format validation remains S15; this step does not claim tax validity.

## Admin boundary

All five business ModelAdmins scope rows, related choices, filters and saves.
Another office's change/history/delete URLs return 404. Shared autocomplete is
scoped too; an administrator with Office A context receives only A's records.
Office lookup overrides and unsupported bulk actions are denied. Ordinary Django
admin permission checks remain in force; an office role does not grant admin flags.

The global recent-action sidebar is omitted because historical object labels
have no office key. Audit entries are retained; individual object history uses
the scoped object lookup. Office/profile administration is still not registered
here. Owner capability/handover policy remains D01/S14, and privileged MFA is S13.

## Apply and verify on the laptop

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
git fetch origin --tags
git switch -c step/s12-office-ownership s11-complete
git am --keep-cr ~/Downloads/accounting-platform-S12.patch
python3 tools/verify_s12.py --record
```

The default verifier creates and removes a randomly named local Docker project
with its own PostgreSQL volume and generated credentials. It does not migrate the
ordinary development database or the VM. It runs 157 tests: 131 pass, 26 exact
known financial failures, no unexpected outcomes. Thirty-seven tests are new for
S12, including real concurrent uniqueness and staged migration/backfill cases.

The migration tests seed the old schema, exercise the pause/review/apply/final
constraint sequence, compare all original row hashes, reject conflicting/stale
mappings, prove rollback on a later assignment failure, and prove idempotent retry.
Database links, immutable ownership, two-way HTTP/admin isolation, authenticated
revocation, forged related choices, autocomplete and historical-label exclusion
are tested on real PostgreSQL. Fixtures now supply explicit office ownership;
no financial assertion or regression registry entry is weakened.

Native maintainer proof:

```bash
python3 tools/verify_s12.py --native-bin /path/to/postgresql17/bin \
  --python /path/to/locked-runtime/python --record
```

Native proof is Prepared. A successful default Docker run records Verified and
makes S13 eligible. The included secret scan is from the implementation workspace,
not a new scan of every operator machine/ref. Full requirement/Greek release
acceptance remains Pending. Docker/production image and VM execution are not
inferred from the native proof.

After the local Docker result is Verified:

```bash
git add docs/implementation
git commit -m "docs: record S12 office ownership verification"
git push -u origin step/s12-office-ownership
git tag -a s12-complete -m "S12 office ownership and access isolation verified"
git push origin s12-complete
```

## Existing local database: reviewed staged migration

The commands in this section are for a separately selected, existing **local**
database upgrading from S11. Run the disposable verifier above first. Human
accounts, actual legacy ownership approval and VM deployment are not part of this
section. Existing offices must already be explicitly reviewed/provisioned through
the S11 service; no default office or inferred user-to-office assignment is made.

`0004_office_ownership_nullable` adds nullable office columns only.
`0005_enforce_office_ownership` stops before enforcement if any record is unassigned
or any parent/child has conflicting ownership. An empty database can pass both
without a mapping, because there are no legacy records to assign.

These are phases S12A (nullable schema/reviewed backfill) and S12B (final schema
and access enforcement) under the existing S12 identifier; later steps retain
their numbering.

Use a maintenance window and keep application writers stopped while migrating
and reviewing. For a nonempty S11 database, build the local image and stop at 0004:

```bash
docker compose build web
docker compose up -d db
docker compose run --rm --no-deps --entrypoint python web manage.py \
  migrate accounting 0004_office_ownership_nullable --noinput
```

Do not target 0004 if 0005 is already applied; that would be a rollback rather
than an upgrade. Export the complete private review file using a narrowly mounted
local directory, with your laptop UID so its owner can edit the mode-0600 file:

```bash
mkdir -p private/s12-review
chmod 700 private/s12-review
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  --volume "$PWD/private/s12-review:/review" --entrypoint python web manage.py \
  backfill_office_records --export-template /review/ownership.json
```

The explicit export contains record IDs, private review labels and original-row
SHA-256 fingerprints; it contains no authentication credentials. It refuses to
overwrite an existing file. Keep the file private and outside public Git/chat.
The parser bounds the complete review document to 1 MiB and rejects duplicate
JSON keys/non-finite values; larger inventories need a reviewed tooling update.

The actual reviewer completes `reviewed_by`, a timezone-aware `reviewed_at`, and
one existing office UUID for **every** `(model, id)` assignment. Preserve the
inventory and its digest. Missing/duplicate/unknown rows, changed source data,
conflicting existing ownership, cross-office parents, mixed transfer groups and
duplicate scoped cash names/nonempty AFMs are rejected. Inactive offices may own
historical data but do not grant access. This tool creates no office or profile.

Review the dry run, then apply only its exact digest:

```bash
docker compose run --rm --no-deps -T --entrypoint python web manage.py \
  backfill_office_records --mapping /dev/stdin < private/s12-review/ownership.json

docker compose run --rm --no-deps -T --entrypoint python web manage.py \
  backfill_office_records --mapping /dev/stdin --apply \
  --expected-sha256 'sha256:PASTE_REVIEWED_DRY_RUN_DIGEST' \
  < private/s12-review/ownership.json

docker compose run --rm --no-deps --entrypoint python web manage.py migrate --noinput
```

Apply locks the five business tables and office inventory, revalidates the complete
review, then fills only null ownership atomically. It preserves IDs, amounts,
descriptions and timestamps. An exact retry is safe; it never moves an already
owned record. Unassigned records are hidden from ordinary scoped reads even at
the nullable stage. Inconsistent data needs an explicit review decision, not an
automatic correction. No real mapping was approved/applied by implementation tests.

Do not use schema reversal as a routine data rollback: restoring old global
uniqueness may fail after independent offices reuse names/AFMs. Reversal rehearsals
run only in disposable tests. Use a reviewed restore/migration plan for a selected
deployment. The old preview/operations installers are context-pinned to their
original image; future deployment needs a matching backup binding and new image
verification. Do not run them from S12 source to update the existing VM.

## Remaining boundary coverage

| Entry point | S12 result | Continuing gate |
| --- | --- | --- |
| Current staff views, reports, filters and forms | Two-office/forged-ID tests pass | S16 complete boundary review |
| Current business admin, choices, filters, autocomplete/history | Scoped; unsupported bulk actions denied | S13 privileged MFA; S14 capabilities |
| Database links and owner changes | Composite keys, non-null and immutable-owner triggers tested | Future schema additions need equivalent guards |
| Existing record ownership migration | Reviewed synthetic backfill and failure/retry proof | Actual legacy ownership is D05/S25 |
| Future exports, files and workers | `records`/`execution_record` foundations tested, including revocation | Concrete adapters/tests at S26/S30/S38/S39 |
| Portal identities/client grants | No portal authority inferred from staff profile | S43–S46 separate grant model |

Unsupported model types are rejected by the access helper. Future adapters must
resolve authority at execution, verify the expected office and scope the selected
record; an enqueued office ID is only a consistency check. No worker, export or
file feature is claimed delivered here. D01's capability matrix, full AT-OFF-05 /
QT-01 and staged AT-LOC-01 acceptance remain Pending until their assigned gates.

Primary references: [PostgreSQL 17 composite foreign keys](https://www.postgresql.org/docs/17/sql-createtable.html),
[Django 5.2 admin scoping/lookup controls](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/).
