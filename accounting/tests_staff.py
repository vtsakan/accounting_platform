"""S14 policy, onboarding, office boundaries, audit and PostgreSQL races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import io
import json
import re
import secrets
from threading import Barrier
import time
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.auth_mail import deliver
from core.redaction import redact_text
from .admin import GuardedUserChangeForm
from .auth_policy import state_for
from .capabilities import MATRIX, require_capability
from .membership import change_membership, create_accountant_profile
from .models import AccountantProfile, CashAccount, Category, Entity, Office, Transaction
from .office_access import execution_record
from .office_models import OfficeAuditEvent, OwnershipHandover, StaffInvitation
from .office_services import decide_handover, propose_handover
from .tests_auth_support import staff_client_login

A = "00000000-0000-4000-8000-00000000000a"
B = "00000000-0000-4000-8000-00000000000b"


class StaffFixtures:
    fixtures = ["s11_offices"]

    def setUp(self):
        self.password = secrets.token_urlsafe(32)
        User = get_user_model()
        self.owner = User.objects.create_user("s14-owner-a", "owner-a@example.invalid", self.password)
        self.member = User.objects.create_user("s14-member-a", "member-a@example.invalid", self.password)
        self.foreign = User.objects.create_user("s14-owner-b", "owner-b@example.invalid", self.password)
        self.platform = User.objects.create_superuser("s14-platform", "platform@example.invalid", self.password)
        for user, office, role in ((self.owner, A, "owner"), (self.member, A, "accountant"), (self.foreign, B, "owner")):
            create_accountant_profile(user_id=user.pk, office_id=office, role=role)
        self.office = Office.objects.get(pk=A)
        self.client = Client(); staff_client_login(self.client, self.owner)
        self.member_client = Client(); staff_client_login(self.member_client, self.member)
        self.foreign_client = Client(); staff_client_login(self.foreign_client, self.foreign)

    def settings_data(self, **overrides):
        return {"name": "ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ ΝΕΟ", "vat_number": "000000123", "email": "office@example.invalid",
                "phone": "2100000000", "address": "Δοκιμαστική οδός 1", "city": "Αθήνα", "postal_code": "10000",
                "version": self.office.settings_version, "password": self.password, **overrides}

    def invite(self, email="recruit@example.invalid", *, client=None):
        client = client or self.client
        with self.captureOnCommitCallbacks(execute=True) if isinstance(self, TestCase) else _null_context():
            response = client.post(reverse("office-members"), {"email": email, "password": self.password})
        self.assertEqual(response.status_code, 302)
        office_id = AccountantProfile.objects.get(user_id=client.session["_auth_user_id"]).office_id
        invitation = StaffInvitation.objects.get(office_id=office_id, recipient_email=email, status="pending")
        links = [re.search(r"https?://[^\s]+/join/[^\s]+", message.body).group(0)
                 for message in mail.outbox if re.search(r"https?://[^\s]+/join/[^\s]+", message.body)]
        return invitation, links[-1]

    def enter(self, link, client=None):
        client = client or Client()
        response = client.get(link)
        self.assertEqual(response.status_code, 302)
        return client, response["Location"]

    def accept(self, link, *, username="s14-recruit", password=None, extra=None):
        visitor, location = self.enter(link)
        password = password or self.password
        response = visitor.post(location, {"username": username, "password1": password, "password2": password, **(extra or {})})
        self.assertContains(response, "Η πρόσκληση έγινε δεκτή")
        return visitor, get_user_model().objects.get(username=username)

    def approve(self, invite, *, client=None):
        with self.captureOnCommitCallbacks(execute=True) if isinstance(self, TestCase) else _null_context():
            response = (client or self.client).post(reverse("office-invitation-action", args=[invite.pk, "approve"]), {"password": self.password})
        return response

    def offer(self):
        with self.captureOnCommitCallbacks(execute=True) if isinstance(self, TestCase) else _null_context():
            response = self.client.post(reverse("office-ownership"), {"recipient": self.member.pk, "password": self.password})
        self.assertEqual(response.status_code, 302)
        return OwnershipHandover.objects.get(status="pending")

    def verified_member(self, client=None):
        client = client or self.member_client
        # Explicit fixture passes the actual S13 OTP view.
        from .auth_models import AuthenticatorDevice
        if not AuthenticatorDevice.objects.filter(user=self.member, confirmed=True).exists():
            from core.auth_crypto import cipher
            device = AuthenticatorDevice(user=self.member, name="ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΣΚΕΥΗ S14", confirmed=True,
                setup_expires_at=timezone.now() + timedelta(minutes=10))
            device.encrypted_secret = cipher(self.member.pk, device.secret_salt).encrypt(secrets.token_bytes(20)).decode("ascii")
            device.save()
            state = state_for(self.member); state.enrolled_at = timezone.now(); state.save(update_fields=["enrolled_at"])
        staff_client_login(client, self.member)
        return client


from contextlib import nullcontext as _null_context


class OfficeSettingsTests(StaffFixtures, TestCase):
    def test_owner_revoked_while_waiting_for_identity_lock_cannot_change_settings(self):
        from .office_services import lock_request_state
        change_membership(user_id=self.member.pk, office_id=A, role="owner", is_active=True)
        def revoked_while_waiting(request):
            state = lock_request_state(request)
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
            return state
        with patch("accounting.office_services.lock_request_state", side_effect=revoked_while_waiting):
            response = self.client.post(reverse("office-settings"), self.settings_data())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Office.objects.get(pk=A).settings_version, 0)
        self.assertFalse(OfficeAuditEvent.objects.exists())

    def test_owner_edits_and_reloads_greek_identity_and_contacts(self):
        response = self.client.get(reverse("office-settings"), HTTP_ACCEPT_LANGUAGE="en-US,en")
        self.assertContains(response, "Στοιχεία λογιστικού γραφείου")
        self.assertEqual(response["Content-Language"], "el")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(self.client.post(reverse("office-settings"), self.settings_data()).status_code, 302)
        office = Office.objects.get(pk=A)
        for field, value in self.settings_data().items():
            if field not in {"password", "version"}:
                self.assertEqual(getattr(office, field), value)
        self.assertEqual(office.settings_version, 1)
        self.assertEqual(Office.objects.get(pk=B).settings_version, 0)
        event = OfficeAuditEvent.objects.get(action="office.settings")
        self.assertEqual(event.actor_id, self.owner.pk)

    def test_submitted_office_active_role_and_privilege_fields_have_no_authority(self):
        self.client.post(reverse("office-settings"), self.settings_data(office_id=B, is_active=False, role="owner", is_superuser=True))
        self.owner.refresh_from_db(); self.office.refresh_from_db()
        self.assertTrue(self.office.is_active)
        self.assertFalse(self.owner.is_staff or self.owner.is_superuser)
        self.assertNotEqual(Office.objects.get(pk=B).name, self.office.name)
        self.assertEqual(self.office.pk, OfficeAuditEvent.objects.get().office_id)

    def test_accountant_cannot_administer_settings_staff_or_roles_by_direct_requests(self):
        paths = [reverse("office-settings"), reverse("office-members"), reverse("office-audit"),
                 reverse("office-member-action", args=[self.member.pk, "reactivate"])]
        for path in paths:
            self.assertEqual(self.member_client.get(path).status_code, 403)
            self.assertEqual(self.member_client.post(path, {"password": self.password, "role": "owner"}).status_code, 403)
        self.assertFalse(OfficeAuditEvent.objects.exists())

    def test_platform_administrator_without_profile_has_no_office_bypass(self):
        client = Client(); staff_client_login(client, self.platform)
        for path in (reverse("office-settings"), reverse("office-members"), reverse("office-ownership")):
            self.assertEqual(client.get(path).status_code, 403)

    def test_cross_office_setting_query_returns_only_actor_office(self):
        Office.objects.filter(pk=B).update(name="S14_FOREIGN_OFFICE_CANARY", email="foreign@example.invalid")
        response = self.client.get(reverse("office-settings"), {"office_id": B})
        self.assertNotContains(response, "S14_FOREIGN_OFFICE_CANARY")
        self.assertNotContains(response, "foreign@example.invalid")

    def test_settings_version_prevents_lost_update(self):
        self.client.post(reverse("office-settings"), self.settings_data(name="ΠΡΩΤΗ ΑΛΛΑΓΗ"))
        response = self.client.post(reverse("office-settings"), self.settings_data(name="ΠΑΛΙΑ ΑΛΛΑΓΗ"))
        self.assertContains(response, "Τα στοιχεία άλλαξαν από άλλον υπεύθυνο")
        self.assertEqual(Office.objects.get(pk=A).name, "ΠΡΩΤΗ ΑΛΛΑΓΗ")
        self.assertEqual(OfficeAuditEvent.objects.count(), 1)

    def test_password_and_recent_mfa_are_required_to_change_settings(self):
        bad = self.settings_data(password=secrets.token_urlsafe(32))
        self.assertContains(self.client.post(reverse("office-settings"), bad), "Απαιτείται κωδικός πρόσβασης")
        session = self.client.session; session["s13_mfa_at"] = time.time() - 301; session.save()
        self.assertContains(self.client.post(reverse("office-settings"), self.settings_data()), "Απαιτείται κωδικός πρόσβασης")
        self.assertEqual(Office.objects.get(pk=A).settings_version, 0)

    def test_invalid_afm_and_blank_name_are_rejected_without_changing_data(self):
        for changes in ({"vat_number": "12x"}, {"name": " "}):
            response = self.client.post(reverse("office-settings"), self.settings_data(**changes))
            self.assertTrue(response.context["form"].errors)
        self.assertEqual(Office.objects.get(pk=A).settings_version, 0)

    def test_csrf_is_required_on_settings_staff_and_handover_actions(self):
        client = Client(enforce_csrf_checks=True); client.cookies = self.client.cookies.copy()
        for path in (reverse("office-settings"), reverse("office-members"), reverse("office-ownership"),
                     reverse("office-member-action", args=[self.member.pk, "deactivate"])):
            self.assertEqual(client.post(path, {}).status_code, 403)
        client.get(reverse("office-settings"))
        data = self.settings_data(csrfmiddlewaretoken=client.cookies[settings.CSRF_COOKIE_NAME].value)
        self.assertEqual(client.post(reverse("office-settings"), data).status_code, 302)

    def test_role_revocation_is_rechecked_on_next_settings_request(self):
        peer = get_user_model().objects.create_user("s14-peer-owner")
        create_accountant_profile(user_id=peer.pk, office_id=A, role="owner")
        change_membership(user_id=self.owner.pk, office_id=A, role="accountant", is_active=True)
        self.assertEqual(self.client.get(reverse("office-settings")).status_code, 403)

    def test_approved_accountant_matrix_includes_clients_and_financial_posting(self):
        for capability in MATRIX["accountant"]:
            self.assertEqual(require_capability(self.member, capability).office_id, self.office.pk)
        for capability in MATRIX["owner"] - MATRIX["accountant"]:
            with self.assertRaises(PermissionDenied):
                require_capability(self.member, capability)
        with self.assertRaises(PermissionDenied):
            require_capability(self.owner, "future-unknown-operation")
        self.assertEqual(self.member_client.post("/entity/add/", {"entity_type": "CUSTOMER", "name": "ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S14"}).status_code, 302)
        entity = Entity.objects.get(name="ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S14")
        cash = CashAccount.objects.create(office=self.office, name="ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S14")
        category = Category.objects.create(office=self.office, name="ΔΟΚΙΜΑΣΤΙΚΗ ΚΑΤΗΓΟΡΙΑ S14")
        response = self.member_client.post("/income/add/", {"transaction_date": "2026-11-10", "amount": "12,34",
            "description": "ΔΟΚΙΜΑΣΤΙΚΗ ΕΙΣΠΡΑΞΗ S14", "cash_account": cash.pk, "category": category.pk, "entity": entity.pk, "agreement": ""})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Transaction.objects.filter(office=self.office).count(), 1)

    def test_execution_adapter_denies_ungranted_or_revoked_capability(self):
        entity = Entity.objects.create(office=self.office, name="ΔΟΚΙΜΑΣΤΙΚΟ", entity_type="CUSTOMER")
        args = dict(user_id=self.member.pk, expected_office_id=A, model=Entity, key=entity.pk)
        self.assertEqual(execution_record(**args, capability="clients.read").pk, entity.pk)
        for capability in ("staff.manage", "unimplemented.export"):
            with self.assertRaises(PermissionDenied):
                execution_record(**args, capability=capability)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            execution_record(**args, capability="clients.read")


class InvitationTests(StaffFixtures, TestCase):
    def test_existing_recipient_credentials_are_rechecked_after_waiting_for_user_lock(self):
        from django.contrib.auth.hashers import make_password
        from .office_services import lock_users
        user = get_user_model().objects.create_user("s14-waiting", "waiting@example.invalid", self.password)
        invite, link = self.invite(user.email)
        visitor, location = self.enter(link)
        for values in ({"is_active": False}, {"password": make_password(secrets.token_urlsafe(32))}, {"email": "changed@example.invalid"}):
            def changed_while_waiting(*ids):
                get_user_model().objects.filter(pk=user.pk).update(**values)
                return lock_users(*ids)
            with self.subTest(fields=list(values)), patch("accounting.office_services.lock_users", side_effect=changed_while_waiting):
                response = visitor.post(location, {"password": self.password})
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, "Η πρόσκληση έγινε δεκτή")
            self.assertFalse(AccountantProfile.objects.filter(user=user).exists())
            self.assertEqual(StaffInvitation.objects.get(pk=invite.pk).status, "pending")

    def test_invitation_mail_is_greek_origin_bound_and_token_not_in_owner_page(self):
        with override_settings(AUTH_PUBLIC_ORIGIN="https://localhost:8443"):
            invite, link = self.invite()
        self.assertTrue(link.startswith("https://localhost:8443/join/"))
        self.assertIn("Πρόσκληση", mail.outbox[-1].subject)
        self.assertIn("24 ώρες", mail.outbox[-1].body)
        token = link.rstrip("/").rsplit("/", 1)[-1]
        self.assertNotEqual(invite.token_digest, token)
        self.assertNotContains(self.client.get(reverse("office-members")), token)
        self.assertEqual(StaffInvitation.objects.get(pk=invite.pk).mail_status, "test")

    def test_token_get_does_not_consume_and_redirect_hides_secret(self):
        invite, link = self.invite(); visitor, location = self.enter(link)
        invite.refresh_from_db(); self.assertIsNone(invite.used_at)
        token = link.rstrip("/").rsplit("/", 1)[-1]
        self.assertNotIn(token, location)
        self.assertNotIn(token, str(dict(visitor.session)))
        response = visitor.get(location)
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "Αποδοχή πρόσκλησης")

    def test_acceptance_creates_one_inactive_regular_profile_then_owner_approves(self):
        invite, link = self.invite()
        visitor, user = self.accept(link, extra={"office_id": B, "role": "owner", "is_staff": "1", "is_superuser": "1"})
        profile = AccountantProfile.objects.get(user=user)
        self.assertEqual(str(profile.office_id), A)
        self.assertEqual(profile.role, "accountant"); self.assertFalse(profile.is_active)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertNotIn("_auth_user_id", visitor.session)
        self.assertContains(visitor.post("/login/", {"username": user.username, "password": self.password}), "ο λογαριασμός δεν είναι διαθέσιμος")
        self.assertEqual(self.approve(invite).status_code, 302)
        profile.refresh_from_db(); self.assertTrue(profile.is_active)
        self.assertEqual(visitor.post("/login/", {"username": user.username, "password": self.password}).status_code, 302)
        self.assertEqual(visitor.get("/customers/").status_code, 200)
        self.assertFalse(get_user_model().objects.get(pk=user.pk).is_staff)
        self.assertEqual(AccountantProfile.objects.filter(user=user).count(), 1)

    def test_invitation_reuse_fails_and_cannot_create_a_second_user(self):
        invite, link = self.invite(); self.accept(link)
        self.assertEqual(Client().get(link).status_code, 404)
        self.assertEqual(get_user_model().objects.filter(email=invite.recipient_email).count(), 1)

    def test_expired_and_wrong_tokens_fail_without_disclosing_recipient(self):
        invite, link = self.invite()
        wrong = link.rstrip("/").rsplit("/", 1)[0] + "/" + secrets.token_urlsafe(32) + "/"
        response = Client().get(wrong)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(invite.recipient_email, response.content.decode())
        StaffInvitation.objects.filter(pk=invite.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(Client().get(link).status_code, 404)

    def test_resend_revokes_previous_link_and_previous_browser_proof(self):
        invite, link = self.invite(); visitor, location = self.enter(link)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse("office-invitation-action", args=[invite.pk, "resend"]), {"password": self.password})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Client().get(link).status_code, 404)
        self.assertEqual(visitor.get(location).status_code, 404)

    def test_cancellation_revokes_link_without_creating_membership(self):
        invite, link = self.invite()
        response = self.client.post(reverse("office-invitation-action", args=[invite.pk, "cancel"]), {"password": self.password})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Client().get(link).status_code, 404)
        self.assertFalse(get_user_model().objects.filter(email=invite.recipient_email).exists())

    def test_existing_unaffiliated_user_needs_own_password_and_is_not_reset(self):
        user = get_user_model().objects.create_user("s14-unaffiliated", "unaffiliated@example.invalid", self.password)
        invite, link = self.invite(user.email); visitor, location = self.enter(link)
        self.assertEqual(visitor.post(location, {"password": secrets.token_urlsafe(32)}).status_code, 200)
        self.assertFalse(AccountantProfile.objects.filter(user=user).exists())
        self.assertContains(visitor.post(location, {"password": self.password}), "Η πρόσκληση έγινε δεκτή")
        user.refresh_from_db(); self.assertTrue(user.check_password(self.password))
        self.assertEqual(get_user_model().objects.filter(email=user.email).count(), 1)

    def test_affiliated_inactive_and_platform_accounts_cannot_be_invited(self):
        for user in (self.member, self.foreign, self.platform):
            response = self.client.post(reverse("office-members"), {"email": user.email, "password": self.password})
            self.assertContains(response, "Η διεύθυνση δεν είναι διαθέσιμη")
        inactive = get_user_model().objects.create_user("s14-inactive", "inactive@example.invalid", self.password, is_active=False)
        self.assertContains(self.client.post(reverse("office-members"), {"email": inactive.email, "password": self.password}), "Η διεύθυνση δεν είναι διαθέσιμη")
        self.assertFalse(StaffInvitation.objects.exists())

    def test_two_office_invitations_cannot_affiliate_one_account_twice(self):
        first, link_a = self.invite()
        second, link_b = self.invite(client=self.foreign_client)
        self.accept(link_a)
        visitor, location = self.enter(link_b)
        response = visitor.post(location, {"password": self.password})
        self.assertContains(response, "υπάρχει ήδη προφίλ λογιστή")
        self.assertEqual(AccountantProfile.objects.filter(user__email=first.recipient_email).count(), 1)
        second.refresh_from_db(); self.assertEqual(second.status, "pending")

    def test_duplicate_open_invitation_is_rejected(self):
        self.invite()
        response = self.client.post(reverse("office-members"), {"email": "RECRUIT@example.invalid", "password": self.password})
        self.assertContains(response, "Υπάρχει ήδη ανοικτή πρόσκληση")
        self.assertEqual(StaffInvitation.objects.count(), 1)

    def test_cross_office_approval_and_ordinary_accountant_approval_are_denied(self):
        invite, link = self.invite(); self.accept(link)
        for client, code in ((self.foreign_client, 404), (self.member_client, 403)):
            self.assertEqual(self.approve(invite, client=client).status_code, code)
        self.assertFalse(AccountantProfile.objects.get(user__email=invite.recipient_email).is_active)

    def test_reject_keeps_profile_inactive_and_approval_reuse_fails(self):
        invite, link = self.invite(); _, user = self.accept(link)
        self.client.post(reverse("office-invitation-action", args=[invite.pk, "reject"]), {"password": self.password})
        self.assertEqual(self.approve(invite).status_code, 200)
        self.assertFalse(AccountantProfile.objects.get(user=user).is_active)

    def test_pending_member_cannot_be_activated_through_the_reactivation_shortcut(self):
        invite, link = self.invite(); _, user = self.accept(link)
        response = self.client.post(reverse("office-member-action", args=[user.pk, "reactivate"]), {"password": self.password})
        self.assertContains(response, "γίνεται από την έγκριση πρόσκλησης")
        self.assertFalse(AccountantProfile.objects.get(user=user).is_active)

    def test_issuer_security_revocation_invalidates_unaccepted_invitation(self):
        invite, link = self.invite()
        state = state_for(self.owner); state.revision += 1; state.save()
        self.assertEqual(Client().get(link).status_code, 404)

    def test_recipient_global_deactivation_prevents_owner_approval(self):
        invite, link = self.invite(); _, user = self.accept(link)
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        self.assertEqual(self.approve(invite).status_code, 200)
        self.assertFalse(AccountantProfile.objects.get(user=user).is_active)

    def test_email_change_between_acceptance_and_approval_is_rejected(self):
        invite, link = self.invite(); _, user = self.accept(link)
        get_user_model().objects.filter(pk=user.pk).update(email="changed@example.invalid")
        self.assertEqual(self.approve(invite).status_code, 200)
        self.assertFalse(AccountantProfile.objects.get(user=user).is_active)

    def test_join_requires_csrf_and_cannot_use_another_invitation_id(self):
        invite, link = self.invite()
        other, _ = self.invite("other-recruit@example.invalid")
        client = Client(enforce_csrf_checks=True); client, location = self.enter(link, client)
        self.assertEqual(client.post(location, {}).status_code, 403)
        self.assertEqual(client.get(reverse("staff-join", args=[other.pk])).status_code, 404)


class MembershipAndHandoverTests(StaffFixtures, TestCase):
    def test_deactivation_revokes_next_request_and_explicit_reactivation_restores_only_accountant(self):
        self.assertEqual(self.member_client.get("/customers/").status_code, 200)
        path = reverse("office-member-action", args=[self.member.pk, "deactivate"])
        self.assertEqual(self.client.post(path, {"password": self.password}).status_code, 302)
        self.assertEqual(self.member_client.get("/customers/").status_code, 403)
        self.assertEqual(self.client.post(reverse("office-member-action", args=[self.member.pk, "reactivate"]), {"password": self.password}).status_code, 302)
        profile = AccountantProfile.objects.get(user=self.member)
        self.assertTrue(profile.is_active); self.assertEqual(profile.role, "accountant")

    def test_last_owner_deactivation_and_demotion_are_denied(self):
        response = self.client.post(reverse("office-member-action", args=[self.owner.pk, "deactivate"]), {"password": self.password})
        self.assertContains(response, "τουλάχιστον έναν ενεργό υπεύθυνο")
        with self.assertRaises(ValidationError):
            change_membership(user_id=self.owner.pk, office_id=A, role="accountant", is_active=True)
        self.assertTrue(AccountantProfile.objects.get(user=self.owner).is_active)

    def test_database_guards_last_owner_user_profile_and_identity_changes(self):
        for model, changes in ((AccountantProfile, {"is_active": False}), (AccountantProfile, {"role": "accountant"}),
                               (get_user_model(), {"is_active": False})):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.filter(**({"user": self.owner} if model is AccountantProfile else {"pk": self.owner.pk})).update(**changes)
        for field, value in (("office_id", B), ("user_id", self.platform.pk)):
            with self.assertRaises(IntegrityError), transaction.atomic():
                AccountantProfile.objects.filter(user=self.member).update(**{field: value})

    def test_cross_office_member_action_and_role_injection_cannot_change_profiles(self):
        self.assertEqual(self.client.post(reverse("office-member-action", args=[self.foreign.pk, "deactivate"]), {"password": self.password}).status_code, 404)
        self.client.post(reverse("office-member-action", args=[self.member.pk, "deactivate"]), {"password": self.password, "role": "owner", "is_superuser": True})
        self.assertEqual(AccountantProfile.objects.get(user=self.member).role, "accountant")
        self.assertFalse(get_user_model().objects.get(pk=self.member.pk).is_superuser)

    def test_handover_requires_recipient_acceptance_and_forces_recipient_mfa(self):
        offer = self.offer()
        self.assertEqual(AccountantProfile.objects.get(user=self.owner).role, "owner")
        self.assertEqual(AccountantProfile.objects.get(user=self.member).role, "accountant")
        response = self.member_client.get(reverse("office-handover-detail", args=[offer.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/mfa/setup/", response["Location"])

    def test_successful_handover_changes_both_roles_and_revokes_both_sessions(self):
        offer = self.offer(); self.verified_member()
        response = self.member_client.post(reverse("office-handover-detail", args=[offer.pk]), {"action": "accept", "password": self.password})
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.member_client.session)
        self.assertEqual(AccountantProfile.objects.get(user=self.owner).role, "accountant")
        self.assertEqual(AccountantProfile.objects.get(user=self.member).role, "owner")
        self.assertEqual(AccountantProfile.objects.filter(office_id=A, role="owner", is_active=True).count(), 1)
        self.assertEqual(self.client.get(reverse("office-settings")).status_code, 302)
        self.assertEqual(OfficeAuditEvent.objects.filter(action="handover.accept").count(), 2)

    def test_sender_cannot_accept_and_foreign_recipient_cannot_open_offer(self):
        offer = self.offer()
        self.assertEqual(self.client.post(reverse("office-handover-detail", args=[offer.pk]), {"action": "accept", "password": self.password}).status_code, 403)
        self.assertEqual(self.foreign_client.get(reverse("office-handover-detail", args=[offer.pk])).status_code, 404)
        self.assertEqual(OwnershipHandover.objects.get(pk=offer.pk).status, "pending")

    def test_recipient_promoted_to_platform_staff_after_proposal_is_not_given_ownership(self):
        offer = self.offer(); self.verified_member()
        get_user_model().objects.filter(pk=self.member.pk).update(is_staff=True)
        response = self.member_client.post(reverse("office-handover-detail", args=[offer.pk]), {"action":"accept", "password":self.password})
        self.assertContains(response, "Η εξουσιοδότηση ή η κατάσταση")
        self.assertEqual(AccountantProfile.objects.get(user=self.owner).role, "owner")
        self.assertEqual(AccountantProfile.objects.get(user=self.member).role, "accountant")
        self.assertEqual(OwnershipHandover.objects.get(pk=offer.pk).status, "pending")

    def test_accountant_cannot_propose_handover_or_target_foreign_member(self):
        data = {"recipient": self.foreign.pk, "password": self.password}
        self.assertEqual(self.member_client.post(reverse("office-ownership"), data).status_code, 403)
        self.assertEqual(self.client.post(reverse("office-ownership"), data).status_code, 200)
        self.assertFalse(OwnershipHandover.objects.exists())

    def test_expired_handover_and_stale_recipient_mfa_cannot_elevate_role(self):
        offer = self.offer(); self.verified_member()
        session = self.member_client.session; session["s13_mfa_at"] = time.time() - 301; session.save()
        path = reverse("office-handover-detail", args=[offer.pk])
        self.assertEqual(self.member_client.post(path, {"action": "accept", "password": self.password}).status_code, 200)
        session = self.member_client.session; session["s13_mfa_at"] = time.time(); session.save()
        OwnershipHandover.objects.filter(pk=offer.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertContains(self.member_client.post(path, {"action": "accept", "password": self.password}), "Η πρόταση έχει λήξει")
        self.assertEqual(AccountantProfile.objects.get(user=self.member).role, "accountant")

    def test_sender_security_revocation_blocks_previously_proposed_handover(self):
        offer = self.offer(); self.verified_member()
        state = state_for(self.owner); state.revision += 1; state.save()
        response = self.member_client.post(reverse("office-handover-detail", args=[offer.pk]), {"action": "accept", "password": self.password})
        self.assertContains(response, "Η εξουσιοδότηση ή η κατάσταση")
        self.assertEqual(AccountantProfile.objects.get(user=self.owner).role, "owner")

    def test_cancellation_and_single_use_handover_leave_no_automatic_promotion(self):
        offer = self.offer()
        self.client.post(reverse("office-handover-detail", args=[offer.pk]), {"action": "cancel", "password": self.password})
        self.verified_member()
        response = self.member_client.post(reverse("office-handover-detail", args=[offer.pk]), {"action": "accept", "password": self.password})
        self.assertContains(response, "Η πρόταση δεν είναι πλέον σε αναμονή")
        self.assertEqual(AccountantProfile.objects.get(user=self.member).role, "accountant")

    def test_audit_is_office_scoped_append_only_and_contains_no_invitation_secret(self):
        invite, link = self.invite()
        token = link.rstrip("/").rsplit("/", 1)[-1]
        event = OfficeAuditEvent.objects.get(action="invite.create")
        self.assertNotIn(token, json.dumps(list(OfficeAuditEvent.objects.values()), default=str))
        self.assertNotContains(self.foreign_client.get(reverse("office-audit")), self.owner.username)
        for operation in (lambda: OfficeAuditEvent.objects.filter(pk=event.pk).update(subject="changed"),
                          lambda: OfficeAuditEvent.objects.filter(pk=event.pk).delete()):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_database_rejects_cross_office_workflow_links(self):
        for model, values in ((StaffInvitation, {"office_id": A, "invited_by": self.foreign, "inviter_revision": 0,
                    "recipient_email": "synthetic@example.invalid", "token_digest": secrets.token_hex(32), "expires_at": timezone.now()}),
                (OwnershipHandover, {"office_id": A, "requested_by": self.owner, "recipient": self.foreign,
                    "requester_revision": 0, "expires_at": timezone.now()}),
                (OfficeAuditEvent, {"office_id": A, "actor": self.foreign, "action": "invite.create"})):
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.create(**values)
                connection.check_constraints()

    def test_platform_user_admin_form_prevents_accidental_last_owner_deactivation(self):
        form = GuardedUserChangeForm({"username": self.owner.username, "is_active": "", "date_joined": self.owner.date_joined}, instance=self.owner)
        self.assertFalse(form.is_valid())
        self.assertIn("is_active", form.errors)


class BootstrapOwnerTests(TestCase):
    def test_initial_account_requires_a_named_operator_without_prompting_for_password(self):
        with patch("accounting.management.commands.bootstrap_office_owner.getpass") as prompt, self.assertRaises(CommandError):
            call_command("bootstrap_office_owner", new_office_name="ΔΟΚΙΜΑΣΤΙΚΟ", username="s14-operator-required", email="operator@example.invalid", stdout=io.StringIO())
        prompt.assert_not_called()
        self.assertFalse(Office.objects.exists())

    def test_command_creates_regular_owner_and_first_login_requires_mfa(self):
        password = secrets.token_urlsafe(32)
        out = io.StringIO()
        with patch("accounting.management.commands.bootstrap_office_owner.getpass", return_value=password):
            call_command("bootstrap_office_owner", operator="s14-synthetic-operator", new_office_name="ΔΟΚΙΜΑΣΤΙΚΟ ΝΕΟ ΓΡΑΦΕΙΟ", username="s14-bootstrap-owner", email="bootstrap@example.invalid", stdout=out)
        user = get_user_model().objects.get(username="s14-bootstrap-owner")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertTrue(user.check_password(password))
        self.assertEqual(AccountantProfile.objects.get(user=user).role, "owner")
        event = OfficeAuditEvent.objects.get(action="office.bootstrap")
        self.assertIsNone(event.actor_id)
        self.assertEqual(event.operator_ref, "s14-synthetic-operator")
        self.assertEqual(event.target_user_id, user.pk)
        self.assertNotIn(password, out.getvalue())
        response = self.client.post("/login/", {"username": user.username, "password": password})
        self.assertEqual(response.status_code, 302); self.assertIn("/auth/mfa/setup/", response["Location"])
        with patch("accounting.management.commands.bootstrap_office_owner.getpass") as prompt:
            call_command("bootstrap_office_owner", operator="s14-synthetic-operator", new_office_name="ΔΟΚΙΜΑΣΤΙΚΟ ΝΕΟ ΓΡΑΦΕΙΟ", username=user.username, email=user.email, stdout=io.StringIO())
            prompt.assert_not_called()
        self.assertEqual(Office.objects.count(), 1)

    def test_command_cannot_add_second_owner_or_convert_platform_admin(self):
        password = secrets.token_urlsafe(32)
        with patch("accounting.management.commands.bootstrap_office_owner.getpass", return_value=password):
            call_command("bootstrap_office_owner", operator="s14-synthetic-operator", new_office_name="ΔΟΚΙΜΑΣΤΙΚΟ", username="s14-initial", email="initial@example.invalid", stdout=io.StringIO())
            with self.assertRaises(CommandError):
                call_command("bootstrap_office_owner", operator="s14-synthetic-operator", office=str(Office.objects.get().pk), username="s14-second", email="second@example.invalid", stdout=io.StringIO())
        admin = get_user_model().objects.create_superuser("s14-existing-admin", "admin@example.invalid", password)
        with self.assertRaises(CommandError), patch("accounting.management.commands.bootstrap_office_owner.getpass") as prompt:
            call_command("bootstrap_office_owner", operator="s14-synthetic-operator", new_office_name="ΔΟΚΙΜΑΣΤΙΚΟ ΑΛΛΟ", username=admin.username, email=admin.email, stdout=io.StringIO())
        prompt.assert_not_called()
        self.assertEqual(Office.objects.count(), 1)

    def test_weak_password_rolls_back_office_and_user(self):
        with patch("accounting.management.commands.bootstrap_office_owner.getpass", return_value="123"):
            with self.assertRaises(CommandError):
                call_command("bootstrap_office_owner", operator="s14-synthetic-operator", new_office_name="ΔΟΚΙΜΑΣΤΙΚΟ", username="s14-weak", email="weak@example.invalid", stdout=io.StringIO())
        self.assertFalse(Office.objects.exists())
        self.assertFalse(get_user_model().objects.exists())

    def test_existing_email_does_not_create_another_owner_identity(self):
        password = secrets.token_urlsafe(32)
        get_user_model().objects.create_user("s14-email-existing", "existing@example.invalid", password)
        with patch("accounting.management.commands.bootstrap_office_owner.getpass", return_value=password), self.assertRaises(CommandError):
            call_command("bootstrap_office_owner", operator="s14-synthetic-operator", new_office_name="ΔΟΚΙΜΑΣΤΙΚΟ", username="s14-email-new", email="EXISTING@example.invalid", stdout=io.StringIO())
        self.assertFalse(Office.objects.exists())
        self.assertEqual(get_user_model().objects.count(), 1)


class StaffMailBoundaryTests(SimpleTestCase):
    @override_settings(AUTH_MAIL_MODE="smtp", AUTH_MAIL_LIVE_ENABLED=True, AUTH_STAFF_MAIL_LIVE_ENABLED=False)
    def test_staff_mail_needs_separate_live_scope_even_when_recovery_smtp_is_enabled(self):
        with patch("core.auth_mail.get_connection") as backend:
            result = deliver("ΔΟΚΙΜΑΣΤΙΚΟ", "ΔΟΚΙΜΑΣΤΙΚΟ", "synthetic@example.invalid", purpose="staff")
            self.assertEqual(result, "disabled")
            backend.assert_not_called()

    @override_settings(AUTH_MAIL_MODE="smtp", AUTH_MAIL_LIVE_ENABLED=True, AUTH_STAFF_MAIL_LIVE_ENABLED=True)
    def test_enabled_staff_adapter_uses_django_backend_without_actual_network(self):
        with patch("core.auth_mail.get_connection") as backend:
            self.assertEqual(deliver("ΔΟΚΙΜΑΣΤΙΚΟ", "ΔΟΚΙΜΑΣΤΙΚΟ", "synthetic@example.invalid", purpose="staff"), "submitted")
            backend.return_value.send_messages.assert_called_once()

    def test_invitation_path_redaction_protects_secret(self):
        token = secrets.token_urlsafe(32)
        self.assertNotIn(token, redact_text("GET /join/00000000-0000-4000-8000-00000000000a/" + token + "/"))


class StaffConcurrencyTests(StaffFixtures, TransactionTestCase):
    def parallel(self, operation):
        barrier = Barrier(2)
        def worker(index):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation(index)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            return list(executor.map(worker, range(2)))

    def test_parallel_invitation_accepts_create_only_one_profile(self):
        invite, link = self.invite()
        clients, paths = [], []
        for _ in range(2):
            client, path = self.enter(link); clients.append(client); paths.append(path)
        def accept(index):
            response = clients[index].post(paths[index], {"username": "s14-race-recruit", "password1": self.password, "password2": self.password})
            return "Η πρόσκληση έγινε δεκτή" in response.content.decode()
        result = self.parallel(accept)
        self.assertEqual(sum(result), 1)
        self.assertEqual(AccountantProfile.objects.filter(user__email=invite.recipient_email).count(), 1)

    def test_parallel_two_office_accepts_cannot_create_two_memberships_for_email(self):
        invite_a, link_a = self.invite()
        invite_b, link_b = self.invite(client=self.foreign_client)
        clients, paths = [], []
        for link in (link_a, link_b):
            client, path = self.enter(link); clients.append(client); paths.append(path)
        def accept(index):
            response = clients[index].post(paths[index], {"username": "s14-race-shared-email", "password1": self.password, "password2": self.password, "password": self.password})
            return "Η πρόσκληση έγινε δεκτή" in response.content.decode()
        self.assertEqual(sum(self.parallel(accept)), 1)
        self.assertEqual(get_user_model().objects.filter(email=invite_a.recipient_email).count(), 1)
        self.assertEqual(AccountantProfile.objects.filter(user__email=invite_a.recipient_email).count(), 1)

    def test_parallel_raw_owner_profile_deactivation_preserves_one_active_owner(self):
        create_accountant_profile(user_id=self.member.pk, office_id=A, role="accountant")
        change_membership(user_id=self.member.pk, office_id=A, role="owner", is_active=True)
        users = [self.owner.pk, self.member.pk]
        def deactivate(index):
            try:
                with transaction.atomic():
                    AccountantProfile.objects.filter(user_id=users[index]).update(is_active=False)
                return "changed"
            except IntegrityError:
                return "guarded"
        self.assertEqual(sorted(self.parallel(deactivate)), ["changed", "guarded"])
        self.assertEqual(AccountantProfile.objects.filter(office_id=A, role="owner", is_active=True, user__is_active=True).count(), 1)

    def test_parallel_raw_owner_user_deactivation_preserves_one_authorised_owner(self):
        change_membership(user_id=self.member.pk, office_id=A, role="owner", is_active=True)
        users = [self.owner.pk, self.member.pk]
        def deactivate(index):
            try:
                with transaction.atomic():
                    get_user_model().objects.filter(pk=users[index]).update(is_active=False)
                return "changed"
            except IntegrityError:
                return "guarded"
        self.assertEqual(sorted(self.parallel(deactivate)), ["changed", "guarded"])
        self.assertEqual(AccountantProfile.objects.filter(office_id=A, role="owner", is_active=True, user__is_active=True).count(), 1)

    def test_parallel_handover_accepts_record_one_transfer(self):
        offer = self.offer()
        clients = [Client(), Client()]
        for client in clients:
            self.verified_member(client)
        path = reverse("office-handover-detail", args=[offer.pk])
        def accept(index):
            return clients[index].post(path, {"action": "accept", "password": self.password}).status_code
        result = self.parallel(accept)
        self.assertTrue(all(code in (200, 302, 403) for code in result))
        self.assertEqual(OwnershipHandover.objects.get(pk=offer.pk).status, "accepted")
        self.assertEqual(OfficeAuditEvent.objects.filter(action="handover.accept").count(), 2)
        self.assertEqual(AccountantProfile.objects.filter(office_id=A, role="owner", is_active=True).count(), 1)
