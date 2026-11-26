"""Fresh membership, server attribution and retry-safe note creation."""
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404

from .counterparty_services import ARCHIVED
from .models import CounterpartyNote, Entity
from .office_access import locked_office


def note_text(value):
    if not isinstance(value, str) or '\x00' in value:
        raise ValidationError({'body': 'Γράψτε έγκυρο κείμενο σημείωσης.'})
    value = value.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not value or len(value) > 5000:
        raise ValidationError({'body': 'Η σημείωση πρέπει να έχει από 1 έως 5.000 χαρακτήρες.'})
    return value


def note_subject(value):
    if not isinstance(value, str):
        raise ValidationError({'subject': 'Γράψτε έγκυρο θέμα.'})
    value = value.strip()
    if len(value) > 200 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError({'subject': 'Το θέμα έχει έως 200 χαρακτήρες, σε μία γραμμή.'})
    return value


@transaction.atomic
def add_note(user, entity_id, *, body, request_key, subject=''):
    office = locked_office(user, 'clients.write')
    body = note_text(body); subject = note_subject(subject)
    try:
        key = uuid.UUID(str(request_key))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Η φόρμα δεν έχει έγκυρο αναγνωριστικό. Ανοίξτε νέα σημείωση.') from None
    try:
        from .counterparty_retirement_selectors import visible_counterparties
        entity = visible_counterparties(Entity.objects.select_for_update()).get(pk=entity_id, office=office)
    except (Entity.DoesNotExist, ValueError, TypeError):
        raise Http404('Η καρτέλα δεν βρέθηκε.') from None
    existing = CounterpartyNote.objects.filter(office=office, request_key=key).first()
    if existing:
        if existing.entity_id != entity.pk or existing.actor_id != user.pk or existing.body != body or existing.subject != subject:
            raise ValidationError('Η υποβολή έχει ήδη χρησιμοποιηθεί για διαφορετική σημείωση. Ανοίξτε νέα φόρμα.')
        return existing, True
    if entity.is_archived:
        raise ValidationError(ARCHIVED)
    # The PG insert guard supplies its own clock and the fresh username; no
    # client date, actor, office or label is accepted by this service.
    note = CounterpartyNote.objects.create(office=office, entity=entity,
        actor_id=user.pk, actor_label='', request_key=key, subject=subject, body=body)
    note.refresh_from_db()
    return note, False
