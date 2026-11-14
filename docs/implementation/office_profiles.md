# S11 — Office and accountant profile foundation

S11 follows the pushed `s10-complete` commit
`06cb37d3342115aebf53dd47e36b7900c3918fcd`. S10's actual scheduled encrypted
upload, recovered-key laptop restore and received alert are Verified. Their
evidence and the selected VM remain intact.

This step implements the S11 prompt in `prompts.json`: schema, explicit membership
services, reviewed legacy mapping and two-office fixtures. Office settings and
invitation screens belong to S14. Regular sign-in/recovery/MFA arrives in S13;
the user has elected to wait for that onboarding before creating a human account.

## Schema and service rules

Additive migration `accounting.0003_office_profiles` creates only:

- `accounting_office`: UUID identity, required Greek-labelled name, active flag
  and timestamps. Contact/AFM settings are S14 work.
- `accounting_accountantprofile`: one-to-one existing `auth.User`, mandatory
  protected office, explicit `owner`/`accountant` role, active flag and timestamps.

One user has at most one profile, including inactive profiles. The database's
unique user key, non-null foreign keys and role check remain effective when a
caller bypasses the service. Several accountants can share an office. Existing
business tables, field definitions, original migrations and auth user identities
are preserved. No user receives a profile through a signal or default office.

`accounting.membership.create_accountant_profile` locks the existing user before
the office/profile, serializing competing first assignments to different offices.
An exact retry returns the same profile; a different office/role or inactive
existing profile is rejected. `change_membership` explicitly changes role/activity
within the same office. It rejects office transfer and implicit reactivation.
These are trusted internal services, with no public write endpoint or new admin
registration. S14 must add actor/capability checks and the agreed last-owner /
handover policy before exposing staff administration. Role names alone do not
approve D01's unresolved finance/export/credential permissions.

## Minimum access gate and Greek copy

`ActiveOfficeMiddleware` checks every existing accounting view and accounting
model-admin view. An authenticated user needs an active database user, active
profile, valid role and active office, including when the user is a superuser.
The context is fetched afresh for each protected request; submitted form/query/
header office identifiers cannot select it. Logout, login and health remain
available. A blocked request returns HTTP 403, a Greek page and no-store caching.

**Full office isolation is S12/S16 work.** Existing business records do not yet
carry an office key. S11's profile gate is not proof that two active offices can
safely share the legacy business views. Keep S11 local with synthetic data;
finish record scoping and authentication before enabling real office onboarding.

## Apply and verify on the laptop

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
git fetch origin --tags
git switch -c step/s11-office-profiles s10-complete
git am --keep-cr ~/Downloads/accounting-platform-S11.patch
python3 tools/verify_s11.py --record
```

The default verifier uses a randomly named, disposable local Docker Compose
project with its own generated credentials and PostgreSQL volume. It preserves
the normal development stack and configured WEB_PORT. It upgrades a synthetic
database from the two original migrations, verifies legacy rows and users,
rehearses removal/reapplication of only the additive schema, and runs all 120
tests. Thirty new membership/backfill/access/concurrency tests pass alongside
the original 90-test suite: 94 passed, 26 exact known financial failures, no
unexpected outcomes. No assertion or regression outcome is weakened.

The verifier removes only its own temporary Docker project/volume. Its migration
rollback is a disposable test, not a production rollback procedure. It does not
load fixtures or assign memberships in your regular database or VM. Python and
runtime/maintenance locks remain unchanged. The production build context permits
only the exact synthetic `accounting/fixtures/s11_offices.json` fixture; private
user mappings remain excluded.

Native PG17 proof is available for maintainers:

```bash
python3 tools/verify_s11.py --native-bin /path/to/postgresql17/bin \
  --python /path/to/locked-runtime/python --record
```

Native proof records Prepared; a successful default local Docker run records
Verified and makes S12 eligible. Neither is cloud deployment or full business /
Greek release acceptance. S10's verifier and installer belong to their original
tag: do not rerun the old context-pinned operations installer from changed S11
application source. Future application deployment must review/update its backup
binding to the new image; the current preview keeps its verified S09/S10 release.

After successful Docker verification:

```bash
git add docs/implementation
git commit -m "docs: record S11 PostgreSQL membership verification"
git push -u origin step/s11-office-profiles
git tag -a s11-complete -m "S11 office and accountant profile foundation verified"
git push origin s11-complete
```

## Review a real legacy user mapping when legacy ownership is known

The commands below target the **selected local database**, not the VM. First
apply the additive schema explicitly using the normal development stack:

```bash
python3 tools/dev.py up
python3 tools/dev.py migrate
docker compose exec web python manage.py backfill_accountant_profiles \
  --export-template /tmp/s11-mapping.json
docker compose cp web:/tmp/s11-mapping.json private/s11-mapping.json
chmod 600 private/s11-mapping.json
```

The development stack uses its normal Compose name/env. If you use a separately
named stack, use that exact project's Compose arguments instead. Do not export
or paste mapping contents into public Git/chat. The export is exclusive and
private, contains no password/email/token, and never overwrites an earlier file.
Choose a new private filename for a new review. No mapping is auto-approved.

Have the actual reviewer complete `reviewed_by` and timezone-aware `reviewed_at`.
For every user, record an exact ID/username and an existing active office UUID
plus role, or move that user to `excluded_users` with a reason. Exclusion never
grants business access. Preserve the exported inventory and digest. Do not copy
the synthetic example over a real inventory. It demonstrates only test identities.

Save the reviewed file privately, then stream it into this local container:

```bash
docker compose exec -T web python manage.py backfill_accountant_profiles \
  --mapping /dev/stdin < private/s11-mapping.json
```

This defaults to dry run and prints counts plus `mapping_sha256`, without user
or office names. It rejects missing/duplicate/unknown users, ambiguous identity,
unknown/inactive offices, invalid roles, unreviewed/stale inventories, conflicts
with existing profiles, duplicate JSON keys and unexpected document fields.
Only the exact reviewed document can be applied:

```bash
docker compose exec -T web python manage.py backfill_accountant_profiles \
  --mapping /dev/stdin --apply --expected-sha256 'sha256:PASTE_DRY_RUN_DIGEST' \
  < private/s11-mapping.json
```

Apply revalidates under locks and commits all assignments atomically. An identical
retry is safe. It never creates offices/users, reassigns an existing profile or
grants staff/superuser flags. Current tests use reviewed synthetic mappings only;
actual legacy ownership, capabilities and handover approval remain Pending.

## Evidence and references

- `accounting/tests_offices.py`: 30 PG17 tests; independent database connections
  race different-office first assignments, same-office retries and direct inserts.
- `evidence/S11-verification.json`: actual migration/suite mode and remaining gate.
- The two financial test fixtures now explicitly create their office/profile;
  all financial assertions, registry identities and 26 expected failures remain.
- [Django 5.2 profile models](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/#extending-the-existing-user-model).
- [Django 5.2 row locks and transaction-test guidance](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update).
- [Django 5.2 transactions](https://docs.djangoproject.com/en/5.2/topics/db/transactions/).

AT-OFF-01's complete office-boundary acceptance remains S16. AT-LOC-01 remains
Pending for staged journeys; S11 proves its new labels/denial responses only.
