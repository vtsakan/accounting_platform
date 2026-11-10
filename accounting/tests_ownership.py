"""S12: two-office HTTP/admin/database and reviewed migration contracts."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
from threading import Barrier
from unittest.mock import patch

from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .forms import AgreementForm, EntityForm, IncomeForm
from .legacy_membership import fingerprint
from .legacy_ownership import MODELS, backfill, template
from .membership import create_accountant_profile
from .models import AccountantProfile, Agreement, CashAccount, Category, Entity, Office, Transaction
from .office_access import execution_record, record, records, save_for_user
from .tests_auth_support import staff_client_login

A = "00000000-0000-4000-8000-00000000000a"
B = "00000000-0000-4000-8000-00000000000b"
DAY = date(2026, 1, 15)


class OfficeBoundaryTests(TestCase):
    fixtures = ["s11_offices"]

    @classmethod
    def setUpTestData(cls):
        cls.user_a = get_user_model().objects.create_user("s12-synthetic-a")
        cls.user_b = get_user_model().objects.create_user("s12-synthetic-b")
        cls.admin_a = get_user_model().objects.create_user("s12-synthetic-platform", is_staff=True, is_superuser=True)
        for user, office in ((cls.user_a, A), (cls.user_b, B), (cls.admin_a, A)):
            create_accountant_profile(user_id=user.pk, office_id=office, role="owner")
        for suffix, office, income in (("a", A, "5.00"), ("b", B, "777.00")):
            entity = Entity.objects.create(office_id=office, name="ΠΕΛΑΤΗΣ_ΓΡΑΦΕΙΟΥ_" + ("Α" if suffix == "a" else "Β"), entity_type="CUSTOMER", vat_number="000000101")
            supplier = Entity.objects.create(office_id=office, name="ΠΡΟΜΗΘΕΥΤΗΣ_ΓΡΑΦΕΙΟΥ_" + ("Α" if suffix == "a" else "Β"), entity_type="SUPPLIER", vat_number="000000102")
            account = CashAccount.objects.create(office_id=office, name="ΚΟΙΝΟ ΤΑΜΕΙΟ", opening_balance=Decimal("100.00"))
            category = Category.objects.create(office_id=office, name="ΚΑΤΗΓΟΡΙΑ_ΓΡΑΦΕΙΟΥ_" + ("Α" if suffix == "a" else "Β"))
            agreement = Agreement.objects.create(office_id=office, entity=entity, agreement_type="RECEIVABLE", description="ΣΥΜΦΩΝΙΑ_ΓΡΑΦΕΙΟΥ_" + ("Α" if suffix == "a" else "Β"), total_amount=Decimal("9999.00"), start_date=DAY)
            payable = Agreement.objects.create(office_id=office, entity=supplier, agreement_type="PAYABLE", description="ΥΠΟΧΡΕΩΣΗ_ΓΡΑΦΕΙΟΥ_" + ("Α" if suffix == "a" else "Β"), total_amount=Decimal("100.00"), start_date=DAY)
            movement = Transaction.objects.create(office_id=office, transaction_date=DAY, transaction_type="INCOME", amount=Decimal(income),
                description="ΚΙΝΗΣΗ_ΓΡΑΦΕΙΟΥ_" + ("Α" if suffix == "a" else "Β"), cash_account=account, category=category, entity=entity, agreement=agreement)
            Transaction.objects.create(office_id=office, transaction_date=DAY, transaction_type="EXPENSE", amount=Decimal("2.00"),
                description="ΕΞΟΔΟ_ΓΡΑΦΕΙΟΥ_" + ("Α" if suffix == "a" else "Β"), cash_account=account, category=category)
            for name, value in (("entity", entity), ("supplier", supplier), ("account", account), ("category", category),
                                ("agreement", agreement), ("payable", payable), ("movement", movement)):
                setattr(cls, name + "_" + suffix, value)

    def setUp(self):
        staff_client_login(self.client, self.user_a)

    def income_data(self):
        return {"transaction_date": DAY.isoformat(), "description": "ΔΟΚΙΜΑΣΤΙΚΗ ΕΓΓΡΑΦΗ", "amount": "1,00",
                "cash_account": self.account_a.pk, "category": self.category_a.pk,
                "entity": self.entity_a.pk, "agreement": self.agreement_a.pk}

    def test_lists_and_reports_never_render_other_office_labels(self):
        for path in ("/", "/customers/", "/suppliers/", "/transactions/", "/agreements/", "/report/",
                     reverse("entity-detail", args=[self.entity_a.pk]), reverse("agreement-detail", args=[self.agreement_a.pk])):
            with self.subTest(path=path):
                response = self.client.get(path, HTTP_ACCEPT_LANGUAGE="en-US,en")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("ΓΡΑΦΕΙΟΥ_Β", response.content.decode())
                self.assertEqual(response["Content-Language"], "el")

    def test_cash_and_agreement_aggregates_are_office_scoped(self):
        response = self.client.get("/")
        self.assertEqual([(a.pk, a.current_balance) for a in response.context["cash_accounts"]], [(self.account_a.pk, Decimal("103.00"))])
        response = self.client.get("/report/")
        self.assertEqual(response.context["total_income"], Decimal("5.00"))
        self.assertEqual(response.context["total_expense"], Decimal("2.00"))
        self.assertEqual(response.context["accounts_receivable"], Decimal("9994.00"))

    def test_foreign_details_and_edits_return_404_for_get_and_post(self):
        for name, obj in (("entity-detail", self.entity_b), ("edit-entity", self.entity_b),
                          ("agreement-detail", self.agreement_b), ("edit-agreement", self.agreement_b)):
            for method in (self.client.get, self.client.post):
                with self.subTest(name=name, method=method.__name__):
                    self.assertEqual(method(reverse(name, args=[obj.pk]), {"name": "ATTEMPT"}).status_code, 404)
        self.entity_b.refresh_from_db()
        self.assertIn("ΓΡΑΦΕΙΟΥ_Β", self.entity_b.name)

    def test_foreign_filter_and_initial_ids_are_rejected(self):
        for path in ("/transactions/", "/report/"):
            for field, obj in (("cash_account", self.account_b), ("category", self.category_b), ("entity", self.entity_b)):
                self.assertEqual(self.client.get(path, {field: obj.pk}).status_code, 404)
        for path in ("/income/add/", "/expense/add/", "/agreement/add/"):
            self.assertEqual(self.client.get(path, {"entity_id": self.entity_b.pk}).status_code, 404)

    def test_both_directions_of_office_isolation(self):
        staff_client_login(self.client, self.user_b)
        response = self.client.get("/customers/")
        self.assertContains(response, "ΠΕΛΑΤΗΣ_ΓΡΑΦΕΙΟΥ_Β")
        self.assertNotContains(response, "ΠΕΛΑΤΗΣ_ΓΡΑΦΕΙΟΥ_Α")
        self.assertEqual(self.client.get(reverse("entity-detail", args=[self.entity_a.pk])).status_code, 404)

    def test_all_frontend_related_choices_are_scoped(self):
        for path in ("/income/add/", "/expense/add/", "/agreement/add/", "/transfer/add/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            for field in response.context["form"].fields.values():
                if hasattr(field, "queryset"):
                    self.assertFalse(field.queryset.exclude(office_id=A).exists())

    def test_forged_income_relations_are_field_errors_with_no_write(self):
        before = Transaction.objects.count()
        for field, obj in (("cash_account", self.account_b), ("category", self.category_b),
                           ("entity", self.entity_b), ("agreement", self.agreement_b)):
            data = self.income_data(); data[field] = obj.pk
            response = self.client.post("/income/add/", data)
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context["form"].errors)
            self.assertEqual(Transaction.objects.count(), before)

    def test_forged_expense_relations_are_rejected(self):
        before = Transaction.objects.count()
        base = self.income_data(); base.update(entity=self.supplier_a.pk, agreement=self.payable_a.pk)
        for field, obj in (("cash_account", self.account_b), ("category", self.category_b),
                           ("entity", self.supplier_b), ("agreement", self.payable_b)):
            response = self.client.post("/expense/add/", {**base, field: obj.pk})
            self.assertEqual(response.status_code, 200)
            self.assertIn(field, response.context["form"].errors)
        self.assertEqual(Transaction.objects.count(), before)

    def test_forged_transfer_and_agreement_relations_cannot_write(self):
        response = self.client.post("/transfer/add/", {"transfer_date": DAY.isoformat(), "amount": "1,00", "description": "ΔΟΚΙΜΗ",
            "from_account": self.account_a.pk, "to_account": self.account_b.pk})
        self.assertIn("to_account", response.context["form"].errors)
        before = Agreement.objects.count()
        response = self.client.post("/agreement/add/", {"entity": self.entity_b.pk, "agreement_type": "RECEIVABLE",
            "description": "ΔΟΚΙΜΗ", "total_amount": "10,00", "start_date": DAY.isoformat(), "status": "ACTIVE"})
        self.assertIn("entity", response.context["form"].errors)
        self.assertEqual(Agreement.objects.count(), before)

    def test_submitted_office_fields_do_not_select_ownership(self):
        response = self.client.post("/entity/add/", {"name": "ΔΟΚΙΜΑΣΤΙΚΟΣ ΝΕΟΣ", "entity_type": "CUSTOMER",
            "vat_number": "000000199", "office": B, "office_id": B})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(str(Entity.objects.get(vat_number="000000199").office_id), A)

    def test_own_entity_and_agreement_edits_remain_allowed(self):
        response = self.client.post(reverse("edit-entity", args=[self.entity_a.pk]), {
            "name": "ΔΟΚΙΜΑΣΤΙΚΗ ΕΝΗΜΕΡΩΣΗ", "entity_type": "CUSTOMER", "vat_number": self.entity_a.vat_number, "office": B})
        self.assertEqual(response.status_code, 302)
        self.entity_a.refresh_from_db(); self.assertEqual(str(self.entity_a.office_id), A)
        response = self.client.post(reverse("edit-agreement", args=[self.agreement_a.pk]), {
            "entity": self.entity_a.pk, "agreement_type": "RECEIVABLE", "description": "ΔΟΚΙΜΑΣΤΙΚΗ ΕΝΗΜΕΡΩΣΗ",
            "total_amount": "9999,00", "start_date": DAY.isoformat(), "status": "ACTIVE", "office_id": B})
        self.assertEqual(response.status_code, 302)
        self.agreement_a.refresh_from_db(); self.assertEqual(str(self.agreement_a.office_id), A)

    def test_validated_form_cannot_save_after_revocation(self):
        form = EntityForm({"name": "ΔΟΚΙΜΑΣΤΙΚΗ ΝΕΑ", "entity_type": "CUSTOMER", "vat_number": "000000177"}, user=self.user_a)
        self.assertTrue(form.is_valid(), form.errors)
        AccountantProfile.objects.filter(user=self.user_a).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            form.save()
        self.assertFalse(Entity.objects.filter(vat_number="000000177").exists())

    def test_form_without_actor_exposes_no_choices_and_cannot_validate(self):
        form = IncomeForm(self.income_data(), agreements_queryset=Agreement.objects.all())
        self.assertFalse(form.is_valid())
        for field in form.fields.values():
            if hasattr(field, "queryset"):
                self.assertFalse(field.queryset.exists())

    def test_form_rechecks_revocation_and_rejects_foreign_instance(self):
        form = IncomeForm(self.income_data(), user=self.user_a, agreements_queryset=Agreement.objects.all())
        AccountantProfile.objects.filter(user=self.user_a).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            form.is_valid()
        with self.assertRaises(PermissionDenied):
            EntityForm(user=self.user_b, instance=self.entity_a)

    def test_model_validation_rejects_cross_office_links_and_moving_rows(self):
        for obj, field, value in ((self.agreement_a, "entity", self.entity_b), (self.movement_a, "cash_account", self.account_b),
                                  (self.category_a, "parent", self.category_b), (self.entity_a, "office_id", B)):
            setattr(obj, field, value)
            with self.assertRaises(ValidationError):
                obj.save()

    def test_database_composite_foreign_keys_cover_every_relation(self):
        for child, field, target in ((Category, "parent_id", self.category_b.pk), (Agreement, "entity_id", self.entity_b.pk),
                                    (Transaction, "cash_account_id", self.account_b.pk), (Transaction, "category_id", self.category_b.pk),
                                    (Transaction, "entity_id", self.entity_b.pk), (Transaction, "agreement_id", self.agreement_b.pk)):
            obj = self.category_a if child is Category else self.agreement_a if child is Agreement else self.movement_a
            with self.subTest(field=field), self.assertRaises(IntegrityError), transaction.atomic():
                child.objects.filter(pk=obj.pk).update(**{field: target})
                connection.check_constraints()

    def test_database_blocks_null_and_changed_office_on_all_five_tables(self):
        for obj in (self.entity_a, self.account_a, self.category_a, self.agreement_a, self.movement_a):
            for office in (None, B):
                with self.subTest(model=type(obj).__name__, office=office), self.assertRaises(IntegrityError), transaction.atomic():
                    type(obj).objects.filter(pk=obj.pk).update(office_id=office)

    def test_unique_values_are_per_office_and_empty_afm_is_repeatable(self):
        self.assertEqual(CashAccount.objects.filter(name="ΚΟΙΝΟ ΤΑΜΕΙΟ").count(), 2)
        self.assertEqual(Entity.objects.filter(vat_number="000000101").count(), 2)
        for vat in (None, "", None, ""):
            Entity.objects.create(office_id=A, name="ΔΟΚΙΜΑΣΤΙΚΟ ΧΩΡΙΣ ΑΦΜ", entity_type="CUSTOMER", vat_number=vat)
        for model, obj in ((CashAccount, CashAccount(office_id=A, name="ΚΟΙΝΟ ΤΑΜΕΙΟ")),
                           (Entity, Entity(office_id=A, name="ΔΟΚΙΜΗ", entity_type="CUSTOMER", vat_number="000000101"))):
            with self.assertRaises(IntegrityError), transaction.atomic():
                model.objects.bulk_create([obj])

    def test_admin_lists_foreign_key_choices_and_filters_do_not_leak(self):
        staff_client_login(self.client, self.admin_a)
        for model in MODELS:
            response = self.client.get(reverse("admin:accounting_" + model + "_changelist"))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.context["cl"].queryset.exclude(office_id=A).exists())
            self.assertNotIn("ΓΡΑΦΕΙΟΥ_Β", response.content.decode())
        response = self.client.get(reverse("admin:accounting_transaction_add"))
        form = response.context["adminform"].form
        self.assertNotIn("office", form.fields)
        for field in form.fields.values():
            if hasattr(field, "queryset"):
                self.assertFalse(field.queryset.exclude(office_id=A).exists())

    def test_admin_foreign_change_history_delete_are_denied(self):
        staff_client_login(self.client, self.admin_a)
        for suffix in ("change", "history", "delete"):
            path = reverse("admin:accounting_entity_" + suffix, args=[self.entity_b.pk])
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.post(path, {"post": "yes"}).status_code, 404)
        self.assertTrue(Entity.objects.filter(pk=self.entity_b.pk).exists())

    def test_admin_autocomplete_is_scoped(self):
        staff_client_login(self.client, self.admin_a)
        response = self.client.get(reverse("admin:autocomplete"), {"app_label": "accounting", "model_name": "transaction", "field_name": "entity", "term": "ΠΕΛΑΤΗΣ"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({r["id"] for r in response.json()["results"]}, {str(self.entity_a.pk)})

    def test_admin_cannot_forge_office_lookup_or_bulk_action(self):
        staff_client_login(self.client, self.admin_a)
        path = reverse("admin:accounting_entity_changelist")
        self.assertEqual(self.client.get(path, {"office__id__exact": B}).status_code, 400)
        self.assertEqual(self.client.post(path, {"action": "delete_selected", "_selected_action": [self.entity_a.pk, self.entity_b.pk]}).status_code, 403)
        self.assertTrue(Entity.objects.filter(pk=self.entity_a.pk).exists())
        self.assertTrue(Entity.objects.filter(pk=self.entity_b.pk).exists())

    def test_admin_forged_fk_post_does_not_create_transaction(self):
        staff_client_login(self.client, self.admin_a)
        before = Transaction.objects.count()
        data = self.income_data(); data.update(transaction_type="INCOME", cash_account=self.account_b.pk, amount="1,00")
        response = self.client.post(reverse("admin:accounting_transaction_add"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("cash_account", response.context["adminform"].form.errors)
        self.assertEqual(Transaction.objects.count(), before)

    def test_admin_index_hides_unscoped_historical_labels(self):
        LogEntry.objects.create(user=self.admin_a, content_type=ContentType.objects.get_for_model(Entity),
            object_id=str(self.entity_b.pk), object_repr="FOREIGN_AUDIT_CANARY", action_flag=ADDITION)
        staff_client_login(self.client, self.admin_a)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "FOREIGN_AUDIT_CANARY")
        self.assertEqual(LogEntry.objects.filter(object_repr="FOREIGN_AUDIT_CANARY").count(), 1)

    def test_execution_adapter_rechecks_actor_office_and_revocation(self):
        args = {"user_id": self.user_a.pk, "expected_office_id": A, "model": Entity, "key": self.entity_a.pk}
        self.assertEqual(execution_record(**args).pk, self.entity_a.pk)
        with self.assertRaises(PermissionDenied):
            execution_record(**{**args, "expected_office_id": B})
        AccountantProfile.objects.filter(user=self.user_a).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            execution_record(**args)

    def test_unsupported_models_and_anonymous_context_are_denied(self):
        for actor in (AnonymousUser(), get_user_model().objects.create_user("s12-no-profile")):
            with self.assertRaises(PermissionDenied):
                records(Entity, actor)
        with self.assertRaises(PermissionDenied):
            records(Office, self.user_a)
        with self.assertRaises(PermissionDenied):
            save_for_user(self.entity_b, self.user_a)


@override_settings(MIDDLEWARE=[m for m in settings.MIDDLEWARE if m not in {
    "django_otp.middleware.OTPMiddleware", "accounting.auth_middleware.StaffSecurityMiddleware"}])
class OwnershipMigrationTests(TransactionTestCase):
    # Rehearses the historical 0003/0004 schema before S13 auth tables exist.
    def migrate_to(self, name):
        executor = MigrationExecutor(connection)
        executor.migrate([("accounting", name)])
        return executor.loader.project_state([("accounting", name)]).apps

    def setUp(self):
        apps = self.migrate_to("0003_office_profiles")
        Office.objects.create(pk=A, name="ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ Α S12")
        Office.objects.create(pk=B, name="ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ Β S12")
        entity = apps.get_model("accounting", "Entity").objects.create(name="ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΕΓΓΡΑΦΗ", entity_type="CUSTOMER", vat_number="000000111")
        account = apps.get_model("accounting", "CashAccount").objects.create(name="ΔΟΚΙΜΑΣΤΙΚΟ ΠΑΛΑΙΟ ΤΑΜΕΙΟ", opening_balance="1234.56")
        category = apps.get_model("accounting", "Category").objects.create(name="ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΚΑΤΗΓΟΡΙΑ")
        agreement = apps.get_model("accounting", "Agreement").objects.create(entity=entity, agreement_type="RECEIVABLE", description="ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΣΥΜΦΩΝΙΑ", total_amount=Decimal("100.00"), start_date=DAY)
        apps.get_model("accounting", "Transaction").objects.create(transaction_date=DAY, transaction_type="INCOME", amount="12.34", description="ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΚΙΝΗΣΗ", cash_account=account, category=category, entity=entity, agreement=agreement)
        self.migrate_to("0004_office_ownership_nullable")

    def tearDown(self):
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE accounting_transaction, accounting_agreement, accounting_category, accounting_cashaccount, accounting_entity CASCADE")
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def mapping(self):
        document = template()
        document.update(reviewed_by="S12 automated synthetic reviewer", reviewed_at=datetime.now(timezone.utc).isoformat())
        for row in document["assignments"]:
            row["office_id"] = A
        return document

    def test_unreviewed_database_pauses_at_nullable_stage(self):
        with self.assertRaisesRegex(RuntimeError, "S12 paused"):
            self.migrate_to("0005_enforce_office_ownership")
        applied = MigrationRecorder(connection).applied_migrations()
        self.assertIn(("accounting", "0004_office_ownership_nullable"), applied)
        self.assertNotIn(("accounting", "0005_enforce_office_ownership"), applied)
        self.assertTrue(all(model.objects.filter(office_id__isnull=True).exists() for model in MODELS.values()))

    def test_reviewed_dry_run_apply_retry_and_final_enforcement_preserve_source(self):
        document = self.mapping(); initial = deepcopy(document["inventory"])
        self.assertFalse(backfill(document)["database_changed"])
        self.assertEqual(sum(model.objects.filter(office_id__isnull=True).count() for model in MODELS.values()), 5)
        self.assertEqual(backfill(document, apply=True)["would_assign"], 5)
        self.migrate_to("0005_enforce_office_ownership")
        self.assertEqual(template()["inventory"], initial)
        self.assertFalse(backfill(document, apply=True)["database_changed"])
        self.assertEqual(Office.objects.count(), 2)
        for model in MODELS.values():
            self.assertEqual(str(model.objects.get().office_id), A)

    def test_incomplete_duplicate_unknown_and_conflicting_mappings_rejected(self):
        documents = []
        d = self.mapping(); d["assignments"].pop(); documents.append(d)
        d = self.mapping(); d["assignments"].append(d["assignments"][0].copy()); documents.append(d)
        d = self.mapping(); d["assignments"][0]["id"] = 900000; documents.append(d)
        d = self.mapping(); next(r for r in d["assignments"] if r["model"] == "agreement")["office_id"] = B; documents.append(d)
        d = self.mapping(); d["reviewed_by"] = ""; documents.append(d)
        for document in documents:
            with self.assertRaises(ValidationError):
                backfill(document, apply=True)
        self.assertTrue(all(model.objects.get().office_id is None for model in MODELS.values()))

    def test_source_changes_invalidate_review(self):
        document = self.mapping()
        Entity.objects.update(name="ΔΟΚΙΜΑΣΤΙΚΗ ΑΛΛΑΓΗ ΜΕΤΑ ΤΟΝ ΕΛΕΓΧΟ")
        with self.assertRaises(ValidationError):
            backfill(document, apply=True)

    def test_partial_backfill_failure_rolls_back_all_tables(self):
        document = self.mapping()
        with patch.object(Transaction.objects, "filter", side_effect=RuntimeError("Synthetic backfill failure")):
            with self.assertRaises(RuntimeError):
                backfill(document, apply=True)
        self.assertTrue(all(model.objects.get().office_id is None for model in MODELS.values()))

    def test_unassigned_records_are_invisible_to_existing_profile(self):
        user = get_user_model().objects.create_user("s12-pre-backfill-synthetic")
        create_accountant_profile(user_id=user.pk, office_id=A, role="owner")
        self.assertFalse(records(Entity, user).exists())
        self.client.force_login(user)
        self.assertNotContains(self.client.get("/customers/"), "ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΕΓΓΡΑΦΗ")

    def test_final_guard_rejects_raw_conflicting_ownership(self):
        for model in MODELS.values():
            model.objects.update(office_id=A)
        Transaction.objects.update(office_id=B)
        with self.assertRaisesRegex(RuntimeError, "conflicting office ownership"):
            self.migrate_to("0005_enforce_office_ownership")

    def test_command_requires_digest_and_export_is_private(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ownership.json"
            call_command("backfill_office_records", export_template=path, stdout=io.StringIO())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            document = self.mapping(); path.write_text(json.dumps(document))
            call_command("backfill_office_records", mapping=path, stdout=io.StringIO())
            with self.assertRaises(CommandError):
                call_command("backfill_office_records", mapping=path, apply=True, stdout=io.StringIO())
            call_command("backfill_office_records", mapping=path, apply=True, expected_sha256=fingerprint(document), stdout=io.StringIO())
        self.assertTrue(all(str(model.objects.get().office_id) == A for model in MODELS.values()))


class OfficeUniquenessConcurrencyTests(TransactionTestCase):
    fixtures = ["s11_offices"]

    def race(self, model, offices):
        gate = Barrier(2)
        def worker(office):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                gate.wait(timeout=10)
                obj = (CashAccount(office_id=office, name="ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ ΑΓΩΝΑ") if model is CashAccount else
                       Entity(office_id=office, name="ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ ΑΓΩΝΑ", entity_type="CUSTOMER", vat_number="000000188"))
                model.objects.bulk_create([obj])
                return "created"
            except IntegrityError:
                return "duplicate"
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, office) for office in offices]
            return sorted(f.result(timeout=20) for f in futures)

    def test_same_office_account_name_race_is_unique(self):
        self.assertEqual(self.race(CashAccount, [A, A]), ["created", "duplicate"])

    def test_same_office_nonempty_afm_race_is_unique(self):
        self.assertEqual(self.race(Entity, [A, A]), ["created", "duplicate"])

    def test_different_offices_can_create_the_same_name_concurrently(self):
        self.assertEqual(self.race(CashAccount, [A, B]), ["created", "created"])
