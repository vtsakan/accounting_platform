# CR-002 — Automatic initial agreement charge

Requested by the product owner on 2026-11-20 following accountant feedback:
“όταν γίνεται μια συμφωνία, θέλει η χρέωση να γίνεται αυτόματα”.

Implementation selected; source **Prepared**. Technical verification, accountant
acceptance and VM rollout remain Pending. This supplements UR-AGR-01 and the
initial occurrence of UR-BIL-03; original requirement/policy baselines and their
acceptance statuses remain unchanged.

Saving a new active agreement through either the ordinary Greek creation screen
or the service catalogue records reviewed terms and the initial charge in one
atomic transaction. ONE_OFF posts the full agreed amount once. MONTHLY posts
only the first calendar occurrence, dated at the agreement start, with the full
reviewed monthly amount or an explicitly entered first partial-month amount.
Later occurrences continue through the existing monthly schedule and its
explicit automation consent; this change does not enable automation globally.

The start must be no later than today in Athens. A blank payment deadline means
the selected start date; a supplied deadline may not precede it. Future-start
immediate posting is rejected with an explained Greek field error. No proration,
VAT or automatic historical catch-up is inferred.

The same form identity must return the same agreement and retained charge,
including concurrent requests. Changed data under that identity is rejected.
The immutable initial charge/terms snapshot binds the replay even if there is
a later amendment, correction or reversal. Fresh office/actor authority is
required before replay or posting. Any failed charge rolls back new agreement,
terms and financial audit together.

Saving terms in the edit workflow remains separate from posting: an edit must
not charge again. Existing agreements, movements, credit and allocations are
not retroactively changed. Creating an obligation must not create cash, settle
an existing receipt, issue an invoice or mark the agreement paid.

The two historical HTTP tests which required zero charges after ordinary or
catalogue creation are explicitly superseded by this request. Their cash,
scope, amount, immutable snapshot and Greek checks remain; all other historical
test bodies and all 36 financial regression cases stay intact.

Evidence: `accounting/tests_agreement_creation.py`, updated creation contracts
in `accounting/tests_agreement_charges.py` and `accounting/tests_fees.py`, and
`docs/implementation/evidence/CR002-source-lock.json`. No test execution is
claimed by source delivery.
