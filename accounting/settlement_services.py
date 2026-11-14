"""Explicit, atomic same-party settlement; no cash movement or automatic offset."""
from datetime import date
from decimal import Decimal
import uuid
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.utils import timezone
from .finance_services import audit_context, canonical, clean_reason, complete, fingerprint, scoped_lock
from .finance_money import money
from .office_access import locked_office
from .models import AllocationRelease, CashAllocation, Charge, Entity, SettlementCommand, Transaction
from .settlement_selectors import effective_allocations


def cash_key(value):
    value = getattr(value, 'pk', value)
    if type(value) is int and 0 < value <= 9223372036854775807:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and 0 < len(value) <= 19:
        result = int(value)
        if 0 < result <= 9223372036854775807:
            return result
    raise ValidationError('Επιλέξτε έγκυρη αρχική είσπραξη ή πληρωμή.')


def event_key(value):
    value = getattr(value, 'pk', value)
    try:
        if isinstance(value, uuid.UUID):
            return value
        if not isinstance(value, str):
            raise ValueError
        return uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Επιλέξτε έγκυρη χρέωση ή αντιστοίχιση.') from None


def allocation_lines(lines):
    if not isinstance(lines, (list, tuple)) or not 1 <= len(lines) <= 100:
        raise ValidationError('Επιβεβαιώστε από μία έως εκατό αντιστοιχίσεις.')
    result = []
    for line in lines:
        if not isinstance(line, dict) or set(line) != {'charge', 'amount'}:
            raise ValidationError('Κάθε γραμμή χρειάζεται μόνο χρέωση και ποσό.')
        result.append((event_key(line['charge']), money(line['amount'])))
    if len({key for key, _ in result}) != len(result):
        raise ValidationError('Η ίδια χρέωση επιλέγεται μία φορά ανά επιβεβαίωση.')
    return sorted(result, key=lambda item: str(item[0]))


def metadata(effective_date, reason, idempotency_key):
    if type(effective_date) is not date or effective_date > timezone.localdate():
        raise ValidationError('Επιλέξτε έγκυρη ημερομηνία αντιστοίχισης έως σήμερα.')
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160 or any(ord(c) < 33 for c in idempotency_key):
        raise ValidationError('Ανανεώστε τη φόρμα για έγκυρη ταυτότητα επιβεβαίωσης.')
    return clean_reason(reason), fingerprint(idempotency_key)


def replay_command(office, operation, key_digest, payload_digest):
    existing = SettlementCommand.objects.select_for_update().filter(office=office, operation=operation, key_digest=key_digest).first()
    if existing and (existing.state != 'completed' or existing.payload_digest != payload_digest):
        raise ValidationError('Η ταυτότητα επιβεβαίωσης χρησιμοποιήθηκε με διαφορετικά στοιχεία.')
    return existing


def eligible_source(source):
    if source.posting_kind != 'ORDINARY' or source.entity_id is None or source.transaction_type not in {'INCOME', 'EXPENSE'}:
        raise ValidationError('Η κίνηση δεν είναι διαθέσιμη για νέα αντιστοίχιση. Οι παλαιές κινήσεις απαιτούν την ανασκόπηση μετάπτωσης.')
    if Transaction.objects.filter(office_id=source.office_id, reversal_of_id=source.pk).exists():
        raise ValidationError('Η αρχική κίνηση έχει αντιλογιστεί.')


