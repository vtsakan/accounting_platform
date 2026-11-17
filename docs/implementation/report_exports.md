# S30 — authenticated PDF and CSV financial exports

Status: **Prepared, source only**. S29 is operator-Verified at
2026-11-17T21:24:53+02:00: 808/808, all 36 financial cases, 360 retained
sources, four host contracts and the actual scheduler/Redis/worker/ack-loss
gate. Keep that exact receipt. Its source is
git:e40485f760d28e9149d1ed86e5f2b1f027db69d7 and image is
sha256:08367b193ad6458272e8b87bed16b994a3ddbe341cdd278f44ca3178c1a15448.
S30 implements UR-REP-04, QR-01/07 and UR-LOC-01; full acceptance stays Pending.

## Scope and source of every value

The period report, fixed-counterparty statement and annual fee overview each
have Greek PDF/CSV download links. Links preserve the validated filters and
freeze default as-of/year/month values. Pagination parameters do not restrict
an export: all rows of the displayed detail tables are included. Annual
exports include all twelve monthly summary rows and all detail pages for the
selected analysis month, exactly as labelled on the annual screen.

The export facade calls the unchanged S29 period_report or annual_report
inside an outer read_snapshot. It reads each returned paginator's original
queryset, rather than writing another financial query or recalculating debt.
The outer top-level PostgreSQL REPEATABLE READ READ ONLY transaction remains
open until totals, complete source rows and primitive presentation values
have been materialised. Nested callers retain their existing isolation, as
documented in S29. The serializers access no database.

Cash period filters, whole dated charge/credit positions and full selected-
account cash bridges remain separate labelled sections. Transfers affect
account cash but never operating income/expense. Unknown openings remain
unknown. Cancellation, reversal/refund/release dates, outside-year cohorts
and the absence of automatic credit offset all retain the S29 definitions.
Legacy unreviewed cash remains labelled and is not invented as credit.

## Download authority and lifetime

All three routes require finance.read and derive office context from live
membership. Model-choice filters and the statement route's entity remain
office-owned; foreign identifiers return 404 and invalid/duplicate filters
produce Greek errors without an attachment. POST and unknown formats fail.

PDF/CSV bytes are generated synchronously in memory. After serialization the
view rechecks live membership and the expected office before releasing headers
or bytes. There is no queued export, stored artifact, bucket object, token,
public URL, cache or anonymous download. Server-side artifact retention is
request-only: buffers are released after the response; another download
requires fresh authentication and scope checks. No expiry record or cleanup
job is needed for a stored artifact because none is created.

Responses are private/no-store attachments with Greek filenames, correct MIME,
Content-Length, nosniff and no-cache. Permission failures release no financial
attachment. Tests include real concurrent committed revocation after the money
snapshot, and another-office route/filter denial for both formats.

Exports reject scopes above 10,000 source rows for CSV or 2,000 for PDF. An
additional bound covers summary/account rows and a 16 MiB serialized-output
limit applies to both formats. The response is Greek 422, with no partial
attachment or partial totals. PDF serialization is locked per process with a
five-second wait; a busy process returns Greek 503 and Retry-After. No running
environment, worker settings or domain approval is changed.

## CSV contract

CSV is UTF-8 with BOM, semicolon-delimited, CRLF and every cell quoted using
the standard csv writer. One rectangular table contains the union of the
report's typed columns. `Ενότητα` identifies the source/summary table and
`Γραμμή` the row within that section. Empty columns belong to other sections;
`Άγνωστο` is an unknown monetary balance and must never be read as zero.

Money remains finite Decimal cents until serialization and uses Greek decimal
text, for example 1.234,56, with EUR in the column heading. Dates are DD/MM/YYYY;
months are MM/YYYY. Identifiers and AFMs have a literal apostrophe prefix to
retain text identity and leading zeroes. Untrusted text with formula-triggering
ASCII/full-width prefixes, leading whitespace or controls receives a literal
tab plus apostrophe prefix. Quotes, delimiters and line breaks remain within
one quoted cell. Exact typed negative money remains numeric text, not an
untrusted expression. UTF-8 Greek names are preserved.

Tabs/apostrophes are part of the CSV data contract for programmatic consumers.
Do not remove text protection and reopen the resulting untrusted values as
spreadsheet formulas. Spreadsheet re-save/reopen behaviour varies; no universal
cross-application reprocessing guarantee is claimed. Office/period/filter/basis
and provenance rows travel with the financial detail, so a filtered dataset
can be interpreted without guessing its scope.

## PDF, fonts and provenance

ReportLab 5.1.0 is pinned from its official PyPI release. Its new transitive
requirements are charset-normalizer 3.5.2 and Pillow 13.0.0. All 28 existing
runtime dependency versions and the maintenance lock remain unchanged.
pypdf 7.1.0 is also pinned for actual PDF text/font/structure readback in the
production-image test gate, which already ships application tests. It is not
used by the download endpoint to parse user-supplied files.

Greek/euro DejaVu Sans regular/bold fonts are shipped locally with their license
and embedded/subset in PDF. Static cmap inspection covers accented Greek and
the euro glyph. Landscape A4 tables have wrapped plain text, repeated Greek
headers and page numbers. Office, period, reporting basis and generation time
in Athens are included. User text is XML-escaped before Paragraph processing;
there is no user-authored layout, macro, image, remote asset or filesystem path.
PDF requests never fetch URLs. Actual PDF reading and visual inspection are
operator work, not an agent-rendered preview.

The immutable Provenance type is the S59 extension point. Posted S30 data has
the posted-actuals label, source as-of date and no forecast rule version. A
future estimate provider must explicitly identify itself, supply source dates
and a rule version, and receives a separate Greek estimate label in PDF/CSV.
There is no forecast request switch or estimate arithmetic in S30 cash reports.

## Delivery and verification

No model or migration is added. All 26 migrations, financial services/selectors/
forms, prior test assertions, runtime/image pins, membership/MFA and old receipts
remain unchanged. Only the old boundary URL adapter adds export route/format
arguments. The new routes join the existing finance.read boundary inventory.

APPLY_S30.sh performs Git/source/tracking only and can retain the four already
generated S29 Verified tracking files before creating step/s30-report-exports.
The optional operator command builds a fresh exact committed-context image:

```bash
export PATH="$HOME/.local/bin:$PATH"
python3 tools/verify_s30.py --record --host-dns
```

The gate requires all 808 retained tests plus 40 new export/snapshot contracts
(**848 target, unobserved**), all 36 financial cases, four host source contracts
and the unchanged real S28 broker/scheduler/generation/commit-before-ack gate.
New contracts compare screen/CSV/PDF totals, read back Greek text and embedded
Unicode fonts, exercise multiple PDF pages and all source pages, reject invalid
scope/formulas/foreign downloads, and verify real concurrent snapshot/revocation.
No assertion is waived and no expected failure is added.

Agent work is static AST/hash/route/template/font/license/dependency/text review
only. No tests, application/PDF rendering, Docker/build, migration, browser,
SSH/cloud/push or VM action. S30 remains Prepared until the full operator gate.
PDF visual/browser review, D05/G2, VM rollout and all 85 full acceptances remain
Pending. Stop after S30; S31 is separately selected.

Primary implementation references:
- https://pypi.org/project/reportlab/5.1.0/
- https://docs.reportlab.com/reportlab/userguide/ch3_fonts/
- https://docs.reportlab.com/releases/notes/whats-new-51/
- https://pypi.org/project/pypdf/7.1.0/
- https://docs.djangoproject.com/en/5.2/howto/outputting-pdf/
- https://owasp.org/www-community/attacks/CSV_Injection
