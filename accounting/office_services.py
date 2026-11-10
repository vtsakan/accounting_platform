"""Atomic office workflows. Authority is always derived from the actor profile."""
from datetime import timedelta
import hashlib
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.http import Http404
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .auth_models import AuthenticatorDevice
from .auth_policy import recent_mfa, state_for
from .auth_services import lock_request_state, lock_state, password_matches
from .capabilities import require_capability
from .membership import change_membership, create_accountant_profile, require_office_profile
from .models import AccountantProfile, Office
from .office_models import OfficeAuditEvent, OwnershipHandover, StaffInvitation

AUDIT_LABELS = {"office.settings": "Ενημέρωση στοιχείων γραφείου", "office.bootstrap": "Αρχική δημιουργία υπευθύνου",
    "invite.create": "Δημιουργία πρόσκλησης", "invite.resend": "Επανέκδοση πρόσκλησης",
    "invite.accept": "Αποδοχή πρόσκλησης", "invite.approve": "Έγκριση λογιστή",
    "invite.cancel": "Ακύρωση πρόσκλησης", "invite.reject": "Απόρριψη αίτησης",
    "member.deactivate": "Απενεργοποίηση λογιστή", "member.reactivate": "Επανενεργοποίηση λογιστή",
    "handover.propose": "Πρόταση παράδοσης ευθύνης", "handover.accept": "Αποδοχή ευθύνης",
    "handover.cancel": "Ακύρωση παράδοσης ευθύνης"}
OFFICE_FIELDS = ("name", "vat_number", "email", "phone", "address", "city", "postal_code")
INVITATION_ERROR = "Η πρόσκληση δεν είναι διαθέσιμη, έχει λήξει ή έχει ήδη χρησιμοποιηθεί."


def email_key(value):
    return str(value).strip().casefold()


def lock_identifiers(*values):
    # Transaction-scoped stable keys serialize cross-office signup of the same
    # recipient/username without changing Django's historical auth.User schema.
    for value in sorted(set(values)):
        key = int.from_bytes(hashlib.sha256(("s14:" + value).encode()).digest()[:8], "big", signed=True)
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def token_digest(invite_id, token, secret=None):
    return salted_hmac("s14-invitation", str(invite_id) + ":" + str(token), secret=secret, algorithm="sha256").hexdigest()


def audit(office, actor, action, *, target=None, subject="", before=None, after=None, operator_ref=""):
    if action not in AUDIT_LABELS:
        raise ValueError("Unsupported office audit action")
    if actor is None and not operator_ref.strip():
        raise ValueError("Operator bootstrap must identify its declared operator")
    return OfficeAuditEvent.objects.create(office=office, actor=actor, target_user=target, action=action,
        operator_ref=operator_ref.strip(),
        subject=str(subject), role_before=before[0] if before else "", role_after=after[0] if after else "",
        active_before=before[1] if before else None, active_after=after[1] if after else None)


def lock_users(*ids):
    return {u.pk: u for u in get_user_model().objects.select_for_update().filter(pk__in=set(ids)).order_by("pk")}


def lock_office(actor, capability):
    profile = require_capability(actor, capability)
    return Office.objects.select_for_update().get(pk=profile.office_id)


def prove_actor(request, office, password, capability):
    state = lock_request_state(request)
    profile = require_capability(request.user, capability)
    if profile.office_id != office.pk or not office.is_active:
        raise PermissionDenied("Η πρόσβαση στο γραφείο δεν είναι πλέον διαθέσιμη.")
    device = getattr(request.user, "otp_device", None)
    confirmed = device and AuthenticatorDevice.objects.filter(pk=device.pk, user_id=request.user.pk, confirmed=True).exists()
    if not password_matches(request.user, password) or not recent_mfa(request) or not confirmed:
        raise ValidationError("Απαιτείται κωδικός πρόσβασης και επαλήθευση συσκευής στα τελευταία πέντε λεπτά.")
    return profile, state


def issuer_valid(invite):
    return (AccountantProfile.objects.filter(user_id=invite.invited_by_id, office_id=invite.office_id,
            role="owner", is_active=True, user__is_active=True, office__is_active=True).exists()
        and state_for(invite.invited_by).revision == invite.inviter_revision)


def invitation_available(invite):
    return bool(invite and invite.status == "pending" and invite.used_at is None
                and invite.expires_at > timezone.now() and issuer_valid(invite))


