# CR-004 — Consolidated counterparty card, notes and calendar

Selected by the product owner on 2026-11-21 after accountant feedback. Improve
the client/supplier card with an overview of agreements and payments, coloured
entries, attributable notes and a complete client journal. Source Prepared;
new operator execution and Greek accountant/browser acceptance remain Pending.

1. Show counts of agreements and notes, actual cash inflows/outflows and the
   existing separate receivable/payable charge, allocation, debt and credit
   projections. Never sum agreements, charges and payments into one balance.
2. Green identifies receivable agreements and incoming cash; red identifies
   payable agreements and outgoing cash; blue identifies notes. Classify each
   financial entry by its own direction, including parties with both roles.
   Keep a visible type/direction label so colour is not the only distinction.
3. An authorised accountant may add a plain-text note of 1–5,000 characters to
   an active same-office client or supplier. Capture server time and the actual
   accountant automatically. Snapshot the username so a later rename does not
   rewrite authorship. Submitted office, actor, date and label are not authority.
4. Repeated submission with the same key and payload returns the original note.
   Changed payloads under one key are denied; concurrent duplicates create one
   record. Revocation and archival serialize with creation and are checked fresh.
5. Retain notes and their original text/time/actor. A new note supplies any later
   correction; no note edit/delete endpoint is introduced. SQL row guards and
   same-office foreign keys also protect direct ORM/bulk/SQL writes. Archived
   cards retain their journal and notes; restore before new work.
6. Supply one complete, paginated chronological list and a navigable monthly
   calendar with daily counts and day selection. Include agreement versions,
   charges, cash entries, allocations, releases, charge reversals and every note.
   Keep originals and corrections visible separately; no retrospective entries
   or financial effects are created by viewing the journal or adding a note.
7. Filter by date range, record kind, direction and literal text search. The
   monthly grid and result list use the same filters and database snapshot.
   All-page counts come from SQL, not the current page; no silent first-N cap.
   Note days and displayed times use Europe/Athens. Financial business dates
   remain distinct from their recorded timestamp.
8. Scope every journal arm, choice, read and write to the authenticated office
   and selected party. Foreign identifiers return 404; revoked/missing staff
   and missing CSRF are denied. Render note content with HTML escaping and
   suppress caching of private card/journal pages.

This change covers the selected notes portion of UR-CRM-04 and supports
UR-CRM-03/07, UR-CSH-06, UR-AGR-03, UR-OFF-05, UR-LOC-01 and QR-01/03. It does
not implement the other CRM labels/activities/relations or select S32. All 85
full requirement acceptance statuses remain Pending. Preserve all 26 existing
migrations, old financial services, historical receipts and every old assertion.
The boundary URL fixture gains two new routes. Ordinary setup hooks restore the discovered test schema; explicit historical migration targets and all financial assertions remain unchanged.
