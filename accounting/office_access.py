"""Explicit per-action authority, reusable by future export/file/job adapters."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.http import Http404

from .membership import require_office_profile
from .models import Agreement, CashAccount, Category, Entity, Transaction
from .capabilities import model_capability, require_capability

MODELS = (Entity, CashAccount, Category, Agreement, Transaction)


def records(model, user):
    if model not in MODELS:
        raise PermissionDenied("Η πρόσβαση σε αυτόν τον τύπο εγγραφής δεν υποστηρίζεται.")
    profile = require_capability(user, model_capability(model))
    return model.objects.filter(office_id=profile.office_id)


def record(model, user, key):
    queryset = records(model, user)
    try:
        return queryset.get(pk=key)
    except (model.DoesNotExist, ValueError, TypeError):
        raise Http404("Η εγγραφή δεν βρέθηκε.") from None


@transaction.atomic
def save_for_user(instance, user):
    profile = require_office_profile(user)
    if type(instance) not in MODELS or (instance.office_id and str(instance.office_id) != str(profile.office_id)):
        raise PermissionDenied("Δεν έχετε πρόσβαση σε αυτή την εγγραφή.")
    require_capability(user, model_capability(type(instance), write=True))
    instance.office_id = profile.office_id
    try:
        with transaction.atomic():
            instance.save()
    except IntegrityError as error:
        if getattr(getattr(error.__cause__, 'diag', None), 'constraint_name', None) == 's15_archived_work':
            from .counterparty_services import ARCHIVED
            raise ValidationError(ARCHIVED) from None
        raise
    return instance


def execution_record(*, user_id, expected_office_id, model, key, capability=None):
    """Call at execution, not enqueue time; expected office is a check, not authority."""
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None or str(require_office_profile(user).office_id) != str(expected_office_id):
        raise PermissionDenied("Η εξουσιοδότηση για το λογιστικό γραφείο δεν είναι πλέον ενεργή.")
    if capability is not None:
        require_capability(user, capability)
    return record(model, user, key)


def validate_filter_ids(request):
    for parameter, model in (("cash_account", CashAccount), ("category", Category),
                             ("entity", Entity), ("entity_id", Entity)):
        value = request.GET.get(parameter)
        if value:
            try:
                int(value)
            except ValueError:
                # Preserve the separately tracked S29 malformed-filter defects;
                # those paths still fail generically and return no office data.
                continue
            record(model, request.user, value)
