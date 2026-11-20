"""One atomic receipt/payment and explicit agreement-scoped auto-settlement."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .cash_entry_selectors import settlement_capacity
from .correction_selectors import terms_on
from .finance_services import fingerprint, post_cash, scoped_lock
from .models import Agreement, FinanceCommand, Transaction
from .office_access import locked_office
from .settlement_selectors import business_day
from .settlement_services import allocate_cash, cash_key


@transaction.atomic
def post_agreement_cash(user, *, idempotency_key, transaction_type, **inputs):
    office = locked_office(user, 'finance.write')
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160:
        raise ValidationError('Ανανεώστε τη φόρμα για έγκυρη ταυτότητα καταχώρισης.')
    day = business_day(inputs.get('transaction_date'))
    if transaction_type not in {'INCOME', 'EXPENSE'}:
        raise ValidationError('Επιλέξτε έσοδο ή έξοδο.')
    previous = FinanceCommand.objects.filter(office=office, operation='cash.post',
        key_digest=fingerprint(idempotency_key), state='completed').first()
    old = Transaction.objects.filter(office=office, command=previous).first() if previous else None
    selected = inputs.get('agreement')
    agreement = None
    if selected is not None:
        agreement = scoped_lock(Agreement, office, cash_key(selected))
    if not inputs.get('description'):
        if agreement is None:
            raise ValidationError({'description': 'Συμπληρώστε περιγραφή ή επιλέξτε συμφωνία.'})
        if old and old.agreement_id == agreement.pk:
            # Reuse the original text on retry after later terms/name changes.
            inputs['description'] = old.description
        else:
            terms = terms_on(agreement, day)
            prefix = 'Είσπραξη για συμφωνία: ' if transaction_type == 'INCOME' else 'Πληρωμή για συμφωνία: '
            inputs['description'] = (prefix + (terms.description if terms else agreement.description))[:255]
    entry = post_cash(user, idempotency_key=idempotency_key, transaction_type=transaction_type, **inputs)
    if previous:
        # A replay never allocates again, including pre-CR003 cash-only entries,
        # released allocations and receipts later reversed/refunded by an owner.
        return entry, Decimal('0.00'), True
    allocated = Decimal('0.00')
    if agreement is not None:
        remaining = entry.amount
        lines = []
        for key, capacity in settlement_capacity(office.pk, agreement.pk, day):
            if capacity <= 0:
                continue
            amount = min(remaining, capacity)
            lines.append({'charge': key, 'amount': amount})
            remaining -= amount
            allocated += amount
            if remaining == 0:
                break
        reason = 'Αυτόματη αντιστοίχιση νέας κίνησης στην επιλεγμένη συμφωνία'
        for start in range(0, len(lines), 100):
            allocate_cash(user, source_cash=entry.pk, lines=lines[start:start + 100], effective_date=day,
                reason=reason, idempotency_key=f'agreement-cash:{entry.pk}:{start // 100}')
    return entry, allocated, False
