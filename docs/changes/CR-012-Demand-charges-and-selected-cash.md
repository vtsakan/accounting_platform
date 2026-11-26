# CR-012 — Demand charges, finite agreement budgets and selected-charge cash

Status: Prepared. Agent checks source/AST/import/call/template/SQL grammar/hash/Git/archive/secret text only. No tests, application setup, Docker, databases, migrations, browser, SSH, deployment or push executed by agent.

## Selected behaviour

- Add ON_DEMAND to reviewed agreement terms. New ordinary agreements remain terms-only. Different explicit requests may post charges on arbitrary dates, including the same date.
- ONE_OFF and ON_DEMAND have a dated finite budget equal to the agreed gross amount. All non-reversed charges consume it, including paid charges. MONTHLY keeps its per-period price and independent calendar sources.
- New income/expense agreement entry requires an explicit same-party, same-direction charge. Allocate only to that charge. **User corrected the overpayment choice:** cash200 against charge150 allocates150 and leaves50 unallocated credit; do not reject the overpayment or spend the excess elsewhere.
- Immutable initial-selection proof binds cash payload, charge, actor and completed allocation. Exact retries never allocate twice. Changed choice/payload fails.
- Precheck charge/replacement/amendment budgets, including future terms/reversals. PostgreSQL enforces the same invariant against raw writers. Known failures render Greek field/form errors and roll back the full financial operation.

## Retained source and evidence

Preserve all40 original migrations bytewise, every1855 original test method AST, all176 prior deployment contracts and all31 genuine historical receipt/binding files. Existing FIFO backend remains for historical replay and original financial contracts; new interactive entry selects a charge. Only the shared old HTTP input helper supplies that newly required choice; no old assertion or method changes.

Add0041/0042 only: billing choices and one empty immutable selection table; no financial backfill or historical selection inference. Downgrade denies removal after demand/selection history exists. All10 CR011 deployment source files remain unchanged; no VM rollout in this package.

Published CR011 completion is08ad19063de7bf47de385ffdf5f30f45738d701b, actual native result81da3bca37662779f4507ae52460aceb7610c5af, source4fb2f5d454e6f96630c1e2960c5aa65243543eed. These public identities are verified only against genuine operator history. Agent observations are not native receipts.

## Required operator gate

Full1387/1387 PG17 application contracts (1307 retained +80 new),36 finance cases,176 retained deployment guards;42 migrations and makemigrations check. Real clean/EICAR/fail-closed scanning; prior Excel, vault, direct staff first-login/reset and10 files recovered with independent material across all65 tables. Real demand500/charges200+300/cash350→selected300+credit50 and exact retry/rejected mutation proofs survive encrypted recovery. Retained real monthly worker, revocation and singleton scheduler gate.

Actual result status remains Pending until this gate succeeds and --record commits only CR012-verification.json plus an appended CR012 state section. Full85 requirements and browser/business/G2 acceptance remain Pending. Native VM40→42 publication requires a later separately reviewed rollout, preserving4GiB, current people/MFA/keys and queue.

User guide and invalid-request matrix: ../implementation/cr012_demand_charges_el.md.
