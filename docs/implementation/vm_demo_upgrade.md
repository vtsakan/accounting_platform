# S14A — Local and VM client demonstration

The selected follow-up is a synthetic demonstration of the completed S14
workflows on the existing `accounting-preview` VM. It does not implement S15.
The operator reported the corrected S14 Docker gate on 2026-11-12: 287 tests,
261 passes, the same 26 known financial failures and no unexpected outcomes.
The local owner has also logged in successfully. The new deployment tools have
native PostgreSQL proof in `evidence/S14A-demo-preparation.json`; their Docker,
registry, VM, recovery and browser execution remains Pending until run below.

## Local office and colleague

Reuse `accounting-client-demo` at `http://localhost:8003/login/` and the existing
regular owner `vtsakan`. Do not bootstrap it again or reset its volume/password.
Complete MFA if needed. Recovery downloads belong outside Git, with mode 600.
The existing owner's private recovery file has already been moved there.

To demonstrate several accountants in one office, use **Συνεργάτες** while
logged in as the owner. Invite a synthetic address such as
`demo.accountant@example.invalid`, using the owner's password and recent MFA.
Local messages are captured; no live email is sent. Read the newest invitation
in your own terminal:

```bash
WEB_PORT=8003 docker compose -p accounting-client-demo exec web python -c \
  'from pathlib import Path; from email import policy; from email.parser import BytesParser; p=max(Path("/tmp/accounting-auth-mail").glob("staff-*.eml"), key=lambda p:p.stat().st_mtime); print(BytesParser(policy=policy.default).parsebytes(p.read_bytes()).get_body(preferencelist=("plain",)).get_content())'
```

Open that private link in another browser profile, create `demo_accountant`,
then return as the owner and approve the application in **Συνεργάτες**.
The accountant belongs to that office only. It can read/post the current office
business workflows; office/staff management remains restricted to the owner.
Use synthetic client and financial data. The 26 known financial failures are
still present; this is an onboarding demonstration, not financial acceptance.

## VM scope and database preservation

| Item | Selected value / behavior |
| --- | --- |
| Project / VM / zone | `accounting-514109` / `accounting-preview` / `europe-west1-b` |
| HTTPS address | `https://totalaccounting.duckdns.org` |
| Existing source | S09 pinned image, accounting migrations 0001/0002 |
| Allowed source contents | No users, exactly the two canonical S09 sample records, no contact data/private media |
| New demo database | A separately named `accounting_demo_<random>` database in the existing PostgreSQL 17 instance |
| Ownership | An explicit plan assigns those two record IDs to one new sample office UUID |
| Original database | Retained unchanged; never dropped or migrated by these tools |
| Cloud resources / identity | Existing VM, disk, hostname, service account, secret versions, registry and buckets |
| Backup | Same public age recipient, bucket, retention and monitoring; binding updated to the new database/image |
| Decryption key | Stays on the laptop; separately recovered copy proves off-VM recovery |
| Accounts | Created interactively only after deployment and recovery proof; regular application flags, not Django admin |

Additional records, users, changed images, nonzero cash, contact details or private
media stop the plan. Do not edit the checks to force a different inventory through
this narrow procedure. That case needs its own reviewed migration mapping.

