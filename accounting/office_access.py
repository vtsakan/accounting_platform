"""Explicit per-action authority, reusable by future export/file/job adapters."""
from functools import wraps
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.http import Http404

from .membership import require_office_profile
from .models import Agreement, CashAccount, Category, Entity, Office, Transaction
from .capabilities import model_capability, require_capability

MODELS = (Entity, CashAccount, Category, Agreement, Transaction)


def locked_office(user, capability):
    """Use inside an atomic write: office, user, then fresh authority.

    Staff revocation holds the same locks. A writer waiting behind it must
    re-check membership after the wait, before creating any business record.
    """
    profile = require_capability(user, capability)
    office = Office.objects.select_for_update().get(pk=profile.office_id)
    get_user_model().objects.select_for_update().get(pk=user.pk)
    fresh = require_capability(user, capability)
    if fresh.office_id != office.pk or not office.is_active:
        raise PermissionDenied("Η πρόσβαση στο λογιστικό γραφείο δεν είναι πλέον ενεργή.")
    return office


def office_write_guard(capability):
    """Keep legacy calculations intact while serializing their direct writes."""
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method == "POST" and request.user.is_authenticated:
                with transaction.atomic():
                    locked_office(request.user, capability)
                    return view(request, *args, **kwargs)
            return view(request, *args, **kwargs)
        wrapped.office_capability = capability
        return wrapped
    return decorate


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
def save_for_user(instance, user, *, idempotency_key=None):
    if type(instance) not in MODELS:
        raise PermissionDenied("Δεν έχετε πρόσβαση σε αυτή την εγγραφή.")
    office = locked_office(user, model_capability(type(instance), write=True))
    if instance.office_id and str(instance.office_id) != str(office.pk):
        raise PermissionDenied("Δεν έχετε πρόσβαση σε αυτή την εγγραφή.")
    instance.office_id = office.pk
    try:
        with transaction.atomic():
            if isinstance(instance, Transaction):
                if instance.pk:
                    instance.save()
                    return instance
                from .finance_services import post_cash
                import uuid
                saved=post_cash(user,idempotency_key=idempotency_key or str(uuid.uuid4()),
                    amount=instance.amount,transaction_date=instance.transaction_date,transaction_type=instance.transaction_type,
                    cash_account=instance.cash_account_id,category=instance.category_id,entity=instance.entity_id,
                    agreement=instance.agreement_id,description=instance.description,remarks=instance.remarks)
                instance.__dict__.update(saved.__dict__)
            elif isinstance(instance,(CashAccount,Category,Agreement)):
                from .finance_services import save_master
                save_master(instance,user)
            else:
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
