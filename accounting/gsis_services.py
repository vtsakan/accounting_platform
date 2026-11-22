"""Read the selected sealed pair only after an explicit scoped user action."""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.views.decorators.debug import sensitive_variables

from core.taxis_crypto import open_sealed
from .counterparty_services import ARCHIVED
from .entity_profile_selectors import profile_installed
from .entity_profile_services import audit, profile_context
from .models import Entity, EntityProfile, TaxisCredential
from .office_access import locked_office, record


@transaction.atomic
@sensitive_variables('__ALL__')
def credentials_for_gsis(user, key, subject):
    office = locked_office(user, 'clients.credentials')
    if subject not in {'MAIN', 'SPOUSE'}:
        raise Http404('Η επιλογή κωδικών δεν βρέθηκε.')
    entity = record(Entity, user, key)
    entity = Entity.objects.select_for_update().get(pk=entity.pk, office=office)
    if entity.is_archived:
        raise ValidationError(ARCHIVED)
    if not profile_installed():
        raise ValidationError('Η αποθήκευση κωδικών δεν είναι ακόμη διαθέσιμη.')
    row = TaxisCredential.objects.select_for_update().filter(
        office=office, entity=entity, subject=subject).first()
    if row is None:
        return '', ''
    if subject == 'SPOUSE' and not EntityProfile.objects.filter(
            office=office, entity=entity, spouse_enabled=True).exists():
        raise ValidationError('Η ενότητα συζύγου δεν είναι ενεργή.')
    with profile_context(user, 'REVEAL'):
        username, password = open_sealed(row)
        if not username or not password:
            raise ValidationError('Δεν βρέθηκε πλήρες αποθηκευμένο ζεύγος κωδικών.')
        audit(entity, user, 'REVEAL', [subject])
    return username, password
