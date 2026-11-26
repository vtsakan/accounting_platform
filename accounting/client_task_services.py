"""Fresh office/object authority and retry-safe, atomic manual task commands."""
from contextlib import contextmanager
from datetime import date, datetime
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.http import Http404

from .counterparty_note_services import add_note, note_text, note_subject
from .counterparty_services import ARCHIVED, STALE
from .finance_services import audit_context, canonical, fingerprint
from .models import AccountantProfile, ClientTask, ClientTaskActivity, CounterpartyNote, Entity
from .office_access import locked_office

OPEN_TASKS = 'Δεν επιτρέπεται η αρχειοθέτηση: υπάρχουν ανοιχτές εργασίες. Ολοκληρώστε τις εργασίες του πελάτη πρώτα.'


def request_id(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Η υποβολή δεν έχει έγκυρο αναγνωριστικό. Ανοίξτε νέα φόρμα.') from None


def deadline(value):
    if not isinstance(value, date) or isinstance(value, datetime) or not date(1900, 1, 1) <= value <= date(2200, 12, 31):
        raise ValidationError({'due_date': 'Επιλέξτε ημερομηνία λήξης από το 1900 έως το 2200.'})
    return value


def installed():
    from .client_task_selectors import tasks_installed
    if not tasks_installed():
        raise ValidationError('Ο χώρος εργασιών δεν είναι ακόμη διαθέσιμος.')


def client(office, entity_id):
    from .counterparty_retirement_selectors import visible_counterparties
    try:
        return visible_counterparties(Entity.objects.select_for_update()).get(pk=entity_id, office=office)
    except (Entity.DoesNotExist, TypeError, ValueError):
        raise Http404('Η καρτέλα δεν βρέθηκε.') from None


def assigned_user(office, value):
    key = getattr(value, 'pk', value)
    if isinstance(key, bool):
        raise ValidationError({'assignee': 'Επιλέξτε ενεργό χρήστη του ίδιου γραφείου.'})
    # Reject foreign users before locking them. Membership changes serialize
    # on this office first, so neither foreign locks nor stale choices grant access.
    try:
        profile = AccountantProfile.objects.filter(office=office, user_id=key, is_active=True,
            user__is_active=True, role__in=['accountant', 'owner']).first()
    except (TypeError, ValueError):
        profile = None
    if profile is None:
        raise ValidationError({'assignee': 'Επιλέξτε ενεργό χρήστη του ίδιου γραφείου.'})
    try:
        return get_user_model().objects.select_for_update().get(pk=profile.user_id, is_active=True)
    except get_user_model().DoesNotExist:
        raise ValidationError({'assignee': 'Ο χρήστης δεν είναι πλέον ενεργός. Επιλέξτε άλλον υπεύθυνο.'}) from None


def replay(office, key, user, payload):
    event = ClientTaskActivity.objects.filter(office=office, request_key=key).select_related('note', 'task').first()
    if event is not None and (event.actor_id != user.pk or event.payload_sha256 != payload):
        raise ValidationError('Η υποβολή χρησιμοποιήθηκε για διαφορετική ενέργεια. Ανοίξτε νέα φόρμα.')
    return event


@contextmanager
def task_context(user, key, payload):
    names = ('accounting.cr006_request', 'accounting.cr006_payload')
    with audit_context(user, 'Διαχείριση εργασίας πελάτη'):
        with connection.cursor() as cursor:
            cursor.execute('SELECT current_setting(%s,true),current_setting(%s,true)', names)
            previous = cursor.fetchone()
            for name, value in zip(names, (str(key), payload)):
                cursor.execute('SELECT set_config(%s,%s,true)', [name, value])
        try:
            yield
        except DatabaseError:
            if connection.in_atomic_block:
                connection.set_rollback(True)
            raise
        finally:
            if not connection.needs_rollback:
                with connection.cursor() as cursor:
                    for name, value in zip(names, previous):
                        cursor.execute('SELECT set_config(%s,%s,true)', [name, value or ''])


def create_locked(user, office, person, note, *, body, due_date, assignee, subject=''):
    if person.is_archived:
        raise ValidationError(ARCHIVED)
    if ClientTask.objects.filter(source_note=note, office=office).exists():
        raise ValidationError('Αυτή η σημείωση έχει ήδη συνδεθεί με εργασία. Ανοίξτε την υπάρχουσα εργασία.')
    target = assigned_user(office, assignee)
    task = ClientTask.objects.create(office=office, entity=person, source_note=note,
        creator=user, creator_label='', assignee=target, assignee_label='', subject=subject, body=body, due_date=due_date)
    task.refresh_from_db()
    return task


@transaction.atomic
def add_work_note(user, entity_id, *, body, request_key, as_task=False, due_date=None, assignee=None, subject=''):
    office = locked_office(user, 'tasks.write')
    installed(); key = request_id(request_key); body = note_text(body); subject = note_subject(subject)
    if type(as_task) is not bool:
        raise ValidationError('Επιλέξτε αν η σημείωση θα γίνει εργασία.')
    if as_task:
        due_date = deadline(due_date)
        target_id = getattr(assignee, 'pk', assignee) if assignee is not None else user.pk
    else:
        due_date = None; target_id = None
    payload = fingerprint(canonical({'action': 'work-note', 'entity': str(entity_id), 'body': body,
        **({'subject': subject} if subject else {}), 'as_task': as_task, 'due_date': due_date.isoformat() if due_date else None, 'assignee': str(target_id) if target_id is not None else None}))
    person = client(office, entity_id)
    old = replay(office, key, user, payload)
    if old:
        return old.note, old.task, True
    # Pre-CR006 plain-note retries must stay plain. Conversion of an old note
    # uses its explicit new request, rather than changing an earlier submission.
    legacy = CounterpartyNote.objects.filter(office=office, request_key=key).first()
    if legacy is not None:
        if as_task:
            raise ValidationError('Η σημείωση έχει ήδη αποθηκευτεί. Χρησιμοποιήστε «Να γίνει εργασία» στη σημείωση.')
        note, _ = add_note(user, entity_id, body=body, subject=subject, request_key=key)
        return note, None, True
    if person.is_archived:
        raise ValidationError(ARCHIVED)
    if as_task:
        assigned_user(office, target_id)  # Reject an invalid choice before creating the note.
    with task_context(user, key, payload):
        note, _ = add_note(user, entity_id, body=body, subject=subject, request_key=key)
        if as_task:
            task = create_locked(user, office, person, note, body=body, due_date=due_date, assignee=target_id, subject=subject)
        else:
            task = None
            ClientTaskActivity.objects.create(office=office, note=note, task=None, request_key=key,
                payload_sha256=payload, actor=user, actor_label='', action='NOTE')
    return note, task, False


@transaction.atomic
def convert_note(user, entity_id, note_id, *, body, due_date, assignee, request_key, subject=None):
    office = locked_office(user, 'tasks.write')
    installed(); key = request_id(request_key); body = note_text(body); due_date = deadline(due_date)
    target_id = getattr(assignee, 'pk', assignee) if assignee is not None else user.pk
    person = client(office, entity_id)
    try:
        note = CounterpartyNote.objects.select_for_update().get(pk=note_id, office=office, entity=person)
    except (CounterpartyNote.DoesNotExist, ValueError, TypeError, ValidationError):
        raise Http404('Η σημείωση δεν βρέθηκε.') from None
    subject = note_subject(note.subject if subject is None else subject)
    payload = fingerprint(canonical({**({'subject': subject} if subject else {}), 'action': 'convert', 'note': str(note.pk), 'entity': str(person.pk),
        'body': body, 'due_date': due_date.isoformat(), 'assignee': str(target_id)}))
    old = replay(office, key, user, payload)
    if old:
        return old.task, True
    with task_context(user, key, payload):
        task = create_locked(user, office, person, note, body=body, due_date=due_date, assignee=target_id, subject=subject)
    return task, False


def may_change(task, user, profile):
    return profile.role == 'owner' or user.pk in (task.creator_id, task.assignee_id)


@transaction.atomic
def change_task(user, key, *, version, request_key, action, body=None, due_date=None, assignee=None, subject=None):
    office = locked_office(user, 'tasks.write')
    installed(); nonce = request_id(request_key)
    if action not in {'UPDATE', 'COMPLETE', 'REOPEN', 'PENDING', 'RESUME'} or type(version) is not int or version < 0:
        raise ValidationError('Η ενέργεια ή η έκδοση της εργασίας δεν είναι έγκυρη.')
    try:
        # Office serialisation precedes the record locks on every mutation.
        task = ClientTask.objects.select_for_update().get(pk=key, office=office)
    except (ClientTask.DoesNotExist, ValueError, TypeError, ValidationError):
        raise Http404('Η εργασία δεν βρέθηκε.') from None
    person = client(office, task.entity_id)
    from .capabilities import require_capability
    values = {'action': action, 'task': str(task.pk), 'version': version}
    if action == 'UPDATE':
        body = note_text(body); due_date = deadline(due_date)
        subject = note_subject(task.subject if subject is None else subject)
        target_id = getattr(assignee, 'pk', assignee) if assignee is not None else user.pk
        values.update(body=body, due_date=due_date.isoformat(), assignee=str(target_id))
        if subject: values['subject'] = subject
    payload = fingerprint(canonical(values))
    old = replay(office, nonce, user, payload)
    if old:
        return task, True
    if not may_change(task, user, require_capability(user, 'tasks.write')):
        raise PermissionDenied('Η εργασία αλλάζει μόνο από τον δημιουργό, τον υπεύθυνο ή τον ιδιοκτήτη.')
    if task.version != version:
        raise ValidationError(STALE)
    if action == 'UPDATE':
        if person.is_archived:
            raise ValidationError(ARCHIVED)
        task.body, task.due_date, task.subject = body, due_date, subject
        if task.assignee_id != target_id:
            task.assignee = assigned_user(office, target_id)
    else:
        target_status = {'COMPLETE': 'DONE', 'REOPEN': 'OPEN', 'PENDING': 'WAIT', 'RESUME': 'OPEN'}[action]
        if (action == 'PENDING' and task.status != 'OPEN' or action == 'RESUME' and task.status != 'WAIT'
                or action == 'REOPEN' and task.status != 'DONE'):
            raise ValidationError('Η ενέργεια δεν αντιστοιχεί στην τρέχουσα κατάσταση της εργασίας.')
        if task.status == target_status:
            raise ValidationError('Η κατάσταση της εργασίας έχει ήδη αλλάξει. Ανανεώστε τη σελίδα.')
        if person.is_archived and target_status != 'DONE':
            raise ValidationError(ARCHIVED)
        task.status = target_status
    task.version += 1
    with task_context(user, nonce, payload):
        task.save()
    task.refresh_from_db()
    return task, False
