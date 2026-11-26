"""Actual schema40→42 migration preserves original rows and retains new history."""
from decimal import Decimal
from importlib import import_module
import uuid

from django.db import connection,IntegrityError
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from .charge_services import save_terms,post_charge
from .cash_entry_services import post_agreement_cash
from .manual_agreement_creation import create_manual
from .models import Agreement,Charge,Transaction
from .schema_test_support import restore_current_test_schema
from .tests_finance_posting import Fixtures,DAY
from .tests_demand_charges import WHY


class DemandMigrationContracts(Fixtures,TransactionTestCase):
    def setUp(self):
        restore_current_test_schema()
        MigrationExecutor(connection).migrate([('accounting','0040_staff_access_guards')])
        self.seed()
        save_terms(self.member,self.agreement,billing_mode='ONE_OFF',lifecycle='ACTIVE',expected_revision=0,reason=WHY)
        self.charge=post_charge(self.member,agreement_id=self.agreement.pk,terms_revision=1,amount='100.00',
            effective_date=DAY,due_date=DAY,reason=WHY,idempotency_key=str(uuid.uuid4()))
        self.entry,_,_=post_agreement_cash(self.member,idempotency_key=str(uuid.uuid4()),transaction_type='INCOME',
            amount='25.00',transaction_date=DAY,cash_account=self.account,entity=self.customer,agreement=self.agreement,description='',remarks='')

    def tearDown(self):
        restore_current_test_schema();super().tearDown()

    def snapshot(self):
        result={}
        with connection.cursor() as cursor:
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'django_migrations' ORDER BY tablename")
            for name, in cursor.fetchall():
                if name=='accounting_cashchargeselection':continue
                quoted=connection.ops.quote_name(name)
                cursor.execute('SELECT count(*),md5(coalesce(string_agg(md5(to_jsonb(t)::text),\'\' ORDER BY md5(to_jsonb(t)::text)),\'\')) FROM '+quoted+' t')
                result[name]=cursor.fetchone()
        return result

    def test_forward_migration_preserves_all_existing_financial_and_identity_rows(self):
        before=self.snapshot();MigrationExecutor(connection).migrate([('accounting','0042_demand_charge_guards')])
        self.assertEqual(self.snapshot(),before)
        self.charge.refresh_from_db();self.entry.refresh_from_db()
        self.assertEqual((self.charge.amount,self.entry.amount),(Decimal('100.00'),Decimal('25.00')))
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM accounting_cashchargeselection');self.assertEqual(cursor.fetchone()[0],0)
            cursor.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'");self.assertEqual(cursor.fetchone()[0],65)

    def test_migration_does_not_infer_selections_for_historical_fifo_receipts(self):
        MigrationExecutor(connection).migrate([('accounting','0042_demand_charge_guards')])
        from .models import CashChargeSelection
        self.assertFalse(CashChargeSelection.objects.exists())
        self.assertEqual((Charge.objects.count(),Transaction.objects.count()),(1,1))

    def test_new_demand_history_blocks_unsafe_downgrade(self):
        MigrationExecutor(connection).migrate([('accounting','0042_demand_charge_guards')])
        create_manual(self.member,Agreement(entity=self.customer,agreement_type='RECEIVABLE',description=WHY,
            total_amount='500.00',start_date=DAY,status='ACTIVE'),billing_mode='ON_DEMAND',reason=WHY,creation_key=uuid.uuid4())
        with self.assertRaises(IntegrityError):MigrationExecutor(connection).migrate([('accounting','0040_staff_access_guards')])
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM django_migrations WHERE app='accounting'");self.assertEqual(cursor.fetchone()[0],42)
