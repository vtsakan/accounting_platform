# S15 — Client and supplier workspace

Implements the selected S15 prompt for UR-CRM-01/02/03/06/07, QR-07 and
UR-LOC-01. The actual pushed prerequisite is
`ab9602592cb699684450bc4ee70438f80d30351f` on `step/s14-vm-demo`, read through
GitHub and fetched before this step. S12/S14 Docker verification is preserved.
The user subsequently reported the VM demonstration working; the evidence
limits are explicit in `evidence/S14A-operator-report.json`. S15 changes no VM,
human account, key or private recovery configuration.

## One identity, independent roles

The existing Entity primary key, office and historical foreign keys stay in
place. There is no parallel client/supplier table or automatic duplicate merge.
The `is_customer` and `is_supplier` booleans are independent; at least one is
required. A dual-role identity appears in both lists with the same ID. Both
owner and accountant use the existing S14 `clients.read` / `clients.write`
capabilities. Submitted office/admin/archive fields have no authority.

| Legacy field/state | S15 mapping |
| --- | --- |
| ID, office, original identity/contact fields and historical links | Preserved exactly by migration |
| `entity_type=CUSTOMER` | Customer true, supplier false |
| `entity_type=SUPPLIER` | Supplier true, customer false |
| Original `entity_type` after upgrade | Read-only provenance; immutable in PostgreSQL |
| Classification missing from old data | `UNREVIEWED`, with a visible confirmation reminder |
| New or edited workspace record | Explicit individual/business selection required |
| AFM | Original retained by migration; canonical `vat_key` supplies uniqueness/search |
| Archive/version state | Active, no archive actor/time, version zero |

The old ORM constructor remains compatible with maintenance/test callers using
only `entity_type`. New forms use independent flags. Existing money models,
calculations and all 26 registered financial mismatches remain unchanged.
Settlement, report correctness, reversal and full agreement-eligibility rules
stay in their assigned S18–S24/S29 steps.

## Input validation and AFM uniqueness

Names are required and trimmed; contact fields reject control characters.
Email uses Django validation. Optional phone values allow a leading plus,
spaces/parentheses/dots/hyphens and 7–15 digits. Optional postal codes use a
bounded alphanumeric/space/hyphen format so foreign contacts are possible.
These checks do not verify a real address, phone or tax registration.

AFM may be blank; otherwise its canonical value must have nine ASCII digits,
preserving leading zeroes. The defined local normalization accepts full-width
digits, a case-insensitive `EL` prefix, the frozen whitespace list and hyphens.
A prefix without digits is invalid. No checksum, registry or representative
verification is claimed; synthetic zero-prefixed values remain supported.

Python, frozen migration and PostgreSQL normalization have parity tests. A
trigger derives `vat_key` on every insert/update, ignoring a forged key. A
conditional unique index covers nonempty `(office_id, vat_key)`, including
archived identities. Equivalent AFMs race safely within an office and remain
independent across offices. Restore/edit an archived identity rather than
creating its duplicate. New form submissions store canonical AFMs.

## Greek workspace

`/counterparties/` provides AFM/name search, role and person-kind filters,
active/archive/all status, stable name/ID ordering and 25-row pagination.
`/customers/` and `/suppliers/` remain role-specific entry points. Invalid
filters show Greek field errors and no result rows; bound search and pagination
parameters cannot choose another office.

The consolidated `/entity/<id>/` card shows classification, roles and all
contacts, and links the enabled agreements, income/expense and movement modules.
Agreements and movements each have independent ten-row pagination. Dates use
day/month/year with Europe/Athens conversion and money uses the existing exact
Greek euro formatter. User/provider text is preserved and HTML-escaped. Future
portal/files/jobs do not acquire links or permissions in S15.

Forms show field/non-field errors in Greek. Hidden version checks reject stale
edits, and actor authority is rechecked after locking office/user, including
revocation between validation and save. Race-time AFM errors become field
errors. Entity admin uses the same scoped service; stale changes show a Greek
message and archived records cannot be edited there.

## Archive, restore and history

