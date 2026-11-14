"""Locked MFA lifecycle; no password-only reset of an enrolled authenticator."""
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from core.auth_crypto import cipher
from .auth_models import AuthenticatorDevice, AuthSecurityState, MFARecoveryCode
from .auth_policy import recent_mfa, recovery_authorized, require_eligible


def code_digest(user_id, code, secret=None):
    return salted_hmac("s13-backup", str(user_id) + ":" + code, secret=secret, algorithm="sha256").hexdigest()


def lock_state(user):
    get_user_model().objects.select_for_update().get(pk=user.pk)
    state, _ = AuthSecurityState.objects.get_or_create(user_id=user.pk)
    return AuthSecurityState.objects.select_for_update().get(pk=state.pk)


def lock_request_state(request):
    state = lock_state(request.user)
    if state.revision != request.session.get("s13_revision"):
        raise PermissionDenied("Η συνεδρία άλλαξε. Συνδεθείτε ξανά.")
    return state


def password_matches(user, password):
    return get_user_model().objects.get(pk=user.pk).check_password(password)


def may_manage(request, state):
    enrolled = bool(state.enrolled_at or AuthenticatorDevice.objects.filter(user=request.user, confirmed=True).exists())
    return not enrolled or recent_mfa(request) or recovery_authorized(request)


def issue_codes(user):
    MFARecoveryCode.objects.filter(user=user).delete()
    codes = [secrets.token_hex(16) for _ in range(8)]
    MFARecoveryCode.objects.bulk_create([MFARecoveryCode(user=user, digest=code_digest(user.pk, code)) for code in codes])
    return codes


@transaction.atomic
def begin_enrollment(request, password):
    require_eligible(request.user)
    state = lock_request_state(request)
    if not password_matches(request.user, password) or not may_manage(request, state):
        raise PermissionDenied("Απαιτείται κωδικός πρόσβασης και πρόσφατη επαλήθευση ή κωδικός ανάκτησης.")
    device = AuthenticatorDevice(user=request.user, name="Εφαρμογή επαλήθευσης", confirmed=False,
        setup_expires_at=timezone.now() + timedelta(seconds=settings.AUTH_MFA_PENDING_SECONDS))
    secret = secrets.token_bytes(20)
    device.encrypted_secret = cipher(request.user.pk, device.secret_salt).encrypt(secret).decode("ascii")
    device.save()
    return device


def complete_enrollment(request, key, token):
    require_eligible(request.user)
    with transaction.atomic():
        state = lock_request_state(request)
        if not may_manage(request, state):
            raise PermissionDenied("Απαιτείται πρόσφατη επαλήθευση ή κωδικός ανάκτησης.")
        device = AuthenticatorDevice.objects.select_for_update().filter(pk=key, user=request.user,
            confirmed=False, setup_expires_at__gt=timezone.now()).first()
        if device is None or not device.verify_token(token):
            return None  # Commit failed-attempt throttling; never roll it back.
        AuthenticatorDevice.objects.filter(user=request.user).exclude(pk=device.pk).delete()
        device.confirmed = True; device.save(update_fields=["confirmed"])
        state.revision += 1; state.enrolled_at = timezone.now(); state.save()
        codes = issue_codes(request.user)
        return device, state, codes


def verify_authenticator(request, token):
    user = request.user
    require_eligible(user)
    with transaction.atomic():
        lock_request_state(request)
        device = AuthenticatorDevice.objects.select_for_update().filter(user=user, confirmed=True).first()
        return device if device and device.verify_token(token) else None


def consume_recovery(request, code):
    user = request.user
    require_eligible(user)
    normalized = str(code).replace("-", "").replace(" ", "").strip().lower()
    with transaction.atomic():
        state = lock_request_state(request)
        hashes = [code_digest(user.pk, normalized, key) for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]]
        match = MFARecoveryCode.objects.select_for_update().filter(user=user, digest__in=hashes).first()
        if match is None:
            return None
        match.delete()
        AuthenticatorDevice.objects.filter(user=user).update(confirmed=False)
        state.revision += 1; state.save(update_fields=["revision"])
        return state


@transaction.atomic
def regenerate_codes(request, password):
    require_eligible(request.user)
    state = lock_request_state(request)
    if not password_matches(request.user, password) or not recent_mfa(request):
        raise PermissionDenied("Απαιτείται κωδικός πρόσβασης και πρόσφατη επαλήθευση.")
    state.revision += 1; state.save(update_fields=["revision"])
    return state, issue_codes(request.user)
