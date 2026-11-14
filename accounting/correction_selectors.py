"""Read-only, scoped correction history and effective agreement versions."""
from django.db.models import Exists, OuterRef
from django.utils import timezone
from .capabilities import require_capability
from .models import AgreementTermsVersion, CashRefund, FinanceCorrection, FinancePeriodClose, Transaction


def terms_on(agreement, day=None):
    return AgreementTermsVersion.objects.filter(office_id=agreement.office_id, agreement_id=agreement.pk,
        effective_date__lte=day or timezone.localdate()).order_by('-revision').first()


def correction_history(user, *, source_cash=None, agreement=None):
    rows = FinanceCorrection.objects.filter(office_id=require_capability(user, 'finance.read').office_id, state='completed')
    if source_cash is not None:
        rows = rows.filter(source_cash_id=getattr(source_cash, 'pk', source_cash))
    if agreement is not None:
        from django.db.models import Q
        key = getattr(agreement, 'pk', agreement)
        rows = rows.filter(Q(agreement_id=key) | Q(source_charge__agreement_id=key) | Q(source_cash__agreement_id=key))
    return rows.select_related('actor', 'source_charge', 'charge_replacement__replacement', 'terms_change__version').prefetch_related(
        'cash_command__entries', 'allocation_releases__release').order_by('-recorded_at', '-pk')


def refund_history(user, *, entity=None, as_of=None):
    from .settlement_selectors import business_day
    day = business_day(as_of)
    office = require_capability(user, 'finance.read').office_id
    rows = CashRefund.objects.filter(office_id=office, correction__state='completed', effective_date__lte=day)
    if entity is not None:
        rows = rows.filter(source_cash__entity_id=getattr(entity, 'pk', entity))
    return rows.select_related('source_cash', 'entry__cash_account', 'correction__actor').annotate(
        reversed_by_day=Exists(Transaction.objects.filter(office_id=office, reversal_of_id=OuterRef('entry_id'), transaction_date__lte=day))
    ).order_by('-effective_date', '-recorded_at', '-pk')


def closed_through(user):
    return FinancePeriodClose.objects.filter(office_id=require_capability(user, 'finance.read').office_id).order_by('-closed_through').first()
