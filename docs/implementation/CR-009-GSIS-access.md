# CR-009 — Πρόσβαση GSIS και αντιγραφή αποθηκευμένων στοιχείων

Status: Prepared. Selected22/11/2026 before the pending VM update.

The product owner confirmed two controls on the CENTRAL client card as well as
the editor: GSIS for the client and GSIS for the spouse. They selected NO browser
extension after the cross-origin restriction was explained. Each control opens
the official GSIS entry in a separate window and exposes only the selected saved
pair inside the authenticated application for explicit copy/paste. Missing pair
means two blank fields. It does not fill or submit the external site's form.

Reuse the existing sealed vault and owner/active-accountant authority; add a
POST/CSRF/MFA-only same-office read with attributed value-free REVEAL audit.
No plaintext in GET/URLs/logs/storage/exports; mask password, clear the transient
panel on close/pagehide/90seconds and reject stale asynchronous results. GSIS
receives credentials only when the human pastes and submits its official form.

No migration, financial change, account/key reset or external connector API.
Keep36 old migrations,1186 original test methods/assertions and every actual
prior receipt/binding. A new source lock declares exactly six necessary old
integration changes and binds all new source. Supply24 new PG17 contracts.
Fresh production image/full1210 suite/36 finance cases, real file antivirus/
recovery and monthly worker are OPERATOR gates. Actual GSIS/window/clipboard
browser acceptance remains separate and Pending. Agent static checks only.

GitHub and VM deployment are explicitly HELD. After the new gate, a separately
bound update must deploy the NEW image while retaining the4GB test-upload choice.
All85 full requirement acceptances and D06/S38/R1/G2 remain Pending.