Archive/restore require POST, CSRF and the current version. GET confirmation
does not mutate. Archive records actor/time, retains IDs, contacts, agreements
and movements, and removes the identity from active lists/new-work choices.
Historical detail, movement filters and reports still include it. Editing
requires restoration first. Restore does not create another identity.

Forms, model validation and PostgreSQL deny new agreements/payments against an
archive, including a payment with only an agreement link. Changing a historical
link to an archived identity is denied; an unchanged old link remains valid.
This does not introduce a new financial-edit/reversal policy.

The database guard locks office before referenced entities in ID order, matching
archive/revocation lock ordering and preventing a deferred FK lock inversion.
Independent-connection tests observe real waits in both orders: archive first
rejects the waiting posting; posting first commits and is retained when archive
follows. The trigger does not recalculate money or settlement.

Atomic append-only `CounterpartyEvent` rows record office, identity, actor,
action, time, version and changed field names. Contact/credential values are
excluded. Composite keys bind actor, event and archiver to the same office.
Physical Entity deletion is blocked in PostgreSQL, protecting financial history
even if an ORM caller tries to cascade. General audit/privacy/retention
acceptance remains S18/S46; no statutory retention period is invented here.

## Additive migrations and review

`0009_counterparty_workspace` preflights before schema changes. Malformed AFMs,
normalization collisions within an office, empty legacy names and unknown old
roles stop with record IDs/reason, without printing contact values. There is
no winner selection, merge, invented office or rewritten original AFM. Make a
separately reviewed data correction, then retry. Valid rows receive deterministic
role/key fields, an event table and constraints.

`0010_counterparty_database_guards` adds normalized keys/versions, immutable
identity/history, same-office event links and archive/new-work guards. Apply
both before running S15. See `counterparty_migration_map.json`. All original
eight migrations stay unchanged. Tests preserve original financial columns,
IDs, relations, user/password hashes and encrypted MFA device data.

S12 ownership inventory still reads the historical Entity columns; its rehearsal
uses a historical Entity model at 0004. Only four old form request fixtures gain
the new role/classification/version fields. Their expected results and all
financial/authentication assertions and regression contracts remain unchanged.

Legacy-only reversal is tested. Downgrade stops before dropping guards if dual
roles, classification, archive or events would be lost. Do not force it by
deleting records. Recovery for an already used environment must preserve the
exact database/image binding and the latest work.

## Verify and demonstrate

From clean committed source on laptop Docker:

```bash
python3 tools/verify_s15.py --record
```

The verifier creates a random disposable Compose project/PG17 volume, preserving
`.env`, `accounting-client-demo` and the VM. It checks locks, Greek catalog,
source/history secret scanning, migration drift, runtime packages and all tests.
Only the same 26 registered failures are accepted. Commit the four generated
implementation records after success, before another `--record` run.

Native proof is Prepared: 57 S15 tests, 344 total (318 passed plus 26 known
failures), migrations under a non-superuser/non-createdb/non-createrole role.
The native Chromium probe could not open the app: process-singleton socket
creation was denied. Visual/responsive/keyboard acceptance is therefore Pending.
On the laptop, demonstrate creating one dual-role business, finding its same
card in both lists, normalized AFM duplication, invalid contacts, stale edit,
archive/history/restore and enabled links. Check labelled controls, error/focus
handling and tables/pagination at 375, 768 and 1440 CSS pixels.

After the Docker gate, explicitly upgrade the retained local demo with a private
pre-change backup as described in the handoff `START_HERE.txt`. The S14 VM demo
continues independently. This patch does not publish an image or migrate/deploy
to the VM. That later rollout needs a tested image and updated backup/recovery
binding; the S14A S09/two-marker installer is not a general updater for a database
now containing people/MFA. All 85 full requirement acceptances remain Pending.
S16 is next after the Docker gate and covers the complete implemented office
boundary; future portal, files, exports, connectors and jobs remain explicit gaps.

Technical contracts: [Django constraints](https://docs.djangoproject.com/en/5.2/ref/models/constraints/),
[model validation](https://docs.djangoproject.com/en/5.2/ref/models/instances/#validating-objects),
[PostgreSQL 17 locking](https://www.postgresql.org/docs/17/explicit-locking.html).