def exchange_invitation(invite_id, token):
    invite = StaffInvitation.objects.select_related("invited_by", "office").filter(pk=invite_id).first()
    matches = invite and any(constant_time_compare(invite.token_digest, token_digest(invite_id, token, key))
                            for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS])
    if not matches or not invitation_available(invite):
        raise Http404(INVITATION_ERROR)
    return invite


def session_invitation(request, invite_id):
    proof = request.session.get("s14_invitation_proof", {})
    invite = StaffInvitation.objects.select_related("invited_by", "office").filter(pk=invite_id).first()
    if str(invite_id) != proof.get("id") or not invite or not constant_time_compare(invite.token_digest, proof.get("digest", "")) or not invitation_available(invite):
        raise Http404(INVITATION_ERROR)
    return invite


@transaction.atomic
def update_settings(request, values, password):
    office = lock_office(request.user, "office.settings")
    prove_actor(request, office, password, "office.settings")
    if office.settings_version != values["version"]:
        raise ValidationError("Τα στοιχεία άλλαξαν από άλλον υπεύθυνο. Ανανεώστε τη σελίδα και ελέγξτε τις αλλαγές.")
    for name in OFFICE_FIELDS:
        setattr(office, name, values[name].strip())
    office.full_clean()
    office.settings_version += 1
    office.save(update_fields=[*OFFICE_FIELDS, "settings_version", "updated_at"])
    audit(office, request.user, "office.settings", subject=office.settings_version)
    return office


@transaction.atomic
def invite_staff(request, email, password, *, resend=None):
    office = lock_office(request.user, "staff.manage")
    email = email_key(email)
    from django.core.validators import validate_email
    validate_email(email)
    if resend:
        invite = StaffInvitation.objects.select_for_update().filter(pk=resend, office=office, status="pending").first()
        if not invite:
            raise Http404(INVITATION_ERROR)
        email = invite.recipient_email
    lock_identifiers("email:" + email)
    _, state = prove_actor(request, office, password, "staff.manage")
    if not resend:
        users = list(get_user_model().objects.filter(email__iexact=email)[:2])
        if len(users) > 1 or (users and (not users[0].is_active or users[0].is_staff or users[0].is_superuser or
                AccountantProfile.objects.filter(user=users[0]).exists())):
            raise ValidationError("Η διεύθυνση δεν είναι διαθέσιμη για νέα πρόσκληση λογιστή.")
        # Expired unaccepted invitations can be replaced; accepted applications
        # stay pending until an explicit owner decision.
        StaffInvitation.objects.filter(office=office, recipient_email=email, status="pending", expires_at__lte=timezone.now()).update(status="cancelled")
        if StaffInvitation.objects.filter(office=office, recipient_email=email, status__in=["pending", "accepted"]).exists():
            raise ValidationError("Υπάρχει ήδη ανοικτή πρόσκληση για αυτή τη διεύθυνση.")
        invite = StaffInvitation(office=office, invited_by=request.user, inviter_revision=state.revision, recipient_email=email)
    token = secrets.token_urlsafe(32)
    invite.token_digest = token_digest(invite.pk, token)
    invite.invited_by = request.user; invite.inviter_revision = state.revision
    invite.expires_at = timezone.now() + timedelta(seconds=settings.STAFF_INVITATION_SECONDS)
    invite.mail_status = "pending"; invite.save()
    audit(office, request.user, "invite.resend" if resend else "invite.create", subject=invite.pk)
    from .office_mail import schedule_invitation
    schedule_invitation(invite, token)
    return invite


