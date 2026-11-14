"""S24A operator-run contracts for the new read-only overview and search path."""
from datetime import timedelta
from decimal import Decimal
import secrets

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .finance_services import post_cash, post_transfer
from .membership import create_accountant_profile
from .models import CashAccount
from .tests_auth_support import staff_client_login
from .tests_finance_posting import DAY, Fixtures
from .workspace_selectors import workspace_snapshot


class WorkspacePresentationTests(Fixtures, TestCase):
    def setUp(self):
        self.seed()

    def test_month_scope_keeps_exact_operating_semantics_and_excludes_transfers(self):
        self.post(amount='12.34', agreement=None)
        self.post(amount='2.34', transaction_type='EXPENSE', entity=self.supplier, agreement=None)
        post_transfer(self.member, from_account=self.account, to_account=self.other, amount='5.00',
                      transfer_date=DAY, description='Δοκιμαστική μεταφορά επισκόπησης', idempotency_key=secrets.token_hex(16))
        result = workspace_snapshot(self.member, as_of=DAY)
        self.assertEqual(result['month_totals'], {'total_income': Decimal('12.34'),
                         'total_expense': Decimal('2.34'), 'net_for_period': Decimal('10.00')})
        self.assertEqual(len(result['recent_transactions']), 4)  # Both cash transfer legs remain visible.

    def test_month_and_as_of_cutoffs_do_not_show_previous_or_later_cash_as_month_income(self):
        previous = DAY.replace(day=1) - timedelta(days=1)
        older = CashAccount.objects.create(office=self.office, name='Παλαιό δοκιμαστικό ταμείο',
                                          opening_balance='0.00', opening_date=previous)
        before = self.post(amount='99.00', transaction_date=previous, cash_account=older, agreement=None)
        included = self.post(amount='10.00', agreement=None)
        after = self.post(amount='88.00', transaction_date=DAY + timedelta(days=1), agreement=None)
        result = workspace_snapshot(self.member, as_of=DAY)
        self.assertEqual(result['month_totals']['total_income'], Decimal('10.00'))
        visible = {row.pk for row in result['recent_transactions']}
        self.assertIn(before.pk, visible); self.assertIn(included.pk, visible); self.assertNotIn(after.pk, visible)

    def test_foreign_office_cash_and_people_never_enter_the_overview(self):
        foreign_user = get_user_model().objects.create_user('s24a-foreign', password=secrets.token_urlsafe(32))
        create_accountant_profile(user_id=foreign_user.pk, office_id=self.foreign.pk, role='owner')
        foreign = post_cash(foreign_user, idempotency_key=secrets.token_hex(16), amount='999.00',
                            transaction_date=DAY, transaction_type='INCOME', cash_account=self.foreign_account,
                            description='Ξένη δοκιμαστική κίνηση επισκόπησης')
        own = self.post(amount='25.00', agreement=None)
        result = workspace_snapshot(self.member, as_of=DAY)
        self.assertEqual(result['month_totals']['total_income'], Decimal('25.00'))
        self.assertEqual([row.pk for row in result['recent_transactions']], [own.pk])
        self.assertNotIn(self.foreign_account.pk, {row.pk for row in result['cash_accounts']})
        self.assertNotIn(foreign.pk, {row.pk for row in result['recent_transactions']})

    def test_unknown_opening_stays_unknown_and_overview_never_posts_financial_work(self):
        pending = CashAccount.objects.create(office=self.office, name='Δοκιμαστικό ταμείο χωρίς έναρξη', opening_balance='125.00')
        for number in range(8):
            self.post(amount='1.00', description='Δοκιμαστική κίνηση ' + str(number), agreement=None)
        before = self.snapshot()
        result = workspace_snapshot(self.member, as_of=DAY)
        self.assertEqual(result['pending_openings'], 1)
        self.assertIsNone(next(row for row in result['cash_accounts'] if row.pk == pending.pk).current_balance)
        self.assertEqual(len(result['recent_transactions']), 6)
        self.assertEqual(result['month_totals']['total_income'], Decimal('8.00'))
        self.assertEqual(self.snapshot(), before)
        pending.refresh_from_db(); self.assertIsNone(pending.opening_date)

    def test_header_search_uses_existing_scoped_query_and_member_navigation_keeps_owner_links_hidden(self):
        staff_client_login(self.client, self.member)
        overview = self.client.get(reverse('dashboard'))
        self.assertContains(overview, 'name="q"')
        self.assertNotContains(overview, 'href="' + reverse('office-members') + '"')
        self.assertContains(overview, 'method="post"')  # Logout retains CSRF-protected POST semantics.
        response = self.client.get(reverse('counterparty-list'), {'q': self.customer.name})
        self.assertContains(response, self.customer.name)
        self.assertNotContains(response, self.supplier.name)
