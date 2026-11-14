# S16 — Complete office boundary and G1 technical foundation

S16 starts from the actual pushed S15 Docker-verification head
`5fc66cb6161c76482501b31499e8745f79181a93` on
`step/s15-client-workspace`. S15 ran 344 tests: 318 passes and the 26 exact
known financial failures. This step retains all those tests, all ten existing
migrations, business models/calculations, dependency locks, MFA and referrer
policy, and historical evidence. No schema migration is added.

## Authority and trust boundaries

| Entry point | Authority | Implemented check |
| --- | --- | --- |
| 25 office business routes | Fresh active user/profile/office and declared role capability | Owner/accountant positives; anonymous, inactive user/profile/office, missing profile and platform administrator without a profile are denied |
| Identity and recipient proof | Existing login, MFA, reset or invitation proof | Exact module **and** route-name exceptions; the S13/S14 suites retain their identity/recipient tests |
| Five registered business admin models | Office membership/capability **and** Django model permissions | Even a superuser with an office sees only that office; regular app accounts cannot enter admin |
| Shared admin autocomplete | Editable, declared business source relation and both source/remote permissions | Remote rows are scoped; read-only archive metadata cannot query global users; archived identities/agreements are excluded from new work |
| Global auth admin | Explicit platform staff/superuser authority and MFA | A platform operator can manage auth identities; that privilege gives no office business access without a valid profile |
| Database references | Non-null immutable office ownership and composite foreign keys | One user/profile/office identity; same-office business, staff-workflow and event references |
| Business writes | Office lock, user lock, then fresh capability/profile check | A writer waiting behind committed revocation is denied; a write committed first can precede later revocation |
| Six management commands | Trusted process with database credentials | Explicit office or complete reviewed mapping; private export, exact apply digest, immutable ownership, no conversion of an existing account |
| Execution adapter | Fresh user/profile/capability plus expected-office check | Denied on mismatch/revocation/unsupported type; this is a synchronous adapter, not a deployed worker |

`accounting/office_boundary_matrix.json` is the reusable route/admin/command
inventory. `accounting/tests_boundary.py` compares it to the real URL and admin
registries and runs the matrix against synthetic offices A and B, plus an
explicit inactive-office fixture. New entry points must extend the inventory,
role/identifier/choice tests and the verifier's reviewed coverage counts.
Undeclared `accounting.*` business views also fail closed at runtime, including
anonymous requests. Existing admin callbacks use their dedicated permission
path; exact identity exceptions cannot exempt a new module by reusing a name.

An `--office` CLI argument selects an operator's maintenance target; it does
**not** authenticate a staff user. Database credentials can inspect multiple
offices and are kept outside the web trust boundary. Mapping exports contain
private inventories and remain in ignored `private/` or outside Git with mode
0600. No management command is exposed as a staff HTTP endpoint. Direct SQL
checks prove ownership/reference constraints, not PostgreSQL row-level security:
this architecture uses application scoping with a trusted database role.

## Findings fixed in their owning layers

The original S15 source was tested on disposable PostgreSQL 17.11. The recorded
baseline findings are in `evidence/S16-baseline-findings.json`.

1. Business classification previously recognised only the old views module or
   an annotated view. An undeclared `accounting.future_views` test endpoint
   returned foreign data to anonymous and authenticated callers. Shared route
   classification now requires declared capability for every business module.
2. Django's shared autocomplete checked the remote model. A read-only
   `Entity.archived_by` source could therefore search global usernames when a
   limited staff user had `auth.view_user`. The source field/model/permission
   and remote office boundary are now checked before Django executes it.
3. Business admin dropdowns offered archived identities and agreements for new
   work. New-work choices now exclude them. On historical edits, only the
   already stored archived link is retained; other archived records remain
   unavailable. Concurrent validation errors return a Greek message.
4. The old save helper checked membership before a database wait. A separate
   connection committed deactivation while the blocked writer then created a
   transaction. Writes now lock office/user and recheck authority after that
   wait. A URL wrapper applies the same sequence to the legacy direct transfer
   pair without changing its calculations or atomic transaction body. The old
   transfer body already rolled back its pair when its second membership check
   failed; the baseline control did not demonstrate a committed transfer leak.

The two local-only seed/probe commands also translate malformed UUIDs to a
bounded `CommandError`; their production-profile prohibition remains intact.
Normal admin history still includes archived records. CashAccountAdmin has no
search configuration, so its shared autocomplete intentionally returns 404;
its ordinary choice field is scoped. No search feature is invented for it.

## Test and evidence contract

The S16 module adds 38 integrated test methods. The expected complete suite is
382 tests: **356 passes plus the same 26 known financial failures**, with zero
unexpected failures/errors/passes or skips. The separate boundary report has
652 explicit cases, including the 25-route/eight-persona GET matrix, invalid
membership POSTs, foreign and nonexistent detail/edit IDs, forged relations and
promotion fields, all five business admin models, autocomplete sources, SQL
constraints, operator commands and five actual PostgreSQL lock-order cases.
The exact outcomes are generated by execution, not by copying this document.

