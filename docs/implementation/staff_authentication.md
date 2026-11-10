# S13 — staff authentication, recovery and privileged MFA

Selected against operator-Verified `s12-complete`
(`13ef2a1c8c96984da88c4cf73e695d128023555b`). Requirements: UR-OFF-06 /
AT-OFF-06, UR-OFF-07 / AT-OFF-07, QR-02 / QT-02 and UR-LOC-01 / AT-LOC-01.
Implementation evidence is `evidence/S13-verification.json`; native PG17 proof
is Prepared until the laptop's disposable Docker gate passes. All 85 full
requirement acceptances remain Pending. S14 onboarding/capabilities and S16
integrated isolation remain separate gates. No live account, mail, VM change,
production image publication or production migration is made by this step.

## Delivered behavior

`/login/` uses Django's authentication/password hashing. An ordinary active
accountant needs its active profile and office; each business request rechecks
them using S12. Inactive/unassigned/incorrect credentials receive the same Greek
message. A platform superuser with `is_staff` can authenticate without an office
to manage the platform, but still cannot access office records without explicit
membership. An office owner does not gain Django admin authority. Global user/
group admin and its shared autocomplete/app routes are limited to superusers.
`/admin/login/` redirects to the canonical login, including for POST.

Owners, staff/platform administrators and anybody who has enrolled MFA must
verify a confirmed authenticator before business or admin access. Ordinary
accountants may opt in; future logins then require MFA. The password session is
limited to setup/challenge/recovery until verification succeeds. Auth routes
are Greek, private/no-store and no-referrer; POST operations require CSRF.
Foreign `next` URLs are rejected. Logout is POST-only and destroys the session.

| Rule | S13 implementation default |
| --- | --- |
| Idle / absolute session | 30 minutes / 8 hours, checked on the server |
| Cookie | Browser-session, HttpOnly, SameSite Lax; Secure in production |
| Pending MFA / recovery setup permit | 10 minutes |
| Recent MFA for replacement / backup regeneration | 5 minutes plus password recheck |
| Authenticator | Six-digit TOTP, 30-second step, one adjacent step of clock tolerance |
| Recovery codes | Eight independent 128-bit random values; each single use |
| Password reset | Django token, one-hour expiry, one successful use, no automatic login |
| Shared rate window | 15 minutes; sign-in 10/identity, 100/source IP; reset 3/50; MFA 20/200; management 10/100 |

Limits are provisional security defaults, not domain-policy approval. Attempts
reserve PostgreSQL rows before authentication and across workers. Rows retain
HMAC identifiers, not raw usernames/emails/IPs. Per-device exponential throttling
is also enabled. Only REMOTE_ADDR is trusted; forged X-Forwarded-For cannot change
the budget. Behind the current Caddy bridge, users share a conservative proxy-IP
budget. Trusted client-IP propagation needs separate review before adjusting
those limits. Run `manage.py prune_auth_attempts` periodically through the
operator to delete expired budgets and unconfirmed setup devices; no S26 worker
or scheduler is added here. Expired budgets otherwise remain bounded per source
and inactive; pruning still matters to long-term storage.

## MFA enrolment, replacement and recovery

1. Password sign-in creates a bounded session and rotates its key/CSRF token.
2. First setup requires a password recheck. A private, session-bound QR is
   generated locally; there is no third-party QR service or seed URL in logs.
3. The first valid code confirms the device, rotates the session again, revokes
   other sessions and shows eight recovery codes in that response only. Save
   them independently of the authenticator. Refresh/GET never retrieves them.
4. Replacing a device requires the password plus MFA verified in the last five
   minutes, or a valid backup-code recovery permit. Password-only replacement
   of an enrolled factor is denied.
5. A backup code is consumed atomically. It revokes the old device and other
   sessions, and grants only a ten-minute re-enrolment permit. Business/admin
   access remains blocked until a new authenticator is confirmed. A different
   remaining code can resume a lost recovery session.
6. Successful replacement issues new backup codes and invalidates all old ones.
   Backup-code regeneration requires password plus recent MFA and invalidates
   other sessions. There is no self-service MFA-disable endpoint.

The custom `django-otp` Device stores its 20-byte seed with authenticated Fernet
encryption. HKDF-SHA256 derives a per-device key from the existing strong Django
signing secret, a random salt and user-bound context. The secret remains outside
the database in the established secret-management boundary. Backup codes are
stored only as keyed HMAC digests. TOTP use, recovery and enrolment are serialized
with user/device row locks; parallel requests cannot reuse a code or activate two
first devices. Session revisions prevent stale password/MFA sessions from being
promoted after a concurrent replacement/reset.

Keep the relevant Django signing-secret version available through controlled
recovery: a database dump alone cannot decrypt the seeds. MultiFernet supports
Django `SECRET_KEY_FALLBACKS`, with a decryption test, but the current deployment
adapter does not provision a fallback list or automate re-encryption. Plan and
test any signing-key rotation before changing the pinned secret version.
Losing both the device and all recovery codes has no password-only shortcut.
An operator must independently verify the actor and office ownership, obtain
the responsible owner's review, preserve an audit record and invalidate all
sessions before a controlled factor reset. That exceptional operator workflow
is not exposed as an application endpoint in S13.

## Password recovery and controlled mail

Request, acknowledgement, token confirmation and completion screens use Django
auth components with Greek copy. Only a unique eligible active account with a
usable password receives a link; ambiguous shared emails receive the same
acknowledgement without a link. S14 must resolve such addresses at onboarding.
Links use an explicit configured origin, never the incoming Host header. The
token is checked again under the user lock when saving, so simultaneous use
cannot set two passwords. Password reset keeps the MFA requirement, confirmed
device and unused recovery codes, invalidates existing sessions and requires a
new sign-in. Email acknowledgement does not assert successful delivery.