@transaction.atomic
def accept_invitation(request, invite_id, *, username="", password):
    snapshot = session_invitation(request, invite_id)
    office = Office.objects.select_for_update().get(pk=snapshot.office_id)
    identifiers = ["email:" + snapshot.recipient_email]
    if username.strip():
        identifiers.append("username:" + username.strip().casefold())
    lock_identifiers(*identifiers)
    existing = list(get_user_model().objects.filter(email__iexact=snapshot.recipient_email)[:2])
    locked_users = lock_users(snapshot.invited_by_id, *(u.pk for u in existing))
    current_ids = list(get_user_model().objects.filter(email__iexact=snapshot.recipient_email).values_list("pk", flat=True)[:2])
    if set(current_ids) != {u.pk for u in existing}:
        raise ValidationError("Τα στοιχεία του λογαριασμού άλλαξαν. Ανανεώστε τη σελίδα και δοκιμάστε ξανά.")
    existing = [locked_users[key] for key in current_ids]
    invite = StaffInvitation.objects.select_for_update().get(pk=invite_id, office=office)
    session_invitation(request, invite_id)  # Recheck token, issuer and expiry after all locks.
    if len(existing) > 1:
        raise ValidationError("Ο λογαριασμός δεν είναι διαθέσιμος για αυτή την πρόσκληση.")
    if existing:
        user = existing[0]
        if (not user.is_active or user.is_staff or user.is_superuser or not user.check_password(password)
                or AccountantProfile.objects.filter(user=user).exists()):
            raise ValidationError("Τα στοιχεία δεν είναι έγκυρα ή υπάρχει ήδη προφίλ λογιστή.")
    else:
        if get_user_model().objects.filter(username__iexact=username.strip()).exists():
            raise ValidationError("Το όνομα χρήστη δεν είναι διαθέσιμο.")
        user = get_user_model()(username=username.strip(), email=invite.recipient_email, is_active=True, is_staff=False, is_superuser=False)
        password_validation.validate_password(password, user=user)
        user.set_password(password); user.full_clean(); user.save(force_insert=True)
    profile = create_accountant_profile(user_id=user.pk, office_id=office.pk, role="accountant")
    profile.is_active = False; profile.save(update_fields=["is_active", "updated_at"])
    invite.accepted_by = user; invite.used_at = timezone.now(); invite.status = "accepted"
    invite.save(update_fields=["accepted_by", "used_at", "status"])
    audit(office, user, "invite.accept", target=user, subject=invite.pk, after=("accountant", False))
    return user


@transaction.atomic
def decide_invitation(request, invite_id, decision, password):
    office = lock_office(request.user, "staff.manage")
    invite = StaffInvitation.objects.select_for_update().filter(pk=invite_id, office=office).first()
    if invite is None:
        raise Http404(INVITATION_ERROR)
    lock_users(request.user.pk, invite.invited_by_id, *([invite.accepted_by_id] if invite.accepted_by_id else []))
    prove_actor(request, office, password, "staff.manage")
    if decision == "approve":
        if invite.status != "accepted" or not issuer_valid(invite) or not invite.accepted_by_id:
            raise ValidationError("Η αίτηση δεν μπορεί να εγκριθεί.")
        target = AccountantProfile.objects.select_for_update().get(user_id=invite.accepted_by_id, office=office)
        if target.role != "accountant" or target.is_active:
            raise ValidationError("Η κατάσταση του προφίλ άλλαξε. Ανανεώστε τη σελίδα.")
        if target.user.is_staff or target.user.is_superuser:
            raise ValidationError("Η πρόσκληση αφορά κανονικό λογαριασμό λογιστή.")
        change_membership(user_id=target.user_id, office_id=office.pk, role="accountant", is_active=True)
        if email_key(target.user.email) != invite.recipient_email:
            raise ValidationError("Η ηλεκτρονική διεύθυνση του λογαριασμού έχει αλλάξει.")
        state = lock_state(target.user); state.revision += 1; state.save(update_fields=["revision"])
        invite.status = "approved"
        audit(office, request.user, "invite.approve", target=target.user, subject=invite.pk,
              before=("accountant", False), after=("accountant", True))
        from .office_mail import schedule_approval
        schedule_approval(invite)
    elif decision in {"cancel", "reject"} and invite.status in {"pending", "accepted"}:
        invite.status = "rejected" if decision == "reject" else "cancelled"
        audit(office, request.user, "invite." + decision, target=invite.accepted_by, subject=invite.pk)
    else:
        raise ValidationError("Η ενέργεια δεν είναι διαθέσιμη για αυτή την πρόσκληση.")
    invite.save(update_fields=["status"])
    return invite


@transaction.atomic
def set_member_active(request, user_id, active, password):
    office = lock_office(request.user, "staff.manage")
    users = lock_users(request.user.pk, user_id)
    prove_actor(request, office, password, "staff.manage")
    target = AccountantProfile.objects.select_for_update().filter(user_id=user_id, office=office).first()
    if target is None:
        raise Http404("Ο λογιστής δεν βρέθηκε.")
    if users[user_id].is_staff or users[user_id].is_superuser:
        raise PermissionDenied("Η πρόσβαση διαχειριστή πλατφόρμας δεν διαχειρίζεται από αυτή τη σελίδα.")
    if active == target.is_active:
        raise ValidationError("Η κατάσταση του προφίλ έχει ήδη αλλάξει. Ανανεώστε τη σελίδα.")
    if active and StaffInvitation.objects.filter(accepted_by_id=user_id, status="accepted").exists():
        raise ValidationError("Η ενεργοποίηση της νέας αίτησης γίνεται από την έγκριση πρόσκλησης.")
    before = (target.role, target.is_active)
    role = "accountant" if active else target.role  # No silent restoration of ownership.
    change_membership(user_id=user_id, office_id=office.pk, role=role, is_active=active)
    state = lock_state(users[user_id]); state.revision += 1; state.save(update_fields=["revision"])
    if not active:
        StaffInvitation.objects.filter(office=office, invited_by_id=user_id, status="pending").update(status="cancelled")
        OwnershipHandover.objects.filter(office=office, requested_by_id=user_id, status="pending").update(status="cancelled")
    audit(office, request.user, "member.reactivate" if active else "member.deactivate", target=users[user_id],
          before=before, after=(role, active))