The upgrade stops web/proxy briefly while it clones/migrates and checks the new
deployment. It pauses the two existing timers without killing an in-progress
backup. A host-side hold prevents boot-time preview/backup/monitor actions during
an unfinished cutover. Docker and PostgreSQL remain available for recovery.
The source database must have no active sessions when cloned; a conflicting
session stops the attempt rather than being forcibly terminated. See the
[PostgreSQL 17 CREATE DATABASE contract](https://www.postgresql.org/docs/17/sql-createdatabase.html).

## Apply the patch and prepare a tested image

Use the accompanying `START_HERE.txt`. Commit the four generated S14 verification
documents first if they are still modified; do not add MFA downloads, private
configuration or credentials. Apply the patch on top of the corrected S14 branch.
The patch leaves the canonical S14 evidence/state rows and the existing completion
tag intact. It appends this S14A preparation separately.

Run from clean committed source on the laptop:

```bash
python3 tools/verify_delivery.py --report private/demo-delivery.json
python3 tools/demo_release.py configure --operator vtsakan
python3 tools/demo_release.py publish
python3 tools/demo_release.py plan
```

The delivery gate runs the production image and full suite on Docker/PostgreSQL,
including the delegated admin-login route and manifest-backed admin template.
Only the same 26 registered financial failures are accepted. It also checks
Gunicorn, health/readiness failure/recovery, the Greek catalog and static files.
Historical S07 checks keep their historical login expectations.

`configure` reads the actual installed VM deployment and local S10 recovery
binding, then writes ignored `private/demo-release.json`. It is intentionally
create-once. `publish` requires delivery evidence for that exact committed image.
`plan` stages and checks the pinned image/static files and source archive, then
prints the actual source/target database, office UUID, two record assignments
and `plan_sha256`. Staging does not restart services or change business records.
Keep the repository clean between testing, publication and planning; any code
change needs a new image delivery check.

## Review and deploy the concrete plan

Check that the plan identifies the expected VM, sample office and exactly two
known marker assignments, with `source_users: 0`. Use the hash printed by that
plan, including `sha256:`; do not copy a hash from another run:

```bash
python3 tools/demo_release.py apply --plan-sha256 'PASTE_PRINTED_PLAN_SHA256'
python3 tools/demo_release.py status
```

The root apply rechecks the source snapshot, recovery binding, bundle and pinned
image before pausing timers. It creates an encrypted pre-change backup, clones
the source database, applies 0003/0004 to the clone, creates the reviewed office
at that historical schema state, and dry-runs/applies the exact two-record
mapping before the non-null ownership guard. It then applies the remaining
migrations through 0008 using the restricted application role.

The operator database role creates the database; application migrations do not
receive superuser, create-database or create-role rights. Original IDs/values and
the untouched source snapshot are compared before cutover. The new application
starts from the digest-pinned image, with private app/database ports, secure
production settings and the existing metadata firewall. A new encrypted backup
and monitor sample must succeed before timers resume. The result remains
`awaiting_off_vm_restore`; no human account is created by apply.

Canonical host configuration is rebound to the demo image/database together.
The laptop's original `private/preview.json` and `private/operations.json` stay
available for the old release; new recovery configuration is written to
`private/demo-operations.json`. Do not use the old `preview.py ship` or
`operations.py install/status/restore` flow for the new demo binding. Use this
runbook, `demo_release.py status/restore`, or inspect the installed host operation
wrapper directly. Existing encrypted backups retain their original identity.

## Prove recovery, then create the VM owner

Run in the laptop terminal, not Cloud Shell. Supply the separately recovered key
already used successfully for S10. Do not paste the key or invitations into chat:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/demo_release.py restore \
  --identity "$HOME/.config/totalaccounting/recovered-backup-age.key"
```

The restore downloads the exact new backup, decrypts outside the VM, and uses
an isolated local PostgreSQL Docker container with no network, ports or persistent
mounts. All public tables/rows must match; plaintext and the container are removed.
Public HTTPS readiness, trusted hostname/certificate and Greek login/form checks
must also pass. A same-origin POST is exercised with synthetic invalid credentials;
null/foreign origins and a missing CSRF token must be denied. A receipt-bound
operator attestation then changes the host phase to `demo_ready`.

Now create the owner interactively. Choose a VM password; the local database,
password, MFA enrollment and recovery codes are separate:

```bash
python3 tools/demo_release.py bootstrap \
  --username vtsakan --email 'YOUR_EMAIL'
```

Open `https://totalaccounting.duckdns.org/login/`, sign in, enroll a separately
labelled authenticator entry, and save its recovery download outside Git. This
uses `bootstrap_office_owner --office <reviewed UUID>` inside the new image.
It creates no staff/superuser privileges, and an exact repeat does not reset the
password. The remaining browser acceptance is actual owner login, MFA and Greek
office/staff forms; report those outcomes separately from machine checks.

## Optional VM accountant without live SMTP

The running preview deliberately keeps mail disabled. Use the bounded operator
capture helper from the laptop terminal after the owner's MFA enrollment:

```bash
python3 tools/demo_release.py invite \
  --username vtsakan --email demo.accountant@example.invalid
```

The helper proves the active owner's actual password and a fresh, unused TOTP.
It uses the existing invitation service and PostgreSQL rate limits. Capture is
limited to this one process, the temporary message is removed, and no live email
is sent. The private link is displayed only in the authenticated operator's
terminal. Use it in a separate browser session, create `demo_accountant`, then
approve from the owner's **Συνεργάτες** page. No member is created or automatically
approved by this helper. Share an account/link with a client only through your
own intended private channel; never publish it in Git or an issue.

## Failure, retry and rollback

Use `python3 tools/demo_release.py status` first after a failure. Keep private
JSON reports outside commits. A failed apply after the hold attempts to restart
the original deployment and backup binding without deleting either database.
Explicit rollback before demo accounts exist is:

```bash
python3 tools/demo_release.py rollback
```

Rollback refuses to hide a demo database that already contains user accounts.
It stops before changing services in that case; preserve the work and review
recovery separately. An incomplete recovery retains the root journal
`/etc/accounting/demo-release-state.json` and boot hold rather than declaring
success. A failed clone is retained; repeated apply never overwrites an existing
database. Inspect it and make a separately named reviewed plan instead.
Do not drop databases/volumes, reformat the disk, reset keys or bypass S12 guards.

This is a synthetic database demo. Full document/environment recovery, actual
certificate renewal, accepted workload RPO/RTO, accessibility and all 85 full
UR/QR acceptances remain Pending. The retained old database is rollback material,
not a substitute for encrypted off-VM backups. S15 is unchanged and remains the
next implementation step after this selected demonstration follow-up.
