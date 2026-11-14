"""Read-only movement scope: one filter definition, totals before pagination."""
from decimal import Decimal
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from .models import Transaction
from .office_access import records


def filtered_movements(user, form, *, business_direction=False):
    rows = records(Transaction, user).select_related('cash_account', 'category__parent', 'entity', 'agreement')
    if not form.is_valid():
        return rows.none()
    data = form.cleaned_data
    for field, lookup in [('start_date', 'transaction_date__gte'), ('end_date', 'transaction_date__lte'),
                          ('transaction_type', 'transaction_type'), ('cash_account', 'cash_account'),
                          ('category', 'category'), ('entity', 'entity'), ('query', 'description__icontains')]:
        if data.get(field):
            rows = rows.filter(business_direction_condition(data[field])) if field=='transaction_type' and business_direction else rows.filter(**{lookup: data[field]})
    return rows.order_by('-transaction_date', '-pk')


def movement_totals(rows):
    """Cash inflows/outflows, including transfers; use operating_movements first
    when the caller needs operating totals instead of a cash movement total.
    """
    totals = rows.aggregate(
        total_income=Coalesce(Sum('amount', filter=Q(transaction_type='INCOME')), Value(Decimal('0.00')), output_field=DecimalField()),
        total_expense=Coalesce(Sum('amount', filter=Q(transaction_type='EXPENSE')), Value(Decimal('0.00')), output_field=DecimalField()))
    totals['net_for_period'] = totals['total_income'] - totals['total_expense']
    return totals


def internal_transfer_condition():
    """Only an explicit posting kind is authoritative, never a legacy UUID.

    Linked transfer reversals are included in this exclusion for later S24
    pair corrections; the current service/SQL still deny single-leg reversal.
    Legacy pairing and reconciliation remain an explicit S25 review.
    """
    return Q(posting_kind='TRANSFER') | Q(posting_kind='REVERSAL', reversal_of__posting_kind='TRANSFER')


def operating_movements(rows):
    return rows.exclude(internal_transfer_condition())


def operating_component(direction, *, refunds=True):
    """Signed original business direction; correction cash is not reclassified."""
    from django.db.models import Case, When, F
    clauses = []
    if refunds:
        clauses += [When(posting_kind='REFUND', refund_record__source_cash__transaction_type=direction, then=-F('amount')),
                    When(posting_kind='REVERSAL', reversal_of__posting_kind='REFUND',
                         reversal_of__refund_record__source_cash__transaction_type=direction, then=F('amount'))]
    clauses += [When(posting_kind='REVERSAL', reversal_of__posting_kind__in=['ORDINARY', 'LEGACY'],
                     reversal_of__transaction_type=direction, then=-F('amount')),
                When(posting_kind__in=['ORDINARY', 'LEGACY'], transaction_type=direction, then=F('amount'))]
    return Case(*clauses, default=Value(Decimal('0.00')), output_field=DecimalField())


def operating_totals(rows):
    totals = rows.aggregate(total_income=Coalesce(Sum(operating_component('INCOME')), Value(Decimal('0.00')), output_field=DecimalField()),
                            total_expense=Coalesce(Sum(operating_component('EXPENSE')), Value(Decimal('0.00')), output_field=DecimalField()))
    totals['net_for_period'] = totals['total_income'] - totals['total_expense']
    return totals


def business_direction_condition(direction):
    return (Q(posting_kind__in=['ORDINARY','LEGACY'],transaction_type=direction) |
        Q(posting_kind='REVERSAL',reversal_of__posting_kind__in=['ORDINARY','LEGACY'],reversal_of__transaction_type=direction) |
        Q(posting_kind='REFUND',refund_record__source_cash__transaction_type=direction) |
        Q(posting_kind='REVERSAL',reversal_of__posting_kind='REFUND',reversal_of__refund_record__source_cash__transaction_type=direction))
