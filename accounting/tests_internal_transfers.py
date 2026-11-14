"""S21 test source for operator execution; not executed by the implementation agent."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import threading
import uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.http import QueryDict
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from .account_services import save_reference
from .cash_selectors import cash_accounts
from .finance_services import post_transfer, post_cash, command_for, complete, audit_context
from .forms import TransferForm
from .models import CashAccount, FinanceCommand, FinanceAuditEvent, Transaction
from .movement_selectors import movement_totals, operating_movements
from .tests_auth_support import staff_client_login
from .tests_finance_posting import Fixtures, DAY


class TransferWorkspaceTests(Fixtures, TestCase):
    def setUp(self):
        self.seed()
        staff_client_login(self.client, self.member)

    def values(self, **changes):
        return dict(from_account=self.account, to_account=self.other, amount='1000.00',
                    transfer_date=DAY, description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S21',
                    idempotency_key=str(uuid.uuid4())) | changes

    def data(self, **changes):
        return dict(from_account=self.account.pk, to_account=self.other.pk, amount='1.000,00',
                    transfer_date=DAY.isoformat(), description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S21',
                    posting_key=str(uuid.uuid4())) | changes

    def send(self, values):
        return self.client.post(reverse('add-transfer'), values)

    def test_greek_form_has_today_default_and_fresh_operation_identity(self):
        first, second = (self.client.get(reverse('add-transfer'), HTTP_ACCEPT_LANGUAGE='en') for _ in range(2))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first['Content-Language'], 'el')
        self.assertEqual(first['Cache-Control'].find('no-store') >= 0, True)
        self.assertContains(first, 'Νέα εσωτερική μεταφορά')
        self.assertEqual(first.context['form'].initial['transfer_date'], timezone.localdate())
        self.assertNotEqual(first.context['form']['posting_key'].value(), second.context['form']['posting_key'].value())
        self.assertNotContains(first, self.foreign_account.name)

    def test_pair_is_explicit_attributable_and_reference_is_visible_on_both_legs(self):
        self.assertEqual(self.send(self.data()).status_code, 302)
        pair = list(Transaction.objects.order_by('pk'))
        self.assertEqual(len(pair), 2)
        self.assertEqual({entry.posting_kind for entry in pair}, {'TRANSFER'})
        self.assertEqual({entry.transaction_type for entry in pair}, {'INCOME', 'EXPENSE'})
        self.assertEqual(len({entry.command_id for entry in pair}), 1)
        self.assertEqual(len({entry.transfer_id for entry in pair}), 1)
        self.assertTrue(all(entry.entity_id is None and entry.category_id is None and entry.agreement_id is None for entry in pair))
        command = FinanceCommand.objects.get()
        self.assertEqual((command.operation, command.state, command.actor_id), ('cash.transfer', 'completed', self.member.pk))
        self.assertEqual(FinanceAuditEvent.objects.filter(command=command, actor=self.member, operation='cash.transfer').count(), 2)
        response = self.client.get(reverse('transaction-list'))
        self.assertContains(response, str(command.pk))
        self.assertContains(response, 'Αναφορά μεταφοράς: <code>', count=2)
        self.assertContains(response, str(pair[0].transfer_id), count=2)

    def test_1000_moves_each_balance_but_never_operating_totals_or_category_totals(self):
        source = CashAccount.objects.create(office=self.office, name='ΠΡΟΕΛΕΥΣΗ S21', opening_balance='2000.00', opening_date=DAY)
        target = CashAccount.objects.create(office=self.office, name='ΠΡΟΟΡΙΣΜΟΣ S21', opening_balance='100.00', opening_date=DAY)
        post_transfer(self.member, **self.values(from_account=source, to_account=target))
        accounts = {row.pk: row for row in cash_accounts(self.member, as_of=DAY)}
        self.assertEqual((accounts[source.pk].current_balance, accounts[target.pk].current_balance), (Decimal('1000.00'), Decimal('1100.00')))
        self.assertEqual((accounts[source.pk].transfer_out, accounts[target.pk].transfer_in), (Decimal('1000.00'), Decimal('1000.00')))
        self.assertEqual((accounts[source.pk].operating_expense, accounts[target.pk].operating_income), (Decimal('0.00'), Decimal('0.00')))
        post_cash(self.member, amount='50.00', transaction_date=DAY, transaction_type='INCOME', cash_account=source,
                  category=self.category, description='ΛΕΙΤΟΥΡΓΙΚΟ ΕΣΟΔΟ', idempotency_key=str(uuid.uuid4()))
        post_cash(self.member, amount='20.00', transaction_date=DAY, transaction_type='EXPENSE', cash_account=source,
                  category=self.category, description='ΛΕΙΤΟΥΡΓΙΚΟ ΕΞΟΔΟ', idempotency_key=str(uuid.uuid4()))
        response = self.client.get(reverse('summary-report'))
        self.assertEqual(tuple(response.context[key] for key in ('total_income', 'total_expense', 'net_for_period')),
                         (Decimal('50.00'), Decimal('20.00'), Decimal('30.00')))
        self.assertEqual(list(response.context['income_by_category']), [{'category__name': self.category.name, 'total_amount': Decimal('50.00')}])
        self.assertEqual(list(response.context['expense_by_category']), [{'category__name': self.category.name, 'total_amount': Decimal('20.00')}])
        cash = movement_totals(Transaction.objects.filter(office=self.office))
        self.assertEqual((cash['total_income'], cash['total_expense']), (Decimal('1050.00'), Decimal('1020.00')))

    def test_single_account_date_direction_or_text_filter_cannot_leak_one_transfer_leg_into_report(self):
        post_transfer(self.member, **self.values())
        for parameters in ({'cash_account': self.account.pk}, {'cash_account': self.other.pk},
                           {'transaction_type': 'INCOME'}, {'transaction_type': 'EXPENSE'},
                           {'start_date': DAY.isoformat(), 'end_date': DAY.isoformat()}, {'query': 'S21'}):
            with self.subTest(parameters=parameters):
                response = self.client.get(reverse('summary-report'), parameters)
                self.assertEqual(response.status_code, 200)
                self.assertEqual((response.context['total_income'], response.context['total_expense']), (Decimal('0.00'), Decimal('0.00')))

    def test_same_payload_retry_and_changed_payload_share_one_pair_only(self):
        values = self.data()
        self.assertEqual(self.send(values).status_code, 302)
        before = self.snapshot()
        ids = list(Transaction.objects.values_list('pk', flat=True).order_by('pk'))
        self.assertEqual(self.send(values).status_code, 302)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(Transaction.objects.values_list('pk', flat=True).order_by('pk')), ids)
        response = self.send(values | {'amount': '999,00'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].non_field_errors())
        self.assertEqual(self.snapshot(), before)

    def test_new_identity_with_identical_values_is_a_separate_intent(self):
        first = self.data()
        self.assertEqual(self.send(first).status_code, 302)
        self.assertEqual(self.send(first | {'posting_key': str(uuid.uuid4())}).status_code, 302)
        self.assertEqual((Transaction.objects.count(), FinanceCommand.objects.count()), (4, 2))

    def test_exact_retry_after_retirement_succeeds_but_new_or_changed_work_does_not(self):
        values = self.data()
        self.assertEqual(self.send(values).status_code, 302)
        self.other.refresh_from_db()  # Load approval metadata written by the database trigger.
        self.other.is_active = False
        save_reference(self.other, self.owner)
        before = self.snapshot()
        self.assertEqual(self.send(values).status_code, 302)
        changed = self.send(values | {'description': 'ΑΛΛΑΓΜΕΝΟ ΑΙΤΗΜΑ'})
        self.assertTrue(changed.context['form'].errors)
        new = self.send(values | {'posting_key': str(uuid.uuid4())})
        self.assertIn('to_account', new.context['form'].errors)
        self.assertEqual(self.snapshot(), before)

    def test_revoked_actor_cannot_replay_completed_operation(self):
        values = self.values()
        post_transfer(self.member, **values)
        before = self.snapshot()
        user = get_user_model().objects.get(pk=self.member.pk)
        user.is_active = False
        user.save(update_fields=['is_active'])
        with self.assertRaises(PermissionDenied):
            post_transfer(self.member, **values)
        self.assertEqual(self.snapshot(), before)

    def test_canonical_account_ids_share_identity_and_mixed_same_id_is_denied(self):
        values = self.values()
        pair = post_transfer(self.member, **values)
        retry = post_transfer(self.member, **(values | {'from_account': str(self.account.pk), 'to_account': self.other.pk}))
        self.assertEqual([entry.pk for entry in pair], [entry.pk for entry in retry])
        with self.assertRaises(ValidationError):
            post_transfer(self.member, **self.values(from_account=str(self.account.pk), to_account=self.account.pk))
        for value in (True, False, 1.0, '1.0', '-1', None, '９', '99999999999999999999'):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                post_transfer(self.member, **self.values(from_account=value))
        self.assertEqual(Transaction.objects.count(), 2)

    def test_cross_office_either_leg_and_injected_office_are_not_authority(self):
        before = self.snapshot()
        for name in ('from_account', 'to_account'):
            response = self.send(self.data(**{name: self.foreign_account.pk, 'office_id': str(self.foreign.pk)}))
            self.assertEqual(response.status_code, 200)
            self.assertIn(name, response.context['form'].errors)
            with self.assertRaises(ValidationError):
                post_transfer(self.member, **self.values(**{name: self.foreign_account}))
        self.assertEqual(self.snapshot(), before)

    def test_same_account_invalid_amount_dates_and_hidden_identity_are_field_errors(self):
        before = self.snapshot()
        for amount in ('0,00', '-1,00', 'abc', '1,001', '10000000000,00'):
            response = self.send(self.data(amount=amount))
            self.assertIn('amount', response.context['form'].errors)
        same = self.send(self.data(to_account=self.account.pk))
        self.assertTrue(same.context['form'].non_field_errors())
        for day in (DAY - timedelta(days=1), timezone.localdate() + timedelta(days=1)):
            self.assertIn('transfer_date', self.send(self.data(transfer_date=day.isoformat())).context['form'].errors)
        invalid = self.send(self.data(posting_key='invalid'))
        self.assertIn('posting_key', invalid.context['form'].errors)
        self.assertContains(invalid, 'alert-danger')
        self.assertEqual(self.snapshot(), before)

    def test_unreviewed_or_retired_accounts_are_not_new_transfer_choices(self):
        unreviewed = CashAccount.objects.create(office=self.office, name='ΣΕ ΑΝΑΜΟΝΗ S21')
        self.other.refresh_from_db()  # Retirement must preserve the actual approved opening.
        self.other.is_active = False
        save_reference(self.other, self.owner)
        for account in (unreviewed, self.other):
            response = self.send(self.data(to_account=account.pk))
            self.assertIn('to_account', response.context['form'].errors)
            with self.assertRaises(ValidationError):
                post_transfer(self.member, **self.values(to_account=account))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_duplicate_form_parameters_fail_closed(self):
        values = QueryDict('', mutable=True)
        values.update(self.data())
        values.appendlist('to_account', str(self.foreign_account.pk))
        form = TransferForm(values, user=self.member)
        self.assertFalse(form.is_valid())
        self.assertIn('to_account', form.errors)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_description_length_matches_service_and_html_is_escaped(self):
        rejected = self.send(self.data(description='α' * 201))
        self.assertIn('description', rejected.context['form'].errors)
        self.assertEqual(self.send(self.data(description='<script>alert(1)</script>')).status_code, 302)
        response = self.client.get(reverse('transaction-list'))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;', count=2)

    def test_legacy_uuid_does_not_mean_transfer_even_when_uuids_match(self):
        group = uuid.uuid4()
        for direction, amount in (('INCOME', '50.00'), ('EXPENSE', '20.00')):
            Transaction.objects.create(office=self.office, cash_account=self.account, transaction_date=DAY,
                                       transaction_type=direction, amount=amount, description='ΠΑΛΑΙΑ ΑΤΑΞΙΝΟΜΗΤΗ ΚΙΝΗΣΗ', transfer_id=group)
        rows = Transaction.objects.filter(office=self.office)
        self.assertEqual(operating_movements(rows).count(), 2)
        totals = movement_totals(operating_movements(rows))
        self.assertEqual((totals['total_income'], totals['total_expense']), (Decimal('50.00'), Decimal('20.00')))
        self.assertEqual(set(rows.values_list('posting_kind', flat=True)), {'LEGACY'})

    def test_historical_balance_uses_each_transfer_date_and_preserves_total_cash(self):
        later = DAY + timedelta(days=1)
        post_transfer(self.member, **self.values(transfer_date=later, amount='20.00'))
        before = {row.pk: row for row in cash_accounts(self.member, as_of=DAY)}
        after = {row.pk: row for row in cash_accounts(self.member, as_of=later)}
        self.assertEqual((before[self.account.pk].current_balance, before[self.other.pk].current_balance), (Decimal('100.00'), Decimal('0.00')))
        self.assertEqual((after[self.account.pk].current_balance, after[self.other.pk].current_balance), (Decimal('80.00'), Decimal('20.00')))
        self.assertEqual(sum(row.current_balance for row in before.values()), sum(row.current_balance for row in after.values()))
        self.assertEqual((after[self.account.pk].operating_expense, after[self.other.pk].operating_income), (Decimal('0.00'), Decimal('0.00')))

    def test_http_recognised_database_failure_is_safe_and_same_identity_can_retry(self):
        class ConstraintFailure(Exception):
            sqlstate = '23514'
        failure = IntegrityError('synthetic-transfer-constraint')
        failure.__cause__ = ConstraintFailure()
        values = self.data()
        with patch('accounting.transfer_views.post_transfer', side_effect=failure):
            response = self.send(values)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Η μεταφορά δεν ολοκληρώθηκε')
        self.assertEqual(str(response.context['form']['posting_key'].value()), values['posting_key'])
        self.assertNotContains(response, 'synthetic-transfer-constraint')
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(self.send(values).status_code, 302)


class TransferCommitTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.seed()
        if connection.vendor != 'postgresql' or connection.pg_version // 10000 != 17:
            raise AssertionError('S21 concurrency/commit proof requires PostgreSQL 17')

    def values(self, **changes):
        return dict(from_account=self.account.pk, to_account=self.other.pk, amount='20.00', transfer_date=DAY,
                    description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S21', idempotency_key=str(uuid.uuid4())) | changes

    def race(self, functions):
        barrier = threading.Barrier(len(functions))
        pids, guard = [], threading.Lock()
        def worker(function):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    with guard:
                        pids.append(cursor.fetchone()[0])
                barrier.wait(timeout=6)
                try:
                    actor = get_user_model().objects.get(pk=self.member.pk)
                    return ('ok', function(actor))
                except (ValidationError, PermissionDenied) as error:
                    return ('denied', type(error).__name__)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(worker, function) for function in functions]
            result = [future.result(timeout=15) for future in futures]
        self.assertEqual(len(set(pids)), len(functions))
        return result

    def test_concurrent_same_identity_commits_one_pair_and_two_audits(self):
        values = self.values()
        def submit(actor):
            return tuple(entry.pk for entry in post_transfer(actor, **values))
        result = self.race([submit, submit])
        self.assertTrue(all(row[0] == 'ok' for row in result))
        self.assertEqual(result[0][1], result[1][1])
        self.assertEqual((Transaction.objects.count(), FinanceCommand.objects.count()), (2, 1))
        self.assertEqual(FinanceAuditEvent.objects.filter(command_id=FinanceCommand.objects.get().pk).count(), 2)

    def test_concurrent_changed_payload_with_same_identity_has_one_winner(self):
        values = self.values()
        def submit(amount):
            return lambda actor: tuple(entry.pk for entry in post_transfer(actor, **(values | {'amount': amount})))
        result = self.race([submit('20.00'), submit('21.00')])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual((Transaction.objects.count(), FinanceCommand.objects.count()), (2, 1))
        pair = list(Transaction.objects.order_by('pk'))
        self.assertEqual(pair[0].amount, pair[1].amount)

    def test_opposite_direction_concurrent_transfers_both_commit_without_losing_cash(self):
        first = self.values()
        second = self.values(from_account=self.other.pk, to_account=self.account.pk)
        result = self.race([lambda actor: tuple(e.pk for e in post_transfer(actor, **first)),
                            lambda actor: tuple(e.pk for e in post_transfer(actor, **second))])
        self.assertTrue(all(row[0] == 'ok' for row in result))
        self.assertEqual((Transaction.objects.count(), FinanceCommand.objects.count()), (4, 2))
        accounts = {row.pk: row.current_balance for row in cash_accounts(self.member, as_of=DAY)}
        self.assertEqual((accounts[self.account.pk], accounts[self.other.pk]), (Decimal('100.00'), Decimal('0.00')))

    def test_second_leg_failure_rolls_back_command_both_legs_and_audits_then_retry_succeeds(self):
        before, create, calls = self.snapshot(), Transaction.objects.create, []
        values = self.values()
        def insert(**fields):
            calls.append(fields['transaction_type'])
            if len(calls) == 2:
                raise RuntimeError('synthetic-second-leg')
            return create(**fields)
        with patch('accounting.finance_services.Transaction.objects.create', side_effect=insert), self.assertRaises(RuntimeError):
            post_transfer(self.member, **values)
        self.assertEqual(calls, ['EXPENSE', 'INCOME'])
        self.assertEqual(self.snapshot(), before)
        pair = post_transfer(self.member, **values)
        self.assertEqual(len(pair), 2)
        self.assertEqual(FinanceCommand.objects.count(), 1)

    def test_sql_incomplete_pair_cannot_commit_and_posted_leg_cannot_change(self):
        before = self.snapshot()
        with self.assertRaises(IntegrityError), transaction.atomic():
            command, _ = command_for(self.member, self.office, 'cash.transfer', str(uuid.uuid4()), {'synthetic': True}, 'Δοκιμή ημιτελούς μεταφοράς')
            with audit_context(self.member, 'Δοκιμή ημιτελούς μεταφοράς', command):
                Transaction.objects.create(office=self.office, cash_account=self.account, command=command, posting_kind='TRANSFER',
                                           transfer_id=uuid.uuid4(), transaction_type='EXPENSE', amount='20.00',
                                           transaction_date=DAY, description='ΗΜΙΤΕΛΗΣ ΔΟΚΙΜΗ')
                complete(command)
        self.assertEqual(self.snapshot(), before)
        pair = post_transfer(self.member, **self.values())
        for action in (lambda: Transaction.objects.filter(pk=pair[0].pk).update(amount='21.00'),
                       lambda: Transaction.objects.filter(pk=pair[1].pk).delete()):
            with self.assertRaises((IntegrityError, ValidationError)), transaction.atomic():
                action()
        self.assertEqual(Transaction.objects.filter(command=pair[0].command).count(), 2)