`tools/verify_s16.py` reproduces both hashed dependency locks, checks the Greek
catalog and runtime packages, scans Git history, migrates an isolated database,
checks migration drift and runs the complete strict suite. Native mode also
migrates under a role with no superuser/createdb/createrole authority. The
manifest is a non-secret production-context input so immutable-image test runs
can check the same inventory. Recorded CSV rows contain case metadata/status
only, never raw responses, passwords, tokens, private mapping contents or human
identifiers.

| Requirement / acceptance ID | S16 technical evidence |
| --- | --- |
| UR-OFF-01 / AT-OFF-01 | Existing membership race tests plus immutable/unique profile SQL, several colleagues per office |
| UR-OFF-04 / AT-OFF-04 | Owner/accountant route matrix, privileged office-action denials and forged-promotion posts |
| UR-OFF-05 / AT-OFF-05 | Detail/edit/POST/choice/filter/report/admin/autocomplete/command/adapter matrix and no foreign-write snapshots |
| UR-OFF-07 / AT-OFF-07 | Missing/inactive profile/user/office HTTP denials and revocation lock waits |
| QR-01 / QT-01 | Implemented entry-point inventory and composite links, with future modules explicitly Pending |
| UR-LOC-01 / AT-LOC-01 | Existing Greek catalog, authentication and workspace checks retained; human browser acceptance still Pending |

The synthetic G1 client workflow creates a dual-role identity as an accountant,
uses the submitted foreign office as an untrusted input, reads it as a colleague,
records an exact-decimal receipt, archives it while retaining history, restores
it and denies the other office's detail request. This is an HTTP test-client
workflow with database assertions; it is not a claim of browser accessibility
or client acceptance.

## Apply and verify on the laptop

The supplied installer checks the packet checksums and exact pushed S15 base,
creates `step/s16-office-boundary`, and stops only the existing local demo web
service while its bind-mounted source changes. It retains the database volume,
accounts, passwords, MFA and private environment. It neither creates an office
nor changes the VM. The S15 retained-demo migrations, if not yet applied, still
need the explicit migrate step below; S16 itself adds no migration.

```bash
unzip -o ~/Downloads/accounting-platform-S16.zip \
  -d ~/Downloads/accounting-platform-S16
bash ~/Downloads/accounting-platform-S16/APPLY_S16.sh

cd ~/accountant_cloud/accounting_v5/accounting-platform
python3 tools/verify_s16.py --record
```

A native result is **Prepared**. Successful execution in the disposable local
Docker project makes S16 and the scoped G1 **technical** gate **Verified**.
The installer/verifier do not publish, deploy, bootstrap or send mail. After a
successful `--record`, commit these six generated files once:

```bash
git add \
  docs/implementation/evidence/S16-verification.json \
  docs/implementation/evidence/S16-office-boundary.csv \
  docs/implementation/evidence/G1-foundation.json \
  docs/implementation/state.md \
  docs/implementation/steps.csv \
  docs/implementation/traceability.csv
git commit -m "docs: record S16 Docker office-boundary verification"
git push -u origin step/s16-office-boundary
```

Do not rerun the installer or `--record` just to commit its output. Recording
verification deliberately changes those files; a second record request stops
until they are committed. Keep recovery-code downloads outside Git.

If using the already-created `accounting-client-demo`, restart it explicitly
with its retained database and existing account. The run command allows pending
S15 migrations to be applied without starting a web service on the older schema:

```bash
WEB_PORT=8003 docker compose -p accounting-client-demo build web
WEB_PORT=8003 docker compose -p accounting-client-demo run --rm --no-deps \
  --entrypoint python web manage.py migrate --noinput
WEB_PORT=8003 docker compose -p accounting-client-demo up -d --no-deps web
```

Open `http://localhost:8003/counterparties/` and use the existing regular account
and MFA. Review lists, client detail/history and owner/accountant permissions in
Greek, including keyboard operation. This manual review remains Pending until
actually recorded; automated test success does not record it for the client.

## G1 scope and remaining gates

`evidence/G1-foundation.json` records this technical foundation gate and links
its executed matrix. It never marks the 85 full requirement acceptances passed.
Public VM checks in S09/S10 and the operator-reported S14A demo remain historical
evidence; S16 performs no new live rollout or verification. An old context-pinned
S14A updater must not be reused against the retained office/account database.

Future coverage remains Pending: actual queued execution (S26), CSV/PDF/export
downloads (S30), private documents and recovery (S38–S39), portal/grants
(S43–S44), messaging and external connectors in their assigned steps. The
current financial report is scoped HTML only. The 26 financial correctness
failures, legacy generated transfer copy and malformed filter defects remain
assigned to S18–S24/S29. This office-boundary gate does not approve those totals,
real data, performance targets, a full-environment recovery or live release.

After the laptop Docker gate, the next step is **S17: financial policy**. It
requires the accountant's D08 decisions before changing posting behaviour.
