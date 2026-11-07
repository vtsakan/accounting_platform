# CR-001 — Greek frontend

Change date: 2026-11-07. Originator: product owner, vtsakan. Status: **Approved by explicit user instruction**: “i need all the frontend to be in greek”. Recorded during S02.

## Controlled baseline change

This addendum extends ACC-URS-001 v0.1 without modifying the original baseline documents or their hashes. The effective baseline is **ACC-URS-001 v0.1 + CR-001**: 71 user requirements and 14 quality requirements, 85 in total. The 64 implementation steps retain their identifiers. QR-07 still covers Greek data and date/money conventions; UR-LOC-01 adds a fully Greek user experience.

| Attribute | Requirement |
| --- | --- |
| Identifier | UR-LOC-01 |
| Source | U — product owner instruction, 2026-11-07 |
| Definition status | Confirmed |
| Priority / release | Must / R1, continuing through R2 and R3 |
| Work package | WP1, cross-cutting |
| Statement | The system shall present all product-authored user-facing content in Greek across the staff application and client portal, including authentication, navigation, forms, validation, help, errors, notifications, user-visible email and generated report headings. |
| Acceptance | AT-LOC-01: inspect and exercise each implemented user journey in Greek, including success, empty, denied, invalid and failed states; an English browser preference must not switch product copy to English. Check Greek email subjects/bodies and generated PDF/structured export headings. |
| Verification method | Inspection, automated locale/message checks and user demonstration |
| Acceptance status | Pending; S02 records the requirement and does not translate the application |
| Dependencies | S04 locale configuration; each UI feature step; S31, S47, S48 and S63 release reviews |

## Interpretation

Greek applies to staff screens, the client portal, exposed administrative pages, accessible names, tooltips, confirmation dialogs, password recovery and MFA, form errors, pagination, date pickers, charts, background-job outcomes and connection failures. HTTP error pages and authentication/security errors must also be Greek without exposing private details. Product-authored email templates, file/report headings and financial status labels are included.

Keep user-entered text, client names, uploaded documents and original external records unchanged. Brand/service names (myDATA, TAXISnet, VIES), identifiers, AFMs, email addresses and technical references retain their correct spelling. Translate the surrounding explanation; never rewrite source documents or display a raw English exception as the user message. Source code identifiers, internal logs, developer documentation and machine interchange keys may remain English. Structured machine interfaces keep their documented schema; human-facing export column headings are Greek.

The application offers Greek as its supported frontend language. Supporting English or adding a language switcher later requires a recorded product change. This does not alter the meaning or acceptance status of the existing financial, access or tax requirements.

## Delivery and impact

S04 establishes `el`, UTF-8 and Europe/Athens conventions. Each later feature must include Greek copy and its failure states in the same change. R1 acceptance checks implemented office/authentication/finance journeys; R2 extends the check to collaboration and portal journeys; R3 extends it to integrations and forecasts. AT-LOC-01 remains Pending until these staged checks are evidenced. No model, schema or migration change is required by this addendum.

Implementation instructions and the copy glossary are in [frontend_language.md](../implementation/frontend_language.md). The effective machine-readable prompt allocation is [prompts.json](../implementation/prompts.json); use it with this addendum when an original baseline prompt mentions the historical 70-UR count.
