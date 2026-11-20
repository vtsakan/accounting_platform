"""Create reviewed terms and their first obligation in one office-locked action.

The retained Charge is also the durable creation receipt. Its immutable terms
snapshot binds retries, even after later amendments, allocation or reversal.
No model-save hook, migration, cash write or historical backfill is involved.
"""
from datetime import date
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from .charge_services import post_charge, save_terms
from .finance_money import money
from .finance_services import clean_reason, fingerprint, scoped_lock
from .models import Agreement, Charge, Entity
from .office_access import locked_office


def creation_request(value):
    try:
        return 'agreement-create:' + str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Ανανεώστε τη φόρμα για νέα ταυτότητα καταχώρισης.') from None


@transaction.atomic
def create_with_charge(user, instance, *, billing_mode, reason, creation_key,
                       due_date=None, first_charge_amount=None):
    """Return (agreement, charge, replay); failure leaves neither new record."""
    office = locked_office(user, 'finance.write')
    if type(instance) is not Agreement:
        raise PermissionDenied('Η ενέργεια αφορά μόνο νέα συμφωνία.')
    if instance.office_id and str(instance.office_id) != str(office.pk):
        raise PermissionDenied('Δεν έχετε πρόσβαση στη συμφωνία.')
    if billing_mode not in {'ONE_OFF', 'MONTHLY'} or instance.status != 'ACTIVE':
        raise ValidationError('Η νέα συμφωνία απαιτεί ενεργούς όρους και επιλογή τρόπου χρέωσης.')
    day = instance.start_date
    if type(day) is not date or day > timezone.localdate():
        raise ValidationError({'start_date': 'Η άμεση χρέωση απαιτεί ημερομηνία έναρξης έως σήμερα.'})
    due_date = due_date if due_date is not None else day
    if type(due_date) is not date or due_date < day:
        raise ValidationError({'due_date': 'Η προθεσμία πληρωμής δεν μπορεί να προηγείται της έναρξης.'})
    if not isinstance(instance.description, str) or not instance.description.strip() or len(instance.description) > 255:
        raise ValidationError({'description': 'Συμπληρώστε έγκυρη περιγραφή συμφωνίας.'})
    instance.description = instance.description.strip()
    instance.total_amount = money(instance.total_amount)
    amount = money(first_charge_amount) if first_charge_amount is not None else instance.total_amount
    if first_charge_amount is not None and (billing_mode != 'MONTHLY' or day.day == 1):
        raise ValidationError({'first_charge_amount': 'Το ειδικό πρώτο ποσό αφορά μόνο μηνιαία συμφωνία που αρχίζει εντός μήνα.'})
    reason = clean_reason(reason)
    request = creation_request(creation_key)
    entity = scoped_lock(Entity, office, instance.entity_id, active=True)
    if instance.agreement_type not in {'RECEIVABLE', 'PAYABLE'} or not (
            entity.is_customer if instance.agreement_type == 'RECEIVABLE' else entity.is_supplier):
        raise ValidationError({'entity': 'Ο συναλλασσόμενος δεν έχει τον κατάλληλο ρόλο για τη συμφωνία.'})

    existing = Charge.objects.filter(office=office, key_digest=fingerprint(request)).select_related('terms', 'agreement').first()
    period = day.replace(day=1) if billing_mode == 'MONTHLY' else None
    if existing:
        terms = existing.terms
        expected = (entity.pk, instance.agreement_type, instance.description, instance.total_amount,
                    day, billing_mode, 'ACTIVE', amount, day, due_date, period, reason, user.pk)
        retained = (terms.entity_id, terms.direction, terms.description, terms.agreed_amount,
                    terms.start_date, terms.billing_mode, terms.lifecycle, existing.amount,
                    existing.effective_date, existing.due_date, existing.period, existing.reason, existing.actor_id)
        if expected != retained or (instance.pk is not None and instance.pk != existing.agreement_id):
            raise ValidationError('Η ίδια υποβολή χρησιμοποιήθηκε με διαφορετικά στοιχεία. Ξεκινήστε νέα συμφωνία.')
        return existing.agreement, existing, True
    if instance.pk is not None:
        raise ValidationError('Η υπάρχουσα συμφωνία αλλάζει από την ειδική διαδικασία όρων.')
    instance.office_id = office.pk
    save_terms(user, instance, billing_mode=billing_mode, lifecycle='ACTIVE', expected_revision=0, reason=reason)
    terms = instance.terms_versions.get(revision=1)
    charge = post_charge(user, agreement_id=instance.pk, terms_revision=terms.revision,
                         amount=amount, effective_date=day, due_date=due_date, period=period,
                         reason=reason, idempotency_key=request)
    return instance, charge, False
