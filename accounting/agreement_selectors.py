"""Separate agreed terms, posted obligations and cash; never infer paid status."""
from decimal import Decimal
from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value, Q
from django.db.models.functions import Coalesce
from .models import AgreementTermsVersion, Charge
from .finance_services import legacy_settlement


def agreement_projection(agreement):
    terms = AgreementTermsVersion.objects.filter(office_id=agreement.office_id, agreement=agreement).first()
    charges = Charge.objects.filter(office_id=agreement.office_id, agreement=agreement).select_related('terms', 'actor')
    cash = agreement.transactions.filter(office_id=agreement.office_id).select_related('cash_account').order_by('-transaction_date', '-pk')
    total = charges.aggregate(total=Coalesce(Sum('amount'), Value(Decimal('0.00')), output_field=DecimalField()))['total']
    cash_total = cash.aggregate(total=legacy_settlement())['total']
    return {'terms': terms, 'charges': charges, 'charge_total': total, 'cash_total': cash_total,
            'transactions': cash, 'settlement_label': 'Χωρίς χρεώσεις' if total == 0 else 'Χρεώσεις χωρίς αντιστοιχίσεις',
            # Compatibility for the unchanged S06/S18 legacy probes. These are
            # explicitly legacy totals, NOT the new obligation/settlement truth.
            'total_payments': cash_total, 'remaining_balance': agreement.total_amount - cash_total}


def agreement_rows(rows):
    terms = AgreementTermsVersion.objects.filter(agreement_id=OuterRef('pk'), office_id=OuterRef('office_id')).order_by('-revision')
    charges = Charge.objects.filter(agreement_id=OuterRef('pk'), office_id=OuterRef('office_id')).order_by()
    return rows.select_related('entity').annotate(
        billing_mode=Subquery(terms.values('billing_mode')[:1]), contract_lifecycle=Subquery(terms.values('lifecycle')[:1]),
        charge_total=Coalesce(Subquery(charges.values('agreement_id').annotate(total=Sum('amount')).values('total'), output_field=DecimalField()),
                              Value(Decimal('0.00')), output_field=DecimalField()))


def obligation_totals(user):
    from .capabilities import require_capability
    office = require_capability(user, 'finance.read').office_id
    return Charge.objects.filter(office_id=office).aggregate(
        posted_receivable_total=Coalesce(Sum('amount', filter=Q(direction='RECEIVABLE')), Value(Decimal('0.00')), output_field=DecimalField()),
        posted_payable_total=Coalesce(Sum('amount', filter=Q(direction='PAYABLE')), Value(Decimal('0.00')), output_field=DecimalField()))
