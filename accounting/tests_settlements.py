"""S23 operator-run PostgreSQL contracts. Synthetic data; no expected failures."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import threading
import time
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Sum
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from .models import (AccountantProfile, Agreement, AllocationRelease, CashAllocation, Charge, Entity,
                     FinanceCommand, Office, SettlementCommand, Transaction)
from .charge_services import post_charge, save_terms
from .counterparty_services import archive_counterparty
from .finance_services import audit_context, command_for, complete, fingerprint, post_cash, post_transfer, reverse_cash
from .settlement_services import allocate_cash, release_allocation
from .settlement_selectors import allocation_history, cash_sources, charge_balances, settlement_totals
from .agreement_selectors import agreement_projection, agreement_rows
from .tests_auth_support import staff_client_login
from .tests_finance_posting import Fixtures, DAY

WHY = 'ΔΟΚΙΜΑΣΤΙΚΗ ΡΗΤΗ ΑΝΤΙΣΤΟΙΧΙΣΗ S23'


class SettlementSupport(Fixtures):
    def obligation(self, *, agreement=None, mode='ONE_OFF', period=None, effective_date=DAY):
        agreement = agreement or self.agreement
        latest = agreement.terms_versions.first()
        if latest.billing_mode == 'UNREVIEWED':
            save_terms(self.member, agreement, billing_mode=mode, lifecycle='ACTIVE', expected_revision=latest.revision, reason=WHY)
        latest = agreement.terms_versions.first()
        return post_charge(self.member, agreement_id=agreement.pk, terms_revision=latest.revision, amount=agreement.total_amount,
            effective_date=effective_date, due_date=effective_date + timedelta(days=10), period=period, reason=WHY, idempotency_key=str(uuid.uuid4()))

    def second_agreement(self, *, entity=None, direction='RECEIVABLE'):
        return Agreement.objects.create(office=self.office, entity=entity or self.customer, agreement_type=direction,
            description='ΔΟΚΙΜΑΣΤΙΚΗ ΔΕΥΤΕΡΗ ΣΥΜΦΩΝΙΑ S23', total_amount='100.00', start_date=DAY)

    def cash(self, amount='120.00', *, entity=None, direction='INCOME', day=DAY):
        return post_cash(self.member, idempotency_key=str(uuid.uuid4()), amount=amount, transaction_date=day,
            transaction_type=direction, cash_account=self.account, entity=entity or self.customer,
            description='ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ S23')

    def allocation_values(self, source, charge, amount='25.00', **changes):
        return dict(source_cash=source.pk, lines=[{'charge': charge.pk, 'amount': amount}], effective_date=DAY,
                    reason=WHY, idempotency_key=str(uuid.uuid4())) | changes

    def release_values(self, allocation, **changes):
        return dict(allocation=allocation.pk, effective_date=DAY, password=self.password, reason='ΔΟΚΙΜΑΣΤΙΚΗ ΑΠΟΔΕΣΜΕΥΣΗ S23',
                    idempotency_key=str(uuid.uuid4())) | changes

    def current_balances(self, charge, source):
        debt = charge_balances(self.member).get(pk=charge.pk)
        receipt = cash_sources(self.member).get(pk=source.pk)
        return debt.outstanding, receipt.available_credit

    def raw_command(self, source, *, operation='ALLOCATE', actor=None, day=DAY, count=1):
        return SettlementCommand.objects.create(office=self.office, source_cash=source, actor=actor or self.member,
            operation=operation, effective_date=day, reason=WHY, key_digest=fingerprint(str(uuid.uuid4())),
            payload_digest=fingerprint(str(uuid.uuid4())), expected_count=count)

    def raw_allocation(self, source, charge, amount, *, day=DAY, **changes):
        with audit_context(self.member, WHY):
            command = self.raw_command(source, day=day)
            row = CashAllocation(**(dict(office_id=self.office.pk, source_cash_id=source.pk, charge_id=charge.pk, command_id=command.pk,
                                           amount=amount, effective_date=day) | changes))
            values = {field.attname: getattr(row, field.attname) for field in row._meta.concrete_fields}
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO accounting_cashallocation (' + ','.join(connection.ops.quote_name(name) for name in values) +
                               ') VALUES (' + ','.join(['%s'] * len(values)) + ')', list(values.values()))
            complete(command)
        return row

    def form_values(self, charge, **changes):
        return {'effective_date': DAY.isoformat(), 'reason': WHY, 'posting_key': str(uuid.uuid4()),
            'lines-TOTAL_FORMS': '1', 'lines-INITIAL_FORMS': '0', 'lines-MIN_NUM_FORMS': '1', 'lines-MAX_NUM_FORMS': '20',
            'lines-0-charge': str(charge.pk), 'lines-0-amount': '25,00'} | changes


class SettlementTests(SettlementSupport, TestCase):
    def setUp(self):
        self.seed()
        self.charge = self.obligation()
        self.source = self.cash()
        staff_client_login(self.client, self.member)

    def test_receipt_alone_keeps_whole_charge_outstanding_and_credit_separate(self):
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('100.00'), Decimal('120.00')))
        self.assertEqual((CashAllocation.objects.count(), AllocationRelease.objects.count()), (0, 0))
        self.assertEqual(agreement_projection(self.agreement)['settlement_state'], 'OPEN')

    def test_100_charge_with_25_settlement_leaves_75_and_cash_unchanged(self):
        before = self.snapshot()
        command = allocate_cash(self.member, **self.allocation_values(self.source, self.charge))
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('75.00'), Decimal('95.00')))
        self.assertEqual(self.snapshot(), before)
        row = command.allocations.get()
        self.assertEqual((row.charge_id, row.source_cash_id, row.amount, command.actor_id),
                         (self.charge.pk, self.source.pk, Decimal('25.00'), self.member.pk))
        self.assertEqual(command.state, 'completed')
        self.assertEqual(agreement_projection(self.agreement)['settlement_state'], 'PARTIAL')

    def test_120_receipt_allocated_100_leaves_20_customer_credit(self):
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '100.00'))
        totals = settlement_totals(self.member, entity=self.customer)
        self.assertEqual((totals['receivable_remaining'], totals['customer_credit'], totals['supplier_advance']),
                         (Decimal('0.00'), Decimal('20.00'), Decimal('0.00')))
        projection = agreement_projection(self.agreement)
        self.assertEqual((projection['settlement_state'], projection['allocated_total']), ('SETTLED', Decimal('100.00')))
        row = agreement_rows(Agreement.objects.filter(pk=self.agreement.pk)).get()
        self.assertEqual((row.remaining_obligation, row.allocated_total), (Decimal('0.00'), Decimal('100.00')))

    def test_one_receipt_settles_several_charges_across_agreements(self):
        other = self.obligation(agreement=self.second_agreement())
        command = allocate_cash(self.member, **self.allocation_values(self.source, self.charge,
            lines=[{'charge': self.charge, 'amount': '70.00'}, {'charge': other, 'amount': '50.00'}]))
        self.assertEqual(command.allocations.count(), 2)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('30.00'), Decimal('0.00')))
        self.assertEqual(charge_balances(self.member).get(pk=other.pk).outstanding, Decimal('50.00'))

    def test_one_charge_receives_several_partial_receipts_without_cached_state(self):
        second = self.cash('75.00')
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '25.00'))
        allocate_cash(self.member, **self.allocation_values(second, self.charge, '75.00'))
        self.assertEqual(agreement_projection(self.agreement)['remaining_obligation'], Decimal('0.00'))
        self.assertEqual(CashAllocation.objects.count(), 2)

    def test_supplier_advance_and_dual_role_are_never_net_against_customer_debt(self):
        Entity.objects.filter(pk=self.customer.pk).update(is_supplier=True)
        payable = self.obligation(agreement=self.second_agreement(direction='PAYABLE'))
        outgoing = self.cash('60.00', direction='EXPENSE')
        allocate_cash(self.member, **self.allocation_values(outgoing, payable, '40.00'))
        totals = settlement_totals(self.member, entity=self.customer)
        self.assertEqual((totals['receivable_remaining'], totals['payable_remaining'], totals['customer_credit'], totals['supplier_advance']),
                         (Decimal('100.00'), Decimal('60.00'), Decimal('120.00'), Decimal('20.00')))
        for source, charge in ((self.source, payable), (outgoing, self.charge)):
            with self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(source, charge))

    def test_cross_party_and_cross_office_allocations_are_rejected_atomically(self):
        other = Entity.objects.create(office=self.office, name='ΑΛΛΟΣ ΠΕΛΑΤΗΣ S23', entity_type='CUSTOMER')
        charge = self.obligation(agreement=self.second_agreement(entity=other))
        with self.assertRaises(ValidationError):
            allocate_cash(self.member, **self.allocation_values(self.source, charge))
        foreign_source = Transaction.objects.create(office=self.foreign, cash_account=self.foreign_account,
            transaction_type='INCOME', transaction_date=DAY, amount='100.00', description='ΞΕΝΗ ΚΙΝΗΣΗ S23')
        with self.assertRaises(ValidationError):
            allocate_cash(self.member, **self.allocation_values(foreign_source, self.charge))
        self.assertEqual(SettlementCommand.objects.count(), 0)

    def test_available_source_and_charge_caps_reject_overallocation(self):
        for amount in ('100.01', '120.01'):
            with self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(self.source, self.charge, amount))
        small = self.cash('20.00')
        with self.assertRaises(ValidationError):
            allocate_cash(self.member, **self.allocation_values(small, self.charge, '20.01'))
        self.assertEqual(CashAllocation.objects.count(), 0)

    def test_batch_cannot_overspend_source_even_if_each_charge_would_fit(self):
        other = self.obligation(agreement=self.second_agreement())
        with self.assertRaises(ValidationError):
            allocate_cash(self.member, **self.allocation_values(self.source, self.charge,
                lines=[{'charge': self.charge, 'amount': '70.00'}, {'charge': other, 'amount': '70.00'}]))
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count()), (0, 0))

    def test_exact_retry_and_reordered_lines_return_same_retained_group(self):
        other = self.obligation(agreement=self.second_agreement())
        values = self.allocation_values(self.source, self.charge, lines=[{'charge': self.charge, 'amount': '70.00'}, {'charge': other, 'amount': '50.00'}])
        first = allocate_cash(self.member, **values)
        second = allocate_cash(self.member, **(values | {'lines': list(reversed(values['lines']))}))
        self.assertEqual(first.pk, second.pk)
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count()), (1, 2))
        for change in ({'reason': 'ΑΛΛΗ ΔΟΚΙΜΑΣΤΙΚΗ ΑΙΤΙΟΛΟΓΙΑ'}, {'effective_date': DAY + timedelta(days=1)},
                       {'lines': [{'charge': self.charge.pk, 'amount': '60.00'}, {'charge': other.pk, 'amount': '50.00'}]}):
            with self.assertRaises(ValidationError):
                allocate_cash(self.member, **(values | change))

    def test_invalid_exact_amounts_ids_and_duplicate_lines_do_not_create_commands(self):
        for amount in (0, '-1', 'NaN', 'Infinity', '1.001', 1.0, True, '10000000000.00'):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(self.source, self.charge, amount))
        for source in (True, 1.1, '1.1', '١', -1, '999999999999999999999999'):
            with self.subTest(source=source), self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(self.source, self.charge, source_cash=source))
        for lines in ([], [{'charge': self.charge.pk, 'amount': '1'}, {'charge': self.charge.pk, 'amount': '2'}],
                      [{'charge': False, 'amount': '1'}], [{'charge': self.charge.pk, 'amount': '1', 'office': self.foreign.pk}]):
            with self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(self.source, self.charge, lines=lines))
        self.assertEqual(SettlementCommand.objects.count(), 0)

    def test_future_and_predated_events_and_invalid_request_keys_are_denied(self):
        for day in (DAY - timedelta(days=1), timezone.localdate() + timedelta(days=1), '2026-01-15'):
            with self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(self.source, self.charge, effective_date=day))
        for key in ('', 'short', 'has space', 'x' * 161):
            with self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(self.source, self.charge, idempotency_key=key))
        self.assertEqual(CashAllocation.objects.count(), 0)

    def test_legacy_transfer_reversal_and_partyless_cash_are_not_allocation_sources(self):
        legacy = Transaction.objects.create(office=self.office, entity=self.customer, cash_account=self.account,
            amount='50.00', transaction_date=DAY, transaction_type='INCOME', description='ΠΑΛΑΙΑ S23')
        transfer = post_transfer(self.member, from_account=self.account, to_account=self.other, amount='10.00', transfer_date=DAY,
                                 description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S23', idempotency_key=str(uuid.uuid4()))
        partyless = post_cash(self.member, idempotency_key=str(uuid.uuid4()), amount='10.00', transaction_date=DAY,
            transaction_type='INCOME', cash_account=self.account, description='ΧΩΡΙΣ ΣΥΝΑΛΛΑΣΣΟΜΕΝΟ S23')
        reversed_rows = self.reverse(self.source)
        for source in (legacy, *transfer, partyless, self.source, reversed_rows[0]):
            with self.assertRaises(ValidationError):
                allocate_cash(self.member, **self.allocation_values(source, self.charge, '1.00'))
        self.assertEqual(CashAllocation.objects.count(), 0)
        self.assertEqual(cash_sources(self.member).get(pk=self.source.pk).available_credit, Decimal('0.00'))

    def test_completed_retry_survives_archive_but_new_allocation_does_not(self):
        values = self.allocation_values(self.source, self.charge)
        first = allocate_cash(self.member, **values)
        self.customer.refresh_from_db()
        archive_counterparty(self.member, self.customer.pk, version=self.customer.record_version, archive=True)
        self.assertEqual(allocate_cash(self.member, **values).pk, first.pk)
        with self.assertRaises(ValidationError):
            allocate_cash(self.member, **(values | {'idempotency_key': str(uuid.uuid4())}))
        self.assertEqual(charge_balances(self.member).get(pk=self.charge.pk).outstanding, Decimal('75.00'))

    def test_actor_revocation_blocks_completed_replay(self):
        values = self.allocation_values(self.source, self.charge)
        allocate_cash(self.member, **values)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            allocate_cash(self.member, **values)
        self.assertEqual(CashAllocation.objects.count(), 1)

    def test_cancelled_contract_keeps_status_while_retained_debt_can_be_settled(self):
        Agreement.objects.filter(pk=self.agreement.pk).update(status='CANCELLED')
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '100.00'))
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'CANCELLED')
        projection = agreement_projection(self.agreement)
        self.assertTrue(projection['contract_cancelled'])
        self.assertEqual(projection['remaining_obligation'], Decimal('0.00'))

    def test_monthly_settled_label_does_not_claim_future_months_are_paid(self):
        monthly = self.second_agreement()
        charge = self.obligation(agreement=monthly, mode='MONTHLY', period='2026-01')
        allocate_cash(self.member, **self.allocation_values(self.source, charge, '100.00'))
        self.assertEqual(agreement_projection(monthly)['settlement_label'], 'Εξοφλημένη έως τώρα')

    def test_failure_during_second_insert_rolls_back_the_whole_group(self):
        other = self.obligation(agreement=self.second_agreement())
        create = CashAllocation.objects.create
        calls = []
        def fail_second(**values):
            calls.append(values)
            if len(calls) == 2:
                raise RuntimeError('synthetic-s23-second-insert')
            return create(**values)
        before = self.snapshot()
        with patch('accounting.settlement_services.CashAllocation.objects.create', side_effect=fail_second):
            with self.assertRaisesMessage(RuntimeError, 'synthetic-s23-second-insert'):
                allocate_cash(self.member, **self.allocation_values(self.source, self.charge,
                    lines=[{'charge': self.charge.pk, 'amount': '50.00'}, {'charge': other.pk, 'amount': '50.00'}]))
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count()), (0, 0))
        self.assertEqual(self.snapshot(), before)

    def test_dated_projection_preserves_allocation_before_a_later_release(self):
        command = allocate_cash(self.member, **self.allocation_values(self.source, self.charge, effective_date=DAY + timedelta(days=2)))
        row = command.allocations.get()
        release_allocation(self.request(), **self.release_values(row, effective_date=DAY + timedelta(days=5)))
        for offset, debt, available in ((1, '100.00', '120.00'), (3, '75.00', '95.00'), (5, '100.00', '120.00')):
            day = DAY + timedelta(days=offset)
            self.assertEqual(charge_balances(self.member, as_of=day).get(pk=self.charge.pk).outstanding, Decimal(debt))
            self.assertEqual(cash_sources(self.member, as_of=day).get(pk=self.source.pk).available_credit, Decimal(available))
        self.assertFalse(allocation_history(self.member, as_of=DAY + timedelta(days=3)).get().released_by_day)
        self.assertTrue(allocation_history(self.member, as_of=DAY + timedelta(days=5)).get().released_by_day)

    def test_backdated_new_allocation_cannot_reuse_money_before_later_release(self):
        first = allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '100.00'))
        release_allocation(self.request(), **self.release_values(first.allocations.get(), effective_date=DAY + timedelta(days=10)))
        with self.assertRaises(ValidationError):
            allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '100.00', effective_date=DAY + timedelta(days=5)))
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '100.00', effective_date=DAY + timedelta(days=10)))
        self.assertEqual((CashAllocation.objects.count(), AllocationRelease.objects.count()), (2, 1))

    def test_backdated_allocation_checks_later_capacity_changes_too(self):
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '80.00', effective_date=DAY + timedelta(days=10)))
        with self.assertRaises(ValidationError):
            allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '30.00', effective_date=DAY + timedelta(days=5)))
        self.assertEqual(CashAllocation.objects.count(), 1)

    def test_owner_password_recent_mfa_release_restores_credit_without_cash(self):
        row = allocate_cash(self.member, **self.allocation_values(self.source, self.charge)).allocations.get()
        before = self.snapshot()
        request = self.request()
        values = self.release_values(row)
        command = release_allocation(request, **values)
        self.assertEqual(release_allocation(request, **values).pk, command.pk)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('100.00'), Decimal('120.00')))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(AllocationRelease.objects.get().command.actor_id, self.owner.pk)
        with self.assertRaises(ValidationError):
            release_allocation(request, **self.release_values(row))

    def test_accountant_wrong_password_and_expired_mfa_cannot_release(self):
        row = allocate_cash(self.member, **self.allocation_values(self.source, self.charge)).allocations.get()
        with self.assertRaises(PermissionDenied):
            release_allocation(self.request(self.member), **self.release_values(row))
        request = self.request()
        with self.assertRaises(ValidationError):
            release_allocation(request, **self.release_values(row, password='synthetic-wrong-password'))
        request.session['s13_mfa_at'] = 0
        with self.assertRaises(ValidationError):
            release_allocation(request, **self.release_values(row))
        self.assertEqual(AllocationRelease.objects.count(), 0)

    def test_release_of_archived_party_retains_original_and_rejects_earlier_date(self):
        row = allocate_cash(self.member, **self.allocation_values(self.source, self.charge)).allocations.get()
        with self.assertRaises(ValidationError):
            release_allocation(self.request(), **self.release_values(row, effective_date=DAY - timedelta(days=1)))
        self.customer.refresh_from_db()
        archive_counterparty(self.member, self.customer.pk, version=self.customer.record_version, archive=True)
        release_allocation(self.request(), **self.release_values(row))
        self.assertTrue(CashAllocation.objects.filter(pk=row.pk).exists())

    def test_allocated_cash_reversal_requires_explicit_release_and_respects_history_date(self):
        row = allocate_cash(self.member, **self.allocation_values(self.source, self.charge)).allocations.get()
        with self.assertRaises(ValidationError):
            self.reverse(self.source)
        release_allocation(self.request(), **self.release_values(row, effective_date=DAY + timedelta(days=2)))
        with self.assertRaises(ValidationError):
            self.reverse(self.source)
        reversal = reverse_cash(self.request(), entry_id=self.source.pk, password=self.password, reason=WHY,
            effective_date=DAY + timedelta(days=2), idempotency_key=str(uuid.uuid4()))
        self.assertEqual(reversal[0].reversal_of_id, self.source.pk)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('100.00'), Decimal('0.00')))

    def test_posted_settlement_rows_and_command_cannot_be_rewritten_or_deleted(self):
        command = allocate_cash(self.member, **self.allocation_values(self.source, self.charge))
        row = command.allocations.get()
        release = release_allocation(self.request(), **self.release_values(row)).releases.get()
        for query, values in ((CashAllocation.objects.filter(pk=row.pk), {'amount': '50.00'}),
                              (AllocationRelease.objects.filter(pk=release.pk), {'effective_date': DAY + timedelta(days=1)}),
                              (SettlementCommand.objects.filter(pk=command.pk), {'reason': 'ΑΛΛΑΓΜΕΝΗ ΑΙΤΙΟΛΟΓΙΑ'})):
            for action in (lambda: query.update(**values), lambda: query.delete()):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    action()
        self.assertEqual(CashAllocation.objects.get(pk=row.pk).amount, Decimal('25.00'))

    def test_raw_sql_cannot_overallocate_or_forge_party_direction_or_command(self):
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '90.00'))
        other = self.obligation(agreement=self.second_agreement(entity=self.supplier, direction='PAYABLE'))
        for charge, changes in ((self.charge, {}), (other, {}), (self.charge, {'office_id': self.foreign.pk}), (self.charge, {'amount': Decimal('1.001')})):
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.raw_allocation(self.source, charge, '25.00', **changes)
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.member, WHY):
            self.raw_command(self.source, actor=self.owner)
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.member, WHY):
            CashAllocation.objects.create(office=self.office, source_cash=self.source, charge=self.charge,
                command=SettlementCommand.objects.get(operation='ALLOCATE'), amount='1.00', effective_date=DAY)
        self.assertEqual(CashAllocation.objects.count(), 1)

    def test_raw_sql_reversal_cannot_bypass_active_allocation_guard(self):
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge))
        before = self.snapshot()
        with self.assertRaises(IntegrityError), transaction.atomic():
            command, _ = command_for(self.owner, self.office, 'cash.reverse', str(uuid.uuid4()), {'source': self.source.pk}, WHY)
            with audit_context(self.owner, WHY, command):
                Transaction.objects.bulk_create([Transaction(office=self.office, command=command, posting_kind='REVERSAL',
                    reversal_of=self.source, cash_account=self.account, entity=self.customer, amount=self.source.amount,
                    transaction_type='EXPENSE', transaction_date=DAY, description='ΔΟΚΙΜΑΣΤΙΚΟΣ ΑΝΤΙΛΟΓΙΣΜΟΣ S23')])
                complete(command)
        self.assertEqual(self.snapshot(), before)

    def test_greek_workspace_reports_receipts_debt_credit_and_history_together(self):
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge))
        response = self.client.get(reverse('entity-settlements', args=[self.customer.pk]), HTTP_ACCEPT_LANGUAGE='en')
        for text in ('Εξοφλήσεις και αδιάθετα ποσά', 'Ανεξόφλητο', 'Αδιάθετη πίστωση πελάτη', 'Ιστορικό αντιστοιχίσεων'):
            self.assertContains(response, text)
        self.assertEqual(response['Content-Language'], 'el')
        self.assertEqual(response.context['totals']['receivable_remaining'], Decimal('75.00'))
        self.assertEqual(self.client.get(reverse('agreement-detail', args=[self.agreement.pk])).context['remaining_obligation'], Decimal('75.00'))
        report = self.client.get(reverse('summary-report'))
        self.assertEqual(report.context['receivable_remaining'], Decimal('75.00'))
        self.assertEqual(report.context['posted_receivable_total'], Decimal('100.00'))
        self.assertEqual(report.context['total_income'], Decimal('120.00'))

    def test_greek_form_parses_decimal_comma_and_same_post_replays(self):
        values = self.form_values(self.charge)
        url = reverse('cash-allocation-add', args=[self.source.pk])
        self.assertContains(self.client.get(url), 'Επιβεβαίωση αντιστοιχίσεων')
        self.assertEqual(self.client.post(url, values).status_code, 302)
        self.assertEqual(self.client.post(url, values).status_code, 302)
        self.assertEqual(CashAllocation.objects.get().amount, Decimal('25.00'))
        self.assertEqual(SettlementCommand.objects.count(), 1)

    def test_form_rejects_foreign_choices_duplicate_values_and_forged_amounts(self):
        other = self.obligation(agreement=self.second_agreement(entity=self.supplier, direction='PAYABLE'))
        url = reverse('cash-allocation-add', args=[self.source.pk])
        for changes in ({'lines-0-charge': str(other.pk)}, {'lines-0-amount': '25,001'}, {'lines-0-amount': '101,00'},
                        {'posting_key': 'invalid'}, {'lines-TOTAL_FORMS': '999999'}):
            response = self.client.post(url, self.form_values(self.charge, **changes))
            self.assertEqual(response.status_code, 200)
        values = self.form_values(self.charge)
        values['reason'] = [WHY, 'ΔΕΥΤΕΡΗ ΑΙΤΙΟΛΟΓΙΑ']
        self.assertEqual(self.client.post(url, values).status_code, 200)
        self.assertEqual(CashAllocation.objects.count(), 0)

    def test_guessed_foreign_ids_and_csrf_are_denied_without_settlement_writes(self):
        url = reverse('cash-allocation-add', args=[self.source.pk])
        foreign = Entity.objects.create(office=self.foreign, name='ΞΕΝΟΣ ΠΕΛΑΤΗΣ S23', entity_type='CUSTOMER')
        self.assertEqual(self.client.get(reverse('entity-settlements', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('cash-allocation-add', args=[999999999])).status_code, 404)
        client = Client(enforce_csrf_checks=True)
        staff_client_login(client, self.member)
        self.assertEqual(client.post(url, self.form_values(self.charge)).status_code, 403)
        self.assertEqual(CashAllocation.objects.count(), 0)

    def test_release_endpoint_requires_owner_and_rejects_get_and_unknown_id(self):
        row = allocate_cash(self.member, **self.allocation_values(self.source, self.charge)).allocations.get()
        url = reverse('allocation-release', args=[row.pk])
        from .auth_policy import state_for
        state = state_for(self.member); state.enrolled_at = timezone.now(); state.save(update_fields=['enrolled_at'])
        staff_client_login(self.client, self.member)
        values = {key: str(value) if isinstance(value, uuid.UUID) else value.isoformat() if hasattr(value, 'isoformat') else value
                  for key, value in self.release_values(row).items() if key != 'allocation'}
        values['posting_key'] = values.pop('idempotency_key')
        self.assertEqual(self.client.post(url, values).status_code, 403)
        owner = Client(); staff_client_login(owner, self.owner)
        self.assertEqual(owner.get(url).status_code, 405)
        self.assertEqual(owner.post(reverse('allocation-release', args=[uuid.uuid4()]), values).status_code, 404)
        self.assertEqual(owner.post(url, values).status_code, 302)
        self.assertEqual(AllocationRelease.objects.count(), 1)

    def test_date_filter_invalid_future_and_pagination_do_not_change_data(self):
        allocate_cash(self.member, **self.allocation_values(self.source, self.charge, effective_date=DAY + timedelta(days=1)))
        url = reverse('entity-settlements', args=[self.customer.pk])
        response = self.client.get(url, {'as_of': DAY.isoformat()})
        self.assertEqual(response.context['totals']['receivable_remaining'], Decimal('100.00'))
        self.assertEqual(len(response.context['history_page']), 0)
        for value in ('invalid', (timezone.localdate() + timedelta(days=1)).isoformat()):
            response = self.client.get(url, {'as_of': value, 'history_page': 'invalid', 'source_page': '-1'})
            self.assertTrue(response.context['date_form'].errors)
            self.assertIsNone(response.context['totals'])
        self.assertEqual(CashAllocation.objects.count(), 1)

    def test_get_routes_never_create_settlement_events(self):
        before = (SettlementCommand.objects.count(), CashAllocation.objects.count(), AllocationRelease.objects.count(), self.snapshot())
        for route, key in (('entity-settlements', self.customer.pk), ('cash-allocation-add', self.source.pk),
                           ('entity-detail', self.customer.pk), ('agreement-detail', self.agreement.pk)):
            self.assertEqual(self.client.get(reverse(route, args=[key])).status_code, 200)
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count(), AllocationRelease.objects.count(), self.snapshot()), before)


class SettlementConcurrencyTests(SettlementSupport, TransactionTestCase):
    def setUp(self):
        self.seed()
        self.charge = self.obligation()
        self.source = self.cash('100.00')
        if connection.vendor != 'postgresql' or connection.pg_version // 10000 != 17:
            raise AssertionError('S23 requires independent PostgreSQL 17 transactions')

    def race(self, functions):
        barrier, pids, lock = threading.Barrier(len(functions)), [], threading.Lock()
        def worker(function):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    with lock:
                        pids.append(cursor.fetchone()[0])
                barrier.wait(timeout=6)
                try:
                    return 'ok', function()
                except (ValidationError, PermissionDenied, IntegrityError) as error:
                    return 'denied', type(error).__name__
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(worker, function) for function in functions]
            result = [future.result(timeout=18) for future in futures]
        self.assertEqual(len(set(pids)), len(functions))
        return result

    def test_two_independent_requests_cannot_overspend_one_receipt(self):
        other = self.obligation(agreement=self.second_agreement())
        first = self.allocation_values(self.source, self.charge, '75.00')
        second = self.allocation_values(self.source, other, '75.00')
        result = self.race([lambda: allocate_cash(self.member, **first).pk, lambda: allocate_cash(self.member, **second).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(CashAllocation.objects.aggregate(total=Sum('amount'))['total'], Decimal('75.00'))
        self.assertEqual(cash_sources(self.member).get(pk=self.source.pk).available_credit, Decimal('25.00'))

    def test_two_independent_receipts_cannot_overpay_one_charge(self):
        source = self.cash('100.00')
        first = self.allocation_values(self.source, self.charge, '75.00')
        second = self.allocation_values(source, self.charge, '75.00')
        result = self.race([lambda: allocate_cash(self.member, **first).pk, lambda: allocate_cash(self.member, **second).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(charge_balances(self.member).get(pk=self.charge.pk).outstanding, Decimal('25.00'))

    def test_same_confirmation_race_returns_one_command_without_duplicate_rows(self):
        values = self.allocation_values(self.source, self.charge, '100.00')
        result = self.race([lambda: allocate_cash(self.member, **values).pk for _ in range(2)])
        self.assertEqual([row[0] for row in result], ['ok', 'ok'])
        self.assertEqual(result[0][1], result[1][1])
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count()), (1, 1))

    def test_concurrent_owner_releases_can_restore_each_allocation_only_once(self):
        row = allocate_cash(self.member, **self.allocation_values(self.source, self.charge)).allocations.get()
        request = self.request()
        first, second = self.release_values(row), self.release_values(row)
        result = self.race([lambda: release_allocation(request, **first).pk, lambda: release_allocation(request, **second).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(AllocationRelease.objects.count(), 1)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('100.00'), Decimal('100.00')))

    def test_raw_sql_capacity_guard_serializes_bypassing_application_services(self):
        result = self.race([lambda: self.raw_commit('75.00') for _ in range(2)])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(CashAllocation.objects.aggregate(total=Sum('amount'))['total'], Decimal('75.00'))

    def raw_commit(self, amount):
        with transaction.atomic():
            return self.raw_allocation(self.source, self.charge, amount).pk

    def test_incomplete_or_empty_command_cannot_commit(self):
        for count, insert in ((1, False), (2, True)):
            with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.member, WHY):
                command = self.raw_command(self.source, count=count)
                if insert:
                    CashAllocation.objects.create(office=self.office, command=command, source_cash=self.source,
                        charge=self.charge, amount='25.00', effective_date=DAY)
                complete(command)
            self.assertEqual(SettlementCommand.objects.count(), 0)
            self.assertEqual(CashAllocation.objects.count(), 0)
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.member, WHY):
            self.raw_command(self.source)
        self.assertEqual(SettlementCommand.objects.count(), 0)

    def test_revocation_committing_during_office_lock_wait_denies_allocation(self):
        held, release, ready, pids = threading.Event(), threading.Event(), threading.Event(), []
        values = self.allocation_values(self.source, self.charge)
        def revoke():
            connections.close_all()
            try:
                with transaction.atomic():
                    Office.objects.select_for_update().get(pk=self.office.pk)
                    AccountantProfile.objects.filter(user=self.member).update(is_active=False)
                    held.set()
                    if not release.wait(8):
                        raise AssertionError('Release was not signalled')
            finally:
                connections.close_all()
        def write():
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                    cursor.execute('SELECT pg_backend_pid()'); pids.append(cursor.fetchone()[0]); ready.set()
                try:
                    allocate_cash(self.member, **values)
                except PermissionDenied:
                    return 'denied'
                return 'created'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoker = pool.submit(revoke)
            try:
                self.assertTrue(held.wait(6))
                writer = pool.submit(write)
                self.assertTrue(ready.wait(6))
                deadline, blocked = time.monotonic() + 6, False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT cardinality(pg_blocking_pids(%s))', [pids[0]])
                        if cursor.fetchone()[0]:
                            blocked = True
                            break
                    time.sleep(.02)
                self.assertTrue(blocked, 'Observe a real independent PostgreSQL lock wait')
            finally:
                release.set()
            revoker.result(timeout=10)
            self.assertEqual(writer.result(timeout=10), 'denied')
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count()), (0, 0))

    def test_outer_rollback_removes_command_allocations_and_release_together(self):
        with self.assertRaisesMessage(RuntimeError, 'synthetic-s23-rollback'), transaction.atomic():
            command = allocate_cash(self.member, **self.allocation_values(self.source, self.charge))
            release_allocation(self.request(), **self.release_values(command.allocations.get()))
            raise RuntimeError('synthetic-s23-rollback')
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count(), AllocationRelease.objects.count()), (0, 0, 0))


class SettlementMigrationTests(SettlementSupport, TransactionTestCase):
    old = ('accounting', '0016_agreement_charge_guards')
    current = ('accounting', '0018_settlement_guards')

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def setUp(self):
        self.migrate(self.old)
        self.seed()
        self.charge = self.obligation()
        self.source = self.cash()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_upgrade_retains_all_original_cash_charge_people_and_migration_ids_without_auto_links(self):
        from .models import AgreementTermsVersion, CashAccount, FinanceAuditEvent
        models = (Transaction, Charge, Agreement, AgreementTermsVersion, CashAccount, Entity, get_user_model(), FinanceCommand, FinanceAuditEvent)
        before = {model._meta.label: list(model.objects.order_by('pk').values()) for model in models}
        self.migrate(self.current)
        for model in models:
            self.assertEqual(list(model.objects.order_by('pk').values()), before[model._meta.label])
        self.assertEqual((SettlementCommand.objects.count(), CashAllocation.objects.count(), AllocationRelease.objects.count()), (0, 0, 0))
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('100.00'), Decimal('120.00')))
        self.migrate(self.current)
        self.assertEqual(CashAllocation.objects.count(), 0)

    def test_retained_settlement_history_blocks_unsafe_downgrade(self):
        self.migrate(self.current)
        command = allocate_cash(self.member, **self.allocation_values(self.source, self.charge))
        with self.assertRaisesMessage(Exception, 'unsafe downgrade denied'):
            self.migrate(self.old)
        self.assertTrue(CashAllocation.objects.filter(command=command).exists())
