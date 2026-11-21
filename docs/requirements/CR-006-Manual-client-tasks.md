# CR006 — Manual client tasks from retained notes

Selected 2026-11-21 by the product owner. Supports UR-TSK-01/02 and UR-CRM-04
within the selected feedback scope; does not complete every S34/S35/S36/S37
requirement or change the85 frozen baseline acceptance statuses.

1. Create a free-text note and optionally one linked task atomically. A task
   has server creation time/creator, required date deadline and one assignee.
2. Default assignee is self; any active member of the same office may be chosen.
   Foreign, revoked or inactive assignees cannot be supplied through POST/SQL.
3. Existing notes may become tasks without changing any original note field.
   There is at most one task per source note. Task text may evolve separately.
4. Home/personal workspace shows only assigned open tasks, oldest overdue first,
   followed by today/future, with Athens calendar-day counters. Completed tasks
   remain available through status filters and the client card/history.
5. Only an active office owner has the explicit all-office workspace. Same-office
   client cards retain all client tasks alongside agreements and notes.
6. Creator, current assignee or owner may edit/reassign/complete/reopen, with
   fresh authority after locks, optimistic versions, CSRF and immutable history.
7. Record-only and record+task submissions bind nonce/actor/intent. Repeat
   submissions and conversion/status races produce no duplicate or old effects.
8. Open tasks prevent client archive in service and SQL; complete tasks first.
   Archived clients retain closed history; restore before new edits/reopening.
9. No task action posts charges, receipts or allocations. Existing accounts,
   MFA, money, migration identities and historical receipts are preserved.
10. Greek screens, labels, validation and accessible non-colour state labels.

Delivery is Prepared until the operator's isolated PG17/current-image full
suite and retained real-worker gate. Agent uses static checks only. Current
VM/GitHub remain the actual Verified CR005 until a separate later rollout.
