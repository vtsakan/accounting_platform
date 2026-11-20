"""Scoped agreement choices and capacity reused from the retained PG guards."""
from django.db import connection
from django.db.models import F

from .agreement_selectors import agreement_rows
from .models import Agreement
from .office_access import records


def receipt_agreements(user, direction):
    kind = 'RECEIVABLE' if direction == 'INCOME' else 'PAYABLE'
    role = 'entity__is_customer' if direction == 'INCOME' else 'entity__is_supplier'
    rows = records(Agreement, user).filter(agreement_type=kind, status='ACTIVE',
        entity__is_archived=False, **{role: True})
    return agreement_rows(rows).annotate(remaining_balance=F('remaining_obligation')).order_by('description', 'pk')


def settlement_capacity(office_id, agreement_id, day):
    """FIFO capacities safe at every later retained allocation/release date.

    Caller holds the office lock. Reuse the SQL guard's used-at definition;
    a later release must not make an earlier over-allocation appear possible.
    A reversed charge consumes its source permanently and is never reopened.
    """
    with connection.cursor() as cursor:
        cursor.execute('''
            SELECT c.id, c.amount - (
                SELECT max(accounting_s23_used_at('charge', c.id::text, points.day))
                FROM (
                    SELECT %s::date AS day
                    UNION SELECT a.effective_date FROM accounting_cashallocation a
                        WHERE a.charge_id=c.id AND a.effective_date>=%s
                    UNION SELECT r.effective_date FROM accounting_allocationrelease r
                        JOIN accounting_cashallocation a ON a.id=r.allocation_id
                        WHERE a.charge_id=c.id AND r.effective_date>=%s
                ) points
            ) AS capacity
            FROM accounting_charge c
            WHERE c.office_id=%s AND c.agreement_id=%s AND c.effective_date<=%s
                AND NOT EXISTS (SELECT 1 FROM accounting_chargereversal r WHERE r.charge_id=c.id)
            ORDER BY c.due_date, c.effective_date, c.id
        ''', [day, day, day, office_id, agreement_id, day])
        return cursor.fetchall()
