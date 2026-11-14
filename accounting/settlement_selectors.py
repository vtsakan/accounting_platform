"""Dated settlement projections; totals come from retained events, never flags."""
from datetime import date
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Case, DecimalField, Exists, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from .capabilities import require_capability
from .models import AllocationRelease, CashAllocation, CashRefund, Charge, ChargeReversal, Transaction

ZERO = Decimal('0.00')


def corrections_installed():
    # Historical migration tests deliberately execute the original S23 schema.
    # No feature flag or user input can disable current database guards.
    from django.db import connection
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('accounting_cashrefund') IS NOT NULL AND to_regclass('accounting_chargereversal') IS NOT NULL")
        return cursor.fetchone()[0]


def business_day(value=None):
    value = timezone.localdate() if value is None else value
    if type(value) is not date or value > timezone.localdate():
        raise ValidationError('Επιλέξτε έγκυρη ημερομηνία αναφοράς έως σήμερα.')
    return value


def effective_allocations(office_id, *, as_of=None):
    day = business_day(as_of)
    releases = AllocationRelease.objects.filter(office_id=office_id, allocation_id=OuterRef('pk'),
                                                 effective_date__lte=day, command__state='completed')
    return CashAllocation.objects.filter(office_id=office_id, effective_date__lte=day, command__state='completed').annotate(
        released_by_day=Exists(releases)).filter(released_by_day=False)


def _allocated_subquery(office_id, field, day):
    rows = effective_allocations(office_id, as_of=day).filter(**{field: OuterRef('pk')}).order_by()
    return Coalesce(Subquery(rows.values(field).annotate(total=Sum('amount')).values('total'), output_field=DecimalField()),
                    Value(ZERO), output_field=DecimalField())


def _charge_balances(office_id, *, as_of=None):
    day = business_day(as_of)
    reversed_rows=ChargeReversal.objects.filter(office_id=office_id,charge_id=OuterRef('pk'),effective_date__lte=day)
    return Charge.objects.filter(office_id=office_id, effective_date__lte=day).annotate(
        allocated_total=_allocated_subquery(office_id, 'charge_id', day),reversed_by_day=Exists(reversed_rows) if corrections_installed() else Value(False)).annotate(
        net_amount=Case(When(reversed_by_day=True,then=Value(ZERO)),default=F('amount'),output_field=DecimalField())
    ).annotate(outstanding=F('net_amount')-F('allocated_total'))


def charge_balances(user, *, entity=None, agreement=None, as_of=None):
    office_id = require_capability(user, 'finance.read').office_id
    rows = _charge_balances(office_id, as_of=as_of)
    if entity is not None:
        rows = rows.filter(entity_id=getattr(entity, 'pk', entity))
    if agreement is not None:
        rows = rows.filter(agreement_id=getattr(agreement, 'pk', agreement))
    return rows.select_related('agreement', 'terms', 'actor').order_by('due_date', 'effective_date', 'id')


def _cash_sources(office_id, *, as_of=None):
    day = business_day(as_of)
    reversal = Transaction.objects.filter(office_id=office_id, reversal_of_id=OuterRef('pk'), transaction_date__lte=day)
    returned=CashRefund.objects.filter(office_id=office_id,source_cash_id=OuterRef('pk'),effective_date__lte=day,correction__state='completed').annotate(
        voided=Exists(Transaction.objects.filter(reversal_of_id=OuterRef('entry_id'),transaction_date__lte=day))).filter(voided=False).order_by()
    refunded=Coalesce(Subquery(returned.values('source_cash_id').annotate(total=Sum('amount')).values('total'),output_field=DecimalField()),Value(ZERO),output_field=DecimalField()) if corrections_installed() else Value(ZERO,output_field=DecimalField())
    return Transaction.objects.filter(office_id=office_id, posting_kind='ORDINARY', entity__isnull=False,
                                      transaction_date__lte=day).annotate(
        allocated_total=_allocated_subquery(office_id, 'source_cash_id', day), refunded_total=refunded, reversed_by_day=Exists(reversal)).annotate(
        available_credit=Case(When(reversed_by_day=True, then=Value(ZERO)), default=F('amount') - F('allocated_total') - F('refunded_total'),
                              output_field=DecimalField()))


def cash_sources(user, *, entity=None, as_of=None):
    rows = _cash_sources(require_capability(user, 'finance.read').office_id, as_of=as_of)
    if entity is not None:
        rows = rows.filter(entity_id=getattr(entity, 'pk', entity))
    return rows.select_related('cash_account', 'entity').order_by('-transaction_date', '-pk')


def settlement_totals(user, *, entity=None, agreement=None, as_of=None):
    charges = charge_balances(user, entity=entity, agreement=agreement, as_of=as_of)
    values = {}
    for direction, prefix in (('RECEIVABLE', 'receivable'), ('PAYABLE', 'payable')):
        aggregate = charges.filter(direction=direction).aggregate(
            charged=Coalesce(Sum('net_amount'), Value(ZERO), output_field=DecimalField()),
            allocated=Coalesce(Sum('allocated_total'), Value(ZERO), output_field=DecimalField()),
            remaining=Coalesce(Sum('outstanding'), Value(ZERO), output_field=DecimalField()))
        values.update({prefix + '_' + key: value for key, value in aggregate.items()})
    # Credit belongs to a counterparty/direction, never an individual agreement.
    sources = cash_sources(user, entity=entity, as_of=as_of)
    values.update(sources.aggregate(
        customer_credit=Coalesce(Sum('available_credit', filter=Q(transaction_type='INCOME')), Value(ZERO), output_field=DecimalField()),
        supplier_advance=Coalesce(Sum('available_credit', filter=Q(transaction_type='EXPENSE')), Value(ZERO), output_field=DecimalField())))
    return values


def allocation_history(user, *, entity=None, agreement=None, as_of=None):
    office_id = require_capability(user, 'finance.read').office_id
    day = business_day(as_of)
    rows = CashAllocation.objects.filter(office_id=office_id, command__state='completed', effective_date__lte=day)
    if entity is not None:
        rows = rows.filter(charge__entity_id=getattr(entity, 'pk', entity))
    if agreement is not None:
        rows = rows.filter(charge__agreement_id=getattr(agreement, 'pk', agreement))
    return rows.select_related('source_cash', 'charge__agreement', 'command__actor', 'release_record__command__actor').annotate(
        released_by_day=Exists(AllocationRelease.objects.filter(allocation_id=OuterRef('pk'), office_id=office_id,
                                                                effective_date__lte=day, command__state='completed'))).order_by('-effective_date', '-recorded_at', '-id')
