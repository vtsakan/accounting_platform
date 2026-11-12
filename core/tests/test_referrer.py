"""Browser form privacy/CSRF regression for S14's reported Origin:null login."""
from html.parser import HTMLParser
import re
import secrets

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django_otp.oath import totp

from accounting.auth_models import AuthenticatorDevice
from accounting.membership import create_accountant_profile, create_office
from accounting.models import AccountantProfile
from accounting.office_models import StaffInvitation
from accounting.tests_auth_support import staff_client_login


class TokenParser(HTMLParser):
    token = None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "input" and attrs.get("name") == "csrfmiddlewaretoken":
            self.token = attrs["value"]


class FormReferrerTests(TestCase):
    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        self.office = create_office(name="ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ ΠΡΟΕΛΕΥΣΗΣ")
        self.owner = get_user_model().objects.create_user("referrer-owner", "owner@example.invalid", self.password)
        create_accountant_profile(user_id=self.owner.pk, office_id=self.office.pk, role="owner")
        self.client = Client(enforce_csrf_checks=True)
        self.host = "localhost:8003"

    def token(self, response):
        parser = TokenParser(); parser.feed(response.content.decode())
        self.assertIsNotNone(parser.token)
        return parser.token

    def get(self, path, *, secure=False, client=None):
        return (client or self.client).get(path, secure=secure, HTTP_HOST=self.host)

    def post(self, path, page, data, *, secure=False, origin=None, client=None):
        origin = origin or ("https://" if secure else "http://") + self.host
        return (client or self.client).post(path, {"csrfmiddlewaretoken":self.token(page), **data},
            secure=secure, HTTP_HOST=self.host, HTTP_ORIGIN=origin)

    def assert_form_policy(self, response):
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("no-store", response["Cache-Control"])

    def enrollment_and_settings(self, secure):
        login = self.get("/login/", secure=secure)
        self.assert_form_policy(login)
        response = self.post("/login/", login, {"username":self.owner.username, "password":self.password}, secure=secure)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("mfa-setup"))
        setup = self.get(response["Location"], secure=secure)
        self.assert_form_policy(setup)
        response = self.post(reverse("mfa-setup"), setup, {"action":"start", "password":self.password}, secure=secure)
        self.assertEqual(response.status_code, 302)
        setup = self.get(reverse("mfa-setup"), secure=secure)
        self.assert_form_policy(setup)
        device = AuthenticatorDevice.objects.get(user=self.owner, confirmed=False)
        response = self.post(reverse("mfa-setup"), setup,
            {"action":"confirm", "otp_token":f"{totp(device.bin_key):06d}"}, secure=secure)
        self.assertContains(response, "Κωδικοί ανάκτησης")
        self.assertTrue(AuthenticatorDevice.objects.get(pk=device.pk).confirmed)
        page = self.get(reverse("office-settings"), secure=secure)
        self.assert_form_policy(page)
        data = {"name":"ΔΟΚΙΜΑΣΤΙΚΟ ΝΕΟ ΟΝΟΜΑ", "version":"0", "vat_number":"000000000",
            "email":"contact@example.invalid", "phone":"", "address":"", "city":"Αθήνα", "postal_code":"", "password":self.password}
        response = self.post(reverse("office-settings"), page, data, secure=secure)
        self.assertEqual(response.status_code, 302)
        self.office.refresh_from_db(); self.assertEqual(self.office.name, data["name"])
        response = self.post(reverse("logout"), page, {}, secure=secure)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_http_login_mfa_enrollment_office_edit_and_logout_with_real_csrf_fields(self):
        self.enrollment_and_settings(False)

    def test_https_login_mfa_enrollment_office_edit_and_logout_with_real_csrf_fields(self):
        self.enrollment_and_settings(True)

    def test_null_origin_is_still_denied_with_an_otherwise_valid_csrf_token(self):
        page = self.get("/login/")
        response = self.post("/login/", page, {"username":self.owner.username, "password":self.password}, origin="null")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_foreign_origin_is_still_denied_with_an_otherwise_valid_csrf_token(self):
        page = self.get("/login/")
        response = self.post("/login/", page, {"username":self.owner.username, "password":self.password}, origin="https://foreign.example.invalid")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_matching_origin_does_not_bypass_missing_or_wrong_csrf_tokens(self):
        self.get("/login/")
        for token in ("", secrets.token_hex(16)):
            response = self.client.post("/login/", {"username":self.owner.username, "password":self.password, "csrfmiddlewaretoken":token},
                HTTP_HOST=self.host, HTTP_ORIGIN="http://"+self.host)
            self.assertEqual(response.status_code, 403)

    def invitation_form(self, secure):
        owner_client = Client()
        staff_client_login(owner_client, self.owner)
        origin = ("https://" if secure else "http://")+self.host
        with override_settings(AUTH_PUBLIC_ORIGIN=origin), self.captureOnCommitCallbacks(execute=True):
            response = owner_client.post(reverse("office-members"), {"email":"recruit@example.invalid", "password":self.password})
        self.assertEqual(response.status_code, 302)
        link = re.search(r"https?://[^\s]+/join/[^\s]+", mail.outbox[-1].body).group(0)
        response = self.get(link, secure=secure)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        form_url = response["Location"]
        self.assertNotIn(link.rstrip("/").rsplit("/",1)[-1], form_url)
        page = self.get(form_url, secure=secure)
        self.assert_form_policy(page)
        response = self.post(form_url, page, {"username":"referrer-recruit", "password1":self.password, "password2":self.password}, secure=secure)
        self.assertContains(response, "Η πρόσκληση έγινε δεκτή")
        recruit = get_user_model().objects.get(username="referrer-recruit")
        self.assertFalse(AccountantProfile.objects.get(user=recruit).is_active)
        invite = StaffInvitation.objects.get(accepted_by=recruit)
        response = owner_client.post(reverse("office-invitation-action", args=[invite.pk,"approve"]), {"password":self.password})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AccountantProfile.objects.get(user=recruit).is_active)

    def test_http_invitation_secret_redirect_then_token_free_csrf_acceptance(self):
        self.invitation_form(False)

    def test_https_invitation_secret_redirect_then_token_free_csrf_acceptance(self):
        self.invitation_form(True)

    def test_reset_secret_redirect_then_token_free_https_csrf_password_change(self):
        page = self.get(reverse("password-reset"), secure=True)
        self.assert_form_policy(page)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post(reverse("password-reset"), page, {"email":self.owner.email}, secure=True)
        self.assertEqual(response.status_code, 302)
        link = re.search(r"https?://[^\s]+/auth/password/reset/[^\s]+", mail.outbox[-1].body).group(0)
        response = self.get(link, secure=True)
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        form_url = response["Location"]
        self.assertTrue(form_url.endswith("/set-password/"))
        page = self.get(form_url, secure=True)
        self.assert_form_policy(page)
        new_password = secrets.token_urlsafe(32)
        response = self.post(form_url, page, {"new_password1":new_password, "new_password2":new_password}, secure=True)
        self.assertEqual(response.status_code, 302)
        self.owner.refresh_from_db(); self.assertTrue(self.owner.check_password(new_password))

    def test_invalid_bearer_urls_keep_no_referrer_without_weakening_form_pages(self):
        for path in ("/join/00000000-0000-4000-8000-000000000001/invalid/", "/auth/password/reset/MQ/invalid/"):
            response = self.get(path)
            self.assertEqual(response["Referrer-Policy"], "no-referrer")
            self.assertIn("no-store", response["Cache-Control"])
