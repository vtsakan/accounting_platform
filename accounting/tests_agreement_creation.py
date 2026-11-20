"""CR-002 contracts for operator-run PostgreSQL verification, not APPLY."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, IntegrityError
from django.db.migrations.executor import MigrationExecutor
from django.http import QueryDict
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .agreement_creation import create_with_charge
from .agreement_creation_forms import AgreementCreationForm
from .agreement_selectors import agreement_projection
from .charge_services import post_charge, save_terms
from .correction_services import amend_agreement, close_period, correct_charge
from .fee_services import create_schedule, preview
from .finance_services import post_cash
from .models import Agreement, AgreementTermsVersion, AccountantProfile, Charge, FinanceCommand, FinanceAuditEvent, Transaction
from .settlement_services import allocate_cash
from .tests_auth_support import staff_client_login
from .tests_finance_posting import Fixtures, DAY

WHY = 'Δημιουργία δοκιμαστικής συμφωνίας και αρχικής χρέωσης'


class CreationSupport(Fixtures):
    def candidate(self, **changes):
        return Agreement(**(
            {'entity': self.customer, 'agreement_type': 'RECEIVABLE', 'description': 'ΔΟΚΙΜΑΣΤΙΚΗ ΝΕΑ ΣΥΜΦΩΝΙΑ CR002',
             'total_amount': '400.00', 'start_date': DAY} | changes))

    def intent(self, **changes):
        return {'billing_mode': 'ONE_OFF', 'reason': WHY, 'creation_key': str(uuid.uuid4()),
                'due_date': DAY + timedelta(days=10)} | changes

    def counts(self):
        return tuple(model.objects.count() for model in (Agreement, AgreementTermsVersion, Charge, FinanceAuditEvent))

    def form_data(self, **changes):
        return {'entity': self.customer.pk, 'agreement_type': 'RECEIVABLE', 'description': 'ΔΟΚΙΜΑΣΤΙΚΗ ΝΕΑ ΣΥΜΦΩΝΙΑ CR002',
                'total_amount': '400,00', 'start_date': DAY.isoformat(), 'status': 'ACTIVE', 'billing_mode': 'ONE_OFF',
                'lifecycle': 'ACTIVE', 'reason': WHY, 'terms_revision': '0', 'creation_key': str(uuid.uuid4())} | changes


class AgreementCreationTests(CreationSupport, TestCase):
    def setUp(self):
        self.seed()
        staff_client_login(self.client, self.member)

    def test_get_defaults_to_active_one_off_and_has_no_writes(self):
        before = self.counts()
        response = self.client.get(reverse('add-agreement'), HTTP_ACCEPT_LANGUAGE='en')
        form = response.context['form']
        self.assertEqual((form.initial['billing_mode'], form.initial['lifecycle']), ('ONE_OFF', 'ACTIVE'))
        self.assertEqual(form.initial['start_date'], timezone.localdate())
        self.assertIn('creation_key', form.fields)
        self.assertContains(response, 'Αποθήκευση συμφωνίας και χρέωσης')
        self.assertEqual(self.counts(), before)

    def test_new_customer_agreement_immediately_shows_400_debt_and_no_cash(self):
        response = self.client.post(reverse('add-agreement'), self.form_data())
        self.assertEqual(response.status_code, 302)
        agreement = Agreement.objects.get(description='ΔΟΚΙΜΑΣΤΙΚΗ ΝΕΑ ΣΥΜΦΩΝΙΑ CR002')
        self.assertRedirects(response, reverse('agreement-detail', args=[agreement.pk]))
        projection = agreement_projection(agreement)
        self.assertEqual((projection['charge_total'], projection['remaining_obligation']), (Decimal('400.00'), Decimal('400.00')))
        self.assertEqual((Transaction.objects.count(), FinanceCommand.objects.count()), (0, 0))

    def test_supplier_agreement_creates_payable_without_payment(self):
        agreement, charge, replay = create_with_charge(self.member, self.candidate(entity=self.supplier, agreement_type='PAYABLE'), **self.intent())
        self.assertEqual((charge.direction, charge.entity_id, charge.amount, replay), ('PAYABLE', self.supplier.pk, Decimal('400.00'), False))
        self.assertEqual(agreement_projection(agreement)['remaining_obligation'], Decimal('400.00'))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_monthly_creation_posts_only_its_first_calendar_occurrence(self):
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **self.intent(billing_mode='MONTHLY'))
        self.assertEqual((charge.period, charge.effective_date, charge.amount), (DAY.replace(day=1), DAY, Decimal('400.00')))
        self.assertEqual(charge.source_key, f'agreement:{agreement.pk}:month:{DAY:%Y-%m}')
        self.assertEqual(Charge.objects.count(), 1)

    def test_first_partial_month_uses_explicit_amount_without_proration(self):
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **self.intent(billing_mode='MONTHLY', first_charge_amount='175.00'))
        self.assertEqual((charge.amount, agreement.total_amount), (Decimal('175.00'), Decimal('400.00')))
        self.assertEqual(agreement_projection(agreement)['remaining_obligation'], Decimal('175.00'))

    def test_same_request_returns_same_agreement_charge_and_audit(self):
        intent = self.intent()
        first = create_with_charge(self.member, self.candidate(), **intent)
        before = self.counts()
        second = create_with_charge(self.member, self.candidate(), **intent)
        self.assertEqual((first[0].pk, first[1].pk), (second[0].pk, second[1].pk))
        self.assertTrue(second[2])
        self.assertEqual(self.counts(), before)

    def test_http_double_submission_creates_only_one_agreement_and_charge(self):
        data = self.form_data()
        first = self.client.post(reverse('add-agreement'), data)
        before = self.counts()
        second = self.client.post(reverse('add-agreement'), data)
        self.assertEqual((first.status_code, second.status_code), (302, 302))
        self.assertEqual(first.url, second.url)
        self.assertEqual(self.counts(), before)

    def test_changed_creation_payload_is_denied_without_writes(self):
        intent = self.intent()
        create_with_charge(self.member, self.candidate(), **intent)
        before = self.counts()
        for fields, options in (({'total_amount': '401.00'}, {}), ({'description': 'Άλλη συμφωνία'}, {}),
                ({'start_date': DAY + timedelta(days=1)}, {}), ({}, {'reason': 'Άλλη αιτιολογία χρέωσης'}),
                ({}, {'due_date': DAY + timedelta(days=11)}), ({}, {'billing_mode': 'MONTHLY'})):
            with self.subTest(fields=fields, options=options), self.assertRaises(ValidationError):
                create_with_charge(self.member, self.candidate(**fields), **(intent | options))
            self.assertEqual(self.counts(), before)

    def test_distinct_intent_can_create_distinct_legitimate_agreements(self):
        first = create_with_charge(self.member, self.candidate(), **self.intent())
        second = create_with_charge(self.member, self.candidate(), **self.intent())
        self.assertNotEqual(first[0].pk, second[0].pk)
        self.assertEqual(Charge.objects.count(), 2)

    def test_charge_failure_rolls_back_terms_agreement_and_audit(self):
        before = self.counts()
        with patch('accounting.agreement_creation.post_charge', side_effect=ValidationError('Δοκιμαστική αποτυχία χρέωσης')):
            with self.assertRaises(ValidationError):
                create_with_charge(self.member, self.candidate(), **self.intent())
        self.assertEqual(self.counts(), before)

    def test_closed_period_cannot_leave_an_uncharged_new_agreement(self):
        close_period(self.request(), closed_through=DAY, password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        before = self.counts()
        with self.assertRaises(ValidationError):
            create_with_charge(self.member, self.candidate(), **self.intent())
        self.assertEqual(self.counts(), before)

    def test_future_start_is_explained_and_leaves_no_records(self):
        before = self.counts()
        form = AgreementCreationForm(self.form_data(start_date=(timezone.localdate() + timedelta(days=1)).isoformat()), user=self.member)
        self.assertFalse(form.is_valid())
        self.assertIn('start_date', form.errors)
        self.assertEqual(self.counts(), before)

    def test_invalid_due_date_and_partial_amount_are_atomic(self):
        before = self.counts()
        for values in ({'due_date': DAY - timedelta(days=1)}, {'first_charge_amount': '50.00'},
                       {'billing_mode': 'MONTHLY', 'first_charge_amount': '0.00'}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                create_with_charge(self.member, self.candidate(), **self.intent(**values))
            self.assertEqual(self.counts(), before)

    def test_foreign_office_instance_or_party_cannot_be_created(self):
        before = self.counts()
        with self.assertRaises(PermissionDenied):
            create_with_charge(self.member, self.candidate(office=self.foreign), **self.intent())
        foreign_party = type(self.customer).objects.create(office=self.foreign, name='ΞΕΝΟΣ ΠΕΛΑΤΗΣ CR002', entity_type='CUSTOMER')
        with self.assertRaises(ValidationError):
            create_with_charge(self.member, self.candidate(entity=foreign_party), **self.intent())
        self.assertEqual(self.counts(), before)

    def test_role_mismatch_and_archived_party_are_denied(self):
        before = self.counts()
        with self.assertRaises(ValidationError):
            create_with_charge(self.member, self.candidate(entity=self.supplier), **self.intent())
        from .counterparty_services import archive_counterparty
        self.customer.refresh_from_db()
        archive_counterparty(self.member, self.customer.pk, version=self.customer.record_version, archive=True)
        with self.assertRaises(ValidationError):
            create_with_charge(self.member, self.candidate(), **self.intent())
        self.assertEqual(self.counts(), before)

    def test_revoked_membership_blocks_replay(self):
        intent = self.intent()
        create_with_charge(self.member, self.candidate(), **intent)
        before = self.counts()
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            create_with_charge(self.member, self.candidate(), **intent)
        self.assertEqual(self.counts(), before)

    def test_missing_identity_cannot_silently_fall_back_to_terms_only(self):
        data = self.form_data()
        del data['creation_key']
        before = self.counts()
        response = self.client.post(reverse('add-agreement'), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn('creation_key', response.context['form'].errors)
        self.assertEqual(self.counts(), before)

    def test_fully_populated_foreign_party_http_submission_is_denied(self):
        party = type(self.customer).objects.create(office=self.foreign, name='ΞΕΝΟΣ ΠΕΛΑΤΗΣ ΦΟΡΜΑΣ', entity_type='CUSTOMER')
        before = self.counts()
        response = self.client.post(reverse('add-agreement'), self.form_data(entity=party.pk))
        self.assertEqual(response.status_code, 200)
        self.assertIn('entity', response.context['form'].errors)
        self.assertEqual(self.counts(), before)

    def test_another_accountant_cannot_claim_an_existing_creation_receipt(self):
        intent = self.intent()
        create_with_charge(self.member, self.candidate(), **intent)
        before = self.counts()
        with self.assertRaises(ValidationError):
            create_with_charge(self.owner, self.candidate(), **intent)
        self.assertEqual(self.counts(), before)

    def test_malformed_creation_key_is_denied_before_any_write(self):
        before = self.counts()
        with self.assertRaises(ValidationError):
            create_with_charge(self.member, self.candidate(), **self.intent(creation_key='invalid'))
        self.assertEqual(self.counts(), before)

    def test_duplicate_form_values_are_rejected(self):
        data = QueryDict('', mutable=True)
        data.update(self.form_data())
        data.appendlist('total_amount', '500,00')
        form = AgreementCreationForm(data, user=self.member)
        self.assertFalse(form.is_valid())
        self.assertIn('total_amount', form.errors)

    def test_manual_second_one_off_charge_cannot_duplicate_automatic_source(self):
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **self.intent())
        with self.assertRaises(ValidationError):
            post_charge(self.member, agreement_id=agreement.pk, terms_revision=charge.terms.revision,
                amount=charge.amount, effective_date=DAY, due_date=charge.due_date, reason=WHY, idempotency_key=str(uuid.uuid4()))
        self.assertEqual(Charge.objects.count(), 1)

    def test_monthly_schedule_reuses_initial_source_and_preserves_next_month(self):
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **self.intent(billing_mode='MONTHLY', first_charge_amount='175.00'))
        schedule = create_schedule(self.member, agreement_id=agreement.pk, start_period=DAY.replace(day=1),
            due_day=25, first_amount='175.00', reason=WHY)
        rows = preview(self.member, schedule.pk, start_period=DAY.replace(day=1), months=2)
        self.assertEqual((rows[0]['source_key'], rows[0]['amount']), (charge.source_key, charge.amount))
        self.assertEqual(rows[1]['amount'], Decimal('400.00'))
        self.assertEqual(Charge.objects.count(), 1)

    def test_unchanged_edit_does_not_charge_again(self):
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **self.intent())
        save_terms(self.member, agreement, billing_mode='ONE_OFF', lifecycle='ACTIVE',
            expected_revision=charge.terms.revision, reason=WHY)
        self.assertEqual((Charge.objects.count(), Transaction.objects.count()), (1, 0))

    def test_reversed_initial_charge_cannot_be_recreated_by_retry(self):
        intent = self.intent()
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **intent)
        correct_charge(self.request(), charge_id=charge.pk, password=self.password, effective_date=DAY,
            reason=WHY, idempotency_key=str(uuid.uuid4()))
        result = create_with_charge(self.member, self.candidate(), **intent)
        self.assertEqual((result[0].pk, result[1].pk, result[2]), (agreement.pk, charge.pk, True))
        self.assertEqual(Charge.objects.count(), 1)
        self.assertEqual(agreement_projection(agreement)['remaining_obligation'], Decimal('0.00'))

    def test_retry_binds_initial_snapshot_after_a_prospective_amendment(self):
        intent = self.intent()
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **intent)
        amend_agreement(self.request(), agreement_id=agreement.pk, expected_revision=charge.terms.revision,
            description='Μελλοντικοί δοκιμαστικοί όροι', amount='500.00', lifecycle='ACTIVE', password=self.password,
            effective_date=timezone.localdate() + timedelta(days=1), reason=WHY, idempotency_key=str(uuid.uuid4()))
        result = create_with_charge(self.member, self.candidate(), **intent)
        self.assertEqual((result[0].pk, result[1].pk, result[2]), (agreement.pk, charge.pk, True))
        self.assertEqual((Charge.objects.count(), charge.amount), (1, Decimal('400.00')))

    def test_400_charge_existing_100_receipt_and_allocation_leave_300_debt(self):
        entry = post_cash(self.member, idempotency_key=str(uuid.uuid4()), amount='100.00', transaction_date=DAY,
            transaction_type='INCOME', cash_account=self.account, entity=self.customer, description='ΔΟΚΙΜΑΣΤΙΚΗ ΕΙΣΠΡΑΞΗ CR002')
        agreement, charge, _ = create_with_charge(self.member, self.candidate(), **self.intent())
        allocate_cash(self.member, source_cash=entry.pk, lines=[{'charge': charge.pk, 'amount': '100.00'}],
            effective_date=DAY, reason=WHY, idempotency_key=str(uuid.uuid4()))
        projection = agreement_projection(agreement)
        self.assertEqual((projection['allocated_total'], projection['remaining_obligation']), (Decimal('100.00'), Decimal('300.00')))
        self.assertEqual((Transaction.objects.count(), FinanceCommand.objects.count()), (1, 1))

    def test_existing_unreviewed_agreement_is_not_backfilled_by_new_form_get(self):
        before = self.counts()
        self.client.get(reverse('add-agreement'))
        self.assertEqual(self.agreement.terms_versions.first().billing_mode, 'UNREVIEWED')
        self.assertEqual(self.counts(), before)


class AgreementCreationConcurrency(CreationSupport, TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().setUpClass()

    def setUp(self):
        self.seed()

    def race(self, intents):
        barrier = Barrier(2)
        def run(intent):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'")
                actor = get_user_model().objects.get(pk=self.member.pk)
                barrier.wait(timeout=6)
                try:
                    result = create_with_charge(actor, self.candidate(), **intent)
                    return 'ok', result[0].pk, result[1].pk
                except (ValidationError, PermissionDenied, IntegrityError):
                    return 'denied', None, None
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, intent) for intent in intents]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_identical_submission_returns_one_agreement_and_charge(self):
        intent = self.intent()
        before = Agreement.objects.count()
        results = self.race([intent, intent])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0][0], 'ok')
        self.assertEqual((Agreement.objects.count(), Charge.objects.count()), (before + 1, 1))

    def test_concurrent_changed_payload_has_one_winner(self):
        intent = self.intent()
        before = Agreement.objects.count()
        results = self.race([intent, intent | {'reason': 'Άλλη δοκιμαστική επιβεβαίωση'}])
        self.assertEqual(sorted(row[0] for row in results), ['denied', 'ok'])
        self.assertEqual((Agreement.objects.count(), Charge.objects.count()), (before + 1, 1))
