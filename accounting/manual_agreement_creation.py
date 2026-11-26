"""Terms-only creation. Retries bind to a receipt, never to a financial charge."""
from datetime import date
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .charge_services import save_terms
from .finance_money import money
from .finance_services import audit_context, canonical, clean_reason, fingerprint, scoped_lock
from .models import Agreement, Charge, Entity
from .cr010_models import AgreementCreationReceipt
from .office_access import locked_office


@transaction.atomic
def create_manual(user, instance, *, billing_mode, reason, creation_key):
    office = locked_office(user, 'finance.write')
    try:
        key = uuid.UUID(str(creation_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Ανοίξτε νέα φόρμα συμφωνίας.') from None
    if type(instance) is not Agreement or instance.office_id not in (None, office.pk):
        raise ValidationError('Η ενέργεια αφορά νέα συμφωνία του γραφείου.')
    if billing_mode not in {'ONE_OFF', 'MONTHLY'} or instance.status != 'ACTIVE' or type(instance.start_date) is not date:
        raise ValidationError('Ελέγξτε τους όρους της νέας συμφωνίας.')
    if instance.start_date > timezone.localdate():
        raise ValidationError({'start_date': 'Η ημερομηνία έναρξης πρέπει να είναι έως σήμερα.'})
    instance.description = str(instance.description or '').strip()
    if not instance.description or len(instance.description) > 255:
        raise ValidationError({'description': 'Συμπληρώστε περιγραφή συμφωνίας έως 255 χαρακτήρες.'})
    instance.total_amount = money(instance.total_amount)
    reason = clean_reason(reason)
    entity = scoped_lock(Entity, office, instance.entity_id, active=True)
    if instance.agreement_type not in {'RECEIVABLE', 'PAYABLE'} or not (
            entity.is_customer if instance.agreement_type == 'RECEIVABLE' else entity.is_supplier):
        raise ValidationError({'entity': 'Ο συναλλασσόμενος δεν έχει τον κατάλληλο ρόλο.'})
    payload = fingerprint(canonical({'actor': user.pk, 'entity': entity.pk, 'direction': instance.agreement_type,
        'description': instance.description, 'amount': str(instance.total_amount), 'day': instance.start_date.isoformat(),
        'mode': billing_mode, 'reason': reason}))
    previous = AgreementCreationReceipt.objects.filter(office=office, request_key=key).select_related('agreement').first()
    if previous:
        if previous.actor_id != user.pk or previous.payload_sha256 != payload:
            raise ValidationError('Η υποβολή χρησιμοποιήθηκε με διαφορετικά στοιχεία. Ανοίξτε νέα συμφωνία.')
        return previous.agreement, True
    # A stale browser form from CR002 must not create a second agreement.
    if Charge.objects.filter(office=office, key_digest=fingerprint('agreement-create:' + str(key))).exists():
        raise ValidationError('Αυτή η παλιά υποβολή έχει ήδη καταχωριστεί. Ανοίξτε την υπάρχουσα συμφωνία.')
    if instance.pk is not None:
        raise ValidationError('Η υπάρχουσα συμφωνία αλλάζει από τη διαδικασία αλλαγής όρων.')
    instance.office_id = office.pk
    save_terms(user, instance, billing_mode=billing_mode, lifecycle='ACTIVE', expected_revision=0, reason=reason)
    with audit_context(user, reason):
        AgreementCreationReceipt.objects.create(office=office, request_key=key, agreement=instance,
            actor=user, payload_sha256=payload)
    return instance, False
