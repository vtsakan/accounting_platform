# Module map

S01 source inventory on 2026-11-07. Existing means present in source, not accepted as correct.

| Area | Source state | Responsibility | Planned steps |
|---|---|---|---|
| core | Existing | Settings, root URL routing, ASGI/WSGI entry points | S04 S07 S09 |
| accounting models | Existing | Entity, CashAccount, Category, Agreement, Transaction | S11 to S30 |
| accounting forms and views | Existing | 5 forms, 2 custom field/widget classes, 15 staff views | S12 to S30 |
| accounting templates | Existing | 17 templates; Bootstrap 5.3.3 from CDN | S15 S29 S34 S47 |
| accounting admin | Existing | All 5 models registered; no office scoping or posting protection | S12 S14 S18 |
| offices | Absent | Office, mandatory accountant profile, membership and role checks | S11 to S16 |
| finance services and allocations | Absent | Explicit charges, allocations, credit and attributable reversals | S17 to S30 |
| work | Absent | Tasks, recurrence, calendar, reminders and task billing | S34 to S37 |
| documents | Absent | Private files, versions, quarantine, matching and sharing | S38 to S40 S44 |
| communications | Absent | Templates, office SMTP, outbox and submission history | S41 S42 |
| portal | Absent | Verified client identity, file exchange, requests and grants | S43 to S48 S54 S59 |
| integrations | Absent | Authorised adapters, encrypted connections and retrieval jobs | S49 to S54 S60 to S62 |
| forecasting | Absent | Approved tax-year rules, reviewable estimates and snapshots | S55 to S59 |
| deploy and operations | Incomplete | Legacy Compose has db only; VM/HTTPS/backup stack is planned | S07 to S10 S31 S48 S63 S64 |

Keep existing accounting models and migration/table identities while adding the new office and service boundaries. The original development note in `The Development Plan.txt` is historical; its implemented marker is not an acceptance record.
