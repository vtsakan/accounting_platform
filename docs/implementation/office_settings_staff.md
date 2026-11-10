# S14 — Office settings and staff onboarding

Implements UR-OFF-02, UR-OFF-03, the current-operation policy for UR-OFF-04,
and Greek product copy under UR-LOC-01. The baseline is the actual pushed
`s13-complete` tag, `16501f4ffeafc15f7361bce1ef790e8e19031f77`. This step is
local and synthetic. See `evidence/S14-verification.json` for the observed gate;
native PostgreSQL proof is Prepared until the laptop Docker gate passes.

## Selected policy

The product owner explicitly selected **Read and post** and **Colleague accepts**
in the S14 implementation conversation on 2026-11-10. The selections and exact
capability names are recorded in `office_role_policy.json`. These resolve D01
for the operations implemented here; they do not approve later connector,
reversal, export, portal or background-job operations or full release acceptance.

| Operation in the accountant's own active office | Owner | Accountant |
| --- | --- | --- |
| Read/create/change current client and supplier records | Yes | Yes |
| Read/post current financial entries and agreement forms | Yes | Yes |
| Change office identity/contact settings | Yes | No |
| Invite, approve, deactivate or explicitly reactivate staff | Yes | No |
| Read the office staff/settings audit | Yes | No |
| Propose ownership handover | Yes | No |
| Accept an incoming handover addressed to oneself | Yes, if eligible | Yes, if eligible |
| Unknown or future capabilities | Denied | Denied |

Every business URL has a named server-side capability. Object/form/admin access
still requires S12 office ownership, and execution adapters can recheck a named
capability against fresh membership at execution. Django admin permissions are
additional checks, not an office bypass. Posted-record deletion through admin
is blocked pending the planned attributable reversal workflows. Existing money
calculations and all 26 registered financial mismatches are preserved.

## Office settings and membership lifecycle

Owners can maintain the office name, nine-digit AFM and contact email, phone,
address, city and postal code in Greek forms. AFM validation here is format
validation only; it does not claim registry verification. A hidden version
detects another owner's intervening change. Submitted office/role/admin flags
have no authority. Mutations require the actor's current password, a confirmed
authenticator verified within five minutes, a current session revision and a
fresh active membership. Management requests have the shared PostgreSQL budget
of 30 per actor and 200 per IP per fifteen minutes.

An owner creates an invitation for one normalized recipient email and one office.
An unguessable 24-hour bearer token is emailed through the explicit mail adapter;
only its keyed digest is stored in the invitation row. A valid GET exchanges the
token for a server-side session proof and redirects to a token-free form. It
does not consume the invitation or create a user. All join responses, including
denials, are private/no-store with `Referrer-Policy: no-referrer`. The application
redacts invitation paths, and the proxy keeps request URIs out of access logs.

The recipient creates a validated regular account, or proves the password of an
existing unique, active, unaffiliated regular account with the invited email.
Acceptance atomically consumes the link and creates exactly one **inactive
accountant profile**. There is no implicit login, owner role or admin flag. An
already affiliated user, ambiguous email identity, inactive user or platform
administrator is rejected. User/password/email state is rechecked after waiting
for identity locks. Concurrent accepts, including invitations from two offices
to the same email, cannot create two memberships through this workflow.

An owner must then approve the accepted application. Approval checks the
issuer's still-active owner membership/security revision and the recipient's
unchanged email/eligibility. It activates the profile and sends a captured
approval notice. Expired unaccepted links can be replaced; resend invalidates
both the former link and browser proof. Accepted applications await an explicit
approve/reject/cancel decision. These decisions and deactivation are audited.

Deactivation invalidates the member's security revision and blocks the next
protected request. A pending application cannot skip approval using Reactivate.
Explicit reactivation restores only accountant access and cannot reactivate a
globally disabled user. No interface assigns a user to another office.

## Ownership and audit

An owner proposes handover to an active regular accountant of the same office,
after password and recent MFA verification. The seven-day proposal grants no
role by itself. Only that colleague can accept, after their own password and
recent MFA verification; an accountant is guided through the existing S13 MFA
enrollment/verification flow first. The source must still be an active owner
with the original security revision. Either participant can cancel.

Acceptance promotes the recipient before demoting the source to accountant,
records both role changes and invalidates both session revisions. Repeated,
foreign, expired or stale requests cannot repeat a handover. An already-owned
active office retains at least one active owner with an active user. Both the
service and database protect that rule, including competing raw profile/user
deactivations. Existing ownerless legacy offices are not silently assigned an
invented owner. The 24-hour invitation and seven-day proposal durations are
implementation defaults, not additional policy approvals.

`OfficeAuditEvent` stores the office, authenticated actor, target account,
action, subject identifier and role/active before/after values. Initial CLI
bootstrap instead records its explicitly declared operator and target account;
it does not misattribute creation to the newly created user. Database triggers
reject audit updates/deletes, and composite foreign keys reject cross-office
workflow/audit participants. The owner sees the latest 200 events. Tokens,
passwords, factor material, message bodies and contact snapshots are absent.
This staff/settings audit does not substitute for later finance-wide audit
acceptance, external tamper evidence or an approved audit retention policy.

## Mail boundary

