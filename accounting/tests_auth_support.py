"""Explicit authenticated fixtures for earlier office/financial contracts.

No runtime bypass is provided. Privileged fixtures pass the real MFA view with
a synthetic device; production views and middleware always enforce the policy.
"""
import secrets
from datetime import timedelta
from types import SimpleNamespace

from django.utils import timezone
from django_otp.oath import totp

from core.auth_crypto import cipher
from .auth_models import AuthenticatorDevice
from .auth_policy import bind_session, eligible, requires_mfa, state_for


def staff_client_login(client, user):
    client.force_login(user)
    session = client.session
    state = state_for(user)
    bind_session(SimpleNamespace(user=user, session=session), state, new_login=True)
    session.save()
    if eligible(user) and requires_mfa(user, state):
        device = AuthenticatorDevice.objects.filter(user=user, confirmed=True).first()
        if device is None:
            device = AuthenticatorDevice(user=user, name="ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΣΚΕΥΗ", confirmed=True,
                setup_expires_at=timezone.now() + timedelta(minutes=10))
            device.encrypted_secret = cipher(user.pk, device.secret_salt).encrypt(secrets.token_bytes(20)).decode("ascii")
        device.last_t = -1
        device.throttling_failure_count = 0
        device.throttling_failure_timestamp = None
        device.save()
        state.enrolled_at = timezone.now(); state.save(update_fields=["enrolled_at"])
        response = client.post("/auth/mfa/verify/", {"otp_token": f"{totp(device.bin_key):06d}"})
        if response.status_code != 302:
            raise AssertionError("Synthetic fixture did not pass the real MFA verification view")
