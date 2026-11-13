"""S20 tests supplied for operator execution; not run by the implementation agent."""
from datetime import timedelta
from decimal import Decimal
import uuid
from django.db import IntegrityError, transaction
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import CashAccount, Category, Entity, FinanceCommand, FinanceAuditEvent, Transaction
from .tests_finance_posting import Fixtures, DAY
from .tests_auth_support import staff_client_login
from .account_services import save_reference


class CashMovementWorkspaceTests(Fixtures, TestCase):
    def setUp(self):
        self.seed()
        staff_client_login(self.client, self.member)

    def data(self, **changes):
        return {'transaction_date': DAY.isoformat(), 'description': 'ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ S20', 'amount': '25,00',
                'cash_account': self.account.pk, 'category': '', 'entity': '', 'agreement': '',
                'remarks': 'Δοκιμαστικές παρατηρήσεις', 'posting_key': str(uuid.uuid4())} | changes

    def submit(self, direction='income', **changes):
        return self.client.post(reverse('add-' + direction), self.data(**changes))

    def test_optional_category_counterparty_and_remarks_are_saved(self):
        response = self.submit()
        self.assertEqual(response.status_code, 302)
        entry = Transaction.objects.get()
        self.assertEqual(entry.amount, Decimal('25.00'))
        self.assertEqual(entry.remarks, 'Δοκιμαστικές παρατηρήσεις')
        self.assertIsNone(entry.category_id); self.assertIsNone(entry.entity_id)
        self.assertEqual(entry.office_id, self.office.pk)
        self.assertTrue(FinanceAuditEvent.objects.filter(entry=entry, actor=self.member).exists())

    def test_expense_accepts_only_a_supplier_or_no_counterparty(self):
        rejected = self.submit('expense', entity=self.customer.pk)
        self.assertEqual(rejected.status_code, 200)
        self.assertIn('entity', rejected.context['form'].errors)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.submit('expense', entity=self.supplier.pk).status_code, 302)

    def test_nonpositive_invalid_overprecise_and_future_cash_do_not_write(self):
        for amount in ('0,00', '-1,00', 'abc', '1,001', '10000000000,00'):
            with self.subTest(amount=amount):
                response = self.submit(amount=amount)
                self.assertEqual(response.status_code, 200)
                self.assertIn('amount', response.context['form'].errors)
        response = self.submit(transaction_date=(timezone.localdate() + timedelta(days=1)).isoformat())
        self.assertIn('transaction_date', response.context['form'].errors)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(FinanceCommand.objects.count(), 0)

    def test_cash_before_reviewed_opening_is_a_date_error(self):
        response = self.submit(transaction_date=(DAY - timedelta(days=1)).isoformat())
        self.assertIn('transaction_date', response.context['form'].errors)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_repeated_post_is_one_cash_entry_and_changed_payload_is_rejected(self):
        values = self.data()
        self.assertEqual(self.client.post(reverse('add-income'), values).status_code, 302)
        self.assertEqual(self.client.post(reverse('add-income'), values).status_code, 302)
        self.assertEqual(Transaction.objects.count(), 1)
        changed = self.client.post(reverse('add-income'), {**values, 'amount': '26,00'})
        self.assertEqual(changed.status_code, 200); self.assertTrue(changed.context['form'].errors)
        self.assertEqual(Transaction.objects.get().amount, Decimal('25.00'))

    def test_same_financial_values_with_new_form_identity_are_distinct_intent(self):
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(self.submit().status_code, 302)
        self.assertEqual(Transaction.objects.count(), 2)

    def test_completed_agreement_can_replay_its_original_submission(self):
        values = self.data(amount='100,00', entity=self.customer.pk, agreement=self.agreement.pk)
        self.assertEqual(self.client.post(reverse('add-income'), values).status_code, 302)
        self.agreement.refresh_from_db(); self.assertEqual(self.agreement.status, 'COMPLETED')
        self.assertEqual(self.client.post(reverse('add-income'), values).status_code, 302)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_exact_retry_after_account_retirement_does_not_post_again(self):
        values = self.data()
        self.assertEqual(self.client.post(reverse('add-income'), values).status_code, 302)
        self.account.refresh_from_db(); self.account.is_active = False
        save_reference(self.account, self.member)
        self.assertEqual(self.client.post(reverse('add-income'), values).status_code, 302)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(self.submit().status_code, 200)
        self.assertEqual(Transaction.objects.count(), 1)

    def test_foreign_account_category_and_counterparty_are_denied(self):
        category = Category.objects.create(office=self.foreign, name='ΞΕΝΗ ΚΑΤΗΓΟΡΙΑ S20')
        person = Entity.objects.create(office=self.foreign, name='ΞΕΝΟΣ ΠΕΛΑΤΗΣ S20', entity_type='CUSTOMER')
        for name, key in [('cash_account', self.foreign_account.pk), ('category', category.pk), ('entity', person.pk)]:
            with self.subTest(field=name):
                response = self.submit(**{name: key})
                self.assertEqual(response.status_code, 200); self.assertIn(name, response.context['form'].errors)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_malformed_filters_have_field_errors_and_empty_scope_on_both_screens(self):
        for route in ('transaction-list', 'summary-report'):
            for field in ('start_date', 'end_date', 'cash_account', 'category', 'entity', 'transaction_type', 'page', 'page_size'):
                with self.subTest(route=route, field=field):
                    response = self.client.get(reverse(route), {field: 'invalid'}, HTTP_ACCEPT_LANGUAGE='en-US')
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers['Content-Language'], 'el')
                    self.assertIn(field, response.context['filter_form'].errors)
                    self.assertEqual(response.context['total_income'], Decimal('0.00'))

    def test_reverse_interval_and_duplicate_filter_values_are_rejected(self):
        response = self.client.get(reverse('transaction-list'), {'start_date': '2026-01-16', 'end_date': '2026-01-15'})
        self.assertIn('end_date', response.context['filter_form'].errors)
        response = self.client.get(reverse('transaction-list') + '?transaction_type=INCOME&transaction_type=EXPENSE')
        self.assertIn('transaction_type', response.context['filter_form'].errors)

    def test_combined_filters_and_page_totals_share_the_entire_matching_scope(self):
        for index in range(30):
            self.post(agreement=None, description='Κοινή αναζήτηση S20 ' + str(index), amount='2.00')
        self.post(agreement=None, description='Εκτός φίλτρου', amount='99.00')
        self.post(agreement=None, cash_account=self.other, description='Κοινή αναζήτηση S20 άλλο ταμείο', amount='99.00')
        query = {'query': 'Κοινή αναζήτηση S20', 'transaction_type': 'INCOME', 'cash_account': self.account.pk,
                 'category': self.category.pk, 'entity': self.customer.pk, 'start_date': DAY.isoformat(), 'end_date': DAY.isoformat()}
        first = self.client.get(reverse('transaction-list'), query)
        second = self.client.get(reverse('transaction-list'), {**query, 'page': 2})
        self.assertEqual(first.context['result_count'], 30)
        self.assertEqual(len(first.context['transactions']), 25)
        self.assertEqual(len(second.context['transactions']), 5)
        self.assertEqual(first.context['total_income'], Decimal('60.00'))
        self.assertEqual(second.context['total_income'], Decimal('60.00'))
        self.assertEqual(second.context['total_expense'], Decimal('0.00'))
        self.assertContains(first, 'page=2')

    def test_inactive_references_remain_searchable_in_history(self):
        entry = self.post(agreement=None)
        self.category.is_active = False; save_reference(self.category, self.member)
        self.account.refresh_from_db(); self.account.is_active = False; save_reference(self.account, self.member)
        response = self.client.get(reverse('transaction-list'), {'cash_account': self.account.pk, 'category': self.category.pk})
        self.assertFalse(response.context['filter_form'].errors)
        self.assertEqual([row.pk for row in response.context['transactions']], [entry.pk])

    def test_out_of_range_page_is_a_field_error_not_a_server_error(self):
        self.post(agreement=None)
        response = self.client.get(reverse('transaction-list'), {'page': 99})
        self.assertIn('page', response.context['filter_form'].errors)
        self.assertEqual(response.context['total_income'], Decimal('0.00'))

    def test_posted_history_remains_immutable(self):
        entry = self.post(agreement=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transaction.objects.filter(pk=entry.pk).update(amount=Decimal('999.00'))
        self.assertEqual(Transaction.objects.get(pk=entry.pk).amount, Decimal('25.00'))

    def test_revocation_blocks_the_next_post_and_csrf_stays_enabled(self):
        from .models import AccountantProfile
        csrf = Client(enforce_csrf_checks=True); staff_client_login(csrf, self.member)
        self.assertEqual(csrf.post(reverse('add-income'), self.data()).status_code, 403)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        self.assertIn(self.submit().status_code, (302, 403))
        self.assertEqual(Transaction.objects.count(), 0)
