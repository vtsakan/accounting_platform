"""Office-authorised, optimistic edits and atomic archive/restore."""
from contextlib import contextmanager
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from .capabilities import require_capability
from .models import Entity, Office, CounterpartyEvent
from .counterparty_validation import DUPLICATE_AFM

FIELDS = ("name", "is_customer", "is_supplier", "legal_kind", "vat_number", "tax_office", "address", "city", "postal_code", "phone_number", "email")
STALE = "Η εγγραφή άλλαξε από άλλον λογιστή. Ανανεώστε τη σελίδα και ελέγξτε τις αλλαγές."
ARCHIVED = "Η εγγραφή είναι αρχειοθετημένη. Επαναφέρετέ την πριν από νέα εργασία."


def actor_scope(user):
    profile = require_capability(user, "clients.write")
    # Same lock order as staff revocation: office, user, then business record.
    office = Office.objects.select_for_update().get(pk=profile.office_id)
    get_user_model().objects.select_for_update().get(pk=user.pk)
    fresh = require_capability(user, "clients.write")
    if fresh.office_id != office.pk or not office.is_active:
        raise PermissionDenied("Η πρόσβαση στο λογιστικό γραφείο δεν είναι πλέον ενεργή.")
    return office


def locked_record(office, key, version):
    try:
        entity = Entity.objects.select_for_update().get(pk=key, office=office)
    except (Entity.DoesNotExist, ValueError, TypeError):
        raise Http404("Η εγγραφή δεν βρέθηκε.") from None
    if type(version) is not int or entity.record_version != version:
        raise ValidationError(STALE, code="stale")
    return entity


@contextmanager
def safe_write():
    try:
        with transaction.atomic():
            yield
    except IntegrityError as error:
        constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
        if constraint == "entity_office_afm_key":
            raise ValidationError({"vat_number": DUPLICATE_AFM}) from None
        if constraint == "s15_archived_work":
            raise ValidationError(ARCHIVED) from None
        raise


def event(entity, user, action, changed):
    return CounterpartyEvent.objects.create(office_id=entity.office_id, entity=entity, actor=user,
        action=action, version=entity.record_version, changed_fields=sorted(changed))


@transaction.atomic
def save_counterparty(user, values, *, key=None, version=0):
    office = actor_scope(user)
    entity = locked_record(office, key, version) if key is not None else Entity(office=office)
    if entity.is_archived:
        raise ValidationError(ARCHIVED)
    if values.get("legal_kind") not in {Entity.LegalKind.INDIVIDUAL, Entity.LegalKind.BUSINESS}:
        raise ValidationError({"legal_kind": "Επιλέξτε φυσικό πρόσωπο ή επιχείρηση."})
    changed = [name for name in FIELDS if getattr(entity, name) != values[name]]
    for name in FIELDS:
        setattr(entity, name, values[name])
    if key is not None:
        entity.record_version += 1
    with safe_write():
        entity.clean()
        entity.full_clean()
        entity.save()
        entity.refresh_from_db()
        event(entity, user, "create" if key is None else "update", changed)
    return entity


@transaction.atomic
def archive_counterparty(user, key, *, version, archive):
    office = actor_scope(user)
    entity = locked_record(office, key, version)
    if type(archive) is not bool or archive == entity.is_archived:
        raise ValidationError("Η κατάσταση αρχειοθέτησης έχει ήδη αλλάξει. Ανανεώστε τη σελίδα.")
    entity.is_archived = archive
    entity.archived_at = timezone.now() if archive else None
    entity.archived_by = user if archive else None
    entity.record_version += 1
    # Archive/restore preserves legacy identity/contact fields byte-for-byte.
    with safe_write():
        Entity.objects.filter(pk=entity.pk, office=office).update(is_archived=archive,
            archived_at=entity.archived_at, archived_by=entity.archived_by, record_version=entity.record_version,
            updated_at=timezone.now())
        entity.refresh_from_db()
        event(entity, user, "archive" if archive else "restore", ["is_archived"])
    return entity


def validate_active_references(instance):
    """Friendly model errors; the PG trigger also serializes SQL/racing writes."""
    model = instance._meta.model_name
    if model not in {"agreement", "transaction"}:
        return
    fields = ["entity_id"] + (["agreement_id"] if model == "transaction" else [])
    if instance.pk:
        old = type(instance).objects.filter(pk=instance.pk).values(*fields).first()
        if old and all(old[name] == getattr(instance, name) for name in fields):
            return  # Historical rows remain readable and unchanged links stay valid.
    ids = {instance.entity_id} if instance.entity_id else set()
    if model == "transaction" and instance.agreement_id:
        from .models import Agreement
        ids.update(Agreement.objects.filter(pk=instance.agreement_id, office_id=instance.office_id).values_list("entity_id", flat=True))
    if Entity.objects.filter(pk__in=ids, office_id=instance.office_id, is_archived=True).exists():
        raise ValidationError(ARCHIVED, code="archived_counterparty")
