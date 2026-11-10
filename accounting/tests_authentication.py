"""S13 request, encryption, recovery and independent PostgreSQL race proofs.

Only synthetic identities/addresses are used. No SMTP provider is contacted.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser
import io
import logging
from pathlib import Path
import re
import secrets
import tempfile
from threading import Barrier
import time
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.management import call_command
from django.db import IntegrityError, close_old_connections, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django_otp.oath import hotp

from core.auth_crypto import cipher
from core.auth_mail import deliver, public_origin
from core.redaction import RedactingFormatter, redact_text
from .auth_models import AuthRateBucket, AuthSecurityState, AuthenticatorDevice, MFARecoveryCode
from .auth_policy import AUTH_ERROR, bind_session, reserve_attempt, state_for
from .auth_services import code_digest, consume_recovery, issue_codes, verify_authenticator
from .models import AccountantProfile, Office

A = "00000000-0000-4000-8000-00000000000a"


class AuthFixtures:
    fixtures = ["s11_offices"]

    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        User = get_user_model()
        self.owner = User.objects.create_user("s13-owner", "owner@example.invalid", self.password)
        self.accountant = User.objects.create_user("s13-accountant", "accountant@example.invalid", self.password)
        self.platform = User.objects.create_superuser("s13-platform", "platform@example.invalid", self.password)
        self.unassigned = User.objects.create_user("s13-unassigned", "unassigned@example.invalid", self.password)
        AccountantProfile.objects.create(user=self.owner, office_id=A, role="owner")
        AccountantProfile.objects.create(user=self.accountant, office_id=A, role="accountant")

    def login(self, user=None, client=None, **data):
        return (client or self.client).post("/login/", {"username": (user or self.owner).username,
            "password": self.password, **data})

    def device(self, user=None, confirmed=True):
        user = user or self.owner
        device = AuthenticatorDevice(user=user, name="ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΣΚΕΥΗ S13", confirmed=confirmed,
            setup_expires_at=timezone.now() + timedelta(minutes=10))
        device.encrypted_secret = cipher(user.pk, device.secret_salt).encrypt(secrets.token_bytes(20)).decode("ascii")
        device.save()
        if confirmed:
            state = state_for(user); state.enrolled_at = timezone.now(); state.save()
        return device

    def token(self, device, offset=0):
        return f"{hotp(device.bin_key, int(time.time() // 30) + offset):06d}"

    def enroll(self, client=None):
        client = client or self.client
        self.assertEqual(client.post(reverse("mfa-setup"), {"action": "start", "password": self.password}).status_code, 302)
        device = AuthenticatorDevice.objects.get(pk=client.session["s13_pending_device"])
        result = client.post(reverse("mfa-setup"), {"action": "confirm", "otp_token": self.token(device, -1)})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.context["codes"]), 8)
        return device, result.context["codes"], result

    def request_for(self, user, client):
        return SimpleNamespace(user=user, session=client.session)

    def reset_link(self, user=None):
        user = user or self.owner
        user.refresh_from_db()
        return reverse("password-reset-confirm", kwargs={"uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": default_token_generator.make_token(user)})


class StaffLoginTests(AuthFixtures, TestCase):
    def test_accountant_password_login_and_post_logout_invalidate_session(self):
        self.assertRedirects(self.login(self.accountant), "/", fetch_redirect_response=False)
        old_key = self.client.session.session_key
        self.assertEqual(self.client.get("/customers/").status_code, 200)
        self.assertEqual(self.client.get("/logout/").status_code, 405)
        self.assertRedirects(self.client.post("/logout/"), "/login/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        stolen = Client(); stolen.cookies[settings.SESSION_COOKIE_NAME] = old_key
        self.assertEqual(stolen.get("/customers/").status_code, 302)

    def test_owner_cannot_reach_business_before_mfa_enrollment(self):
        self.assertRedirects(self.login(), reverse("mfa-setup"), fetch_redirect_response=False)
        for method, path in ((self.client.get, "/customers/"), (self.client.post, "/entity/add/")):
            self.assertRedirects(method(path, {}), reverse("mfa-setup"), fetch_redirect_response=False)

    def test_unknown_bad_password_and_unassigned_have_same_greek_error(self):
        for data in ({"username": "missing"}, {"password": secrets.token_urlsafe(24)}, {"username": self.unassigned.username}):
            response = self.login(**data)
            self.assertContains(response, AUTH_ERROR)
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_profile_and_office_cannot_password_login(self):
        for model, pk in ((get_user_model(), self.owner.pk), (AccountantProfile, self.owner.accountant_profile.pk), (Office, A)):
            model.objects.filter(pk=pk).update(is_active=False)
            self.assertContains(self.login(), AUTH_ERROR)
            self.assertNotIn("_auth_user_id", self.client.session)
            model.objects.filter(pk=pk).update(is_active=True)

    def test_platform_admin_has_mfa_but_no_implicit_office_membership(self):
        self.assertRedirects(self.login(self.platform), reverse("mfa-setup"), fetch_redirect_response=False)
        self.enroll()
        self.assertEqual(self.client.get("/admin/").status_code, 200)
        self.assertEqual(self.client.get("/customers/").status_code, 403)
        self.assertFalse(AccountantProfile.objects.filter(user=self.platform).exists())

    def test_owner_is_not_a_platform_administrator(self):
        self.login(); self.enroll()
        self.assertEqual(self.client.get("/customers/").status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 403)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_staff or self.owner.is_superuser)

    def test_staff_flag_requires_mfa_and_cannot_manage_global_user_admin(self):
        get_user_model().objects.filter(pk=self.accountant.pk).update(is_staff=True)
        self.accountant.refresh_from_db()
        self.assertRedirects(self.login(self.accountant), reverse("mfa-setup"), fetch_redirect_response=False)
        self.enroll()
        for path in ("/admin/auth/user/", "/admin/auth/", "/admin/autocomplete/?app_label=auth&model_name=user&field_name=groups"):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_admin_alternate_login_has_no_password_only_bypass(self):
        for method in (self.client.get, self.client.post):
            self.assertRedirects(method("/admin/login/", {}), "/login/?next=/admin/", fetch_redirect_response=False)
        self.login(self.platform)
        self.assertRedirects(self.client.get("/admin/"), reverse("mfa-setup"), fetch_redirect_response=False)

    def test_password_login_rotates_session_and_never_preserves_previous_mfa(self):
        session = self.client.session; session["anonymous"] = True; session.save()
        old = session.session_key
        self.login(); self.assertNotEqual(self.client.session.session_key, old)
        self.enroll()
        self.login()
        self.assertNotIn("otp_device_id", self.client.session)
        self.assertRedirects(self.client.get("/customers/"), reverse("mfa-verify"), fetch_redirect_response=False)

    def test_foreign_next_cannot_redirect_credentials_or_session(self):
        for next_url in ("https://foreign.example.invalid/path", "//foreign.example.invalid/path", r"/\foreign.example.invalid", "/auth/mfa/recover/"):
            self.assertRedirects(self.login(self.accountant, next=next_url), "/", fetch_redirect_response=False)
            self.client.logout()
        self.assertRedirects(self.login(self.accountant, next="/customers/"), "/customers/", fetch_redirect_response=False)

    def test_greek_form_errors_no_store_and_autocomplete_with_english_browser(self):
        response = self.client.get("/login/", HTTP_ACCEPT_LANGUAGE="en-US,en")
        for text in ('lang="el"', 'autocomplete="username"', 'autocomplete="current-password"', "Σύνδεση στην εφαρμογή"):
            self.assertContains(response, text)
        self.assertEqual(response["Content-Language"], "el")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")

    def test_idle_and_absolute_timeouts_and_missing_metadata_fail_closed(self):
        for field, value in (("s13_last_activity", time.time() - 1801), ("s13_started", time.time() - 28801), ("s13_revision", -1)):
            self.login(self.accountant)
            session = self.client.session; session[field] = value; session.save()
            self.assertRedirects(self.client.get("/customers/"), "/login/?expired=1", fetch_redirect_response=False)
            self.assertNotIn("_auth_user_id", self.client.session)
        self.client.force_login(self.accountant)
        self.assertRedirects(self.client.get("/customers/"), "/login/?expired=1", fetch_redirect_response=False)

    def test_pending_mfa_expires_on_auth_routes_too(self):
        self.login()
        session = self.client.session; session["s13_mfa_deadline"] = time.time() - 1; session.save()
        self.assertRedirects(self.client.post(reverse("mfa-setup"), {"action": "start", "password": self.password}), "/login/?expired=1", fetch_redirect_response=False)
        self.assertFalse(AuthenticatorDevice.objects.exists())

    def test_role_promotion_immediately_enforces_mfa(self):
        self.login(self.accountant)
        AccountantProfile.objects.filter(user=self.accountant).update(role="owner")
        self.assertRedirects(self.client.get("/customers/"), reverse("mfa-setup"), fetch_redirect_response=False)

    def test_profile_and_office_deactivation_block_an_existing_verified_session(self):
        self.login(); self.enroll()
        for model, pk in ((AccountantProfile, self.owner.accountant_profile.pk), (Office, A)):
            model.objects.filter(pk=pk).update(is_active=False)
            self.assertEqual(self.client.get("/customers/").status_code, 403)
            self.assertEqual(self.client.get(reverse("security-settings")).status_code, 403)
            model.objects.filter(pk=pk).update(is_active=True)

    def test_user_deactivation_rejects_existing_session(self):
        self.login(self.accountant)
        get_user_model().objects.filter(pk=self.accountant.pk).update(is_active=False)
        self.assertEqual(self.client.get("/customers/").status_code, 302)

    @override_settings(AUTH_RATE_LIMITS={"login": (2, 5)})
    def test_shared_login_limit_uses_no_plaintext_identifier_or_forwarded_ip(self):
        self.login(password=secrets.token_urlsafe(24)); self.login(password=secrets.token_urlsafe(24))
        response = self.client.post("/login/", {"username": self.owner.username, "password": self.password}, HTTP_X_FORWARDED_FOR="203.0.113.99")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(len(list(AuthRateBucket.objects.values_list("key", flat=True))), 2)
        for key in AuthRateBucket.objects.values_list("key", flat=True):
            self.assertRegex(key, r"^[0-9a-f]{64}$")
            self.assertNotIn(self.owner.username, key)

    def test_cookie_is_browser_scoped_with_independent_server_limit(self):
        response = self.login(self.accountant)
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertFalse(cookie["max-age"] or cookie["expires"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")


class AuthenticatorTests(AuthFixtures, TestCase):
    def test_setup_requires_password_and_get_creates_no_device(self):
        self.login()
        self.client.get(reverse("mfa-setup"))
        self.assertFalse(AuthenticatorDevice.objects.exists())
        self.client.post(reverse("mfa-setup"), {"action": "start", "password": secrets.token_urlsafe(24)})
        self.assertFalse(AuthenticatorDevice.objects.exists())

    def test_complete_setup_enables_business_and_shows_backup_codes_once(self):
        self.login(); old = self.client.session.session_key
        device, codes, response = self.enroll()
        self.assertNotEqual(self.client.session.session_key, old)
        device.refresh_from_db(); self.assertTrue(device.confirmed)
        self.assertEqual(self.client.get("/customers/").status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        next_response = self.client.get(reverse("mfa-setup"))
        for code in codes:
            self.assertNotContains(next_response, code)
            self.assertFalse(MFARecoveryCode.objects.filter(digest=code).exists())
            self.assertNotIn(code, str(dict(self.client.session)))

    def test_private_qr_requires_same_setup_session_and_is_never_public(self):
        self.login()
        self.client.post(reverse("mfa-setup"), {"action": "start", "password": self.password})
        response = self.client.get(reverse("mfa-qr"))
        self.assertEqual(response["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", response.content)
        self.assertIn("no-store", response["Cache-Control"])
        other = Client(); self.login(client=other)
        self.assertEqual(other.get(reverse("mfa-qr")).status_code, 403)
        self.assertEqual(Client().get(reverse("mfa-qr")).status_code, 302)

    def test_secret_is_encrypted_and_bound_to_user_salt_and_external_key(self):
        device = self.device()
        secret = device.bin_key
        self.assertFalse(base64.b32encode(secret).decode() in device.encrypted_secret)
        self.assertFalse(secret.hex() in device.encrypted_secret)
        with self.assertRaises(InvalidToken):
            cipher(self.accountant.pk, device.secret_salt).decrypt(device.encrypted_secret.encode())
        with self.assertRaises(InvalidToken):
            cipher(self.owner.pk, secrets.token_bytes(16)).decrypt(device.encrypted_secret.encode())
        with override_settings(SECRET_KEY=secrets.token_urlsafe(64), SECRET_KEY_FALLBACKS=[]):
            with self.assertRaises(InvalidToken):
                _ = device.bin_key
        old_key = settings.SECRET_KEY
        with override_settings(SECRET_KEY=secrets.token_urlsafe(64), SECRET_KEY_FALLBACKS=[old_key]):
            self.assertTrue(device.bin_key == secret)

    def test_expired_or_other_users_pending_setup_cannot_be_confirmed(self):
        self.login()
        self.client.post(reverse("mfa-setup"), {"action": "start", "password": self.password})
        device = AuthenticatorDevice.objects.get(pk=self.client.session["s13_pending_device"])
        AuthenticatorDevice.objects.filter(pk=device.pk).update(setup_expires_at=timezone.now() - timedelta(seconds=1))
        self.client.post(reverse("mfa-setup"), {"otp_token": self.token(device)})
        self.assertFalse(AuthenticatorDevice.objects.filter(confirmed=True).exists())
        alien = self.device(self.accountant, confirmed=False)
        session = self.client.session; session["s13_pending_device"] = alien.pk; session.save()
        self.client.post(reverse("mfa-setup"), {"otp_token": self.token(alien)})
        alien.refresh_from_db(); self.assertFalse(alien.confirmed)

    def test_totp_challenge_accepts_once_and_rejects_replay(self):
        device = self.device(); self.login()
        token = self.token(device)
        self.assertEqual(self.client.post(reverse("mfa-verify"), {"otp_token": token}).status_code, 302)
        self.assertEqual(self.client.get("/customers/").status_code, 200)
        self.assertContains(self.client.post(reverse("mfa-verify"), {"otp_token": token}), "Ο κωδικός δεν είναι έγκυρος")

    def test_totp_wrong_user_and_outside_window_are_denied(self):
        device = self.device(); alien = self.device(self.accountant)
        self.login()
        # Different factors and a five-step-old token are separate failed trials.
        for token in (self.token(alien), self.token(device, -5)):
            AuthenticatorDevice.objects.filter(pk=device.pk).update(throttling_failure_count=0, throttling_failure_timestamp=None)
            self.assertEqual(self.client.post(reverse("mfa-verify"), {"otp_token": token}).status_code, 200)
            self.assertNotIn("otp_device_id", self.client.session)

    def test_bad_token_commits_device_throttle_and_tamper_fails_closed(self):
        device = self.device(); self.login()
        AuthenticatorDevice.objects.filter(pk=device.pk).update(encrypted_secret=secrets.token_urlsafe(24))
        response = self.client.post(reverse("mfa-verify"), {"otp_token": "123456"})
        self.assertEqual(response.status_code, 200)
        device.refresh_from_db(); self.assertEqual(device.throttling_failure_count, 1)
        self.assertNotIn("otp_device_id", self.client.session)

    def test_revoking_device_blocks_already_verified_session(self):
        device = self.device(); self.login()
        self.client.post(reverse("mfa-verify"), {"otp_token": self.token(device)})
        AuthenticatorDevice.objects.filter(pk=device.pk).update(confirmed=False)
        self.assertRedirects(self.client.get("/customers/"), reverse("mfa-verify"), fetch_redirect_response=False)

    def test_password_only_session_cannot_replace_existing_factor(self):
        self.device(); self.login()
        self.client.post(reverse("mfa-setup"), {"action": "start", "password": self.password})
        self.assertEqual(AuthenticatorDevice.objects.count(), 1)
        self.assertEqual(self.client.get(reverse("mfa-qr")).status_code, 403)

    def test_accountant_optional_enrollment_becomes_mandatory_on_future_login(self):
        self.login(self.accountant); self.enroll()
        self.client.logout()
        self.assertRedirects(self.login(self.accountant), reverse("mfa-verify"), fetch_redirect_response=False)

    def test_database_allows_only_one_confirmed_device_per_user(self):
        self.device()
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.device()

    def test_rotation_invalidates_other_sessions_and_old_factor(self):
        self.login(); original, _, _ = self.enroll()
        other = Client(); self.login(client=other)
        self.client.post(reverse("mfa-setup"), {"action": "start", "password": self.password})
        pending = AuthenticatorDevice.objects.get(pk=self.client.session["s13_pending_device"])
        response = self.client.post(reverse("mfa-setup"), {"otp_token": self.token(pending)})
        self.assertEqual(len(response.context["codes"]), 8)
        self.assertFalse(AuthenticatorDevice.objects.filter(pk=original.pk).exists())
        self.assertRedirects(other.get("/customers/"), "/login/?expired=1", fetch_redirect_response=False)

    def test_rotation_needs_recent_mfa_even_after_a_verified_login(self):
        self.login(); self.enroll()
        session = self.client.session; session["s13_mfa_at"] = time.time() - 301; session.save()
        response = self.client.post(reverse("mfa-setup"), {"action": "start", "password": self.password})
        self.assertContains(response, "Για αλλαγή συσκευής απαιτείται πρόσφατη επαλήθευση")
        self.assertEqual(AuthenticatorDevice.objects.count(), 1)


class RecoveryTests(AuthFixtures, TestCase):
    def test_backup_code_is_single_use_and_grants_only_new_device_setup(self):
        self.login(); old_device, codes, _ = self.enroll()
        other = Client(); self.login(client=other)
        response = other.post(reverse("mfa-recover"), {"recovery_code": codes[0]})
        self.assertRedirects(response, reverse("mfa-setup"), fetch_redirect_response=False)
        old_device.refresh_from_db(); self.assertFalse(old_device.confirmed)
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.owner).count(), 7)
        self.assertRedirects(other.get("/customers/"), reverse("mfa-setup"), fetch_redirect_response=False)
        self.assertNotIn("otp_device_id", other.session)
        self.assertRedirects(self.client.get("/customers/"), "/login/?expired=1", fetch_redirect_response=False)
        self.assertContains(other.post(reverse("mfa-recover"), {"recovery_code": codes[0]}), "Ο κωδικός δεν είναι έγκυρος")

    def test_recovery_reenrollment_restores_access_and_replaces_all_backup_codes(self):
        self.login(); original, codes, _ = self.enroll()
        self.client.post(reverse("mfa-recover"), {"recovery_code": codes[0]})
        _, new_codes, _ = self.enroll()
        self.assertEqual(self.client.get("/customers/").status_code, 200)
        self.assertNotIn("s13_recovery_until", self.client.session)
        self.assertTrue(set(codes).isdisjoint(new_codes))
        self.assertFalse(MFARecoveryCode.objects.filter(digest__in=[code_digest(self.owner.pk, c) for c in codes]).exists())

    def test_backup_code_cannot_be_used_by_another_account(self):
        codes = issue_codes(self.owner)
        self.login(self.accountant)
        self.assertContains(self.client.post(reverse("mfa-recover"), {"recovery_code": codes[0]}), "Ο κωδικός δεν είναι έγκυρος")
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.owner).count(), 8)

    def test_expired_recovery_permit_does_not_reset_an_existing_factor(self):
        self.login(); _, codes, _ = self.enroll()
        self.client.post(reverse("mfa-recover"), {"recovery_code": codes[0]})
        session = self.client.session; session["s13_recovery_until"] = time.time() - 1; session.save()
        self.client.post(reverse("mfa-setup"), {"action": "start", "password": self.password})
        self.assertEqual(AuthenticatorDevice.objects.count(), 1)
        self.assertFalse(AuthenticatorDevice.objects.filter(confirmed=True).exists())

    def test_remaining_backup_code_can_resume_a_lost_recovery_session(self):
        self.login(); _, codes, _ = self.enroll()
        self.client.post(reverse("mfa-recover"), {"recovery_code": codes[0]})
        self.client.logout(); self.login()
        self.assertRedirects(self.client.post(reverse("mfa-recover"), {"recovery_code": codes[1]}), reverse("mfa-setup"), fetch_redirect_response=False)

    def test_regeneration_needs_password_and_recent_mfa_and_invalidates_sessions(self):
        self.login(); _, codes, _ = self.enroll()
        other = Client(); self.login(client=other)
        self.assertContains(self.client.post(reverse("security-settings"), {"password": secrets.token_urlsafe(24)}), "Απαιτείται κωδικός πρόσβασης")
        response = self.client.post(reverse("security-settings"), {"password": self.password})
        self.assertEqual(len(response.context["codes"]), 8)
        self.assertFalse(MFARecoveryCode.objects.filter(digest=code_digest(self.owner.pk, codes[0])).exists())
        self.assertRedirects(other.get(reverse("mfa-verify")), "/login/?expired=1", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/customers/").status_code, 200)

    def test_reset_email_is_greek_captured_and_uses_configured_origin(self):
        with override_settings(AUTH_PUBLIC_ORIGIN="https://localhost:8443"):
            self.client.post(reverse("password-reset"), {"email": self.owner.email}, HTTP_HOST="testserver", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("Ανάκτηση", message.subject)
        self.assertIn("https://localhost:8443/auth/password/reset/", message.body)
        self.assertNotIn("testserver", message.body)
        self.assertIn("μία ώρα", message.body)

    def test_unknown_inactive_ambiguous_and_unassigned_reset_requests_are_generic(self):
        self.owner.is_active = False; self.owner.save()
        for email in ("missing@example.invalid", self.owner.email, self.unassigned.email):
            self.assertRedirects(self.client.post(reverse("password-reset"), {"email": email}), reverse("password-reset-done"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 0)
        self.owner.is_active = True; self.owner.save()
        get_user_model().objects.create_user("s13-duplicate-email", self.owner.email, self.password)
        self.client.post(reverse("password-reset"), {"email": self.owner.email})
        self.assertEqual(len(mail.outbox), 0)

    def test_reset_link_expires_and_does_not_expose_token_in_referrer(self):
        link = self.reset_link()
        response = self.client.get(link)
        self.assertTrue(response["Location"].endswith("/set-password/"))
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        with patch.object(default_token_generator, "_now", return_value=datetime.now() + timedelta(hours=2)):
            self.assertContains(self.client.get(link), "Ο σύνδεσμος δεν είναι έγκυρος ή έχει λήξει")

    def test_password_reset_keeps_mfa_and_codes_revokes_old_sessions_and_is_single_use(self):
        self.login(); device, codes, _ = self.enroll()
        old_session = self.client.session.session_key
        recovery = Client(); link = self.reset_link()
        url = recovery.get(link)["Location"]
        new_password = secrets.token_urlsafe(32)
        response = recovery.post(url, {"new_password1": new_password, "new_password2": new_password})
        self.assertRedirects(response, reverse("password-reset-complete"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", recovery.session)
        self.assertTrue(AuthenticatorDevice.objects.filter(pk=device.pk, confirmed=True).exists())
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.owner).count(), 8)
        self.assertEqual(self.client.get("/customers/").status_code, 302)
        self.assertContains(Client().get(link), "Ο σύνδεσμος δεν είναι έγκυρος ή έχει λήξει")
        self.password = new_password
        self.assertRedirects(self.login(client=recovery), reverse("mfa-verify"), fetch_redirect_response=False)

    def test_weak_or_mismatched_password_is_rejected_and_reset_token_not_consumed(self):
        url = self.client.get(self.reset_link())["Location"]
        response = self.client.post(url, {"new_password1": "123", "new_password2": "456"})
        self.assertTrue(response.context["form"].errors)
        self.owner.refresh_from_db(); self.assertTrue(self.owner.check_password(self.password))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_account_deactivation_after_reset_request_invalidates_link(self):
        link = self.reset_link()
        AccountantProfile.objects.filter(user=self.owner).update(is_active=False)
        self.assertContains(self.client.get(link), "Ο σύνδεσμος δεν είναι έγκυρος ή έχει λήξει")

    def test_csrf_is_required_for_login_reset_and_factor_mutations(self):
        client = Client(enforce_csrf_checks=True)
        for path in ("/login/", reverse("password-reset")):
            self.assertEqual(client.post(path, {}).status_code, 403)
        # Correct password POST with a real CSRF cookie starts only a pending session.
        client.get("/login/")
        response = client.post("/login/", {"username": self.owner.username, "password": self.password,
            "csrfmiddlewaretoken": client.cookies[settings.CSRF_COOKIE_NAME].value})
        self.assertEqual(response.status_code, 302)
        for path in (reverse("mfa-setup"), reverse("mfa-verify"), reverse("mfa-recover"), reverse("security-settings")):
            self.assertEqual(client.post(path, {}).status_code, 403)

    def test_expired_auth_rows_can_be_pruned_without_deleting_active_factor(self):
        device = self.device()
        expired = self.device(self.accountant, confirmed=False)
        AuthenticatorDevice.objects.filter(pk=expired.pk).update(setup_expires_at=timezone.now() - timedelta(days=1))
        reserve_attempt("login", "temporary", "192.0.2.1")
        AuthRateBucket.objects.update(expires_at=timezone.now() - timedelta(days=1))
        call_command("prune_auth_attempts", stdout=io.StringIO())
        self.assertFalse(AuthRateBucket.objects.exists())
        self.assertFalse(AuthenticatorDevice.objects.filter(pk=expired.pk).exists())
        self.assertTrue(AuthenticatorDevice.objects.filter(pk=device.pk).exists())


class AuthBoundaryTests(SimpleTestCase):
    def test_production_mail_modes_and_https_origin_fail_closed(self):
        from core.tests.test_s04 import load_profile, production_env
        for extra in ({"AUTH_MAIL_MODE": "capture"}, {"AUTH_MAIL_MODE": "test"},
                      {"AUTH_MAIL_MODE": "smtp", "AUTH_MAIL_LIVE_ENABLED": "false"},
                      {"AUTH_PUBLIC_ORIGIN": "http://preview.example.test"},
                      {"AUTH_PUBLIC_ORIGIN": "https://foreign.example.invalid"}):
            result = load_profile("production", {**production_env(), **extra})
            self.assertNotEqual(result.returncode, 0)
        values = {**production_env(), "AUTH_MAIL_MODE": "disabled"}
        self.assertEqual(load_profile("production", values).returncode, 0)

    def test_origin_rejects_host_injection_credentials_paths_and_http_production(self):
        for value in ("https://foreign.invalid", "https://localhost/path", "https://user@localhost", "http://localhost", "https://localhost/?bad=1"):
            with self.assertRaises(ImproperlyConfigured):
                public_origin(value, ["localhost"], production=True)
        self.assertEqual(public_origin("https://localhost:8443", ["localhost"], production=True), "https://localhost:8443")

    @override_settings(AUTH_MAIL_MODE="disabled")
    def test_disabled_adapter_never_contacts_mail_provider(self):
        with patch("core.auth_mail.get_connection") as provider:
            deliver("ΔΟΚΙΜΑΣΤΙΚΟ", "ΔΟΚΙΜΑΣΤΙΚΟ", "synthetic@example.invalid")
            provider.assert_not_called()

    @override_settings(AUTH_MAIL_MODE="smtp", AUTH_MAIL_LIVE_ENABLED=False)
    def test_smtp_requires_explicit_opt_in_and_does_not_log_payload(self):
        canary = secrets.token_urlsafe(32)
        with patch("core.auth_mail.get_connection") as provider, self.assertLogs("core.auth_mail", level="WARNING") as logs:
            deliver("ΔΟΚΙΜΑΣΤΙΚΟ", canary, "synthetic@example.invalid")
            provider.assert_not_called()
        self.assertNotIn(canary, str(logs.output))

    @override_settings(AUTH_MAIL_MODE="smtp", AUTH_MAIL_LIVE_ENABLED=True)
    def test_controlled_smtp_adapter_calls_only_django_backend(self):
        with patch("core.auth_mail.get_connection") as provider:
            deliver("ΔΟΚΙΜΑΣΤΙΚΟ", "ΔΟΚΙΜΑΣΤΙΚΟ", "synthetic@example.invalid")
            provider.assert_called_once_with("django.core.mail.backends.smtp.EmailBackend")
            provider.return_value.send_messages.assert_called_once()

    @override_settings(AUTH_MAIL_MODE="capture")
    def test_capture_creates_private_message_without_console_token(self):
        with tempfile.TemporaryDirectory() as temp, override_settings(AUTH_MAIL_CAPTURE_ROOT=str(Path(temp) / "mail")):
            body = secrets.token_urlsafe(32)
            deliver("ΔΟΚΙΜΑΣΤΙΚΟ ΜΗΝΥΜΑ", body, "synthetic@example.invalid")
            root = Path(temp) / "mail"
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            files = list(root.glob("*.eml")); self.assertEqual(len(files), 1)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
            message = BytesParser(policy=policy.default).parsebytes(files[0].read_bytes())
            self.assertTrue(body in message.get_content())

    def test_reset_urls_and_backup_form_values_are_redacted(self):
        canary = secrets.token_urlsafe(32)
        self.assertNotIn(canary, redact_text("Forbidden /auth/password/reset/abc/" + canary + "/"))
        # sensitive_post_parameters plus the configured filter protect form data.
        from core.redaction import RedactingExceptionReporterFilter
        from django.test import RequestFactory
        request = RequestFactory().post("/auth/mfa/recover/", {"recovery_code": canary, "otp_token": canary})
        cleaned = RedactingExceptionReporterFilter().get_post_parameters(request)
        self.assertNotIn(canary, str(cleaned))


class AuthConcurrencyTests(AuthFixtures, TransactionTestCase):
    def parallel(self, action, count=2):
        barrier = Barrier(count)
        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return action(index)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=count) as pool:
            return list(pool.map(worker, range(count)))

    def test_same_totp_can_succeed_in_only_one_concurrent_session(self):
        device = self.device(); code = self.token(device)
        clients = [Client(), Client()]
        for client in clients:
            self.login(client=client)
        result = self.parallel(lambda i: clients[i].post(reverse("mfa-verify"), {"otp_token": code}).status_code)
        self.assertEqual(sorted(result), [200, 302])
        self.assertEqual(sum("otp_device_id" in client.session for client in clients), 1)

    def test_same_backup_code_has_only_one_concurrent_consumer(self):
        self.device(); code = issue_codes(self.owner)[0]
        clients = [Client(), Client()]
        for client in clients:
            self.login(client=client)
        result = self.parallel(lambda i: clients[i].post(reverse("mfa-recover"), {"recovery_code": code}).status_code)
        self.assertEqual(sum("s13_recovery_until" in client.session for client in clients), 1)
        self.assertTrue(all(code in (200, 302, 403) for code in result))
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.owner).count(), 7)

    @override_settings(AUTH_RATE_LIMITS={"login": (1, 100)})
    def test_concurrent_requests_share_the_postgresql_rate_budget(self):
        result = self.parallel(lambda i: reserve_attempt("login", "same-identity", "192.0.2.1"), count=4)
        self.assertEqual(sum(result), 1)
        self.assertEqual(AuthRateBucket.objects.count(), 2)

    @override_settings(AUTH_RATE_LIMITS={"login": (1, 1)})
    def test_ip_exhaustion_bounds_new_identity_rows_and_window_can_restart(self):
        self.assertTrue(reserve_attempt("login", "one", "192.0.2.1"))
        for i in range(5):
            self.assertFalse(reserve_attempt("login", str(i), "192.0.2.1"))
        self.assertEqual(AuthRateBucket.objects.count(), 2)
        AuthRateBucket.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(reserve_attempt("login", "one", "192.0.2.1"))

    def test_two_enrollments_cannot_both_activate_a_first_device(self):
        clients = [Client(), Client()]
        devices = []
        for client in clients:
            self.login(client=client)
            client.post(reverse("mfa-setup"), {"action": "start", "password": self.password})
            devices.append(AuthenticatorDevice.objects.get(pk=client.session["s13_pending_device"]))
        result = self.parallel(lambda i: clients[i].post(reverse("mfa-setup"), {"otp_token": self.token(devices[i])}).status_code)
        self.assertEqual(result.count(200), 1)
        self.assertTrue(all(code in (200, 302, 403) for code in result))
        self.assertEqual(AuthenticatorDevice.objects.filter(confirmed=True).count(), 1)
        self.assertEqual(MFARecoveryCode.objects.count(), 8)

    def test_same_reset_link_cannot_change_password_twice_concurrently(self):
        link = self.reset_link()
        clients = [Client(), Client()]
        urls = [client.get(link)["Location"] for client in clients]
        passwords = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
        result = self.parallel(lambda i: clients[i].post(urls[i], {"new_password1": passwords[i], "new_password2": passwords[i]}).status_code)
        self.assertEqual(sorted(result), [200, 302])
        self.owner.refresh_from_db()
        self.assertEqual(sum(self.owner.check_password(password) for password in passwords), 1)