@transaction.atomic
def propose_handover(request, recipient_id, password):
    office = lock_office(request.user, "ownership.propose")
    lock_users(request.user.pk, recipient_id)
    _, state = prove_actor(request, office, password, "ownership.propose")
    recipient = AccountantProfile.objects.select_related("user").filter(user_id=recipient_id, office=office, role="accountant",
        is_active=True, user__is_active=True, user__is_staff=False, user__is_superuser=False).first()
    if recipient is None:
        raise ValidationError("Επιλέξτε ενεργό λογιστή του ίδιου γραφείου.")
    OwnershipHandover.objects.filter(office=office, requested_by=request.user, status="pending", expires_at__lte=timezone.now()).update(status="expired")
    if OwnershipHandover.objects.filter(office=office, requested_by=request.user, status="pending").exists():
        raise ValidationError("Υπάρχει ήδη πρόταση παράδοσης σε αναμονή.")
    handover = OwnershipHandover.objects.create(office=office, requested_by=request.user, recipient_id=recipient_id,
        requester_revision=state.revision, expires_at=timezone.now() + timedelta(seconds=settings.OWNERSHIP_HANDOVER_SECONDS))
    audit(office, request.user, "handover.propose", target=recipient.user, subject=handover.pk)
    from .office_mail import schedule_handover
    schedule_handover(handover)
    return handover


@transaction.atomic
def decide_handover(request, key, decision, password):
    office = lock_office(request.user, "ownership.accept")
    handover = OwnershipHandover.objects.select_for_update().filter(pk=key, office=office).first()
    if handover is None or request.user.pk not in {handover.requested_by_id, handover.recipient_id}:
        raise Http404("Η πρόταση δεν βρέθηκε.")
    users = lock_users(handover.requested_by_id, handover.recipient_id)
    prove_actor(request, office, password, "ownership.accept")
    if handover.status != "pending":
        raise ValidationError("Η πρόταση δεν είναι πλέον σε αναμονή.")
    if decision == "cancel":
        handover.status = "cancelled"
    elif decision == "accept" and request.user.pk == handover.recipient_id:
        if handover.expires_at <= timezone.now():
            raise ValidationError("Η πρόταση έχει λήξει.")
        source = AccountantProfile.objects.select_for_update().get(user_id=handover.requested_by_id, office=office)
        target = AccountantProfile.objects.select_for_update().get(user_id=handover.recipient_id, office=office)
        if (source.role != "owner" or not source.is_active or not users[source.user_id].is_active or
            target.role != "accountant" or not target.is_active or not users[target.user_id].is_active or
            users[target.user_id].is_staff or users[target.user_id].is_superuser or
            state_for(users[source.user_id]).revision != handover.requester_revision):
            raise ValidationError("Η εξουσιοδότηση ή η κατάσταση των λογιστών έχει αλλάξει.")
        # Promote before demoting so the database never observes a last-owner loss.
        change_membership(user_id=target.user_id, office_id=office.pk, role="owner", is_active=True)
        change_membership(user_id=source.user_id, office_id=office.pk, role="accountant", is_active=True)
        for user in users.values():
            state = lock_state(user); state.revision += 1; state.save(update_fields=["revision"])
        handover.status = "accepted"
        audit(office, request.user, "handover.accept", target=source.user, subject=handover.pk,
              before=("owner", True), after=("accountant", True))
        audit(office, request.user, "handover.accept", target=target.user, subject=handover.pk,
              before=("accountant", True), after=("owner", True))
    else:
        raise PermissionDenied("Δεν μπορείτε να αποδεχτείτε αυτή την πρόταση.")
    handover.decided_at = timezone.now(); handover.save(update_fields=["status", "decided_at"])
    if decision == "cancel":
        audit(office, request.user, "handover.cancel", target=users[handover.recipient_id], subject=handover.pk)
    return handover
