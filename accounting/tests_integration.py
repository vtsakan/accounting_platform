import io
import secrets
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.test import TestCase, override_settings
from django.utils import timezone

from accounting.models import CashAccount, Entity, Transaction
from accounting.membership import create_accountant_profile, create_office


class PostgreSQLFoundationTests(TestCase):
    def setUp(self):
        self.office = create_office(name="ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ S05")

    def test_postgresql17_migration_history_and_tables(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertEqual(connection.pg_version // 10000, 17)
        nodes = {name for app, name in MigrationRecorder(connection).applied_migrations() if app == "accounting"}
        self.assertTrue({"0001_initial", "0002_transaction_agreement_alter_agreement_status_and_more"} <= nodes)
        self.assertTrue({"accounting_entity", "accounting_cashaccount", "accounting_category", "accounting_agreement", "accounting_transaction"}
                        <= set(connection.introspection.table_names()))

    def test_greek_text_afm_decimal_and_aware_timestamp_persist(self):
        client = Entity.objects.create(office=self.office, name="ΔΟΚΙΜΑΣΤΙΚΗ ΕΤΑΙΡΕΙΑ Ωμέγα", entity_type="CUSTOMER", vat_number="000000001")
        account = CashAccount.objects.create(office=self.office, name="ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ", opening_balance=Decimal("1234.56"))
        movement = Transaction.objects.create(office=self.office, transaction_date=timezone.localdate(), transaction_type="INCOME",
            amount=Decimal("12.34"), description="ΔΟΚΙΜΑΣΤΙΚΗ ΕΙΣΠΡΑΞΗ", cash_account=account, entity=client)
        client.refresh_from_db(); account.refresh_from_db(); movement.refresh_from_db()
        self.assertEqual(client.name, "ΔΟΚΙΜΑΣΤΙΚΗ ΕΤΑΙΡΕΙΑ Ωμέγα")
        self.assertEqual(client.vat_number, "000000001")
        self.assertEqual(account.opening_balance, Decimal("1234.56"))
        self.assertEqual(movement.amount, Decimal("12.34"))
        self.assertTrue(timezone.is_aware(movement.created_at))

    @override_settings(SETTINGS_MODULE="core.settings.local")
    def test_explicit_synthetic_seed_is_idempotent(self):
        for _ in range(2):
            call_command("seed_development_data", office=str(self.office.pk), stdout=io.StringIO())
        self.assertEqual(Entity.objects.filter(vat_number="000000000").count(), 1)
        self.assertEqual(CashAccount.objects.filter(name="ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S05").count(), 1)

    def test_seed_refuses_nonlocal_profile(self):
        with self.assertRaises(CommandError):
            call_command("seed_development_data", office=str(self.office.pk), stdout=io.StringIO())
        self.assertEqual(Entity.objects.count(), 0)

    def test_database_backed_login_and_greek_client_list(self):
        password = secrets.token_urlsafe(32)
        user = get_user_model().objects.create_superuser("s05-synthetic-admin", "synthetic@example.invalid", password)
        create_accountant_profile(user_id=user.pk, office_id=self.office.pk,
                                  role="owner")
        Entity.objects.create(office=self.office, name="ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ", entity_type="CUSTOMER", vat_number="000000002")
        self.assertTrue(self.client.login(username=user.username, password=password))
        from .tests_auth_support import staff_client_login
        staff_client_login(self.client, user)
        response = self.client.get("/customers/", HTTP_ACCEPT_LANGUAGE="en-US,en")
        self.assertContains(response, "ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ")
        self.assertEqual(response.headers["Content-Language"], "el")