Development captures MIME messages in `/tmp/accounting-auth-mail` inside the
web container: directory 0700, files 0600, never console output. Copy only a
selected synthetic message into ignored private storage if inspecting it:

```bash
mkdir -p private/auth-mail
chmod 700 private/auth-mail
docker compose exec -T web sh -c 'ls /tmp/accounting-auth-mail/*.eml'
# Substitute the selected filename; recovery tokens are private.
docker compose cp web:/tmp/accounting-auth-mail/recovery-SELECTED.eml private/auth-mail/
chmod 600 private/auth-mail/*.eml
```

The Compose origin follows `WEB_PORT` (including the user's existing port
choice). Native local development may override AUTH_PUBLIC_ORIGIN to an allowed
HTTP/HTTPS origin. Test mail is in-memory and never contacts SMTP. `.eml` is
excluded from Git/build contexts; the production allowlist explicitly includes
only the two authored reset `.txt` templates, not captured messages.

Production defaults to `AUTH_MAIL_MODE=disabled`. To enable the prepared Django
SMTP adapter in a later authorised deployment, review a real sender/provider
and configure `AUTH_MAIL_MODE=smtp`, `AUTH_MAIL_LIVE_ENABLED=true`, EMAIL_HOST,
EMAIL_PORT (default 587), EMAIL_HOST_USER, EMAIL_HOST_PASSWORD through the
existing secret-file interface, DEFAULT_FROM_EMAIL, and an allowed HTTPS
AUTH_PUBLIC_ORIGIN. STARTTLS and a ten-second timeout are enforced. Production
rejects capture/test modes, missing opt-in and foreign/non-HTTPS origins. It
does not enable an unrequested live send. Provider failures emit only the
exception class, never addresses, tokens, message bodies or provider text.
Reset-token paths and recovery form fields are redacted at error/log boundaries.
The text scanner retains full history coverage. Its exact-fingerprint reviewed
exceptions include the public S12 base commit and a historical scanner-provenance
sentence flagged by the keyword detector; no detector or history scope is disabled.
Delivery timing is not an account-enumeration guarantee; asynchronous mail is
future S26 work. No real provider/send/receipt or delivery retry is claimed here.

## Schema, verification and handoff

Migration `0006_staff_authentication` adds four auth tables only. The original
five migrations, office/business model definitions, financial calculations,
regression registry and financial assertions remain unchanged. Earlier tests
now initialize explicit security fixtures; privileged fixtures verify the real
MFA view. Historical 0003/0004 migration rehearsals omit only middleware whose
tables did not yet exist, preserve the S12 office gate, and restore the latest
schema after each rehearsal. No runtime test bypass exists.

```bash
python3 tools/verify_s13.py --record
```

Run from committed source on the laptop with local Docker Engine/Compose. The
verifier owns a random Compose project and temporary PostgreSQL 17 volume and
never opens the existing development database or VM. It tests authentication,
encrypted secrets, recovery, session revocation/timeouts, CSRF, shared budgets,
real competing PostgreSQL transactions and the whole previous suite. Only 26
registered financial mismatches may remain; unexpected errors/passes/skips fail.
Native proof additionally applies all migrations as a role without superuser,
create-database or create-role privileges. Native mode remains Prepared.

After a successful Docker result, commit its evidence/state, push this step and
tag `s13-complete`. Do not tag completion from the prepared native result. S14
then supplies office settings, invitations and the regular account onboarding;
do not create a Django administrator as a substitute. Existing-database review
at S11/S12, live SMTP, signing-key rotation, integrated Greek accessibility and
full security/requirement acceptance remain explicit manual gates. Keep the
current verified VM image/backup binding unchanged: deployment of S11–S13 needs
a separately verified image, reviewed ownership migration and updated recovery
binding, not the old context-pinned S09/S10 install command.

References: [Django authentication views](https://docs.djangoproject.com/en/5.2/topics/auth/default/),
[django-otp custom devices](https://django-otp-official.readthedocs.io/en/stable/extend.html),
[Fernet](https://cryptography.io/en/latest/fernet/),
[HKDF](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/#hkdf).

## Docker profile-test environment correction — 2026-11-10

The first operator Docker run executed 216 tests with six unexpected
configuration-test failures and the same 26 registered financial failures.
Compose sets AUTH_PUBLIC_ORIGIN to the development HTTP origin (localhost:0 in
the verifier). The profile-test helper removed inherited DJANGO_/DB_ settings,
but inherited that new AUTH_ setting into its isolated production subprocess.
Production correctly rejected it against the synthetic HTTPS host. All six
reported failures were independently reproduced with that inherited value.

The helper now removes inherited AUTH_/EMAIL_/DEFAULT_FROM_EMAIL settings as
well, then applies the test's explicit configuration. This also prevents
parent-process SMTP credentials from entering a profile probe. Explicit valid
HTTPS overrides are retained; explicit HTTP/foreign origins still fail.
Production settings, origin validation, auth services, migrations and dependency
locks are unchanged. The source guard checks the complete original configuration
test AST after normalising only that exact environment-prefix change; every
original assertion is retained. Two new regression cases cover inheritance and
explicit origin controls, for 61 S13 tests / 218 total.

See evidence/S13-environment-fix.json and the current S13-verification.json.
The native full-suite retry deliberately inherits the Compose localhost:0
origin. Actual Docker retry remains required before S13 is Verified. The
PermissionDenied messages from deliberate MFA race/denial cases are expected;
the six failing assertions were configuration-profile checks. Apply the follow-up
patch on the existing S13 branch, then rerun tools/verify_s13.py --record.
