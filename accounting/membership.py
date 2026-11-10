"""Trusted membership services; no HTTP caller may use submitted office IDs.

S14 must supply actor/capability checks before exposing these operations. No
signals, default office, implicit transfer, role promotion or reactivation.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from .models import AccountantProfile, Office

DENIED = "Απαιτείται ενεργό προφίλ λογιστή σε ενεργό λογιστικό γραφείο."


def membership_error(message, code):
    raise ValidationError(message, code=code)


@transaction.atomic
def create_office(*, name):
    office = Office(name=name.strip())
    office.full_clean()
    office.save(force_insert=True)
    return office


@transaction.atomic
def create_accountant_profile(*, user_id, office_id, role):
    if role not in AccountantProfile.Role.values:
        membership_error("Ο ρόλος δεν είναι έγκυρος.", "invalid_role")
    # Lock the existing user, not an absent profile: competing first assignments
    # then serialize even when they target different offices.
    user = get_user_model().objects.select_for_update().get(pk=user_id)
    office = Office.objects.select_for_update().get(pk=office_id)
    if not user.is_active or not office.is_active:
        membership_error("Ο χρήστης και το γραφείο πρέπει να είναι ενεργοί.", "inactive_membership")
    existing = AccountantProfile.objects.select_for_update().filter(user_id=user.pk).first()
    if existing:
        if existing.office_id != office.pk or existing.role != role or not existing.is_active:
            membership_error("Υπάρχει ήδη διαφορετικό ή ανενεργό προφίλ λογιστή.", "membership_conflict")
        return existing
    return AccountantProfile.objects.create(user=user, office=office, role=role)


@transaction.atomic
def change_membership(*, user_id, office_id, role, is_active):
    """Explicit same-office changes only; office handover needs S14 policy."""
    if role not in AccountantProfile.Role.values or type(is_active) is not bool:
        membership_error("Τα στοιχεία του προφίλ δεν είναι έγκυρα.", "invalid_membership")
    user = get_user_model().objects.select_for_update().get(pk=user_id)
    office = Office.objects.select_for_update().get(pk=office_id)
    profile = AccountantProfile.objects.select_for_update().get(user_id=user.pk)
    if profile.office_id != office.pk:
        membership_error("Η αλλαγή γραφείου απαιτεί ξεχωριστή εγκεκριμένη διαδικασία.", "office_transfer_denied")
    if is_active and (not user.is_active or not office.is_active):
        membership_error("Ο χρήστης και το γραφείο πρέπει να είναι ενεργοί.", "inactive_membership")
    profile.role, profile.is_active = role, is_active
    profile.save(update_fields=["role", "is_active", "updated_at"])
    return profile


def require_office_profile(user):
    """Fresh DB lookup on every action; never trust cached reverse relations."""
    if not user.is_authenticated:
        raise PermissionDenied(DENIED)
    profile = AccountantProfile.objects.select_related("office").filter(
        user_id=user.pk, user__is_active=True, is_active=True, office__is_active=True,
        role__in=AccountantProfile.Role.values).first()
    if profile is None:
        raise PermissionDenied(DENIED)
    return profile