@transaction.atomic
def allocate_cash(user, *, source_cash, lines, effective_date, reason, idempotency_key):
    office = locked_office(user, 'finance.write')
    source_id, lines = cash_key(source_cash), allocation_lines(lines)
    reason, key_digest = metadata(effective_date, reason, idempotency_key)
    payload_digest = fingerprint(canonical({'source': source_id, 'lines': [[str(key), str(amount)] for key, amount in lines],
                                            'date': effective_date.isoformat(), 'reason': fingerprint(reason)}))
    existing = replay_command(office, 'ALLOCATE', key_digest, payload_digest)
    if existing:
        return existing
    from .correction_services import ensure_open
    ensure_open(office,effective_date)
    source = scoped_lock(Transaction, office, source_id)
    eligible_source(source)
    party = scoped_lock(Entity, office, source.entity_id, active=True)
    if not (party.is_customer if source.transaction_type == 'INCOME' else party.is_supplier):
        raise ValidationError('Ο συναλλασσόμενος δεν έχει τον κατάλληλο ρόλο.')
    if effective_date < source.transaction_date:
        raise ValidationError('Η αντιστοίχιση δεν προηγείται της είσπραξης ή πληρωμής.')
    used = effective_allocations(office.pk, as_of=effective_date)
    available = source.amount - (used.filter(source_cash=source).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'))
    if sum(amount for _, amount in lines) > available:
        raise ValidationError('Το συνολικό ποσό υπερβαίνει το αδιάθετο ποσό της κίνησης.')
    charges = []
    for key, amount in lines:  # UUID order is stable across all submissions.
        charge = scoped_lock(Charge, office, key)
        if charge.entity_id != party.pk or charge.direction != ('RECEIVABLE' if source.transaction_type == 'INCOME' else 'PAYABLE') or charge.currency != 'EUR':
            raise ValidationError('Η χρέωση πρέπει να αφορά τον ίδιο συναλλασσόμενο και την ίδια κατεύθυνση.')
        if effective_date < charge.effective_date:
            raise ValidationError('Η αντιστοίχιση δεν προηγείται της χρέωσης.')
        remaining = charge.amount - (used.filter(charge=charge).aggregate(total=Sum('amount'))['total'] or Decimal('0.00'))
        if amount > remaining:
            raise ValidationError('Το ποσό υπερβαίνει το ανεξόφλητο ποσό της χρέωσης.')
        charges.append((charge, amount))
    try:
        with transaction.atomic(), audit_context(user, reason):
            command = SettlementCommand.objects.create(office=office, source_cash=source, actor=user, operation='ALLOCATE',
                effective_date=effective_date, reason=reason, key_digest=key_digest, payload_digest=payload_digest, expected_count=len(charges))
            for charge, amount in charges:
                CashAllocation.objects.create(office=office, command=command, source_cash=source, charge=charge,
                                               amount=amount, effective_date=effective_date)
            complete(command)
    except IntegrityError:
        raise ValidationError('Η αντιστοίχιση δεν καταχωρίστηκε. Ελέγξτε τα διαθέσιμα ποσά και τις ημερομηνίες και ανανεώστε τη σελίδα.') from None
    return command


@transaction.atomic
def release_allocation(request, *, allocation, effective_date, password, reason, idempotency_key):
    office = locked_office(request.user, 'finance.release')
    from .office_services import prove_actor
    prove_actor(request, office, password, 'finance.release')
    key = event_key(allocation)
    reason, key_digest = metadata(effective_date, reason, idempotency_key)
    payload_digest = fingerprint(canonical({'allocation': str(key), 'date': effective_date.isoformat(), 'reason': fingerprint(reason)}))
    existing = replay_command(office, 'RELEASE', key_digest, payload_digest)
    if existing:
        return existing
    from .correction_services import ensure_open
    ensure_open(office,effective_date)
    allocated = scoped_lock(CashAllocation, office, key)
    scoped_lock(Transaction, office, allocated.source_cash_id)
    scoped_lock(Charge, office, allocated.charge_id)
    if effective_date < allocated.effective_date:
        raise ValidationError('Η αποδέσμευση δεν προηγείται της αρχικής αντιστοίχισης.')
    if AllocationRelease.objects.filter(office=office, allocation=allocated).exists():
        raise ValidationError('Η αντιστοίχιση έχει ήδη αποδεσμευτεί.')
    try:
        with transaction.atomic(), audit_context(request.user, reason):
            command = SettlementCommand.objects.create(office=office, source_cash_id=allocated.source_cash_id, actor=request.user,
                operation='RELEASE', effective_date=effective_date, reason=reason, key_digest=key_digest, payload_digest=payload_digest, expected_count=1)
            AllocationRelease.objects.create(office=office, command=command, allocation=allocated, effective_date=effective_date)
            complete(command)
    except IntegrityError:
        raise ValidationError('Η αποδέσμευση δεν καταχωρίστηκε. Ανανεώστε τη σελίδα και ελέγξτε το ιστορικό.') from None
    return command


def assert_reversible_cash(original, effective_date):
    if CashAllocation.objects.filter(office_id=original.office_id, source_cash=original).filter(
            Q(effective_date__gt=effective_date) |
            Q(release_record__isnull=True) |
            Q(release_record__effective_date__gt=effective_date)).exists():
        raise ValidationError('Αποδεσμεύστε πρώτα τις αντιστοιχίσεις. Ο αντιλογισμός δεν προηγείται του διατηρημένου ιστορικού τους.')
