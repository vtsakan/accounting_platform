"""CR004 retry: older ordinary fixture leaves must not remove the notes schema."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase
from django.urls import reverse

from .models import (Agreement, AgreementTermsVersion, AllocationRelease, CashAllocation,
    Charge, FinanceAuditEvent, FinanceCommand, SettlementCommand, Transaction)
from .schema_test_support import restore_current_test_schema
from .tests_auth_support import staff_client_login
from .tests_counterparty_journal import JournalSupport


class CurrentSchemaFixtureContracts(JournalSupport, TransactionTestCase):
    def tearDown(self):
        restore_current_test_schema()
        super().tearDown()

    def restore_and_read(self, prior_leaf):
        MigrationExecutor(connection).migrate([('accounting', '0026_fee_generation_guards')])
        self.seed_journal()
        models = (Agreement, AgreementTermsVersion, Charge, Transaction, FinanceCommand,
            FinanceAuditEvent, SettlementCommand, CashAllocation, AllocationRelease)
        before = {model._meta.model_name: list(model.objects.order_by('pk').values()) for model in models}
        MigrationExecutor(connection).migrate([('accounting', prior_leaf)])
        self.assertNotIn('accounting_counterpartynote', connection.introspection.table_names())
        restore_current_test_schema()
        self.assertIn(('accounting', '0028_counterparty_note_guards'), MigrationRecorder(connection).applied_migrations())
        self.assertIn('accounting_counterpartynote', connection.introspection.table_names())
        self.assertEqual({model._meta.model_name: list(model.objects.order_by('pk').values()) for model in models}, before)
        staff_client_login(self.client, self.member)
        response = self.client.get(reverse('entity-detail', args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['card_stats']['notes'], 0)
        note, _ = self.note(body='Σημείωση μετά την επαναφορά του σχήματος')
        response = self.client.get(reverse('entity-journal', args=[self.customer.pk]), {'kind': 'note'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, note.body)
        self.assertEqual(response.context['journal_page'].paginator.count, 1)
        self.assertEqual({model._meta.model_name: list(model.objects.order_by('pk').values()) for model in models}, before)

    def test_background_fixture_leaf_restores_notes_and_preserves_financial_rows(self):
        self.restore_and_read('0022_background_job_guards')

    def test_fee_configuration_leaf_restores_notes_and_preserves_financial_rows(self):
        self.restore_and_read('0024_fee_configuration_guards')

    def test_generation_leaf_restores_notes_and_preserves_financial_rows(self):
        self.restore_and_read('0026_fee_generation_guards')
