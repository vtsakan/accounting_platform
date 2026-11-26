"""CR-003 PostgreSQL/HTTP contracts supplied for operator execution only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier
import uuid
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import QueryDict
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .agreement_creation import create_with_charge
from .agreement_selectors import agreement_projection
from .cash_entry_services import post_agreement_cash
from .charge_services import post_charge
from .correction_services import amend_agreement, correct_charge
from .fee_services import next_month
from .finance_services import post_cash
from .forms import IncomeForm, ExpenseForm
from .models import (AccountantProfile, Agreement, CashAllocation, Charge, Entity,
                     FinanceAuditEvent, FinanceCommand, SettlementCommand, Transaction)
from .settlement_selectors import cash_sources, charge_balances, settlement_totals
from .settlement_services import allocate_cash, release_allocation
from .tests_auth_support import staff_client_login
from .tests_finance_posting import DAY, Fixtures

WHY = 'Δοκιμαστική αντιστοίχιση είσπραξης σε συμφωνία CR003'


class ReceiptSupport(Fixtures):
    def target(self, *, entity=None, direction='RECEIVABLE', amount='400.00', mode='ONE_OFF', start=DAY, first=None):
        candidate = Agreement(entity=entity or self.customer, agreement_type=direction,
            description='Δοκιμαστική υπηρεσία CR003', total_amount=amount, start_date=start)
        agreement, charge, _ = create_with_charge(self.member, candidate, billing_mode=mode, reason=WHY,
            creation_key=str(uuid.uuid4()), due_date=start + timedelta(days=5), first_charge_amount=first)
        return agreement, charge

    def seed_receipt(self):
        self.seed()
        self.target_agreement, self.charge = self.target()

    def values(self, **changes):
        return {'idempotency_key': str(uuid.uuid4()), 'transaction_type': 'INCOME', 'transaction_date': DAY,
            'amount': '100.00', 'cash_account': self.account, 'category': None, 'entity': self.customer,
            'agreement': self.target_agreement, 'description': '', 'remarks': 'Δοκιμαστική παρατήρηση'} | changes

    def data(self, **changes):
        values={'posting_key': str(uuid.uuid4()), 'transaction_date': DAY.isoformat(), 'amount': '100,00',
            'cash_account': self.account.pk, 'category': '', 'entity': self.customer.pk,
            'agreement': self.target_agreement.pk, 'description': '', 'remarks': '', 'settle_agreement': 'on'} | changes
        # The current receipt screen requires a concrete choice. Preserve every
        # original assertion; update only this shared HTTP fixture's input.
        choice=Charge.objects.filter(office=self.office,agreement_id=values['agreement']).order_by('effective_date','pk').first() if values['agreement'] else None
        values['charge']=changes.get('charge',str(choice.pk) if choice else '')
        return values

    def counts(self):
        return tuple(model.objects.count() for model in
            (Transaction, FinanceCommand, SettlementCommand, CashAllocation, FinanceAuditEvent))

    def old_allocation(self, *, allocation_day=DAY + timedelta(days=1), amount='60.00'):
        source = post_cash(self.member, **self.values(description='Δοκιμαστική παλαιότερη είσπραξη',
            amount=amount, transaction_date=allocation_day))
        command = allocate_cash(self.member, source_cash=source.pk, lines=[{'charge': self.charge.pk, 'amount': amount}],
            effective_date=allocation_day, reason=WHY, idempotency_key=str(uuid.uuid4()))
        return source, CashAllocation.objects.get(command=command)


class CashAgreementEntryTests(ReceiptSupport, TestCase):
    def setUp(self):
        self.seed_receipt()
        staff_client_login(self.client, self.member)

    def test_400_obligation_and_100_receipt_automatically_leave_300_due(self):
        entry, allocated, replayed = post_agreement_cash(self.member, **self.values())
        projection = agreement_projection(self.target_agreement)
        self.assertEqual((allocated, replayed, entry.amount), (Decimal('100.00'), False, Decimal('100.00')))
        self.assertEqual((projection['charge_total'], projection['allocated_total'], projection['remaining_obligation']),
            (Decimal('400.00'), Decimal('100.00'), Decimal('300.00')))
        self.assertEqual((Transaction.objects.count(), CashAllocation.objects.count()), (1, 1))

    def test_supplier_payment_reduces_payable_and_creates_one_expense(self):
        agreement, charge = self.target(entity=self.supplier, direction='PAYABLE')
        entry, allocated, _ = post_agreement_cash(self.member, **self.values(transaction_type='EXPENSE',
            entity=self.supplier, agreement=agreement))
        self.assertEqual((entry.transaction_type, allocated), ('EXPENSE', Decimal('100.00')))
        self.assertEqual(agreement_projection(agreement)['remaining_obligation'], Decimal('300.00'))
        self.assertEqual(CashAllocation.objects.get().charge_id, charge.pk)

    def test_missing_description_is_copied_from_effective_agreement_terms(self):
        entry, _, _ = post_agreement_cash(self.member, **self.values())
        self.assertEqual(entry.description, 'Είσπραξη για συμφωνία: ' + self.charge.terms.description)
        self.assertEqual(entry.remarks, 'Δοκιμαστική παρατήρηση')

    def test_explicit_description_is_preserved(self):
        entry, _, _ = post_agreement_cash(self.member, **self.values(description='Ειδική δοκιμαστική περιγραφή'))
        self.assertEqual(entry.description, 'Ειδική δοκιμαστική περιγραφή')

    def test_standalone_entry_keeps_existing_manual_description_rule(self):
        entry, allocated, _ = post_agreement_cash(self.member, **self.values(agreement=None, entity=None, description='Ανεξάρτητο έσοδο'))
        self.assertEqual((entry.agreement_id, allocated), (None, Decimal('0.00')))
        with self.assertRaises(ValidationError):
            post_agreement_cash(self.member, **self.values(agreement=None, description=''))
        self.assertEqual(Transaction.objects.count(), 1)

    def test_overpayment_is_allocated_only_up_to_debt_with_excess_as_credit(self):
        entry, allocated, _ = post_agreement_cash(self.member, **self.values(amount='500.00'))
        self.assertEqual(allocated, Decimal('400.00'))
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit, Decimal('100.00'))
        self.assertEqual(agreement_projection(self.target_agreement)['remaining_obligation'], Decimal('0.00'))

    def test_another_agreement_of_same_client_is_not_touched(self):
        other, _ = self.target()
        post_agreement_cash(self.member, **self.values())
        self.assertEqual(agreement_projection(other)['remaining_obligation'], Decimal('400.00'))
        self.assertEqual(set(CashAllocation.objects.values_list('charge__agreement_id', flat=True)), {self.target_agreement.pk})

    def test_unallocated_old_credit_is_not_consumed_by_the_new_receipt(self):
        old = post_cash(self.member, **self.values(agreement=None, description='Παλαιό αδιάθετο ποσό'))
        new, _, _ = post_agreement_cash(self.member, **self.values())
        self.assertEqual(cash_sources(self.member).get(pk=old.pk).available_credit, Decimal('100.00'))
        self.assertEqual(CashAllocation.objects.get().source_cash_id, new.pk)

    def test_monthly_fifo_uses_oldest_due_date_and_partially_covers_next_month(self):
        agreement, january = self.target(amount='100.00', mode='MONTHLY', first='90.00')
        february = post_charge(self.member, agreement_id=agreement.pk, terms_revision=january.terms.revision,
            amount='100.00', effective_date=date(2026, 2, 1), due_date=date(2026, 2, 20), period='2026-02',
            reason=WHY, idempotency_key=str(uuid.uuid4()))
        post_agreement_cash(self.member, **self.values(agreement=agreement, amount='120.00', transaction_date=date(2026, 2, 10)))
        self.assertEqual(CashAllocation.objects.get(charge=january).amount, Decimal('90.00'))
        self.assertEqual(CashAllocation.objects.get(charge=february).amount, Decimal('30.00'))
        self.assertEqual(agreement_projection(agreement)['remaining_obligation'], Decimal('70.00'))

    def test_payment_before_a_later_charge_cannot_settle_that_charge(self):
        agreement, january = self.target(amount='100.00', mode='MONTHLY')
        later = post_charge(self.member, agreement_id=agreement.pk, terms_revision=january.terms.revision,
            amount='100.00', effective_date=date(2026, 2, 1), due_date=date(2026, 2, 20), period='2026-02',
            reason=WHY, idempotency_key=str(uuid.uuid4()))
        entry, allocated, _ = post_agreement_cash(self.member, **self.values(agreement=agreement, amount='150.00'))
        self.assertEqual(allocated, Decimal('100.00'))
        self.assertFalse(CashAllocation.objects.filter(charge=later).exists())
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit, Decimal('50.00'))

    def test_backdated_receipt_respects_later_existing_allocations(self):
        self.old_allocation(amount='350.00')
        entry, allocated, _ = post_agreement_cash(self.member, **self.values(amount='80.00'))
        self.assertEqual(allocated, Decimal('50.00'))
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit, Decimal('30.00'))
        self.assertEqual(charge_balances(self.member, as_of=DAY + timedelta(days=1)).get(pk=self.charge.pk).outstanding, Decimal('0.00'))

    def test_later_release_does_not_create_false_historical_capacity(self):
        _, allocation = self.old_allocation(amount='350.00')
        release_allocation(self.request(), allocation=allocation.pk, effective_date=DAY + timedelta(days=2),
            password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        entry, allocated, _ = post_agreement_cash(self.member, **self.values(amount='80.00'))
        self.assertEqual(allocated, Decimal('50.00'))
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit, Decimal('30.00'))
        self.assertEqual(charge_balances(self.member, as_of=DAY + timedelta(days=1)).get(pk=self.charge.pk).outstanding, Decimal('0.00'))
        self.assertEqual(agreement_projection(self.target_agreement)['remaining_obligation'], Decimal('350.00'))

    def test_reversed_obligation_is_not_reopened_for_a_backdated_receipt(self):
        correct_charge(self.request(), charge_id=self.charge.pk, password=self.password, effective_date=DAY + timedelta(days=1),
            reason=WHY, idempotency_key=str(uuid.uuid4()))
        entry, allocated, _ = post_agreement_cash(self.member, **self.values())
        self.assertEqual((allocated, CashAllocation.objects.count(), Charge.objects.count()), (Decimal('0.00'), 0, 1))
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit, Decimal('100.00'))

    def test_allocation_failure_rolls_back_cash_command_and_audit(self):
        before = self.counts()
        with patch('accounting.cash_entry_services.allocate_cash', side_effect=ValidationError('Δοκιμαστική αποτυχία')):
            with self.assertRaises(ValidationError):
                post_agreement_cash(self.member, **self.values())
        self.assertEqual(self.counts(), before)

    def test_failure_after_first_allocation_batch_rolls_back_the_entire_receipt(self):
        agreement, first = self.target(amount='100.00', mode='MONTHLY', start=date(2015, 1, 1))
        period = date(2015, 1, 1)
        for _ in range(100):
            period = next_month(period)
            post_charge(self.member, agreement_id=agreement.pk, terms_revision=first.terms.revision, amount='100.00',
                effective_date=period, due_date=period, period=period, reason=WHY, idempotency_key=str(uuid.uuid4()))
        before = self.counts()
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(len(kwargs['lines']))
            if len(calls) == 2:
                raise ValidationError('Δοκιμαστική αποτυχία δεύτερης ομάδας')
            return allocate_cash(*args, **kwargs)
        with patch('accounting.cash_entry_services.allocate_cash', side_effect=fail_second):
            with self.assertRaises(ValidationError):
                post_agreement_cash(self.member, **self.values(agreement=agreement, amount='10100.00'))
        self.assertEqual(calls, [100, 1])
        self.assertEqual(self.counts(), before)

    def test_identical_retry_returns_one_receipt_and_one_allocation(self):
        values = self.values()
        entry, _, _ = post_agreement_cash(self.member, **values)
        before = self.counts()
        repeated, _, replayed = post_agreement_cash(self.member, **values)
        self.assertEqual((repeated.pk, replayed), (entry.pk, True))
        self.assertEqual(self.counts(), before)

    def test_changed_amount_or_agreement_under_one_identity_is_denied(self):
        values = self.values()
        post_agreement_cash(self.member, **values)
        other, _ = self.target()
        before = self.counts()
        for change in ({'amount': '101.00'}, {'agreement': other}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                post_agreement_cash(self.member, **(values | change))
        self.assertEqual(self.counts(), before)

    def test_old_cash_only_submission_is_not_allocated_when_replayed(self):
        values = self.values(description='Προϋπάρχουσα συνδεδεμένη είσπραξη')
        original = post_cash(self.member, **values)
        repeated, allocated, replayed = post_agreement_cash(self.member, **values)
        self.assertEqual((original.pk, repeated.pk, allocated, replayed), (original.pk, original.pk, Decimal('0.00'), True))
        self.assertEqual(CashAllocation.objects.count(), 0)

    def test_released_auto_allocation_is_not_silently_reapplied_on_retry(self):
        values = self.values()
        post_agreement_cash(self.member, **values)
        allocation = CashAllocation.objects.get()
        release_allocation(self.request(), allocation=allocation.pk, effective_date=DAY,
            password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        before = self.counts()
        post_agreement_cash(self.member, **values)
        self.assertEqual(self.counts(), before)
        self.assertEqual(agreement_projection(self.target_agreement)['remaining_obligation'], Decimal('400.00'))

    def test_retry_reuses_original_generated_description_after_terms_amendment(self):
        values = self.values()
        original, _, _ = post_agreement_cash(self.member, **values)
        from django.utils import timezone
        amend_agreement(self.request(), agreement_id=self.target_agreement.pk, expected_revision=self.charge.terms.revision,
            description='Μελλοντική νέα περιγραφή', amount='500.00', lifecycle='ACTIVE', effective_date=timezone.localdate() + timedelta(days=1),
            password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        repeated, _, _ = post_agreement_cash(self.member, **values)
        self.assertEqual((repeated.pk, repeated.description), (original.pk, original.description))

    def test_revoked_profile_cannot_post_or_replay(self):
        values = self.values()
        post_agreement_cash(self.member, **values)
        before = self.counts()
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            post_agreement_cash(self.member, **values)
        self.assertEqual(self.counts(), before)

    def test_foreign_or_mismatched_party_and_direction_are_denied(self):
        foreign_party = Entity.objects.create(office=self.foreign, name='Ξένος συναλλασσόμενος CR003', entity_type='CUSTOMER')
        foreign = Agreement.objects.create(office=self.foreign, entity=foreign_party, agreement_type='RECEIVABLE',
            description='Ξένη συμφωνία CR003', total_amount='400.00', start_date=DAY)
        before = self.counts()
        for change in ({'agreement': foreign, 'entity': foreign_party}, {'entity': self.supplier},
                       {'transaction_type': 'EXPENSE'}, {'cash_account': self.foreign_account}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                post_agreement_cash(self.member, **self.values(**change))
        self.assertEqual(self.counts(), before)

    def test_invalid_money_or_identity_never_leaves_a_receipt(self):
        before = self.counts()
        for change in ({'amount': '0.00'}, {'amount': '1.001'}, {'amount': 1.5}, {'idempotency_key': None}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                post_agreement_cash(self.member, **self.values(**change))
        self.assertEqual(self.counts(), before)

    def test_agreement_without_charges_records_an_advance_without_inventing_debt(self):
        entry, allocated, _ = post_agreement_cash(self.member, **self.values(agreement=self.agreement))
        self.assertEqual((allocated, Charge.objects.filter(agreement=self.agreement).count()), (Decimal('0.00'), 0))
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit, Decimal('100.00'))

    def test_bound_form_lists_only_selected_clients_agreements(self):
        other = Entity.objects.create(office=self.office, name='Δεύτερος πελάτης CR003', entity_type='CUSTOMER')
        unrelated, _ = self.target(entity=other)
        form = IncomeForm(self.data(), user=self.member, agreements_queryset=Agreement.objects.all())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.fields['agreement'].queryset.filter(pk=unrelated.pk).exists())
        self.assertTrue(form.fields['agreement'].queryset.filter(pk=self.target_agreement.pk).exists())

    def test_checked_agreement_option_requires_an_agreement_even_with_description(self):
        form = IncomeForm(self.data(agreement='', description='Περιγραφή'), user=self.member, agreements_queryset=Agreement.objects.all())
        self.assertFalse(form.is_valid())
        self.assertIn('agreement', form.errors)

    def test_get_with_client_prefills_scoped_agreement_choices(self):
        response = self.client.get(reverse('add-income'), {'entity_id': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        choices = response.context['form'].fields['agreement'].queryset
        self.assertTrue(choices.filter(pk=self.target_agreement.pk).exists())
        self.assertFalse(choices.exclude(entity=self.customer).exists())

    def test_http_receipt_without_description_settles_and_updates_the_balance(self):
        response = self.client.post(reverse('add-income'), self.data())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(agreement_projection(self.target_agreement)['remaining_obligation'], Decimal('300.00'))
        self.assertTrue(Transaction.objects.get().description.startswith('Είσπραξη για συμφωνία: '))

    def test_http_expense_without_description_settles_the_supplier_agreement(self):
        agreement, _ = self.target(entity=self.supplier, direction='PAYABLE')
        response = self.client.post(reverse('add-expense'), self.data(entity=self.supplier.pk, agreement=agreement.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(agreement_projection(agreement)['remaining_obligation'], Decimal('300.00'))
        self.assertTrue(Transaction.objects.get().description.startswith('Πληρωμή για συμφωνία: '))

    def test_http_switching_client_rejects_a_stale_previous_agreement(self):
        other = Entity.objects.create(office=self.office, name='Άλλος πελάτης CR003', entity_type='CUSTOMER')
        response = self.client.post(reverse('add-income'), self.data(entity=other.pk))
        self.assertEqual(response.status_code, 200)
        self.assertIn('agreement', response.context['form'].errors)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_http_repeated_post_is_one_cash_and_allocation(self):
        data = self.data()
        self.assertEqual(self.client.post(reverse('add-income'), data).status_code, 302)
        before = self.counts()
        self.assertEqual(self.client.post(reverse('add-income'), data).status_code, 302)
        self.assertEqual(self.counts(), before)

    def test_tokenless_legacy_form_retry_keeps_one_receipt(self):
        data = self.data()
        del data['posting_key']
        self.assertEqual(self.client.post(reverse('add-income'), data).status_code, 302)
        self.assertEqual(self.client.post(reverse('add-income'), data).status_code, 302)
        self.assertEqual((Transaction.objects.count(), CashAllocation.objects.count()), (1, 1))

    def test_dependent_options_are_scoped_to_party_direction_and_office(self):
        other = Entity.objects.create(office=self.office, name='Πελάτης εκτός επιλογής', entity_type='CUSTOMER')
        unrelated, _ = self.target(entity=other)
        response = self.client.get(reverse('cash-agreement-options'), {'entity_id': self.customer.pk, 'direction': 'INCOME'})
        self.assertEqual(response.status_code, 200)
        values = {row['value'] for row in response.json()['options']}
        self.assertIn(str(self.target_agreement.pk), values)
        self.assertNotIn(str(unrelated.pk), values)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_foreign_dependent_choice_is_denied_without_names(self):
        foreign = Entity.objects.create(office=self.foreign, name='ΞΕΝΟΣ ΠΕΛΑΤΗΣ CR003', entity_type='CUSTOMER')
        response = self.client.get(reverse('cash-agreement-options'), {'entity_id': foreign.pk, 'direction': 'INCOME'})
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, foreign.name, status_code=404)

    def test_wrong_role_duplicate_direction_and_invalid_direction_are_rejected(self):
        url = reverse('cash-agreement-options')
        self.assertEqual(self.client.get(url, {'entity_id': self.customer.pk, 'direction': 'EXPENSE'}).status_code, 400)
        self.assertEqual(self.client.get(url, {'direction': 'other'}).status_code, 400)
        data = QueryDict('direction=INCOME&direction=EXPENSE')
        self.assertEqual(self.client.get(url, data).status_code, 400)

    def test_dependent_lookup_has_no_financial_side_effects(self):
        before = self.counts()
        response = self.client.get(reverse('cash-agreement-options'), {'entity_id': self.customer.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.counts(), before)


class CashAgreementConcurrency(ReceiptSupport, TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().setUpClass()

    def setUp(self):
        self.seed_receipt()

    def race(self, values):
        barrier = Barrier(2)
        def run(inputs):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                barrier.wait(timeout=6)
                try:
                    entry, _, _ = post_agreement_cash(self.member, **inputs)
                    return 'ok', entry.pk
                except ValidationError:
                    return 'denied', None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, value) for value in values]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_identical_post_commits_one_receipt_and_one_allocation(self):
        values = self.values()
        results = self.race([values, values])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], 'ok')
        self.assertEqual((Transaction.objects.count(), CashAllocation.objects.count()), (1, 1))

    def test_concurrent_distinct_receipts_cannot_overpay_one_obligation(self):
        self.race([self.values(amount='400.00'), self.values(amount='400.00')])
        self.assertEqual((Transaction.objects.count(), CashAllocation.objects.count()), (2, 1))
        totals = settlement_totals(self.member, agreement=self.target_agreement)
        self.assertEqual((totals['receivable_remaining'], totals['customer_credit']), (Decimal('0.00'), Decimal('400.00')))

    def test_concurrent_changed_payload_under_one_identity_has_one_winner(self):
        values = self.values()
        results = self.race([values, values | {'amount': '101.00'}])
        self.assertEqual(sorted(row[0] for row in results), ['denied', 'ok'])
        self.assertEqual((Transaction.objects.count(), CashAllocation.objects.count()), (1, 1))
