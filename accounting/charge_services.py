"""Office-locked S22 terms review and immutable source-bound charge posting."""
from contextlib import contextmanager
from datetime import date
import re
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from .models import Agreement, AgreementTermsVersion, Charge, Entity
from .office_access import locked_office
from .finance_money import money
from .finance_services import audit_context, canonical, clean_reason, fingerprint, scoped_lock

STALE = 'Οι όροι άλλαξαν. Ανανεώστε τη σελίδα πριν από την καταχώριση.'


@contextmanager
def terms_context(mode, lifecycle):
    names = ('accounting.s22_billing_mode', 'accounting.s22_lifecycle')
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_setting(%s,true),current_setting(%s,true)', names)
        before = cursor.fetchone()
        for name, value in zip(names, (mode, lifecycle)):
            cursor.execute('SELECT set_config(%s,%s,true)', [name, value])
    try:
        yield
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                for name, value in zip(names, before):
                    cursor.execute('SELECT set_config(%s,%s,true)', [name, value or ''])


@transaction.atomic
def save_terms(user, instance, *, billing_mode='UNREVIEWED', lifecycle='UNREVIEWED', expected_revision=None,
               reason='Ενημέρωση όρων συμφωνίας'):
    office = locked_office(user, 'finance.write')
    if instance.office_id and instance.office_id != office.pk:
        raise PermissionDenied('Δεν έχετε πρόσβαση στη συμφωνία.')
    instance.office_id = office.pk
    latest = None
    if instance.pk:
        scoped_lock(Agreement, office, instance.pk)
        latest = AgreementTermsVersion.objects.filter(office=office, agreement_id=instance.pk).first()
    revision = latest.revision if latest else 0
    # Historical clients can edit an unreviewed revision-0 record. Rendered
    # forms always include a revision; reviewed records never accept omission.
    if expected_revision is None and revision == 0:
        expected_revision = 0
    if type(expected_revision) is not int or expected_revision != revision:
        raise ValidationError(STALE)
    if billing_mode not in {'UNREVIEWED', 'ONE_OFF', 'MONTHLY'} or lifecycle not in {'UNREVIEWED', 'DRAFT', 'ACTIVE', 'ENDED', 'CANCELLED'}:
        raise ValidationError('Επιλέξτε έγκυρο τρόπο χρέωσης και κατάσταση όρων.')
    if billing_mode == 'UNREVIEWED':
        lifecycle = 'UNREVIEWED'
    elif lifecycle == 'UNREVIEWED':
        raise ValidationError('Επιλέξτε την κατάσταση των ελεγμένων όρων.')
    if latest and Charge.objects.filter(office=office, agreement_id=instance.pk).exists() and (
            billing_mode != latest.billing_mode or lifecycle != latest.lifecycle):
        raise ValidationError('Υπάρχουν καταχωρισμένες χρεώσεις. Οι αλλαγές όρων απαιτούν την ειδική διαδικασία ιστορικού.')
    if billing_mode != 'UNREVIEWED':
        if not isinstance(instance.description, str) or not instance.description.strip() or len(instance.description) > 255:
            raise ValidationError({'description': 'Συμπληρώστε έγκυρη περιγραφή συμφωνίας.'})
        if type(instance.start_date) is not date:
            raise ValidationError({'start_date': 'Επιλέξτε έγκυρη ημερομηνία έναρξης.'})
        entity = scoped_lock(Entity, office, instance.entity_id, active=True)
        if instance.agreement_type not in {'RECEIVABLE', 'PAYABLE'} or not (
                entity.is_customer if instance.agreement_type == 'RECEIVABLE' else entity.is_supplier):
            raise ValidationError({'entity': 'Ο συναλλασσόμενος δεν έχει τον κατάλληλο ρόλο για τη συμφωνία.'})
    if instance.status == 'CANCELLED' and lifecycle not in {'UNREVIEWED', 'CANCELLED'}:
        raise ValidationError('Η ακυρωμένη συμφωνία δεν ενεργοποιείται με απλή επεξεργασία όρων.')
    reason = clean_reason(reason)
    from .finance_services import save_master
    with terms_context(billing_mode, lifecycle), audit_context(user, reason):
        # Reuse the existing role/office/money checks and historical cash guard.
        # The S22 trigger writes the immutable snapshot, including raw SQL paths.
        save_master(instance, user, reason=reason)
    instance.refresh_from_db()
    return instance


def period_start(value):
    if value in (None, ''):
        return None
    if type(value) is date and value.day == 1:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{4}-[0-9]{2}', value):
        try:
            return date.fromisoformat(value + '-01')
        except ValueError:
            pass
    raise ValidationError({'period': 'Επιλέξτε μήνα στη μορφή ΕΕΕΕ-ΜΜ.'})


