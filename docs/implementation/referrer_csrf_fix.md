# S14 follow-up — form Origin and bearer-link privacy

On 2026-11-12 the operator successfully created the regular local owner
`vtsakan`, then login repeatedly failed with `Origin checking failed - null
does not match any trusted origins.` This is a response-header defect, not a
failed bootstrap, incorrect password or missing office membership.

The application applied `Referrer-Policy: no-referrer` to login, MFA, office and
join forms. Under Fetch's request-Origin algorithm, ordinary non-CORS form
submissions using that policy serialize their Origin as `null`. Django correctly
rejects that origin, including when the form has an otherwise valid CSRF token.
The problem can also affect HTTPS; it is not limited to the local HTTP demo.
Earlier HTTP/Django test clients supplied requests directly and did not model
the browser's response-policy-to-Origin behavior. The prior S14 Docker proof
therefore did not establish browser form usability.

## Correction

- Login, MFA, security, office, admin and token-free join/reset forms use
  `same-origin`. Their URLs are not sent as referrers to another origin, while
  same-origin form submissions retain their Origin and HTTPS Referer checks.
- Raw invitation and password-reset URLs keep `no-referrer`, including invalid
  links/errors. They exchange the bearer link for the existing server-side proof
  and redirect to a token-free form before any POST. The reset `set-password`
  route is explicitly a form, not a bearer URL.
- Caddy sets a `same-origin` default without overwriting the upstream header.
  Its bearer-path matcher enforces `no-referrer`, excludes `set-password`, and
  also protects bearer paths when the upstream fails.
- Private/no-store responses, exact host/origin validation, token/cookie checks,
  session/MFA protections and all office/role controls remain enabled. `null` is
  not trusted, no request Origin is rewritten, and no endpoint is CSRF-exempt.

There are no migrations, package changes, account edits or password resets.
The existing sample office/accounts remain in the same demo Compose volume.
No VM image or cloud resource was changed. Deploying the new Caddy/application
configuration remains part of the separately reviewed VM upgrade.

## Proof and limits

Nine new PostgreSQL/Django regression tests exercise actual CSRF form fields:
HTTP and HTTPS login → real TOTP enrollment → office edit → logout; invitation
redirect → token-free acceptance → owner approval over HTTP/HTTPS; HTTPS reset
redirect → token-free password change; invalid-link privacy; and rejection of
null/foreign Origin or missing/wrong tokens. This is server-side HTTP proof,
not a new browser-execution claim.

The full strict suite now has 287 tests: 261 pass plus the same 26 registered
financial failures, with no unexpected outcomes. Dependency locks, Greek catalog,
history/candidate scan, migration drift and restricted-role DDL are checked by
the existing verifier. `check_referrer_proxy.py` validates and runs the actual
Caddy rules on disposable loopback listeners, including default/secret headers
and upstream failure. See `evidence/S14-referrer-fix.json` for observed results.

Three earlier header expectations are deliberately corrected: one S13 login
form and two S14 ordinary forms now expect `same-origin`. The S14 source guard
normalizes only that one S13 assertion; all other historical authentication test
method ASTs remain unchanged, including secret reset-link privacy. Financial
assertions/calculations, original eight migrations and runtime/tools locks are
unchanged. The existing S14 Docker evidence is retained as historical proof;
the fix stays Prepared until the operator reproduces the Docker gate and actual
browser login. Do not move the existing `s14-complete` tag.

## Apply on the laptop

Start on the clean `step/s14-office-settings` branch containing the pushed S14
Docker result. Apply both commits from the follow-up patch, then restart only
the bind-mounted development web service:

```bash
git am --keep-cr ~/Downloads/accounting-platform-S14-referrer-fix/accounting-platform-S14-referrer-fix.patch
WEB_PORT=8003 docker compose -p accounting-client-demo restart web
```

Open a fresh private browser window at `http://localhost:8003/login/` and log in
with the existing `vtsakan` account. Complete MFA enrollment and save the recovery
codes. Do not repeat bootstrap, recreate the database, delete volumes or add
`null` to trusted origins. Then run the disposable Docker regression gate:

```bash
python3 tools/verify_s14.py --record
```

After a Verified result, commit its four updated implementation records and
push the branch. The earlier verification evidence is native-only for this fix;
actual local Docker/browser results remain separate. The VM demo upgrade is
still pending its current migration/image inspection.

References:
[Fetch request-Origin algorithm](https://fetch.spec.whatwg.org/#append-a-request-origin-header),
[Django: removing Referer](https://docs.djangoproject.com/en/5.2/ref/csrf/#removing-the-referer-header),
[Caddy header defaults](https://caddyserver.com/docs/caddyfile/directives/header).
