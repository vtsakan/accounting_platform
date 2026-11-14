"""S24 owner-confirmed atomic corrections. No original financial row is edited."""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import uuid
from django.core.exceptions import ValidationError
from django.db import connection, DatabaseError, IntegrityError, transaction
from django.utils import timezone
from .finance_money import money
from .finance_services import (audit_context, canonical, cash_values, clean_reason, command_for, complete,
                               fingerprint, scoped_lock, validate_references)
from .office_access import locked_office
from .office_services import prove_actor
from .settlement_services import cash_key, event_key
from .models import (Agreement, AgreementChange, AgreementTermsVersion, AllocationRelease, CashAccount, CashAllocation,
                     CashRefund, Charge, ChargeReplacement, ChargeReversal, CorrectionRelease, Entity,
                     FinanceCommand, FinanceCorrection, FinancePeriodClose, SettlementCommand, Transaction)


def ensure_open(office, day):
    """The lookup also permits original migration rehearsals at their old schema.

    On the S24 schema the SQL trigger is authoritative, including raw writers.
    No settings flag can bypass a declared cutoff.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regprocedure('accounting_s24_open_date(uuid,date)') IS NOT NULL")
        installed = cursor.fetchone()[0]
    if installed:
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute('SELECT accounting_s24_open_date(%s::uuid,%s::date)', [str(getattr(office, 'pk', office)), day])
        except IntegrityError as error:
            if getattr(getattr(error.__cause__, 'diag', None), 'constraint_name', None) != 's24_period_closed':
                raise
            raise ValidationError('Η ημερομηνία ανήκει σε κλεισμένη οικονομική περίοδο. Επιλέξτε μεταγενέστερη ανοικτή ημερομηνία.') from None


@contextmanager
def correction_context(action):
    name = 'accounting.s24_correction'
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_setting(%s,true)', [name]); before = cursor.fetchone()[0] or ''
        cursor.execute('SELECT set_config(%s,%s,true)', [name, str(action.pk)])
    try:
        yield
    except DatabaseError:
        if connection.in_atomic_block:
            connection.set_rollback(True)
        raise
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute('SELECT set_config(%s,%s,true)', [name, before])


def proof(request, capability, password, effective_date, *, future=False):
    office = locked_office(request.user, capability)
    prove_actor(request, office, password, capability)
    if type(effective_date) is not date or (not future and effective_date > timezone.localdate()):
        raise ValidationError('Επιλέξτε έγκυρη ημερομηνία ενέργειας.')
    return office


def request_identity(key, payload, reason):
    if not isinstance(key, str) or not 8 <= len(key) <= 160 or any(ord(ch) < 33 for ch in key):
        raise ValidationError('Ανανεώστε τη φόρμα για έγκυρη ταυτότητα επιβεβαίωσης.')
    why = clean_reason(reason)
    return why, fingerprint(key), fingerprint(canonical(payload | {'reason': fingerprint(why)}))


def previous_action(office, operation, key, payload):
    action = FinanceCorrection.objects.select_for_update().filter(office=office, operation=operation, key_digest=key).first()
    if action and (action.state != 'completed' or action.payload_digest != payload):
        raise ValidationError('Η ταυτότητα επιβεβαίωσης χρησιμοποιήθηκε με διαφορετικά στοιχεία.')
    return action


def new_action(request, office, operation, day, why, key, payload, **values):
    ensure_open(office, day)
    return FinanceCorrection.objects.create(office=office, actor=request.user, operation=operation,
        effective_date=day, reason=why, key_digest=key, payload_digest=payload, **values)


def finish(action):
    # The database binds the cash command, without adding fields to the old
    # models; historical migration rehearsals still use their original schemas.
    action.refresh_from_db()
    complete(action)
    action.refresh_from_db()
    return action


def cash_members(request, action, operation):
    cmd, replay = command_for(request.user, action.office, operation, 's24-' + str(action.pk), {'correction': str(action.pk)}, action.reason)
    if replay:
        raise ValidationError('Η ομάδα χρηματικών κινήσεων έχει ήδη καταχωριστεί.')
    return cmd


def unreversed_refunds(source):
    return CashRefund.objects.filter(office_id=source.office_id, source_cash=source, entry__reversal__isnull=True).select_related('entry').order_by('pk')


def release_targets(request, action, *, source=None, charge=None):
    rows = CashAllocation.objects.select_for_update().filter(office=action.office, release_record__isnull=True)
    rows = rows.filter(source_cash=source) if source is not None else rows.filter(charge=charge)
    for row in rows.order_by('source_cash_id', 'charge_id', 'id'):
        # Public correction entry points already proved and locked the owner.
        # The normal S23 SQL guards still validate each retained release.
        cmd = SettlementCommand.objects.create(office=action.office, source_cash_id=row.source_cash_id, actor=request.user,
            operation='RELEASE', effective_date=action.effective_date, reason=action.reason, expected_count=1,
            key_digest=fingerprint('s24-release-' + str(action.pk) + '-' + str(row.pk)),
            payload_digest=fingerprint(canonical({'correction': str(action.pk), 'allocation': str(row.pk)})))
        released = AllocationRelease.objects.create(office=action.office, command=cmd, allocation=row, effective_date=action.effective_date)
        complete(cmd)
        CorrectionRelease.objects.create(office=action.office, correction=action, release=released)


def allocation_dates(target, day, *, source=True):
    rows = CashAllocation.objects.filter(**({'source_cash': target} if source else {'charge': target}))
    if rows.filter(effective_date__gt=day).exists() or AllocationRelease.objects.filter(allocation__in=rows, effective_date__gt=day).exists():
        raise ValidationError('Η διόρθωση δεν μπορεί να προηγείται καταχωρισμένης αντιστοίχισης ή αποδέσμευσής της.')
    count = rows.filter(release_record__isnull=True).count()
    if count > 1000:
        raise ValidationError('Αποδεσμεύστε πρώτα μέρος των αντιστοιχίσεων με την ειδική ενέργεια.')
    return count


def reverse_entry(action, cmd, original, *, group=None):
    from .account_services import validate_account_date
    validate_account_date(scoped_lock(CashAccount, action.office, original.cash_account_id), action.effective_date)
    if action.effective_date < original.transaction_date:
        raise ValidationError('Ο αντιλογισμός δεν προηγείται της αρχικής κίνησης.')
    return Transaction.objects.create(office=action.office, command=cmd, posting_kind='REVERSAL', reversal_of=original,
        amount=original.amount, transaction_date=action.effective_date,
        transaction_type='EXPENSE' if original.transaction_type == 'INCOME' else 'INCOME', cash_account_id=original.cash_account_id,
        entity_id=original.entity_id, category_id=original.category_id, agreement_id=original.agreement_id,
        transfer_id=group or uuid.uuid4(), description='Αντιλογισμός κίνησης #' + str(original.pk))


@transaction.atomic
def correct_cash(request, *, entry_id, password, effective_date, reason, idempotency_key, replacement=None, dependent_refunds=()):
    office = proof(request, 'finance.reverse', password, effective_date)
    key = cash_key(entry_id)
    if not isinstance(dependent_refunds, (list, tuple)) or len(dependent_refunds) > 100:
        raise ValidationError('Επιβεβαιώστε έως εκατό συνδεδεμένες επιστροφές ανά διόρθωση.')
    refund_ids = sorted({str(event_key(value)) for value in dependent_refunds})
    if len(refund_ids) != len(dependent_refunds):
        raise ValidationError('Κάθε συνδεδεμένη επιστροφή επιλέγεται μία φορά.')
    values, replacement_payload = cash_values(**replacement) if replacement else (None, None)
    if values and values['transaction_date'] != effective_date:
        raise ValidationError('Η αντικατάσταση χρησιμοποιεί την ίδια ανοικτή ημερομηνία με τον αντιλογισμό.')
    why, digest, payload = request_identity(idempotency_key, {'entry': key, 'date': effective_date.isoformat(),
        'replacement': replacement_payload, 'refunds': refund_ids}, reason)
    old = previous_action(office, 'CASH', digest, payload)
    if old:
        return old
    source = scoped_lock(Transaction, office, key)
    if source.posting_kind not in {'ORDINARY', 'LEGACY'} or Transaction.objects.filter(reversal_of=source).exists():
        raise ValidationError('Η κίνηση έχει ήδη αντιλογιστεί ή χρειάζεται την ειδική διόρθωση μεταφοράς / επιστροφής.')
    if Transaction.objects.filter(office=office, transfer_id=source.transfer_id).exclude(pk=source.pk).exists():
        raise ValidationError('Η παλαιά σύνδεση μεταφοράς χρειάζεται την ειδική ανασκόπηση μετάπτωσης.')
    releases = allocation_dates(source, effective_date)
    refunds = list(unreversed_refunds(source).select_for_update(of=('self',)))
    if refund_ids != sorted(str(row.pk) for row in refunds):
        raise ValidationError('Επιβεβαιώστε ακριβώς τις ενεργές συνδεδεμένες επιστροφές που εμφανίζονται πριν διορθώσετε την αρχική κίνηση.')
    all_refunds = CashRefund.objects.filter(office=office, source_cash=source)
    if all_refunds.filter(effective_date__gt=effective_date).exists() or all_refunds.filter(entry__reversal__transaction_date__gt=effective_date).exists():
        raise ValidationError('Η διόρθωση δεν προηγείται διατηρημένης επιστροφής ή αντιλογισμού επιστροφής.')
    if values:
        validate_references(values, office)
    with audit_context(request.user, why):
        action = new_action(request, office, 'CASH', effective_date, why, digest, payload, source_cash=source,
            expected_cash_count=1 + bool(values) + len(refunds), expected_release_count=releases,
            refund_reversal_count=len(refunds), has_replacement=bool(values))
        with correction_context(action):
            release_targets(request, action, source=source)
            cmd = cash_members(request, action, 'cash.correct' if values else 'cash.reverse')
            with audit_context(request.user, why, cmd):
                for refund in refunds:
                    reverse_entry(action, cmd, refund.entry)
                reverse_entry(action, cmd, source)
                if values:
                    Transaction.objects.create(office=office, command=cmd, posting_kind='ORDINARY', **values)
                complete(cmd)
            # Only historical, unreviewed agreements retain the old probe bridge.
            from .finance_services import project_agreement
            for agreement_id in sorted({value for value in (source.agreement_id, values['agreement_id'] if values else None) if value}):
                project_agreement(agreement_id, office)
            return finish(action)


@transaction.atomic
def correct_transfer(request, *, entry_id, password, effective_date, reason, idempotency_key, replacement=None):
    office = proof(request, 'finance.reverse', password, effective_date)
    source = scoped_lock(Transaction, office, cash_key(entry_id))
    if source.posting_kind != 'TRANSFER':
        raise ValidationError('Επιλέξτε σκέλος καταχωρισμένης εσωτερικής μεταφοράς.')
    pair = list(Transaction.objects.select_for_update().filter(office=office, posting_kind='TRANSFER', transfer_id=source.transfer_id).order_by('pk'))
    if len(pair) != 2 or pair[0].command_id != pair[1].command_id or pair[0].amount != pair[1].amount or pair[0].transaction_type == pair[1].transaction_type:
        raise ValidationError('Η μεταφορά δεν αποτελεί έγκυρο ζεύγος. Χρειάζεται ανασκόπηση της προέλευσης.')
    normalized = None
    if replacement is not None:
        if not isinstance(replacement, dict) or set(replacement) != {'from_account', 'to_account', 'amount', 'description'}:
            raise ValidationError('Η νέα μεταφορά χρειάζεται δύο ταμεία, ακριβές ποσό και περιγραφή.')
        normalized = {'from': cash_key(replacement['from_account']), 'to': cash_key(replacement['to_account']),
                      'amount': str(money(replacement['amount'])), 'description': replacement['description']}
        if normalized['from'] == normalized['to'] or not isinstance(normalized['description'], str) or not normalized['description'].strip() or len(normalized['description']) > 200:
            raise ValidationError('Επιλέξτε διαφορετικά ταμεία και σύντομη περιγραφή.')
    why, digest, payload = request_identity(idempotency_key, {'pair': str(source.transfer_id), 'date': effective_date.isoformat(),
        'replacement': None if normalized is None else normalized | {'description': fingerprint(normalized['description'])}}, reason)
    old = previous_action(office, 'TRANSFER', digest, payload)
    if old:
        return old
    if Transaction.objects.filter(reversal_of__in=pair).exists():
        raise ValidationError('Η μεταφορά έχει ήδη αντιλογιστεί. Ελέγξτε την υπάρχουσα διόρθωση.')
    accounts = {}
    if normalized:
        from .account_services import validate_account_date
        for key in sorted({normalized['from'], normalized['to']}):
            accounts[key] = scoped_lock(CashAccount, office, key, active=True)
            validate_account_date(accounts[key], effective_date)
    with audit_context(request.user, why):
        action = new_action(request, office, 'TRANSFER', effective_date, why, digest, payload, source_cash=pair[0],
                            expected_cash_count=4 if normalized else 2, has_replacement=bool(normalized))
        with correction_context(action):
            cmd = cash_members(request, action, 'transfer.correct' if normalized else 'transfer.reverse')
            with audit_context(request.user, why, cmd):
                for entry in pair:
                    reverse_entry(action, cmd, entry, group=action.pk)
                if normalized:
                    group = uuid.uuid4()
                    for kind, key in (('EXPENSE', normalized['from']), ('INCOME', normalized['to'])):
                        Transaction.objects.create(office=office, command=cmd, posting_kind='TRANSFER', transfer_id=group,
                            amount=normalized['amount'], transaction_date=effective_date, transaction_type=kind,
                            cash_account=accounts[key], description=normalized['description'])
                complete(cmd)
            return finish(action)


@transaction.atomic
def refund_credit(request, *, source_cash, cash_account, amount, password, effective_date, reason, idempotency_key):
    office = proof(request, 'finance.refund', password, effective_date)
    source_id, account_id, amount = cash_key(source_cash), cash_key(cash_account), money(amount)
    why, digest, payload = request_identity(idempotency_key, {'source': source_id, 'account': account_id, 'amount': str(amount), 'date': effective_date.isoformat()}, reason)
    old = previous_action(office, 'REFUND', digest, payload)
    if old:
        return old
    source = scoped_lock(Transaction, office, source_id)
    if source.posting_kind != 'ORDINARY' or not source.entity_id or Transaction.objects.filter(reversal_of=source).exists():
        raise ValidationError('Η επιστροφή χρειάζεται ενεργή αρχική πίστωση πελάτη ή προκαταβολή προμηθευτή.')
    account = scoped_lock(CashAccount, office, account_id, active=True)
    from .account_services import validate_account_date
    validate_account_date(account, effective_date)
    if effective_date < source.transaction_date:
        raise ValidationError('Η επιστροφή δεν προηγείται της αρχικής κίνησης.')
    from .settlement_selectors import cash_sources
    available = cash_sources(request.user, as_of=effective_date).get(pk=source.pk).available_credit
    if amount > available:
        raise ValidationError('Το ποσό υπερβαίνει την αδιάθετη πίστωση ή προκαταβολή της συγκεκριμένης κίνησης.')
    with audit_context(request.user, why):
        action = new_action(request, office, 'REFUND', effective_date, why, digest, payload, source_cash=source, expected_cash_count=1)
        with correction_context(action):
            cmd = cash_members(request, action, 'cash.refund')
            with audit_context(request.user, why, cmd):
                entry = Transaction.objects.create(office=office, command=cmd, posting_kind='REFUND', amount=amount,
                    transaction_date=effective_date, transaction_type='EXPENSE' if source.transaction_type == 'INCOME' else 'INCOME',
                    cash_account=account, entity_id=source.entity_id, category_id=source.category_id, agreement_id=source.agreement_id,
                    description='Επιστροφή από κίνηση #' + str(source.pk))
                CashRefund.objects.create(office=office, correction=action, source_cash=source, entry=entry, amount=amount, effective_date=effective_date)
                complete(cmd)
            return finish(action)


@transaction.atomic
def reverse_refund(request, *, entry_id, password, effective_date, reason, idempotency_key):
    office = proof(request, 'finance.refund', password, effective_date)
    key = cash_key(entry_id)
    why, digest, payload = request_identity(idempotency_key, {'entry': key, 'date': effective_date.isoformat()}, reason)
    old = previous_action(office, 'REFUND_REVERSE', digest, payload)
    if old:
        return old
    source = scoped_lock(Transaction, office, key)
    if source.posting_kind != 'REFUND' or not CashRefund.objects.filter(office=office, entry=source).exists() or Transaction.objects.filter(reversal_of=source).exists():
        raise ValidationError('Η επιστροφή δεν είναι διαθέσιμη για νέο αντιλογισμό.')
    with audit_context(request.user, why):
        action = new_action(request, office, 'REFUND_REVERSE', effective_date, why, digest, payload, source_cash=source, expected_cash_count=1)
        with correction_context(action):
            cmd = cash_members(request, action, 'refund.reverse')
            with audit_context(request.user, why, cmd):
                reverse_entry(action, cmd, source)
                complete(cmd)
            return finish(action)


@transaction.atomic
def correct_charge(request, *, charge_id, password, effective_date, reason, idempotency_key, replacement_amount=None, replacement_due_date=None):
    office = proof(request, 'finance.reverse', password, effective_date)
    key = event_key(charge_id)
    amount = money(replacement_amount) if replacement_amount is not None else None
    if amount is not None and (type(replacement_due_date) is not date or replacement_due_date < effective_date):
        raise ValidationError('Η νέα προθεσμία δεν προηγείται της ημερομηνίας διόρθωσης.')
    why, digest, payload = request_identity(idempotency_key, {'charge': str(key), 'date': effective_date.isoformat(),
        'replacement': str(amount) if amount is not None else None, 'due': replacement_due_date.isoformat() if amount is not None else None}, reason)
    old = previous_action(office, 'CHARGE', digest, payload)
    if old:
        return old
    charge = scoped_lock(Charge, office, key)
    if effective_date < charge.effective_date or ChargeReversal.objects.filter(charge=charge).exists():
        raise ValidationError('Η χρέωση έχει ήδη αντιλογιστεί ή η ημερομηνία προηγείται της αρχικής.')
    releases = allocation_dates(charge, effective_date, source=False)
    if amount is not None:
        scoped_lock(Entity, office, charge.entity_id, active=True)
    with audit_context(request.user, why):
        action = new_action(request, office, 'CHARGE', effective_date, why, digest, payload, source_charge=charge,
                            expected_release_count=releases, has_replacement=amount is not None)
        with correction_context(action):
            release_targets(request, action, charge=charge)
            ChargeReversal.objects.create(office=office, correction=action, charge=charge, effective_date=effective_date)
            if amount is not None:
                replacement = Charge.objects.create(office=office, agreement_id=charge.agreement_id, terms_id=charge.terms_id,
                    entity_id=charge.entity_id, direction=charge.direction, amount=amount, currency=charge.currency,
                    description=charge.description, effective_date=effective_date, due_date=replacement_due_date, period=charge.period,
                    source_key='correction:' + str(action.pk), actor=request.user, reason=why,
                    key_digest=fingerprint('replacement-' + str(action.pk)), payload_digest=payload)
                ChargeReplacement.objects.create(office=office, correction=action, original=charge, replacement=replacement)
            return finish(action)


@transaction.atomic
def amend_agreement(request, *, agreement_id, expected_revision, description, amount, lifecycle, password, effective_date, reason, idempotency_key):
    office = proof(request, 'finance.amend', password, effective_date, future=True)
    key, amount = cash_key(agreement_id), money(amount)
    if type(expected_revision) is not int or expected_revision < 0 or not isinstance(description, str) or not description.strip() or len(description) > 255 or lifecycle not in {'ACTIVE', 'ENDED', 'CANCELLED'}:
        raise ValidationError('Ελέγξτε την έκδοση, τους νέους όρους και την κατάσταση συμφωνίας.')
    why, digest, payload = request_identity(idempotency_key, {'agreement': key, 'revision': expected_revision,
        'description': fingerprint(description), 'amount': str(amount), 'lifecycle': lifecycle, 'date': effective_date.isoformat()}, reason)
    old = previous_action(office, 'TERMS', digest, payload)
    if old:
        return old
    agreement = scoped_lock(Agreement, office, key)
    latest = AgreementTermsVersion.objects.filter(office=office, agreement=agreement).first()
    if not latest or latest.revision != expected_revision or latest.billing_mode == 'UNREVIEWED' or latest.lifecycle in {'CANCELLED', 'ENDED'} or agreement.status == 'CANCELLED':
        raise ValidationError('Οι όροι άλλαξαν ή δεν επιτρέπουν νέα αλλαγή. Ανανεώστε τη σελίδα.')
    if effective_date < timezone.localdate() or (lifecycle == 'ACTIVE' and effective_date < latest.effective_date):
        raise ValidationError('Η αλλαγή είναι μελλοντική και δεν προηγείται άλλης προγραμματισμένης αλλαγής. Η ακύρωση μπορεί να σταματήσει και προγραμματισμένους όρους.')
    if lifecycle == 'ACTIVE':
        scoped_lock(Entity, office, agreement.entity_id, active=True)
    with audit_context(request.user, why):
        action = new_action(request, office, 'TERMS', effective_date, why, digest, payload, agreement=agreement)
        with correction_context(action):
            change = AgreementChange.objects.create(office=office, correction=action, agreement=agreement,
                previous_revision=expected_revision, description=description, amount=amount,
                billing_mode=latest.billing_mode, lifecycle=lifecycle)
            change.refresh_from_db()
            return finish(action)


@transaction.atomic
def close_period(request, *, closed_through, password, reason, idempotency_key):
    office = proof(request, 'finance.close', password, closed_through)
    why, digest, payload = request_identity(idempotency_key, {'closed_through': closed_through.isoformat()}, reason)
    old = previous_action(office, 'CLOSE', digest, payload)
    if old:
        return old
    with audit_context(request.user, why):
        action = new_action(request, office, 'CLOSE', closed_through, why, digest, payload)
        with correction_context(action):
            FinancePeriodClose.objects.create(office=office, correction=action, closed_through=closed_through)
            return finish(action)


def assert_refunds_reversed(source, day):
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('accounting_cashrefund') IS NOT NULL")
        installed = cursor.fetchone()[0]
    if installed:
        from django.db.models import Q
        rows = CashRefund.objects.filter(office_id=source.office_id, source_cash=source)
        if rows.filter(Q(effective_date__gt=day) | Q(entry__reversal__isnull=True) | Q(entry__reversal__transaction_date__gt=day)).exists():
            raise ValidationError('Χρησιμοποιήστε την ομαδική διόρθωση και επιβεβαιώστε τις συνδεδεμένες επιστροφές.')
