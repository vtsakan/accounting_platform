"""Read-only movement scope: one filter definition, totals before pagination."""
from decimal import Decimal
from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from .models import Transaction
from .office_access import records


def filtered_movements(user, form):
    rows = records(Transaction, user).select_related('cash_account', 'category__parent', 'entity', 'agreement')
    if not form.is_valid():
        return rows.none()
    data = form.cleaned_data
    for field, lookup in [('start_date', 'transaction_date__gte'), ('end_date', 'transaction_date__lte'),
                          ('transaction_type', 'transaction_type'), ('cash_account', 'cash_account'),
                          ('category', 'category'), ('entity', 'entity'), ('query', 'description__icontains')]:
        if data.get(field):
            rows = rows.filter(**{lookup: data[field]})
    return rows.order_by('-transaction_date', '-pk')


def movement_totals(rows):
    totals = rows.aggregate(
        total_income=Coalesce(Sum('amount', filter=Q(transaction_type='INCOME')), Value(Decimal('0.00')), output_field=DecimalField()),
        total_expense=Coalesce(Sum('amount', filter=Q(transaction_type='EXPENSE')), Value(Decimal('0.00')), output_field=DecimalField()))
    totals['net_for_period'] = totals['total_income'] - totals['total_expense']
    return totals
