# S04 — settings, secrets and Greek locale

Implemented 2026-11-07 on pushed S03 commit `1c296bbbd2a1aa3e642b1982a8d0b8dd2cfb7718`. S03 had not yet been merged to `main` at the baseline check. The runtime lock, business models and both accounting migrations are unchanged.

## Settings profiles

| Module | Source and behaviour |
| --- | --- |
| `core.settings.base` | Shared auth.User, middleware, template paths, Greek formats and redacted logging |
| `core.settings.local` | Process environment plus local `.env`; manage.py default; optional debug and in-memory email |
| `core.settings.test` | Explicit environment; never reads `.env`; debug off and PostgreSQL backend; focused tests use no database |
| `core.settings.production` | Injected environment or mounted secret files; never reads `.env`; required configuration and secure cookies |

WSGI and ASGI default to production and reject missing configuration. An explicit `DJANGO_SETTINGS_MODULE` can select another profile for development. The existing authentication model and database identities are retained.

## Local configuration

After installing the runtime lock:

```bash
python3 tools/init_local_env.py
.venv/bin/python manage.py check
```

The generator creates `.env` once with random local signing/database credentials and mode 0600. It never overwrites or prints credentials. S05 supplies PostgreSQL and startup commands; the old Compose file still describes the original PostgreSQL 15 setup.

Only local settings read `.env`; `DJANGO_ENV_FILE` selects another local file. Uppercase `KEY=value`, quoted values and comments are supported. Shell expressions and variable interpolation are never evaluated. Process environment wins; duplicate assignments and invalid quoting fail. Without a configured local signing key, an ephemeral process key permits checks but invalidates sessions after restart. Use the generated `.env` for stable local sessions.

## Production contract

Required: `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`. `DB_PORT` defaults to 5432 and is range-checked. The signing key must be strong and generated. Hosts are explicit names/IPs without wildcards or schemes; CSRF origins must be HTTPS origins matching allowed hosts.

Provide either a direct value or its `_FILE` variable, never both. For example, `DJANGO_SECRET_KEY_FILE` and `DB_PASSWORD_FILE` read mounted UTF-8 single-line secrets, allowing a trailing newline. Missing, conflicting or unreadable values fail with variable names rather than contents or file paths.

At S08/S09 the deployment layer will resolve pinned Secret Manager version references using the VM identity and mount restricted runtime files. This is the prepared Django consumption interface; S04 does not call Google APIs or provision secrets. Real values and version references belong to private deployment configuration. Environment injection also remains supported.

Production enables HTTPS redirects, secure session/CSRF cookies, HttpOnly sessions and frame denial. Proxy trust is off by default. Enable `DJANGO_TRUST_PROXY_HEADERS=true` only after verifying that Caddy overwrites `X-Forwarded-Proto` and Gunicorn is private. TLS, renewal, proxy isolation and final HSTS policy remain S07–S09 checks. Initial HSTS is one hour without preload or automatic subdomain coverage.

## Logs and error pages

Configured handlers use a formatter that masks registered/configured secrets, encoded variants, credential assignments, authentication/cookie headers and URL credentials, including exception messages. The exception-report filter masks sensitive settings and POST fields. Greek 400/403/404/500 pages and CSRF failures omit internal exception details and tokens.

Do not log private request bodies or credentials. Future handlers must use the formatter and integrations must register secrets through the configuration interface. Source scanning remains heuristic; see [the scan policy](../security/README.md).

## Greek presentation

`el` is the sole frontend language, including with English browser preferences or language cookies. LocaleMiddleware follows session middleware. Display timezone is Europe/Athens; instants are timezone-aware and dates display as `DD/MM/YYYY`. Native HTML date controls retain ISO exchange values to preserve valid submissions.

All 17 existing staff templates and their form labels use Greek. A project catalog translates retained choice labels at the presentation boundary, preserving database codes and model definitions. Admin branding/form labels are Greek; complete authenticated admin and permission workflows are reviewed in S12/S13. Portal, email/export and later module copy are checked as those features arrive. Full AT-LOC-01 acceptance remains Pending.

`core.locale` parses `1.234,56` as Decimal. Money inputs use text controls with decimal input hints. Ambiguous dot decimals, floats, non-finite amounts and excess precision are rejected. Display helpers never silently round additional fractional value. Tax and billing rounding policies remain D04/D08 decisions.

The wall-time helper rejects the missing spring hour and requires an explicit occurrence during the repeated autumn hour. Tests cover both 2026 Athens transitions and UTC/local round trips. PostgreSQL persistence and posting checks remain S05 onward.

## Verification and catalogs

```bash
python3 tools/verify_s04.py
```

The verifier creates isolated environments, checks both hashed locks and the compiled Greek catalog, runs focused Django tests, verifies unchanged model/migration state and scans candidate/history text for secrets. It needs package/Python-download access, with no PostgreSQL or VM. Earlier verifiers target their recorded snapshots.

Catalog maintenance uses the tooling environment:

```bash
.venv-tools/bin/python tools/compile_translations.py
.venv-tools/bin/python tools/compile_translations.py --check
```

Commit reviewed `.po` and compiled `.mo` together. `polib==1.2.0` is added only to the hashed maintenance lock; runtime remains seven packages. Full browser/accessibility reviews, live authentication journeys and PostgreSQL tests remain their planned steps.

## Official references reviewed

- [Django settings](https://docs.djangoproject.com/en/5.2/topics/settings/) and [deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
- [Translation](https://docs.djangoproject.com/en/5.2/topics/i18n/translation/), [format localization](https://docs.djangoproject.com/en/5.2/topics/i18n/formatting/) and [timezones](https://docs.djangoproject.com/en/5.2/topics/i18n/timezones/).
- [Error reporting](https://docs.djangoproject.com/en/5.2/howto/error-reporting/), [Python ZoneInfo](https://docs.python.org/3.12/library/zoneinfo.html) and [polib compilation](https://polib.readthedocs.io/en/latest/quickstart.html).
