"""Fresh eligibility, bounded sessions and shared PostgreSQL auth throttles."""
import time
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .auth_models import AuthRateBucket, AuthSecurityState, AuthenticatorDevice
from .models import AccountantProfile

AUTH_ERROR = "Τα στοιχεία σύνδεσης δεν είναι σωστά ή ο λογαριασμός δεν είναι διαθέσιμος."


def eligible(user):
    if not user or not user.is_active:
        return False
    if user.is_staff and user.is_superuser:
        return True  # Platform authority does not confer office business access.
    return AccountantProfile.objects.filter(user_id=user.pk, user__is_active=True,
        is_active=True, office__is_active=True, role__in=["owner", "accountant"]).exists()


def require_eligible(user):
    if not eligible(user):
        raise PermissionDenied("Ο λογαριασμός δεν είναι διαθέσιμος για αυτή την ενέργεια.")


def state_for(user):
    return AuthSecurityState.objects.get_or_create(user_id=user.pk)[0]


def requires_mfa(user, state=None):
    state = state or state_for(user)
    return bool(user.is_staff or user.is_superuser or state.enrolled_at or
        AccountantProfile.objects.filter(user_id=user.pk, role="owner").exists() or
        AuthenticatorDevice.objects.filter(user_id=user.pk, confirmed=True).exists())


def bind_session(request, state=None, *, new_login=False):
    state = state or state_for(request.user)
    now = time.time()
    if new_login:
        request.session["s13_started"] = now
        request.session["s13_password_at"] = now
        request.session["s13_mfa_deadline"] = now + settings.AUTH_MFA_PENDING_SECONDS
    request.session["s13_revision"] = state.revision
    request.session["s13_last_activity"] = now
    request.session.set_expiry(0)  # Browser cookie; server also checks idle/absolute age.


def session_valid(request, state):
    now = time.time()
    try:
        started = float(request.session["s13_started"])
        last = float(request.session["s13_last_activity"])
        revision = int(request.session["s13_revision"])
    except (KeyError, ValueError, TypeError):
        return False
    return (0 <= now - started <= settings.AUTH_ABSOLUTE_SECONDS and
            0 <= now - last <= settings.AUTH_IDLE_SECONDS and revision == state.revision)


def recovery_authorized(request):
    return time.time() < request.session.get("s13_recovery_until", 0)


def recent_mfa(request):
    return bool(request.user.is_verified() and 0 <= time.time() - request.session.get("s13_mfa_at", 0) < settings.AUTH_REAUTH_SECONDS)


@transaction.atomic
def reserve_attempt(action, identifier, remote_addr):
    """Reserve before authentication; concurrent workers share the same budgets.

    REMOTE_ADDR only: untrusted X-Forwarded-For never changes the bucket. Caddy
    shares its bucket until a separately reviewed trusted-client-IP setup exists.
    """
    now = timezone.now()
    limits = settings.AUTH_RATE_LIMITS[action]
    entries = [("ip", str(remote_addr or "unknown"), limits[1]),
               ("identity", str(identifier).strip().casefold(), limits[0])]
    for kind, value, limit in entries:
        digest = salted_hmac("s13-rate", action + ":" + kind + ":" + value, algorithm="sha256").hexdigest()
        bucket, _ = AuthRateBucket.objects.get_or_create(key=digest,
            defaults={"started_at": now, "expires_at": now + timedelta(seconds=settings.AUTH_RATE_WINDOW_SECONDS)})
        bucket = AuthRateBucket.objects.select_for_update().get(pk=digest)
        if bucket.expires_at <= now:
            bucket.attempts = 0; bucket.started_at = now
            bucket.expires_at = now + timedelta(seconds=settings.AUTH_RATE_WINDOW_SECONDS)
        if bucket.attempts >= limit:
            return False  # Bound new identity rows once an IP is exhausted.
        bucket.attempts = min(bucket.attempts + 1, max(limits) + 1)
        bucket.save(update_fields=["attempts", "started_at", "expires_at"])
    return True
