# S24A — Material-inspired Greek office workspace

The product owner selected an intermediate S24A before S25 and requested an
impressive Material-style interface. The existing Django templates and Bootstrap
CSS remain the application stack. Local color/type/shape tokens, original SVG
icons and a small native script provide the new presentation. Dependency locks,
all twenty migrations, the financial services and prior test assertions remain
unchanged. The operator's 2026-11-15 production-image execution passed **661/661
tests and all 36 financial cases**. Preserve the generated S24A verification
receipt. The local-preview helper follow-up is **Prepared** until operator use;
no agent-run tests, containers, builds, migrations, browser acceptance or VM
operations were performed. See evidence/S24A-local-preview-fix.json.

## Design and implemented behavior

- Ink-blue navigation, mint/teal primary accents, tonal cards, consistent spacing,
  outlined inputs and restrained elevation. A light/dark control follows the
  system preference until the user chooses; only that preference is stored in
  localStorage. Theme/icons use local manifest-backed static assets.
- Server-rendered navigation keeps the existing destinations and owner visibility
  conditions. Current-page indicators include nested routes. Mobile navigation
  uses a native disclosure with a labelled summary and Escape/focus enhancement;
  links and normal forms remain available when JavaScript is unavailable.
- Header search submits `q` to the existing scoped counterparty search. No remote
  search index, third-party icon/font service, new endpoint or background request.
- A new dashboard composes the existing cash-balance and operating-flow selectors.
  Month totals cover the first day of the current Greek business month through
  today. Transfers remain excluded from operating flow, while both cash legs stay
  in recent history. Corrections/refunds retain the existing signed semantics.
  The six latest rows, account balances and pending openings are office-scoped.
  Unknown opening dates stay unknown and the display never approves them.
- The shared theme covers staff lists, details, forms, alerts, office tabs,
  authentication/recovery/MFA and safe error pages. Login/logout/reset/MFA form
  names, CSRF, methods, redirects, role checks and money/date conventions remain.
  Generic Django platform admin retains its existing independent control surface.
- No invented KPI, percentage, chart or "all clear" state is shown. The design
  preview included in the package contains clearly labelled illustrative data;
  the actual application reads its existing database and selectors.

