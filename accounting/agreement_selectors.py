"""Separate terms, obligations, dated settlements and cash; never infer paid flags."""
from decimal import Decimal
from django.db.models import DecimalField, Exists, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from .models import AgreementTermsVersion, AllocationRelease, CashAllocation, Charge
from .finance_services import legacy_settlement
from .settlement_selectors import _charge_balances, settlement_totals


def agreement_projection(agreement):
    terms = AgreementTermsVersion.objects.filter(office_id=agreement.office_id, agreement=agreement).first()
    charges = _charge_balances(agreement.office_id).filter(agreement=agreement).select_related('terms', 'actor')
    cash = agreement.transactions.filter(office_id=agreement.office_id).select_related('cash_account').order_by('-transaction_date', '-pk')
    total = charges.aggregate(total=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField()))['total']
    allocated = charges.aggregate(total=Coalesce(Sum('allocated_total'), Value(Decimal('0.00')), output_field=DecimalField()))['total']
    remaining = total - allocated
    state = 'NO_OBLIGATIONS' if total == 0 else 'OPEN' if allocated == 0 else 'PARTIAL' if remaining > 0 else 'SETTLED'
    label = {'NO_OBLIGATIONS': 'Χωρίς χρεώσεις', 'OPEN': 'Χρεώσεις χωρίς αντιστοιχίσεις', 'PARTIAL': 'Μερική εξόφληση',
             'SETTLED': 'Εξοφλημένη έως τώρα' if terms and terms.billing_mode == 'MONTHLY' else 'Εξοφλημένη'}[state]
    cancelled = agreement.status == 'CANCELLED' or bool(terms and terms.lifecycle == 'CANCELLED')
    cash_total = cash.aggregate(total=legacy_settlement())['total']
    return {'terms': terms, 'charges': charges, 'charge_total': total, 'cash_total': cash_total, 'transactions': cash,
            'settlement_label': label, 'settlement_state': state, 'allocated_total': allocated,
            'remaining_obligation': remaining, 'contract_cancelled': cancelled,
            # Retain the original financial probes. Product settlement views use
            # allocations and remaining_obligation, not these legacy aliases.
            'total_payments': cash_total, 'remaining_balance': agreement.total_amount - cash_total}


def agreement_rows(rows):
    day = timezone.localdate()
    terms = AgreementTermsVersion.objects.filter(agreement_id=OuterRef('pk'), office_id=OuterRef('office_id')).order_by('-revision')
    charges = Charge.objects.filter(agreement_id=OuterRef('pk'), office_id=OuterRef('office_id'), effective_date__lte=day).order_by()
    released = AllocationRelease.objects.filter(allocation_id=OuterRef('pk'), effective_date__lte=day, command__state='completed')
    allocations = CashAllocation.objects.filter(office_id=OuterRef('office_id'), charge__agreement_id=OuterRef('pk'),
        effective_date__lte=day, command__state='completed').annotate(released=Exists(released)).filter(released=False).order_by()
    return rows.select_related('entity').annotate(
        billing_mode=Subquery(terms.values('billing_mode')[:1]), contract_lifecycle=Subquery(terms.values('lifecycle')[:1]),
        charge_total=Coalesce(Subquery(charges.values('agreement_id').annotate(total=Sum('amount')).values('total'), output_field=DecimalField()),
                              Value(Decimal('0.00')), output_field=DecimalField()),
        allocated_total=Coalesce(Subquery(allocations.values('charge__agreement_id').annotate(total=Sum('amount')).values('total'), output_field=DecimalField()),
                                 Value(Decimal('0.00')), output_field=DecimalField())
    ).annotate(remaining_obligation=F('charge_total') - F('allocated_total'))


def obligation_totals(user):
    from .capabilities import require_capability
    office = require_capability(user, 'finance.read').office_id
    values = Charge.objects.filter(office_id=office).aggregate(
        posted_receivable_total=Coalesce(Sum('amount', filter=Q(direction='RECEIVABLE')), Value(Decimal('0.00')), output_field=DecimalField()),
        posted_payable_total=Coalesce(Sum('amount', filter=Q(direction='PAYABLE')), Value(Decimal('0.00')), output_field=DecimalField()))
    values.update(settlement_totals(user))
    return values
