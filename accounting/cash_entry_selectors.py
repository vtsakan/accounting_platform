"""Scoped agreement choices and capacity reused from the retained PG guards."""
from django.db import connection
from django.db.models import F

from .agreement_selectors import agreement_rows
from .models import Agreement
from .office_access import records


def legacy_unbilled_agreement(agreement):
    """A retained unreviewed link has no modern obligation to select or settle."""
    from .models import AgreementTermsVersion,Charge
    terms=AgreementTermsVersion.objects.filter(office_id=agreement.office_id,agreement=agreement).first()
    return bool(terms and terms.billing_mode=='UNREVIEWED' and terms.lifecycle=='UNREVIEWED'
        and not Charge.objects.filter(office_id=agreement.office_id,agreement=agreement).exists())


def receipt_charges(user,direction,*,as_of=None,include_key=None):
    from decimal import Decimal
    from django.db.models import Func,Value,DecimalField,Q
    from django.db.models.functions import Coalesce
    from .settlement_selectors import charge_balances,business_day
    day=business_day(as_of)
    kind='RECEIVABLE' if direction=='INCOME' else 'PAYABLE'
    role='entity__is_customer' if direction=='INCOME' else 'entity__is_supplier'
    rows=charge_balances(user,as_of=day).filter(direction=kind,entity__is_archived=False,**{role:True}).annotate(
        receipt_capacity=Coalesce(Func(F('pk'),Value(day),function='accounting_cr012_receipt_capacity',output_field=DecimalField()),
            Value(Decimal('0.00')),output_field=DecimalField()))
    eligible=Q(receipt_capacity__gt=0,reversal_record__isnull=True)
    if include_key is not None:eligible|=Q(pk=include_key)
    return rows.filter(eligible)


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