Design references: [Material color roles](https://m3.material.io/styles/color/the-color-system/)
and [Material typography](https://m3.material.io/styles/typography/applying-type).
Material-inspired styling is not a claim of component-library or accessibility
certification. Full staff/portal accessibility review remains S47.

## Files and technical scope

`accounting/static/accounting/workspace/` contains CSS, presentation-only JS and
the original SVG mark. `workspace_ui` template tags generate safe original SVG
strokes and current-route markers without querying data. The existing base,
dashboard, auth base, office tabs and key headings are updated.
`workspace_selectors.py` composes established scoped selectors; dashboard_view
delegates its read-only context to it. No new route, migration, field, service,
write action, worker or external connector is added. S25 remains separate.

The supplied five meaningful contracts check exact monthly scope/transfer
exclusion, date cutoffs, foreign-office isolation, preserved unknown openings/
read-only overview and the scoped header search/member navigation. They extend
the retained 656 tests: the target is **661 passes**, all 36 financial cases,
zero skips/errors/failures. These targets are not observed results. The prior
922-case office-boundary evidence and all original assertions are preserved.

## Operator source and verification commands

The package apply script performs Git/source operations only, creates
`step/s24a-material-ui` from the current clean S24 branch, and does not stop,
start or modify the retained local demo/VM. If using a bind-mounted development
server, source/template reloads follow its existing development behavior.

```bash
cd ~/accountant_cloud/accounting_v5/accounting-platform
bash ~/Downloads/accounting-platform-S24A/APPLY_S24A.sh
git push -u origin step/s24a-material-ui
python3 tools/verify_s24a.py --record
```

The optional verifier executes the existing production-image Docker gate once
in its disposable project, including all current tests, Greek catalog, dependency
locks, static export and secret scan. It validates the 661/36 outcome and local
theme assets, then records only S24A evidence/state/traceability. The retained
S24 receipt is never replaced. A previously completed current-commit receipt
can be read without another build:

```bash
python3 tools/verify_s24a.py --delivery private/s24a-delivery.json --record
```

After successful recording, commit the four generated documentation files once:

```bash
git add docs/implementation/evidence/S24A-verification.json \
  docs/implementation/state.md docs/implementation/steps.csv \
  docs/implementation/traceability.csv
git commit -m "docs: record S24A production-image verification"
git push
```

Do not rerun verification merely because it generated those documentation edits.
S24A verification does not publish or deploy the theme. New application bytes
need their own verified production image and reviewed release binding before a
VM update; the historical S14-to-S24 clone installer is not a S24A installer.

## View the design and local application

Open the package's `PREVIEW_S24A.html` for the standalone design preview. It
contains illustrative data and no account, database or operational actions.

To restart the retained **already-S24** local demo explicitly:

```bash
python3 tools/preview_s24a.py --port 8003
```

The helper accepts only the existing `accounting-client-demo` project, PostgreSQL
17 and the exact twenty migrations. It keeps web on loopback and the database
private, builds/restarts web with a management entrypoint that never calls migrate,
and retains existing credentials/accounts/MFA. If the local database is older,
it stops before replacing web; its separate migration/recovery scope needs review.
The VM and the currently deployed S24 remain independent of local preview.

### Local-preview authentication follow-up

The operator's production verification passed, followed by a generic local
Compose failure. The original helper did not pass the existing container's
POSTGRES_PASSWORD to psql, although the retained database requires password
authentication for local connections. The helper now exports PGPASSWORD inside
the database container and uses --no-password so SQL input cannot be mistaken
for a password response. No password is printed, copied to the host, changed or
added to Git. This corrects a confirmed source defect; the original generic
message did not identify the exact runtime failure stage.

Failures now identify the stage and exit code with an allowlisted reason such
as database_authentication_failed, port_in_use or unhealthy_or_timed_out.
Resolved Compose configuration and raw subprocess output remain private.

Inspect the existing local schema without building or replacing web:

```bash
python3 tools/preview_s24a.py --inspect --port 8003
```

This can start the already existing demo database if stopped, then performs a
SELECT of version/migration metadata. When s24_schema_matches is true, run the
normal preview command above and visit http://localhost:8003/. A successful
661-test receipt describes its disposable database; it does not upgrade the
retained accounting-client-demo database. A false schema match intentionally
stops normal preview before web replacement. Keep its accounts/MFA and retained
volume intact; use the illustrative PREVIEW_S24A.html until the local upgrade
is separately selected. Do not run old VM clone installers against that database.

The follow-up package preserves and commits only the four generated successful
S24A evidence/state/traceability files when they are the only pending changes.
It then applies operator tools/documentation only. Existing production-context
bytes and the already completed production proof remain unchanged. Do not rerun
verify_s24a.py just because these documentation/tool commits have a new Git ID;
the existing receipt remains tied to its actual tested source commit.

## Manual acceptance, still Pending

Review at 375, 768 and 1440 CSS pixels and at browser zoom 200% in both themes:
navigation/disclosure focus, Escape, search, horizontal table scroll, long Greek
office/client names, empty/pending/negative amounts, date inputs, form errors,
login/reset/MFA/recovery and a representative existing financial action. Check
the same original/charge/cash/allocation/reversal distinction before and after
that action. Confirm financial history, owner-only actions and ordinary-accountant
navigation; check the print view. Record actual browser/client evidence.

Automated tests, static-source checks or a design mockup alone do not complete
S47/WCAG, browser acceptance or all 85 product requirements. This selected scope
stops after S24A; no S25 import/reconciliation is executed here.
