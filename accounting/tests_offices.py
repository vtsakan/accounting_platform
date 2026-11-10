"""S11 contracts, including real PostgreSQL transactions and independent sessions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse

from .legacy_membership import backfill, fingerprint, load_mapping, template
from .membership import change_membership, create_accountant_profile, create_office, require_office_profile
from .middleware import ActiveOfficeMiddleware
from .models import AccountantProfile, Entity, Office

A = "00000000-0000-4000-8000-00000000000a"
B = "00000000-0000-4000-8000-00000000000b"


class OfficeTests(TestCase):
    fixtures = ["s11_offices"]

    def setUp(self):
        self.user = get_user_model().objects.create_user("s11-synthetic-one")
        self.other = get_user_model().objects.create_user("s11-synthetic-two")

    def assign(self, user=None, office=A, role="accountant"):
        return create_accountant_profile(user_id=(user or self.user).pk, office_id=office, role=role)

    def test_retains_auth_user_and_two_greek_office_fixtures(self):
        self.assertEqual(get_user_model()._meta.label, "auth.User")
        self.assertEqual(Office.objects.count(), 2)
        self.assertTrue(Office.objects.get(pk=A).name.startswith("ΔΟΚΙΜΑΣΤΙΚΟ"))
        self.assertFalse(AccountantProfile.objects.exists())  # No signals/defaults.

    def test_multiple_accountants_share_office(self):
        first, second = self.assign(), self.assign(self.other, role="owner")
        self.assertEqual(first.office_id, second.office_id)
        self.assertEqual(first.office.accountants.count(), 2)

    def test_exact_creation_retry_is_idempotent(self):
        first = self.assign()
        self.assertEqual(self.assign().pk, first.pk)
        self.assertEqual(AccountantProfile.objects.count(), 1)

    def test_second_office_rejected_by_service(self):
        self.assign()
        with self.assertRaises(ValidationError):
            self.assign(office=B)
        self.assertEqual(str(self.user.accountant_profile.office_id), A)

    def test_database_unique_user_survives_service_bypass(self):
        self.assign()
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountantProfile.objects.create(user=self.user, office_id=B, role="owner")

    def test_database_requires_office_user_and_valid_role(self):
        for changes in ({"office_id": None}, {"user_id": None}, {"role": "manager"}, {"role": ""}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                AccountantProfile.objects.create(**{"user_id": self.user.pk, "office_id": A, "role": "accountant", **changes})

    def test_database_rejects_unknown_office(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AccountantProfile.objects.create(user=self.user, office_id="00000000-0000-4000-8000-00000000000c", role="owner")
            connection.check_constraints()

    def test_office_and_user_deletion_protect_membership(self):
        profile = self.assign()
        for instance in (profile.office, self.user):
            with self.assertRaises(ProtectedError):
                instance.delete()

    def test_service_rejects_inactive_user_office_invalid_role(self):
        self.user.is_active = False; self.user.save()
        with self.assertRaises(ValidationError):
            self.assign()
        self.user.is_active = True; self.user.save()
        Office.objects.filter(pk=A).update(is_active=False)
        with self.assertRaises(ValidationError):
            self.assign()
        with self.assertRaises(ValidationError):
            self.assign(office=B, role="administrator")

    def test_same_office_membership_changes_and_revocation(self):
        profile = self.assign()
        change_membership(user_id=self.user.pk, office_id=A, role="owner", is_active=False)
        profile.refresh_from_db()
        self.assertEqual(profile.role, "owner")
        self.assertFalse(profile.is_active)
        with self.assertRaises(PermissionDenied):
            require_office_profile(self.user)
        with self.assertRaises(ValidationError):
            self.assign(role="owner")  # Retry cannot silently reactivate.

    def test_changes_cannot_transfer_to_second_office(self):
        self.assign()
        with self.assertRaises(ValidationError):
            change_membership(user_id=self.user.pk, office_id=B, role="owner", is_active=True)
        self.assertEqual(str(require_office_profile(self.user).office_id), A)

    def test_create_office_requires_nonblank_name(self):
        with self.assertRaises(ValidationError):
            create_office(name="  ")
        office = create_office(name="  ΔΟΚΙΜΑΣΤΙΚΟ ΝΕΟ ΓΡΑΦΕΙΟ  ")
        self.assertEqual(office.name, "ΔΟΚΙΜΑΣΤΙΚΟ ΝΕΟ ΓΡΑΦΕΙΟ")

    def test_all_legacy_business_routes_deny_missing_profile_get_and_post(self):
        from .urls import urlpatterns
        self.client.force_login(self.user)
        for entry in urlpatterns:
            if entry.name in {"login", "logout"}:
                continue
            path = reverse(entry.name, kwargs={"pk": 1} if "<int:pk>" in str(entry.pattern) else {})
            for method in (self.client.get, self.client.post):
                with self.subTest(path=path, method=method.__name__):
                    response = method(path, {}, HTTP_ACCEPT_LANGUAGE="en-US,en")
                    self.assertContains(response, "Απαιτείται ενεργό προφίλ λογιστή", status_code=403)
                    self.assertEqual(response["Content-Language"], "el")
                    self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(Entity.objects.count(), 0)

    def test_superuser_has_no_business_bypass(self):
        self.user.is_staff = self.user.is_superuser = True; self.user.save()
        self.client.force_login(self.user)
        Entity.objects.create(office_id=A, name="s11-unmapped-admin-canary", entity_type="CUSTOMER")
        for path in ("/", reverse("admin:accounting_entity_changelist"), reverse("admin:accounting_entity_add"),
                     reverse("admin:autocomplete") + "?app_label=accounting&model_name=transaction&field_name=entity&term=s11",
                     reverse("admin:app_list", kwargs={"app_label": "accounting"})):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_anonymous_login_health_and_logout_stay_available(self):
        self.assertEqual(self.client.get("/customers/").status_code, 302)
        self.assertEqual(self.client.get("/login/").status_code, 200)
        self.assertEqual(self.client.get("/health/live/").status_code, 200)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/logout/").status_code, 302)

    def test_inactive_office_or_profile_blocks_existing_session_next_request(self):
        profile = self.assign()
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/customers/").status_code, 200)
        for model, pk in ((Office, A), (AccountantProfile, profile.pk)):
            model.objects.filter(pk=pk).update(is_active=False)
            self.assertEqual(self.client.get("/customers/").status_code, 403)
            model.objects.filter(pk=pk).update(is_active=True)

    def test_profile_lookup_ignores_cached_user_and_reverse_relation(self):
        self.assign()
        _ = self.user.accountant_profile
        get_user_model().objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            require_office_profile(self.user)

    def test_submitted_office_cannot_override_context(self):
        profile = self.assign()
        request = RequestFactory().get("/customers/", {"office_id": B}, HTTP_X_OFFICE_ID=B)
        request.user = self.user
        def view(request):
            pass
        view.__module__ = "accounting.views"
        self.assertIsNone(ActiveOfficeMiddleware(lambda r: None).process_view(request, view, (), {}))
        self.assertEqual(request.office.pk, profile.office_id)


class LegacyMappingTests(TestCase):
    fixtures = ["s11_offices"]

    def setUp(self):
        self.first = get_user_model().objects.create_user("s11-mapping-one")
        self.second = get_user_model().objects.create_user("s11-mapping-two")

    def mapping(self):
        document = template()
        document.update(reviewed_by="S11 automated synthetic reviewer", reviewed_at=datetime.now(timezone.utc).isoformat())
        for row in document["mappings"]:
            row.update(office_id=A, role="accountant")
        return document

    def test_reviewed_dry_run_changes_nothing_and_apply_retries_match(self):
        document = self.mapping()
        report = backfill(document)
        self.assertEqual(report["would_create"], 2)
        self.assertFalse(AccountantProfile.objects.exists())
        self.assertEqual(backfill(document, apply=True)["status"], "Applied")
        self.assertEqual(backfill(document, apply=True)["already_matching"], 2)
        self.assertEqual(AccountantProfile.objects.count(), 2)

    def test_missing_duplicate_unknown_and_ambiguous_mappings_rejected(self):
        cases = []
        doc = self.mapping(); doc["mappings"].pop(); cases.append(doc)
        doc = self.mapping(); doc["mappings"].append(doc["mappings"][0].copy()); cases.append(doc)
        doc = self.mapping(); doc["mappings"][0]["user_id"] = 900000; cases.append(doc)
        doc = self.mapping(); doc["mappings"][0]["username"] = self.second.username; cases.append(doc)
        for doc in cases:
            with self.assertRaises(ValidationError):
                backfill(doc, apply=True)
        self.assertFalse(AccountantProfile.objects.exists())

    def test_bad_review_stale_inventory_role_and_office_rejected(self):
        cases = []
        for field, value in (("reviewed_by", ""), ("reviewed_at", "2026-11-10"), ("inventory_sha256", "changed")):
            doc = self.mapping(); doc[field] = value; cases.append(doc)
        for field, value in (("role", "administrator"), ("office_id", ""), ("office_id", "00000000-0000-4000-8000-00000000000c")):
            doc = self.mapping(); doc["mappings"][0][field] = value; cases.append(doc)
        for doc in cases:
            with self.assertRaises(ValidationError):
                backfill(doc, apply=True)
        doc = self.mapping()
        get_user_model().objects.create_user("s11-new-user-after-review")
        with self.assertRaises(ValidationError):
            backfill(doc, apply=True)

    def test_explicit_exclusion_is_reviewed_and_has_no_business_access(self):
        doc = self.mapping(); row = doc["mappings"].pop()
        doc["excluded_users"].append({"user_id": row["user_id"], "username": row["username"], "reason": "Synthetic platform-only user"})
        self.assertEqual(backfill(doc, apply=True)["excluded_without_business_access"], 1)
        with self.assertRaises(PermissionDenied):
            require_office_profile(get_user_model().objects.get(pk=row["user_id"]))

    def test_existing_profile_conflict_or_inactive_profile_rejected(self):
        document = self.mapping()
        create_accountant_profile(user_id=self.first.pk, office_id=B, role="owner")
        with self.assertRaises(ValidationError):
            backfill(document, apply=True)
        self.assertEqual(AccountantProfile.objects.count(), 1)

    def test_apply_rolls_back_all_rows_if_later_service_fails(self):
        original = create_accountant_profile
        def failing(**kwargs):
            if kwargs["user_id"] == self.second.pk:
                raise ValidationError("Synthetic failure")
            return original(**kwargs)
        with patch("accounting.legacy_membership.create_accountant_profile", side_effect=failing):
            with self.assertRaises(ValidationError):
                backfill(self.mapping(), apply=True)
        self.assertFalse(AccountantProfile.objects.exists())

    def test_command_template_is_private_exclusive_and_requires_review(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mapping.json"
            call_command("backfill_accountant_profiles", export_template=path, stdout=io.StringIO())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(CommandError):
                call_command("backfill_accountant_profiles", export_template=path, stdout=io.StringIO())
            with self.assertRaises(CommandError):
                call_command("backfill_accountant_profiles", mapping=path, stdout=io.StringIO())

    def test_command_apply_requires_reviewed_digest_and_is_dry_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mapping.json"; document = self.mapping()
            path.write_text(json.dumps(document))
            call_command("backfill_accountant_profiles", mapping=path, stdout=io.StringIO())
            self.assertFalse(AccountantProfile.objects.exists())
            with self.assertRaises(CommandError):
                call_command("backfill_accountant_profiles", mapping=path, apply=True, stdout=io.StringIO())
            call_command("backfill_accountant_profiles", mapping=path, apply=True, expected_sha256=fingerprint(document), stdout=io.StringIO())
            self.assertEqual(AccountantProfile.objects.count(), 2)

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "mapping.json"; path.write_text('{"schema": 1, "schema": 1}')
            with self.assertRaises(ValidationError):
                load_mapping(path)


class MembershipConcurrencyTests(TransactionTestCase):
    fixtures = ["s11_offices"]

    def setUp(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.pg_version // 10000, 17)
        self.user = get_user_model().objects.create_user("s11-concurrent-synthetic")

    def race(self, offices, *, bypass=False):
        gate = Barrier(2)
        user_id = self.user.pk
        def worker(office_id):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                gate.wait(timeout=10)
                if bypass:
                    with transaction.atomic():
                        profile = AccountantProfile.objects.create(user_id=user_id, office_id=office_id, role="accountant")
                else:
                    profile = create_accountant_profile(user_id=user_id, office_id=office_id, role="accountant")
                return ("created", profile.pk)
            except ValidationError as error:
                return (error.code, None)
            except IntegrityError:
                return ("integrity_error", None)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, office_id) for office_id in offices]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(AccountantProfile.objects.filter(user_id=user_id).count(), 1)
        return results

    def test_competing_first_assignments_to_different_offices(self):
        self.assertEqual(sorted(result[0] for result in self.race([A, B])), ["created", "membership_conflict"])

    def test_same_office_concurrent_retry_returns_same_profile(self):
        results = self.race([A, A])
        self.assertEqual([r[0] for r in results], ["created", "created"])
        self.assertEqual(results[0][1], results[1][1])

    def test_database_constraint_prevents_concurrent_direct_inserts(self):
        self.assertEqual(sorted(result[0] for result in self.race([A, B], bypass=True)), ["created", "integrity_error"])
