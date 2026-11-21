"""Explicit owner-only retirement of an archived nonfinancial identity."""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from .counterparty_retirement_selectors import FINANCIAL_HISTORY, has_financial_history, retirement_installed
from .counterparty_services import FIELDS, STALE, event
from .finance_services import audit_context, canonical, fingerprint
from .models import CounterpartyDeletion, Entity, OfficeAuditEvent
from .office_access import locked_office


@transaction.atomic
def delete_counterparty(user, key, *, version, confirmed):
    office = locked_office(user, 'clients.delete')
    if confirmed is not True or type(version) is not int or version < 0:
        raise ValidationError('Επιβεβαιώστε τη διαγραφή της συγκεκριμένης αρχειοθετημένης εγγραφής.')
    if not retirement_installed():
        raise ValidationError('Η αναβάθμιση της βάσης για τη διαγραφή δεν έχει ολοκληρωθεί.')
    try:
        entity = Entity.objects.select_for_update().get(pk=key, office=office)
    except (Entity.DoesNotExist, ValueError, TypeError):
        raise Http404('Η εγγραφή δεν βρέθηκε.') from None
    existing = CounterpartyDeletion.objects.filter(entity=entity, office=office).first()
    if existing:
        if existing.confirmed_version != version:
            raise ValidationError(STALE)
        return existing, True  # The fresh owner check still precedes every retry.
    if entity.record_version != version:
        raise ValidationError(STALE)
    if not entity.is_archived:
        raise ValidationError('Αρχειοθετήστε πρώτα την εγγραφή πριν από τη διαγραφή.')
    if has_financial_history(entity):
        raise ValidationError(FINANCIAL_HISTORY)
    digest = fingerprint(canonical({name: getattr(entity, name) for name in FIELDS}))
    reason = 'Διαγραφή αρχειοθετημένης εγγραφής χωρίς οικονομικό ιστορικό'
    try:
        with transaction.atomic(), audit_context(user, reason):
            # Remove identity/contact values and release the AFM for a genuinely
            # new record. The retained anonymous row anchors notes/audit only.
            Entity.objects.filter(pk=entity.pk, office=office).update(
                name='Διαγραμμένη εγγραφή #' + str(entity.pk), vat_number=None,
                tax_office='', address='', city='', postal_code='', phone_number='', email='',
                updated_at=timezone.now())
            entity.refresh_from_db()
            marker = CounterpartyDeletion.objects.create(office=office, entity=entity,
                actor=user, actor_label='', confirmed_version=version, contact_digest=digest)
            marker.refresh_from_db()
            event(entity, user, 'delete', list(FIELDS))
            OfficeAuditEvent.objects.create(office=office, actor=user,
                action='client.delete', subject='entity:' + str(entity.pk))
    except IntegrityError as error:
        name = getattr(getattr(error.__cause__, 'diag', None), 'constraint_name', None)
        if name == 'cr005_delete_financial':
            raise ValidationError(FINANCIAL_HISTORY) from None
        if name == 'cr005_delete_archived':
            raise ValidationError('Αρχειοθετήστε πρώτα την εγγραφή πριν από τη διαγραφή.') from None
        raise
    return marker, False