def source_identity(agreement_id, mode, period=None):
    """Shared by manual posting and later schedulers; no version/schedule ID."""
    if mode == 'ONE_OFF' and period is None:
        return f'agreement:{agreement_id}:one-off'
    if mode == 'MONTHLY' and type(period) is date and period.day == 1:
        return f'agreement:{agreement_id}:month:{period:%Y-%m}'
    raise ValidationError('Η περίοδος δεν αντιστοιχεί στον τρόπο χρέωσης της συμφωνίας.')


@transaction.atomic
def post_charge(user, *, agreement_id, terms_revision, amount, effective_date, due_date, period=None,
                reason, idempotency_key):
    office = locked_office(user, 'finance.write')
    if isinstance(agreement_id, str) and agreement_id.isascii() and agreement_id.isdecimal() and len(agreement_id) <= 19:
        agreement_id = int(agreement_id)
    if type(agreement_id) is not int or not 0 < agreement_id <= 9223372036854775807:
        raise ValidationError('Επιλέξτε έγκυρη συμφωνία.')
    amount, period, reason = money(amount), period_start(period), clean_reason(reason)
    if type(terms_revision) is not int or terms_revision < 0:
        raise ValidationError(STALE)
    if type(effective_date) is not date or type(due_date) is not date or effective_date > timezone.localdate() or due_date < effective_date:
        raise ValidationError('Ελέγξτε την ημερομηνία χρέωσης και τη λήξη της προθεσμίας.')
    if not isinstance(idempotency_key, str) or not 8 <= len(idempotency_key) <= 160 or any(ord(c) < 33 for c in idempotency_key):
        raise ValidationError('Απαιτείται έγκυρη ταυτότητα καταχώρισης χρέωσης.')
    payload = fingerprint(canonical({'agreement': agreement_id, 'revision': terms_revision, 'amount': str(amount),
                                    'effective': effective_date.isoformat(), 'due': due_date.isoformat(),
                                    'period': period.isoformat() if period else None, 'reason': fingerprint(reason)}))
    key = fingerprint(idempotency_key)
    existing = Charge.objects.filter(office=office, key_digest=key).first()
    if existing:
        if existing.payload_digest != payload:
            raise ValidationError('Η ταυτότητα καταχώρισης χρησιμοποιήθηκε με διαφορετικά στοιχεία.')
        return existing
    agreement = scoped_lock(Agreement, office, agreement_id)
    terms = AgreementTermsVersion.objects.filter(office=office, agreement=agreement).first()
    if terms is None or terms.revision != terms_revision:
        raise ValidationError(STALE)
    if terms.billing_mode == 'UNREVIEWED' or terms.lifecycle != 'ACTIVE' or agreement.status == 'CANCELLED':
        raise ValidationError('Απαιτούνται ελεγμένοι ενεργοί όροι και ρητή επιλογή τρόπου χρέωσης.')
    if (terms.entity_id, terms.direction, terms.agreed_amount, terms.description, terms.start_date) != (
            agreement.entity_id, agreement.agreement_type, agreement.total_amount, agreement.description, agreement.start_date):
        raise ValidationError(STALE)
    entity = scoped_lock(Entity, office, terms.entity_id, active=True)
    if not (entity.is_customer if terms.direction == 'RECEIVABLE' else entity.is_supplier):
        raise ValidationError('Ο συναλλασσόμενος δεν έχει τον κατάλληλο ρόλο για τη χρέωση.')
    if effective_date < terms.effective_date:
        raise ValidationError({'effective_date': 'Η χρέωση δεν μπορεί να προηγείται της έναρξης των όρων.'})
    source = source_identity(agreement.pk, terms.billing_mode, period)
    duplicate = Charge.objects.filter(office=office, source_key=source).first()
    if duplicate:
        raise ValidationError('Η χρέωση αυτής της πηγής υπάρχει ήδη. Αναφορά: ' + str(duplicate.pk))
    if terms.billing_mode == 'ONE_OFF' and amount != terms.agreed_amount:
        raise ValidationError({'amount': 'Η εφάπαξ χρέωση ισούται με το ελεγμένο συμφωνημένο ποσό.'})
    if terms.billing_mode == 'MONTHLY':
        first = terms.start_date.replace(day=1)
        if period < first or period != effective_date.replace(day=1):
            raise ValidationError({'period': 'Ο μήνας πρέπει να αντιστοιχεί στην ημερομηνία χρέωσης και να μην προηγείται της συμφωνίας.'})
        if amount != terms.agreed_amount and not (period == first and terms.start_date.day != 1):
            raise ValidationError({'amount': 'Για πλήρη μήνα χρησιμοποιείται το ελεγμένο μηνιαίο ποσό.'})
        # A partial first period uses the explicitly entered reviewed amount and
        # reason. No VAT calculation, day-count or automatic proration occurs.
    with audit_context(user, reason):
        return Charge.objects.create(office=office, agreement=agreement, terms=terms, entity=entity,
                                     direction=terms.direction, amount=amount, currency='EUR', effective_date=effective_date,
                                     due_date=due_date, period=period, source_key=source, key_digest=key, payload_digest=payload,
                                     description=terms.description, actor=user, reason=reason)
