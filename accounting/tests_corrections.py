"""S24 operator-run PostgreSQL correction, cutoff, access and concurrency contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import threading
import time
import uuid
from unittest.mock import patch
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from .models import (AccountantProfile, Agreement, AgreementChange, AgreementTermsVersion, AllocationRelease,
    CashAccount, CashAllocation, CashRefund, Charge, ChargeReplacement, ChargeReversal, CorrectionRelease,
    Entity, FinanceCommand, FinanceCorrection, FinancePeriodClose, Office, Transaction)
from .finance_services import audit_context, command_for, complete, post_cash, post_transfer, reverse_cash
from .charge_services import post_charge, save_terms
from .settlement_services import allocate_cash
from .settlement_selectors import cash_sources, charge_balances, settlement_totals
from .agreement_selectors import agreement_projection
from .cash_selectors import cash_accounts
from .movement_selectors import operating_totals
from .correction_selectors import terms_on
from .correction_services import (amend_agreement, cash_members, close_period, correct_cash, correct_charge,
    correct_transfer, correction_context, finish, new_action, refund_credit, reverse_entry, reverse_refund)
from .counterparty_services import archive_counterparty
from .tests_auth_support import staff_client_login
from .tests_settlements import SettlementSupport, WHY
from .tests_finance_posting import DAY


class CorrectionSupport(SettlementSupport):
    def prepare(self):
        self.seed()
        self.charge = self.obligation()
        self.source = self.cash()

    def correction_values(self, **changes):
        return dict(entry_id=self.source.pk, password=self.password, effective_date=DAY, reason=WHY, idempotency_key=str(uuid.uuid4())) | changes

    def replacement(self, **changes):
        return dict(amount='25.00', transaction_date=DAY, transaction_type='INCOME', cash_account=self.account,
                    entity=self.customer, agreement=None, category=self.category, description='ΔΟΚΙΜΑΣΤΙΚΗ ΑΝΤΙΚΑΤΑΣΤΑΣΗ S24') | changes

    def refund_values(self, **changes):
        return dict(source_cash=self.source.pk, cash_account=self.account, amount='20.00', password=self.password,
                    effective_date=DAY, reason=WHY, idempotency_key=str(uuid.uuid4())) | changes

    def charge_values(self, **changes):
        return dict(charge_id=self.charge.pk, password=self.password, effective_date=DAY, reason=WHY, idempotency_key=str(uuid.uuid4())) | changes

    def amendment_values(self, agreement=None, **changes):
        agreement = agreement or self.agreement
        return dict(agreement_id=agreement.pk, expected_revision=agreement.terms_versions.first().revision,
                    description='ΔΟΚΙΜΑΣΤΙΚΟΙ ΝΕΟΙ ΟΡΟΙ S24', amount='150.00', lifecycle='ACTIVE', password=self.password,
                    effective_date=timezone.localdate(), reason=WHY, idempotency_key=str(uuid.uuid4())) | changes

    def finance_snapshot(self):
        return tuple(model.objects.count() for model in (Transaction, FinanceCommand, CashAllocation, AllocationRelease,
            FinanceCorrection, CorrectionRelease, CashRefund, ChargeReversal, ChargeReplacement, AgreementChange, FinancePeriodClose))

    def allocated(self, amount='100.00'):
        return allocate_cash(self.member, **self.allocation_values(self.source, self.charge, amount)).allocations.get()

    def cash_balance(self, account=None, day=None):
        return cash_accounts(self.member, as_of=day, include_inactive=True).get(pk=(account or self.account).pk).current_balance

    def owner_client(self):
        client = Client(); staff_client_login(client, self.owner)
        return client

    def form_proof(self, **changes):
        return {'effective_date': DAY.isoformat(), 'password': self.password, 'reason': WHY, 'posting_key': str(uuid.uuid4())} | changes


class CorrectionTests(CorrectionSupport, TestCase):
    def setUp(self):
        self.prepare()

    def test_cash_correction_releases_allocations_and_retains_all_originals(self):
        allocation = self.allocated()
        action = correct_cash(self.request(), **self.correction_values())
        self.assertEqual((action.expected_cash_count, action.expected_release_count), (1, 1))
        self.assertEqual(action.allocation_releases.get().release.allocation_id, allocation.pk)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('100.00'), Decimal('0.00')))
        self.assertEqual(self.cash_balance(), Decimal('100.00'))
        self.assertTrue(Transaction.objects.filter(pk=self.source.pk, amount='120.00').exists())
        self.assertTrue(CashAllocation.objects.filter(pk=allocation.pk, amount='100.00').exists())
        self.assertEqual(agreement_projection(self.agreement)['settlement_state'], 'OPEN')

    def test_replacement_is_new_cash_and_requires_explicit_allocation(self):
        self.allocated()
        action = correct_cash(self.request(), **self.correction_values(replacement=self.replacement()))
        new = action.cash_command.entries.get(posting_kind='ORDINARY')
        self.assertNotEqual(new.pk, self.source.pk)
        self.assertEqual(new.amount, Decimal('25.00'))
        self.assertEqual(self.cash_balance(), Decimal('125.00'))
        self.assertEqual(charge_balances(self.member).get(pk=self.charge.pk).outstanding, Decimal('100.00'))
        self.assertEqual(cash_sources(self.member).get(pk=new.pk).available_credit, Decimal('25.00'))
        allocate_cash(self.member, **self.allocation_values(new, self.charge, '25.00'))
        self.assertEqual(agreement_projection(self.agreement)['remaining_obligation'], Decimal('75.00'))

    def test_dated_cash_reversal_does_not_restate_the_previous_day(self):
        self.allocated()
        correct_cash(self.request(), **self.correction_values(effective_date=DAY + timedelta(days=1)))
        self.assertEqual(self.cash_balance(day=DAY), Decimal('220.00'))
        self.assertEqual(charge_balances(self.member, as_of=DAY).get(pk=self.charge.pk).outstanding, Decimal('0.00'))
        self.assertEqual(self.cash_balance(day=DAY + timedelta(days=1)), Decimal('100.00'))
        self.assertEqual(charge_balances(self.member, as_of=DAY + timedelta(days=1)).get(pk=self.charge.pk).outstanding, Decimal('100.00'))

    def test_exact_correction_retry_returns_same_group_changed_or_second_request_is_denied(self):
        values = self.correction_values(replacement=self.replacement())
        request = self.request()
        first = correct_cash(request, **values)
        before = self.finance_snapshot()
        self.assertEqual(correct_cash(request, **values).pk, first.pk)
        for changes in ({'reason': 'ΑΛΛΗ ΑΙΤΙΟΛΟΓΙΑ S24'}, {'idempotency_key': str(uuid.uuid4())}, {'replacement': self.replacement(amount='26.00')}):
            with self.assertRaises(ValidationError): correct_cash(request, **(values | changes))
        self.assertEqual(self.finance_snapshot(), before)

    def test_wrong_role_password_and_expired_mfa_cannot_correct(self):
        with self.assertRaises(PermissionDenied): correct_cash(self.request(self.member), **self.correction_values())
        request = self.request()
        with self.assertRaises(ValidationError): correct_cash(request, **self.correction_values(password='synthetic-wrong-password'))
        request.session['s13_mfa_at'] = 0
        with self.assertRaises(ValidationError): correct_cash(request, **self.correction_values())
        self.assertEqual(FinanceCorrection.objects.count(), 0)

    def test_cross_office_or_invalid_replacement_leaves_source_unchanged(self):
        before = self.finance_snapshot()
        for replacement in (self.replacement(cash_account=self.foreign_account), self.replacement(amount='1.001'),
                            self.replacement(entity=self.supplier), self.replacement(transaction_date=DAY + timedelta(days=1))):
            with self.assertRaises(ValidationError): correct_cash(self.request(), **self.correction_values(replacement=replacement))
        with self.assertRaises(ValidationError): correct_cash(self.request(), **self.correction_values(entry_id=True))
        self.assertEqual(self.finance_snapshot(), before)
        self.assertFalse(Transaction.objects.filter(reversal_of=self.source).exists())

    def test_correction_cannot_predate_any_allocation_or_release(self):
        self.allocated()
        from .settlement_services import release_allocation
        allocation = CashAllocation.objects.get()
        release_allocation(self.request(), **self.release_values(allocation, effective_date=DAY + timedelta(days=3)))
        with self.assertRaises(ValidationError): correct_cash(self.request(), **self.correction_values())
        self.assertFalse(Transaction.objects.filter(reversal_of=self.source).exists())

    def test_customer_refund_consumes_only_unallocated_credit_and_keeps_settlement(self):
        self.allocated()
        action = refund_credit(self.request(), **self.refund_values())
        refund = action.refund_record
        self.assertEqual((refund.entry.transaction_type, refund.entry.posting_kind), ('EXPENSE', 'REFUND'))
        self.assertEqual(refund.entry.entity_id, self.customer.pk)
        self.assertFalse(self.customer.is_supplier)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('0.00'), Decimal('0.00')))
        self.assertEqual(self.cash_balance(), Decimal('200.00'))
        totals = operating_totals(Transaction.objects.filter(office=self.office))
        self.assertEqual((totals['total_income'], totals['total_expense']), (Decimal('100.00'), Decimal('0.00')))

    def test_supplier_refund_is_advance_return_not_customer_income(self):
        agreement = self.second_agreement(entity=self.supplier, direction='PAYABLE')
        charge = self.obligation(agreement=agreement)
        source = self.cash('120.00', entity=self.supplier, direction='EXPENSE')
        allocate_cash(self.member, **self.allocation_values(source, charge, '100.00'))
        action = refund_credit(self.request(), **self.refund_values(source_cash=source.pk))
        self.assertEqual(action.refund_record.entry.transaction_type, 'INCOME')
        totals = operating_totals(Transaction.objects.filter(office=self.office, entity=self.supplier))
        self.assertEqual((totals['total_income'], totals['total_expense']), (Decimal('0.00'), Decimal('100.00')))
        self.assertEqual(settlement_totals(self.member, entity=self.supplier)['supplier_advance'], Decimal('0.00'))

    def test_dual_role_credit_and_advances_are_not_offset_by_refund(self):
        Entity.objects.filter(pk=self.customer.pk).update(is_supplier=True)
        self.allocated()
        source = self.cash('70.00', direction='EXPENSE')
        refund_credit(self.request(), **self.refund_values(source_cash=source.pk, amount='30.00'))
        totals = settlement_totals(self.member, entity=self.customer)
        self.assertEqual((totals['customer_credit'], totals['supplier_advance']), (Decimal('20.00'), Decimal('40.00')))
        with self.assertRaises(ValidationError): refund_credit(self.request(), **self.refund_values(amount='30.00'))

    def test_refund_retry_replays_but_cannot_exceed_source_precision_or_availability(self):
        self.allocated()
        values = self.refund_values()
        request = self.request()
        first = refund_credit(request, **values)
        self.assertEqual(refund_credit(request, **values).pk, first.pk)
        for changes in ({'amount': '20.01'}, {'amount': '1.001'}, {'amount': True}, {'cash_account': self.foreign_account},
                        {'effective_date': DAY - timedelta(days=1)}):
            with self.assertRaises(ValidationError): refund_credit(request, **self.refund_values(**changes))
        self.assertEqual(CashRefund.objects.count(), 1)

    def test_reverse_refund_restores_exact_source_credit_without_touching_allocations(self):
        self.allocated()
        refund = refund_credit(self.request(), **self.refund_values(effective_date=DAY + timedelta(days=1))).refund_record
        values = self.correction_values(entry_id=refund.entry_id, effective_date=DAY + timedelta(days=2))
        request = self.request()
        action = reverse_refund(request, **values)
        self.assertEqual(reverse_refund(request, **values).pk, action.pk)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('0.00'), Decimal('20.00')))
        self.assertEqual(cash_sources(self.member, as_of=DAY + timedelta(days=1)).get(pk=self.source.pk).available_credit, Decimal('0.00'))
        self.assertEqual((CashAllocation.objects.count(), AllocationRelease.objects.count()), (1, 0))
        with self.assertRaises(ValidationError): reverse_refund(request, **self.correction_values(entry_id=refund.entry_id))
        refund_credit(request, **self.refund_values(effective_date=DAY + timedelta(days=3)))
        self.assertEqual(CashRefund.objects.count(), 2)

    def test_dependent_refunds_need_explicit_exact_confirmation(self):
        self.allocated()
        refund = refund_credit(self.request(), **self.refund_values(amount='10.00')).refund_record
        second = refund_credit(self.request(), **self.refund_values(amount='10.00')).refund_record
        before = self.finance_snapshot()
        with self.assertRaises(ValidationError): correct_cash(self.request(), **self.correction_values())
        with self.assertRaises(ValidationError): correct_cash(self.request(), **self.correction_values(dependent_refunds=[refund.pk]))
        with self.assertRaises(ValidationError): reverse_cash(self.request(), **self.correction_values())
        self.assertEqual(self.finance_snapshot(), before)
        from .correction_forms import CashCorrectionForm
        form = CashCorrectionForm(self.form_proof(dependent_refunds=[str(refund.pk), str(second.pk)]), user=self.owner, source=self.source)
        self.assertTrue(form.is_valid(), form.errors)
        action = correct_cash(self.request(), **self.correction_values(dependent_refunds=[refund.pk, second.pk]))
        self.assertEqual(action.cash_command.entries.count(), 3)
        self.assertEqual((action.expected_release_count, action.refund_reversal_count), (1, 2))
        self.assertEqual(self.cash_balance(), Decimal('100.00'))
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('100.00'), Decimal('0.00')))

    def test_failure_after_release_and_refund_reversal_rolls_every_new_effect_back(self):
        self.allocated()
        refund = refund_credit(self.request(), **self.refund_values()).refund_record
        before = self.finance_snapshot()
        original, calls = reverse_entry, []
        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2: raise RuntimeError('synthetic-s24-second-cash')
            return original(*args, **kwargs)
        with patch('accounting.correction_services.reverse_entry', side_effect=fail_second):
            with self.assertRaisesMessage(RuntimeError, 'synthetic-s24-second-cash'):
                correct_cash(self.request(), **self.correction_values(dependent_refunds=[refund.pk]))
        self.assertEqual(self.finance_snapshot(), before)
        self.assertFalse(Transaction.objects.filter(reversal_of__in=[self.source, refund.entry]).exists())
        self.assertEqual(AllocationRelease.objects.count(), 0)

    def test_refund_or_correction_cannot_reuse_reversed_sources_or_predate_history(self):
        refund = refund_credit(self.request(), **self.refund_values(effective_date=DAY + timedelta(days=2))).refund_record
        with self.assertRaises(ValidationError):
            correct_cash(self.request(), **self.correction_values(dependent_refunds=[refund.pk]))
        correct_cash(self.request(), **self.correction_values(effective_date=DAY + timedelta(days=3), dependent_refunds=[refund.pk]))
        with self.assertRaises(ValidationError): refund_credit(self.request(), **self.refund_values(effective_date=DAY + timedelta(days=4)))
        with self.assertRaises(ValidationError): correct_cash(self.request(), **self.correction_values(entry_id=Transaction.objects.get(reversal_of=self.source).pk))

    def test_charge_reversal_releases_cash_and_does_not_refund_it(self):
        self.allocated()
        balance = self.cash_balance()
        action = correct_charge(self.request(), **self.charge_values())
        self.assertEqual((action.expected_cash_count, action.expected_release_count), (0, 1))
        self.assertEqual(self.cash_balance(), balance)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('0.00'), Decimal('120.00')))
        self.assertEqual(agreement_projection(self.agreement)['settlement_state'], 'NO_OBLIGATIONS')
        self.assertEqual((Charge.objects.count(), ChargeReversal.objects.count()), (1, 1))
        with self.assertRaises(ValidationError): self.obligation()

    def test_charge_replacement_has_distinct_identity_and_retains_generation_source(self):
        self.allocated()
        values = self.charge_values(replacement_amount='80.00', replacement_due_date=DAY + timedelta(days=10))
        request = self.request()
        action = correct_charge(request, **values)
        replacement = action.charge_replacement.replacement
        self.assertEqual(correct_charge(request, **values).pk, action.pk)
        self.assertEqual((replacement.amount, replacement.source_key), (Decimal('80.00'), 'correction:' + str(action.pk)))
        self.assertEqual(self.charge.source_key, 'agreement:' + str(self.agreement.pk) + ':one-off')
        self.assertEqual(agreement_projection(self.agreement)['remaining_obligation'], Decimal('80.00'))
        allocate_cash(self.member, **self.allocation_values(self.source, replacement, '80.00'))
        self.assertEqual(settlement_totals(self.member, entity=self.customer)['customer_credit'], Decimal('40.00'))
        with self.assertRaises(ValidationError): allocate_cash(self.member, **self.allocation_values(self.source, self.charge, '1.00'))

    def test_dated_charge_reversal_keeps_previous_debt_and_settlement(self):
        self.allocated('25.00')
        correct_charge(self.request(), **self.charge_values(effective_date=DAY + timedelta(days=2)))
        self.assertEqual(charge_balances(self.member, as_of=DAY).get(pk=self.charge.pk).outstanding, Decimal('75.00'))
        self.assertEqual(charge_balances(self.member, as_of=DAY + timedelta(days=2)).get(pk=self.charge.pk).outstanding, Decimal('0.00'))
        self.assertEqual(cash_sources(self.member, as_of=DAY).get(pk=self.source.pk).available_credit, Decimal('95.00'))

    def test_archived_history_can_reverse_or_refund_but_not_create_replacement_work(self):
        self.customer.refresh_from_db()
        archive_counterparty(self.member, self.customer.pk, version=self.customer.record_version, archive=True)
        refund_credit(self.request(), **self.refund_values())
        with self.assertRaises(ValidationError): correct_charge(self.request(), **self.charge_values(replacement_amount='80.00', replacement_due_date=DAY))
        correct_charge(self.request(), **self.charge_values())
        self.assertTrue(ChargeReversal.objects.filter(charge=self.charge).exists())

    def test_transfer_reversal_is_one_atomic_pair_and_stays_nonoperating(self):
        pair = post_transfer(self.member, from_account=self.account, to_account=self.other, amount='40.00', transfer_date=DAY,
            description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S24', idempotency_key=str(uuid.uuid4()))
        before = operating_totals(Transaction.objects.filter(office=self.office))
        action = correct_transfer(self.request(), **self.correction_values(entry_id=pair[1].pk, effective_date=DAY + timedelta(days=1)))
        self.assertEqual(action.cash_command.entries.count(), 2)
        self.assertEqual(set(action.cash_command.entries.values_list('reversal_of_id', flat=True)), {row.pk for row in pair})
        self.assertEqual((self.cash_balance(), self.cash_balance(self.other)), (Decimal('220.00'), Decimal('0.00')))
        self.assertEqual(self.cash_balance(day=DAY), Decimal('180.00'))
        self.assertEqual(operating_totals(Transaction.objects.filter(office=self.office)), before)

    def test_transfer_replacement_and_retry_from_opposite_leg_share_one_group(self):
        pair = post_transfer(self.member, from_account=self.account, to_account=self.other, amount='40.00', transfer_date=DAY,
            description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S24', idempotency_key=str(uuid.uuid4()))
        values = self.correction_values(entry_id=pair[0].pk, replacement={'from_account': self.other, 'to_account': self.account,
            'amount': '10.00', 'description': 'ΔΟΚΙΜΑΣΤΙΚΗ ΑΝΤΙΚΑΤΑΣΤΑΣΗ ΜΕΤΑΦΟΡΑΣ'})
        request = self.request()
        action = correct_transfer(request, **values)
        self.assertEqual(correct_transfer(request, **(values | {'entry_id': pair[1].pk})).pk, action.pk)
        self.assertEqual(action.cash_command.entries.count(), 4)
        self.assertEqual((self.cash_balance(), self.cash_balance(self.other)), (Decimal('230.00'), Decimal('-10.00')))
        with self.assertRaises(ValidationError): correct_transfer(request, **(values | {'idempotency_key': str(uuid.uuid4())}))

    def test_invalid_or_failed_transfer_replacement_never_leaves_a_single_reversal(self):
        pair = post_transfer(self.member, from_account=self.account, to_account=self.other, amount='40.00', transfer_date=DAY,
            description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S24', idempotency_key=str(uuid.uuid4()))
        before = self.finance_snapshot()
        with self.assertRaises(ValidationError):
            correct_transfer(self.request(), **self.correction_values(entry_id=pair[0].pk, replacement={'from_account': self.account,
                'to_account': self.foreign_account, 'amount': '10.00', 'description': 'ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ'}))
        original, calls = reverse_entry, []
        def fail_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2: raise RuntimeError('synthetic-s24-transfer')
            return original(*args, **kwargs)
        with patch('accounting.correction_services.reverse_entry', side_effect=fail_second):
            with self.assertRaises(RuntimeError): correct_transfer(self.request(), **self.correction_values(entry_id=pair[0].pk))
        self.assertEqual(self.finance_snapshot(), before)
        self.assertEqual(Transaction.objects.filter(reversal_of__in=pair).count(), 0)

    def test_future_terms_are_retained_without_repricing_posted_charge_or_cash(self):
        original = tuple(Charge.objects.values_list('id', 'amount', 'terms_id'))
        day = timezone.localdate() + timedelta(days=30)
        values = self.amendment_values(effective_date=day)
        action = amend_agreement(self.request(), **values)
        self.assertEqual(action.terms_change.version.agreed_amount, Decimal('150.00'))
        self.assertEqual(terms_on(self.agreement).agreed_amount, Decimal('100.00'))
        self.assertEqual(terms_on(self.agreement, day).agreed_amount, Decimal('150.00'))
        self.assertEqual(tuple(Charge.objects.values_list('id', 'amount', 'terms_id')), original)
        self.assertEqual((self.cash_balance(), Transaction.objects.count()), (Decimal('220.00'), 1))

    def test_new_unposted_month_uses_its_effective_version_and_source_identity(self):
        agreement = self.second_agreement()
        self.obligation(agreement=agreement, mode='MONTHLY', period='2026-01')
        day = timezone.localdate()
        action = amend_agreement(self.request(), **self.amendment_values(agreement))
        terms = action.terms_change.version
        charge = post_charge(self.member, agreement_id=agreement.pk, terms_revision=terms.revision, amount='150.00',
            effective_date=day, due_date=day, period=day.strftime('%Y-%m'), reason=WHY, idempotency_key=str(uuid.uuid4()))
        self.assertEqual((charge.amount, charge.description, charge.terms_id), (Decimal('150.00'), 'ΔΟΚΙΜΑΣΤΙΚΟΙ ΝΕΟΙ ΟΡΟΙ S24', terms.pk))
        self.assertEqual(charge.source_key, f'agreement:{agreement.pk}:month:{day:%Y-%m}')

    def test_future_cancellation_does_not_block_charges_before_its_cutoff(self):
        agreement = self.second_agreement()
        self.obligation(agreement=agreement, mode='MONTHLY', period='2026-01')
        day = timezone.localdate()
        original = terms_on(agreement)
        amend_agreement(self.request(), **self.amendment_values(agreement, effective_date=day + timedelta(days=10), lifecycle='CANCELLED'))
        self.assertEqual(terms_on(agreement).lifecycle, 'ACTIVE')
        charge = post_charge(self.member, agreement_id=agreement.pk, terms_revision=original.revision, amount='100.00',
            effective_date=day, due_date=day, period=day.strftime('%Y-%m'), reason=WHY, idempotency_key=str(uuid.uuid4()))
        self.assertEqual(charge.terms_id, original.pk)
        self.assertEqual(terms_on(agreement, day + timedelta(days=10)).lifecycle, 'CANCELLED')

    def test_cancellation_retains_posted_debt_and_never_reactivates_after_cash_correction(self):
        self.allocated()
        action = amend_agreement(self.request(), **self.amendment_values(lifecycle='CANCELLED'))
        before = (self.cash_balance(), self.current_balances(self.charge, self.source))
        self.assertEqual(action.terms_change.version.lifecycle, 'CANCELLED')
        self.assertEqual((self.cash_balance(), self.current_balances(self.charge, self.source)), before)
        correct_cash(self.request(), **self.correction_values(effective_date=timezone.localdate()))
        self.assertTrue(agreement_projection(self.agreement)['contract_cancelled'])
        self.assertEqual(agreement_projection(self.agreement)['remaining_obligation'], Decimal('100.00'))
        with self.assertRaises(ValidationError): amend_agreement(self.request(), **self.amendment_values())

    def test_cancellation_explicitly_supersedes_a_previously_scheduled_active_version(self):
        day = timezone.localdate()
        amend_agreement(self.request(), **self.amendment_values(effective_date=day + timedelta(days=30)))
        action = amend_agreement(self.request(), **self.amendment_values(lifecycle='CANCELLED'))
        self.assertEqual(terms_on(self.agreement, day + timedelta(days=60)).pk, action.terms_change.version_id)
        self.assertEqual(self.agreement.terms_versions.filter(lifecycle='ACTIVE', agreed_amount='150.00').count(), 1)

    def test_terms_retry_stale_version_past_date_and_unreviewed_contract_are_safe(self):
        request = self.request(); values = self.amendment_values()
        action = amend_agreement(request, **values)
        self.assertEqual(amend_agreement(request, **values).pk, action.pk)
        with self.assertRaises(ValidationError): amend_agreement(request, **(values | {'idempotency_key': str(uuid.uuid4())}))
        with self.assertRaises(ValidationError): amend_agreement(request, **self.amendment_values(effective_date=DAY))
        other = self.second_agreement()
        with self.assertRaises(ValidationError): amend_agreement(request, **self.amendment_values(other))
        self.assertEqual(AgreementChange.objects.count(), 1)

    def test_closed_period_blocks_new_cash_allocations_refunds_and_corrections(self):
        request = self.request()
        cutoff = DAY + timedelta(days=3)
        close_period(request, closed_through=cutoff, password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        before = self.finance_snapshot()
        for operation in (lambda: self.cash('1.00'),
                          lambda: allocate_cash(self.member, **self.allocation_values(self.source, self.charge)),
                          lambda: refund_credit(request, **self.refund_values()),
                          lambda: correct_cash(request, **self.correction_values()),
                          lambda: correct_charge(request, **self.charge_values())):
            with self.assertRaises(ValidationError): operation()
        self.assertEqual(self.finance_snapshot(), before)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transaction.objects.create(office=self.office,cash_account=self.account,transaction_type='INCOME',transaction_date=DAY,amount='1.00',description='ΔΟΚΙΜΑΣΤΙΚΗ SQL ΣΕ ΚΛΕΙΣΜΕΝΗ ΠΕΡΙΟΔΟ')
        correct_cash(request, **self.correction_values(effective_date=cutoff + timedelta(days=1)))
        self.assertEqual(self.cash_balance(day=cutoff), Decimal('220.00'))
        self.assertEqual(self.cash_balance(), Decimal('100.00'))

    def test_period_close_is_forward_only_and_completed_retry_survives_closure(self):
        request = self.request(); values = dict(closed_through=DAY, password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        action = close_period(request, **values)
        self.assertEqual(close_period(request, **values).pk, action.pk)
        for day in (DAY, DAY - timedelta(days=1), timezone.localdate() + timedelta(days=1)):
            with self.assertRaises(ValidationError): close_period(request, **(values | {'closed_through': day, 'idempotency_key': str(uuid.uuid4())}))
        self.assertEqual(FinancePeriodClose.objects.count(), 1)

    def test_existing_new_request_replay_survives_later_period_close(self):
        request = self.request(); values = self.correction_values()
        action = correct_cash(request, **values)
        close_period(request, closed_through=DAY, password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        self.assertEqual(correct_cash(request, **values).pk, action.pk)

    def test_corrected_events_and_terms_are_append_only_through_sql_and_orm(self):
        action = correct_charge(self.request(), **self.charge_values(replacement_amount='80.00', replacement_due_date=DAY))
        amendment = amend_agreement(self.request(), **self.amendment_values())
        for model, key, values in ((FinanceCorrection, action.pk, {'reason': 'ΑΛΛΑΓΗ ΑΙΤΙΟΛΟΓΙΑΣ'}),
                                  (ChargeReversal, action.charge_reversal.pk, {'effective_date': DAY + timedelta(days=1)}),
                                  (ChargeReplacement, action.charge_replacement.pk, {'original_id': uuid.uuid4()}),
                                  (AgreementChange, amendment.terms_change.pk, {'amount': '200.00'})):
            for operation in (lambda: model.objects.filter(pk=key).update(**values), lambda: model.objects.filter(pk=key).delete()):
                with self.assertRaises(IntegrityError), transaction.atomic(): operation()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Agreement.objects.filter(pk=self.agreement.pk).update(total_amount='200.00')
        self.assertEqual(self.charge.amount, Decimal('100.00'))

    def test_extended_cash_operations_cannot_be_posted_without_a_correction_context(self):
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.owner, WHY):
            command_for(self.owner, self.office, 'cash.refund', str(uuid.uuid4()), {'source': self.source.pk}, WHY)
        self.assertEqual(CashRefund.objects.count(), 0)
        self.assertEqual(FinanceCorrection.objects.count(), 0)

    def test_operating_report_filters_corrections_by_original_business_direction(self):
        self.allocated()
        refund_credit(self.request(), **self.refund_values())
        client = self.owner_client()
        for params in ({}, {'transaction_type': 'INCOME'}):
            report = client.get(reverse('summary-report'), params)
            self.assertEqual((report.context['total_income'], report.context['total_expense']), (Decimal('100.00'), Decimal('0.00')))
        values = cash_accounts(self.owner).get(pk=self.account.pk)
        self.assertEqual((values.operating_income, values.operating_expense, values.current_balance), (Decimal('100.00'), Decimal('0.00'), Decimal('200.00')))

    def test_greek_cash_form_corrects_with_password_and_read_pages_never_write(self):
        client = self.owner_client()
        url = reverse('cash-correction', args=[self.source.pk])
        before = self.finance_snapshot()
        page = client.get(url, HTTP_ACCEPT_LANGUAGE='en')
        self.assertContains(page, 'Επιβεβαίωση διόρθωσης')
        self.assertEqual(page['Content-Language'], 'el')
        self.assertEqual(client.get(reverse('finance-correction-history')).status_code, 200)
        self.assertEqual(self.finance_snapshot(), before)
        values = self.form_proof()
        self.assertEqual(client.post(url, values).status_code, 302)
        self.assertEqual(client.post(url, values).status_code, 302)
        self.assertEqual(FinanceCorrection.objects.count(), 1)

    def test_refund_and_charge_correction_forms_use_greek_decimal_input(self):
        client = self.owner_client()
        refund = self.form_proof(cash_account=str(self.account.pk), amount='20,00')
        self.assertEqual(client.post(reverse('cash-refund', args=[self.source.pk]), refund).status_code, 302)
        charge = self.form_proof(replace='on', replacement_amount='80,00', replacement_due_date=DAY.isoformat())
        self.assertEqual(client.post(reverse('charge-correction', args=[self.charge.pk]), charge).status_code, 302)
        self.assertEqual(ChargeReplacement.objects.get().replacement.amount, Decimal('80.00'))

    def test_csrf_foreign_records_and_missing_or_accountant_authority_are_denied(self):
        url = reverse('cash-correction', args=[self.source.pk])
        csrf = Client(enforce_csrf_checks=True); staff_client_login(csrf, self.owner)
        self.assertEqual(csrf.post(url, self.form_proof()).status_code, 403)
        client = self.owner_client()
        foreign = Transaction.objects.create(office=self.foreign, cash_account=self.foreign_account, amount='10.00', transaction_type='INCOME',
            transaction_date=DAY, description='ΞΕΝΗ ΚΙΝΗΣΗ S24')
        self.assertEqual(client.get(reverse('cash-correction', args=[foreign.pk])).status_code, 404)
        self.assertEqual(client.post(reverse('charge-correction', args=[uuid.uuid4()]), self.form_proof()).status_code, 404)
        self.assertEqual(Client().get(url).status_code, 302)
        self.assertEqual(FinanceCorrection.objects.count(), 0)

    def test_invalid_replacement_or_unconfirmed_period_form_cannot_create_events(self):
        client = self.owner_client()
        values = self.form_proof(replace='on', **{'new-transaction_type': 'INCOME', 'new-cash_account': str(self.foreign_account.pk),
            'new-amount': '25,00', 'new-description': 'ΔΟΚΙΜΑΣΤΙΚΗ ΑΝΤΙΚΑΤΑΣΤΑΣΗ'})
        self.assertEqual(client.post(reverse('cash-correction', args=[self.source.pk]), values).status_code, 200)
        self.assertEqual(client.post(reverse('finance-period-close'), self.form_proof()).status_code, 200)
        self.assertEqual(FinanceCorrection.objects.count(), 0)

    def test_admin_retains_posted_originals_and_links_to_confirmed_workflows(self):
        from .admin import AgreementAdmin, TransactionAdmin
        agreement_admin = AgreementAdmin(Agreement, admin.site)
        transaction_admin = TransactionAdmin(Transaction, admin.site)
        request = self.request()
        self.assertIn('amendment_link', agreement_admin.get_readonly_fields(request, self.agreement))
        self.assertIn('correction_link', transaction_admin.get_readonly_fields(request, self.source))
        self.assertIn(reverse('cash-correction', args=[self.source.pk]), str(transaction_admin.correction_link(self.source)))
        self.assertNotIn(FinanceCorrection, admin.site._registry)


class CorrectionConcurrencyTests(CorrectionSupport, TransactionTestCase):
    def setUp(self):
        self.prepare()
        if connection.vendor != 'postgresql' or connection.pg_version // 10000 != 17:
            raise AssertionError('S24 requires independent PostgreSQL 17 transactions')

    def race(self, functions):
        barrier, pids, guard = threading.Barrier(len(functions)), [], threading.Lock()
        def worker(function):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='10s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    with guard: pids.append(cursor.fetchone()[0])
                barrier.wait(timeout=8)
                try: return 'ok', function()
                except (ValidationError, PermissionDenied, IntegrityError) as error: return 'denied', type(error).__name__
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(worker, function) for function in functions]
            results = [future.result(timeout=24) for future in futures]
        self.assertEqual(len(set(pids)), len(functions))
        return results

    def test_refund_and_allocation_cannot_spend_the_same_remaining_twenty(self):
        self.allocated()
        other = self.obligation(agreement=self.second_agreement())
        request = self.request()
        refund, allocation = self.refund_values(), self.allocation_values(self.source, other, '20.00')
        result = self.race([lambda: refund_credit(request, **refund).pk, lambda: allocate_cash(self.member, **allocation).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(cash_sources(self.member).get(pk=self.source.pk).available_credit, Decimal('0.00'))
        self.assertEqual(CashAllocation.objects.count() + CashRefund.objects.count(), 2)

    def test_same_cash_correction_race_returns_one_completed_group(self):
        self.allocated()
        request = self.request(); values = self.correction_values()
        result = self.race([lambda: correct_cash(request, **values).pk for _ in range(2)])
        self.assertTrue(all(row[0] == 'ok' for row in result))
        self.assertEqual(result[0][1], result[1][1])
        self.assertEqual((FinanceCorrection.objects.count(), AllocationRelease.objects.count()), (1, 1))

    def test_transfer_reversal_race_has_one_winner_and_never_one_leg(self):
        pair = post_transfer(self.member, from_account=self.account, to_account=self.other, amount='40.00', transfer_date=DAY,
            description='ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΓΧΡΟΝΗ ΜΕΤΑΦΟΡΑ S24', idempotency_key=str(uuid.uuid4()))
        request = self.request(); first = self.correction_values(entry_id=pair[0].pk); second = self.correction_values(entry_id=pair[1].pk)
        result = self.race([lambda: correct_transfer(request, **first).pk, lambda: correct_transfer(request, **second).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(Transaction.objects.filter(reversal_of__in=pair).count(), 2)

    def test_cash_and_charge_correction_race_release_each_original_allocation_once(self):
        self.allocated()
        request = self.request(); cash = self.correction_values(); charge = self.charge_values()
        result = self.race([lambda: correct_cash(request, **cash).pk, lambda: correct_charge(request, **charge).pk])
        self.assertTrue(all(row[0] == 'ok' for row in result))
        self.assertEqual((AllocationRelease.objects.count(), CorrectionRelease.objects.count()), (1, 1))
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('0.00'), Decimal('0.00')))

    def test_same_expected_terms_revision_cannot_create_two_competing_changes(self):
        request = self.request(); first = self.amendment_values(); second = self.amendment_values(amount='160.00')
        result = self.race([lambda: amend_agreement(request, **first).pk, lambda: amend_agreement(request, **second).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(AgreementChange.objects.count(), 1)
        self.assertEqual(self.agreement.terms_versions.count(), 3)

    def test_period_close_and_cash_post_are_serialized_without_partial_posting(self):
        request = self.request()
        result = self.race([lambda: close_period(request, closed_through=DAY, password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4())).pk,
                            lambda: self.cash('1.00').pk])
        self.assertEqual(result[0][0], 'ok')
        self.assertIn(result[1][0], {'ok', 'denied'})
        self.assertEqual(FinancePeriodClose.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 2 if result[1][0] == 'ok' else 1)
        with self.assertRaises(ValidationError): self.cash('1.00')

    def test_owner_revocation_committing_during_lock_wait_denies_correction(self):
        from .membership import create_accountant_profile
        backup = get_user_model().objects.create_user('s24-backup-owner')
        create_accountant_profile(user_id=backup.pk, office_id=self.office.pk, role='owner')
        request, values = self.request(), self.correction_values()
        held, release, ready, pids = threading.Event(), threading.Event(), threading.Event(), []
        def revoke():
            connections.close_all()
            try:
                with transaction.atomic():
                    Office.objects.select_for_update().get(pk=self.office.pk)
                    AccountantProfile.objects.filter(user=self.owner).update(is_active=False)
                    held.set()
                    if not release.wait(10): raise AssertionError('Release was not signalled')
            finally: connections.close_all()
        def write():
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='10s'")
                    cursor.execute('SELECT pg_backend_pid()'); pids.append(cursor.fetchone()[0]); ready.set()
                try: correct_cash(request, **values)
                except PermissionDenied: return 'denied'
                return 'created'
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoker = pool.submit(revoke)
            try:
                self.assertTrue(held.wait(8)); writer = pool.submit(write); self.assertTrue(ready.wait(8))
                deadline, blocked = time.monotonic() + 8, False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT cardinality(pg_blocking_pids(%s))', [pids[0]])
                        if cursor.fetchone()[0]: blocked = True; break
                    time.sleep(.02)
                self.assertTrue(blocked, 'Observe an actual independent PostgreSQL lock wait')
            finally: release.set()
            revoker.result(timeout=12)
            self.assertEqual(writer.result(timeout=12), 'denied')
        self.assertEqual(FinanceCorrection.objects.count(), 0)
        self.assertFalse(Transaction.objects.filter(reversal_of=self.source).exists())

    def test_completed_correction_without_required_charge_event_cannot_commit(self):
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.owner, WHY):
            action = new_action(self.request(), self.office, 'CHARGE', DAY, WHY, 'sha256:' + '1' * 64,
                'sha256:' + '2' * 64, source_charge=self.charge)
            with correction_context(action): finish(action)
        self.assertEqual(FinanceCorrection.objects.count(), 0)

    def test_single_transfer_reversal_cannot_commit_even_with_forged_completed_flags(self):
        pair = post_transfer(self.member, from_account=self.account, to_account=self.other, amount='40.00', transfer_date=DAY,
            description='ΔΟΚΙΜΑΣΤΙΚΟ ΗΜΙΤΕΛΕΣ ΖΕΥΓΟΣ S24', idempotency_key=str(uuid.uuid4()))
        request = self.request()
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.owner, WHY):
            action = new_action(request, self.office, 'TRANSFER', DAY, WHY, 'sha256:' + '3' * 64,
                'sha256:' + '4' * 64, source_cash=pair[0], expected_cash_count=2)
            with correction_context(action):
                cmd = cash_members(request, action, 'transfer.reverse')
                with audit_context(self.owner, WHY, cmd):
                    reverse_entry(action, cmd, pair[0], group=action.pk)
                    complete(cmd)
                finish(action)
        self.assertEqual(Transaction.objects.filter(reversal_of__in=pair).count(), 0)
        self.assertEqual(FinanceCorrection.objects.count(), 0)

    def test_refund_cash_without_its_source_link_cannot_commit(self):
        request = self.request()
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.owner, WHY):
            action = new_action(request, self.office, 'REFUND', DAY, WHY, 'sha256:' + '5' * 64,
                'sha256:' + '6' * 64, source_cash=self.source, expected_cash_count=1)
            with correction_context(action):
                cmd = cash_members(request, action, 'cash.refund')
                with audit_context(self.owner, WHY, cmd):
                    Transaction.objects.create(office=self.office, command=cmd, posting_kind='REFUND', amount='1.00',
                        transaction_date=DAY, transaction_type='EXPENSE', cash_account=self.account, entity=self.customer,
                        description='ΔΟΚΙΜΑΣΤΙΚΗ ΑΣΥΝΔΕΤΗ ΕΠΙΣΤΡΟΦΗ S24')
                    complete(cmd)
                finish(action)
        self.assertEqual(FinanceCorrection.objects.count(), 0)
        self.assertEqual(self.cash_balance(), Decimal('220.00'))


class CorrectionMigrationTests(CorrectionSupport, TransactionTestCase):
    old = ('accounting', '0018_settlement_guards')
    current = ('accounting', '0020_financial_correction_guards')

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def setUp(self):
        self.migrate(self.old)
        self.prepare()
        self.allocated()

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_upgrade_preserves_original_rows_and_creates_no_inferred_correction_or_closure(self):
        models = (Transaction, FinanceCommand, Charge, AgreementTermsVersion, Agreement, Entity, CashAccount, CashAllocation, AllocationRelease)
        before = {model._meta.label: list(model.objects.order_by('pk').values()) for model in models}
        self.migrate(self.current)
        for model in models:
            self.assertEqual(list(model.objects.order_by('pk').values()), before[model._meta.label])
        for model in (FinanceCorrection, CorrectionRelease, CashRefund, ChargeReversal, ChargeReplacement, AgreementChange, FinancePeriodClose):
            self.assertEqual(model.objects.count(), 0)
        self.assertEqual(self.current_balances(self.charge, self.source), (Decimal('0.00'), Decimal('20.00')))

    def test_retained_correction_and_period_history_deny_unsafe_downgrade(self):
        self.migrate(self.current)
        action = correct_cash(self.request(), **self.correction_values())
        with self.assertRaisesMessage(Exception, 'unsafe downgrade denied'): self.migrate(self.old)
        self.assertTrue(FinanceCorrection.objects.filter(pk=action.pk).exists())
        self.assertTrue(Transaction.objects.filter(reversal_of=self.source).exists())