Local settings capture staff messages as private `staff-*.eml` files beneath
`/tmp/accounting-auth-mail` in the development container (0700 directory, 0600
files). Test settings use Django's in-memory backend. No real mail was sent.
Recovery SMTP opt-in alone does not authorize staff mail: production additionally
requires `AUTH_STAFF_MAIL_LIVE_ENABLED=true` alongside the S13 SMTP/provider,
sender and allowed HTTPS-origin configuration. Production rejects incomplete
configuration. A successful SMTP call means Submitted, not delivered/received;
the owner page labels those states in Greek. Live provider testing is Pending.
There is no worker/retry queue before S26.

Capture files contain live invitation links and are outside Git, image context,
static and public media. View them only in the local operator session; do not
paste them into an issue/chat or commit them. Empty local capture storage when
the synthetic rehearsal ends. Deactivation/role changes can invalidate a link
even if a previously submitted message is subsequently delivered.

## Schema and existing databases

`0007_office_settings_staff_workflows` adds contact/version fields, three workflow
tables and the user/office profile key. `0008_office_workflow_guards` adds the
last-owner, membership-identity and append-only-audit triggers and six same-office
workflow foreign keys. The original six migrations and dependency locks are
unchanged. Migration 0008 is reversible; no migration creates human accounts,
memberships or email. All migrations are also tested with a role that has no
superuser, create-database or create-role privilege.

Earlier S11/S12 inventory services deliberately select the fields available at
their historical migration states. Their reviewed backfill and record-identity
proofs still run. Existing test methods/assertions are preserved; only historical
schema fixtures and a second owner fixture for S13 revocation cases were adapted.
An existing database still needs its reviewed S11/S12 mappings before advancing
past the non-null ownership guard. Never supply a default office, infer a mapping,
remove a volume or rerun an old context-pinned deployment installer to bypass it.

## Verification and the first regular account

From clean, committed source on the laptop:

```bash
python3 tools/verify_s14.py --record
```

The verifier uses a random disposable Compose project/PG17 volume, reproduces
hashed locks and the Greek catalog, scans all reachable Git history/current
source, verifies baseline preservation, and runs S14 plus the entire existing
suite. Only the 26 registered financial failures are expected. Unexpected
failures/errors/passes/skips stop the gate. Native checks
do not claim Docker execution, live SMTP or VM deployment. Full requirements,
Greek accessibility acceptance and real-workload acceptance remain Pending.

The attempted native Chromium visual review could not launch because its local
socket creation was denied by the execution environment. No browser screenshots
or desktop/mobile visual pass are claimed. The PostgreSQL/Django HTTP tests
exercise the Greek forms, denials, CSRF, email copy and complete onboarding/
handover actions; visual and accessibility review remains a manual gate.

After a **Verified Docker result**, S14 is the appropriate step to create the
first regular application owner locally. Use a separate empty Compose project
to rehearse onboarding without touching the existing development volume:

```bash
# Keep the repository's existing private .env. Choose another free port if needed.
WEB_PORT=8002 docker compose -p accounting-s14-onboarding up --build -d

# Replace YOUR_EMAIL. Password input is interactive and absent from shell history.
WEB_PORT=8002 docker compose -p accounting-s14-onboarding exec web \
  python manage.py bootstrap_office_owner \
  --new-office-name 'Δοκιμαστικό λογιστικό γραφείο' \
  --username vtsakan --email 'YOUR_EMAIL' --operator vtsakan
```

Open `http://localhost:8002/login/`, log in and complete MFA enrollment. Store the
single-use recovery codes separately before continuing. This creates a regular
owner (`is_staff=False`, `is_superuser=False`); Django admin is not needed. The
command can also select an explicitly reviewed active ownerless office using
`--office UUID`; it refuses an office with an active owner, existing identities,
weak passwords and platform-admin conversion. An exact repeat is a no-op and
does not change a password. Invitations and mutually verified handover handle
subsequent staff/owner changes. Keep business data synthetic until release gates.

For a local invitation rehearsal, read the newest captured message **locally**:

```bash
WEB_PORT=8002 docker compose -p accounting-s14-onboarding exec web python -c \
  'from pathlib import Path; from email import policy; from email.parser import BytesParser; p=max(Path("/tmp/accounting-auth-mail").glob("staff-*.eml"), key=lambda p:p.stat().st_mtime); print(BytesParser(policy=policy.default).parsebytes(p.read_bytes()).get_body(preferencelist=("plain",)).get_content())'
```

Use a separate browser session for the recipient, then return to the owner's
Staff page to approve. Capture is local only; the address need not receive mail.

The current Google Cloud preview remains on its verified S09 application image
and S10 recovery binding. **Do not run the above bootstrap on that old VM image.**
Deploying S11–S14 needs a separately reviewed release/image, the ownership
migration rehearsal and a backup/recovery plan covering the new auth state.
No VM recreation or additional cloud purchase is needed for S14. S15 is the
next implementation step after the local Docker gate; S16 expands integrated
office-boundary coverage.

Database references: [PostgreSQL function volatility](https://www.postgresql.org/docs/17/xfunc-volatility.html)
and [transaction advisory locks](https://www.postgresql.org/docs/17/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS).
