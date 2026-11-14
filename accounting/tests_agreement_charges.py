"""S22 source-only checks for operator-run PostgreSQL verification."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import copy
import threading
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections, IntegrityError, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, Client
from django.urls import reverse
from django.utils import timezone
from .models import Agreement, AgreementTermsVersion, Charge, Entity, Transaction, FinanceCommand
from .charge_services import save_terms, post_charge, terms_context
from .finance_services import post_cash, audit_context
from .forms import AgreementForm
from .agreement_selectors import agreement_projection, obligation_totals
from .tests_finance_posting import Fixtures, DAY
from .tests_auth_support import staff_client_login
from .counterparty_services import archive_counterparty


class ChargeSupport(Fixtures):
    def review(self, *, agreement=None, mode='ONE_OFF', lifecycle='ACTIVE', actor=None):
        agreement = agreement or self.agreement
        agreement.refresh_from_db()
        latest = agreement.terms_versions.first()
        save_terms(actor or self.member, agreement, billing_mode=mode, lifecycle=lifecycle,
                   expected_revision=latest.revision, reason='ΔΟΚΙΜΑΣΤΙΚΟΣ ΕΛΕΓΧΟΣ ΟΡΩΝ S22')
        return agreement.terms_versions.first()

    def values(self, **changes):
        return dict(agreement_id=self.agreement.pk, terms_revision=self.agreement.terms_versions.first().revision,
                    amount='100.00', effective_date=DAY, due_date=DAY + timedelta(days=10), period=None,
                    reason='ΔΟΚΙΜΑΣΤΙΚΗ ΕΠΙΒΕΒΑΙΩΣΗ ΧΡΕΩΣΗΣ S22', idempotency_key=str(uuid.uuid4())) | changes

    def form_data(self, **changes):
        return {'entity': self.customer.pk, 'agreement_type': 'RECEIVABLE', 'description': 'ΔΟΚΙΜΑΣΤΙΚΟΙ ΟΡΟΙ S22',
                'total_amount': '100,00', 'start_date': DAY.isoformat(), 'status': 'ACTIVE', 'billing_mode': 'ONE_OFF',
                'lifecycle': 'ACTIVE', 'reason': 'ΔΟΚΙΜΑΣΤΙΚΟΣ ΕΛΕΓΧΟΣ ΟΡΩΝ S22', 'terms_revision': 0} | changes


class AgreementChargeTests(ChargeSupport, TestCase):
    def setUp(self):
        self.seed()
        staff_client_login(self.client, self.member)

    def test_existing_agreement_has_unreviewed_snapshot_and_no_automatic_charge(self):
        terms = self.agreement.terms_versions.get()
        self.assertEqual((terms.revision, terms.billing_mode, terms.lifecycle), (0, 'UNREVIEWED', 'UNREVIEWED'))
        self.assertIsNone(terms.actor_id)
        self.assertEqual((terms.entity_id, terms.direction, terms.agreed_amount), (self.customer.pk, 'RECEIVABLE', Decimal('100.00')))
        self.assertEqual(Charge.objects.count(), 0)

    def test_new_greek_agreement_saves_terms_only_without_charge_or_cash(self):
        response = self.client.post(reverse('add-agreement'), self.form_data(), HTTP_ACCEPT_LANGUAGE='en')
        self.assertEqual(response.status_code, 302)
        agreement = Agreement.objects.get(description='ΔΟΚΙΜΑΣΤΙΚΟΙ ΟΡΟΙ S22')
        terms = agreement.terms_versions.get()
        self.assertEqual((terms.billing_mode, terms.lifecycle, terms.actor_id), ('ONE_OFF', 'ACTIVE', self.member.pk))
        self.assertEqual((Charge.objects.count(), Transaction.objects.count(), FinanceCommand.objects.count()), (0, 0, 0))
        response = self.client.get(reverse('agreement-detail', args=[agreement.pk]))
        self.assertEqual(response.context['charge_total'], Decimal('0.00'))
        self.assertEqual(response.context['settlement_label'], 'Χωρίς χρεώσεις')
        self.assertContains(response, 'Συμφωνημένο ποσό')
        self.assertEqual(response['Content-Language'], 'el')

    def test_legacy_completed_flag_does_not_mean_charge_or_paid_state(self):
        self.agreement.status = 'COMPLETED'
        self.agreement.save(update_fields=['status', 'updated_at'])
        terms = self.review()
        self.assertEqual(terms.lifecycle, 'ACTIVE')
        projection = agreement_projection(self.agreement)
        self.assertEqual((projection['charge_total'], projection['cash_total']), (Decimal('0.00'), Decimal('0.00')))
        self.assertEqual(projection['settlement_label'], 'Χωρίς χρεώσεις')
        self.assertEqual(obligation_totals(self.member)['posted_receivable_total'], Decimal('0.00'))

    def test_unreviewed_draft_and_cancelled_terms_cannot_post(self):
        with self.assertRaises(ValidationError):
            post_charge(self.member, **self.values())
        self.review(lifecycle='DRAFT')
        with self.assertRaises(ValidationError):
            post_charge(self.member, **self.values())
        self.review(lifecycle='ACTIVE')
        self.agreement.refresh_from_db()
        self.agreement.status = 'CANCELLED'
        self.agreement.save(update_fields=['status', 'updated_at'])
        with self.assertRaises(ValidationError):
            post_charge(self.member, **self.values())
        self.assertEqual(Charge.objects.count(), 0)

    def test_one_off_obligation_has_snapshot_source_actor_dates_and_no_cash_effect(self):
        terms = self.review()
        before = self.snapshot()
        charge = post_charge(self.member, **self.values())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((charge.agreement_id, charge.terms_id, charge.entity_id), (self.agreement.pk, terms.pk, self.customer.pk))
        self.assertEqual((charge.amount, charge.currency, charge.direction), (Decimal('100.00'), 'EUR', 'RECEIVABLE'))
        self.assertEqual(charge.actor_id, self.member.pk)
        self.assertEqual(charge.source_key, f'agreement:{self.agreement.pk}:one-off')
        self.assertEqual((charge.effective_date, charge.due_date), (DAY, DAY + timedelta(days=10)))
        self.assertEqual(charge.reason, 'ΔΟΚΙΜΑΣΤΙΚΗ ΕΠΙΒΕΒΑΙΩΣΗ ΧΡΕΩΣΗΣ S22')
        self.assertIsNone(charge.period)

    def test_charge_cash_and_terms_are_not_added_together_as_debt(self):
        self.review()
        post_charge(self.member, **self.values())
        post_cash(self.member, idempotency_key=str(uuid.uuid4()), amount='25.00', transaction_date=DAY,
                  transaction_type='INCOME', cash_account=self.account, entity=self.customer,
                  agreement=self.agreement, description='ΔΟΚΙΜΑΣΤΙΚΗ ΠΡΑΓΜΑΤΙΚΗ ΕΙΣΠΡΑΞΗ')
        detail = self.client.get(reverse('agreement-detail', args=[self.agreement.pk]))
        self.assertEqual((detail.context['agreement'].total_amount, detail.context['charge_total'], detail.context['cash_total']),
                         (Decimal('100.00'), Decimal('100.00'), Decimal('25.00')))
        self.assertEqual(detail.context['settlement_label'], 'Χρεώσεις χωρίς αντιστοιχίσεις')
        report = self.client.get(reverse('summary-report'))
        self.assertEqual(report.context['posted_receivable_total'], Decimal('100.00'))
        self.assertEqual(report.context['posted_payable_total'], Decimal('0.00'))
        self.assertEqual(report.context['total_income'], Decimal('25.00'))

    def test_supplier_agreement_posts_payable_but_customer_only_role_is_rejected(self):
        payable = Agreement.objects.create(office=self.office, entity=self.supplier, agreement_type='PAYABLE',
                                           description='ΔΟΚΙΜΑΣΤΙΚΟΙ ΟΡΟΙ ΠΡΟΜΗΘΕΥΤΗ', total_amount='100.00', start_date=DAY)
        terms = self.review(agreement=payable)
        charge = post_charge(self.member, **self.values(agreement_id=payable.pk, terms_revision=terms.revision))
        self.assertEqual((charge.entity_id, charge.direction), (self.supplier.pk, 'PAYABLE'))
        form = AgreementForm(self.form_data(agreement_type='PAYABLE'), user=self.member)
        self.assertFalse(form.is_valid())
        self.assertIn('entity', form.errors)
        self.assertEqual(obligation_totals(self.member)['posted_payable_total'], Decimal('100.00'))

    def test_same_request_replays_and_changed_payload_is_denied(self):
        self.review()
        values = self.values()
        charge = post_charge(self.member, **values)
        self.assertEqual(post_charge(self.member, **values).pk, charge.pk)
        for changes in ({'reason': 'ΑΛΛΗ ΕΠΙΒΕΒΑΙΩΣΗ'}, {'due_date': DAY + timedelta(days=20)}, {'amount': '99.00'}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                post_charge(self.member, **(values | changes))
        self.assertEqual(Charge.objects.count(), 1)

    def test_new_request_identity_cannot_repeat_the_same_one_off_source(self):
        self.review()
        first = post_charge(self.member, **self.values())
        with self.assertRaisesMessage(ValidationError, str(first.pk)):
            post_charge(self.member, **self.values())
        self.assertEqual(Charge.objects.count(), 1)

    def test_monthly_manual_post_and_future_schedule_share_calendar_source(self):
        self.review(mode='MONTHLY')
        values = self.values(period='2026-01')
        first = post_charge(self.member, **values)
        self.assertEqual(first.source_key, f'agreement:{self.agreement.pk}:month:2026-01')
        self.assertEqual(post_charge(self.member, **values).pk, first.pk)
        with self.assertRaises(ValidationError):
            post_charge(self.member, **(values | {'idempotency_key': 'later-schedule-2026-01'}))
        february = post_charge(self.member, **self.values(period='2026-02', effective_date=DAY.replace(month=2), due_date=DAY.replace(month=2, day=28)))
        self.assertNotEqual(first.pk, february.pk)
        self.assertEqual(Charge.objects.count(), 2)

    def test_partial_first_month_is_explicit_without_automatic_proration(self):
        self.review(mode='MONTHLY')
        charge = post_charge(self.member, **self.values(period='2026-01', amount='37.25', reason='Επιβεβαιωμένο ποσό πρώτου μερικού μήνα'))
        self.assertEqual(charge.amount, Decimal('37.25'))
        with self.assertRaises(ValidationError):
            post_charge(self.member, **self.values(period='2026-02', effective_date=DAY.replace(month=2),
                                                  due_date=DAY.replace(month=2, day=28), amount='37.25'))

    def test_period_future_predated_overprecise_and_mismatched_one_off_amount_denied(self):
        self.review()
        for changes in ({'amount': '99.00'}, {'period': '2026-01'}, {'effective_date': DAY - timedelta(days=1)},
                        {'effective_date': timezone.localdate() + timedelta(days=1)}, {'due_date': DAY - timedelta(days=1)}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                post_charge(self.member, **self.values(**changes))
        for amount in ('0.00', '-1.00', 'NaN', 'Infinity', '1.001', '10000000000.00', True, 1.0):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                post_charge(self.member, **self.values(amount=amount))
        self.assertEqual(Charge.objects.count(), 0)

    def test_charge_form_uses_greek_money_retains_identity_and_does_not_accept_office_authority(self):
        terms = self.review()
        url = reverse('agreement-charge-add', args=[self.agreement.pk])
        page = self.client.get(url, HTTP_ACCEPT_LANGUAGE='en')
        self.assertContains(page, 'Επιβεβαίωση και καταχώριση χρέωσης')
        self.assertEqual(page['Content-Language'], 'el')
        key = str(uuid.uuid4())
        values = {'amount': '1,001', 'effective_date': DAY.isoformat(), 'due_date': (DAY + timedelta(days=10)).isoformat(),
                  'period': '', 'reason': 'ΔΟΚΙΜΑΣΤΙΚΗ ΕΠΙΒΕΒΑΙΩΣΗ', 'posting_key': key, 'terms_revision': terms.revision,
                  'office_id': str(self.foreign.pk), 'entity': self.supplier.pk}
        rejected = self.client.post(url, values)
        self.assertIn('amount', rejected.context['form'].errors)
        self.assertEqual(str(rejected.context['form']['posting_key'].value()), key)
        for period in ('2026-13', 'invalid'):
            bad_month = self.client.post(url, values | {'amount': '100,00', 'period': period})
            self.assertEqual(bad_month.status_code, 200)
            self.assertIn('period', bad_month.context['form'].errors)
        response = self.client.post(url, values | {'amount': '100,00'})
        self.assertEqual(response.status_code, 302)
        charge = Charge.objects.get()
        self.assertEqual((charge.office_id, charge.entity_id), (self.office.pk, self.customer.pk))
        self.assertEqual(self.client.post(url, values | {'amount': '100,00'}).status_code, 302)
        self.assertEqual(Charge.objects.count(), 1)

    def test_foreign_agreement_url_and_service_denied_without_disclosing_charge(self):
        other = Agreement.objects.create(office=self.foreign, entity=Entity.objects.create(office=self.foreign, name='ΞΕΝΗ ΕΤΑΙΡΕΙΑ S22', entity_type='CUSTOMER'),
                                         agreement_type='RECEIVABLE', description='ΞΕΝΟΙ ΟΡΟΙ S22', total_amount='100.00', start_date=DAY)
        url = reverse('agreement-charge-add', args=[other.pk])
        for method in (self.client.get, self.client.post):
            response = method(url)
            self.assertEqual(response.status_code, 404)
            self.assertNotContains(response, 'ΞΕΝΟΙ ΟΡΟΙ S22', status_code=404)
        with self.assertRaises(ValidationError):
            post_charge(self.member, **self.values(agreement_id=other.pk))
        self.assertEqual(Charge.objects.count(), 0)

    def test_exact_retry_after_archive_is_read_only_but_new_work_is_blocked(self):
        self.review()
        values = self.values()
        charge = post_charge(self.member, **values)
        archive_counterparty(self.member, self.customer.pk, version=0, archive=True)
        self.assertEqual(post_charge(self.member, **values).pk, charge.pk)
        with self.assertRaises(ValidationError):
            post_charge(self.member, **self.values())
        self.assertEqual(Charge.objects.count(), 1)

    def test_membership_revocation_blocks_even_completed_request_replay(self):
        self.review()
        values = self.values()
        post_charge(self.member, **values)
        user = get_user_model().objects.get(pk=self.member.pk)
        user.is_active = False
        user.save(update_fields=['is_active'])
        with self.assertRaises(PermissionDenied):
            post_charge(self.member, **values)
        self.assertEqual(Charge.objects.count(), 1)

    def test_stale_review_preserves_first_revision_and_unchanged_source(self):
        self.review()
        self.agreement.refresh_from_db()
        stale = copy.copy(self.agreement)
        latest = self.agreement.terms_versions.first()
        self.agreement.description = 'ΝΕΟΙ ΕΛΕΓΜΕΝΟΙ ΟΡΟΙ'
        save_terms(self.member, self.agreement, billing_mode='ONE_OFF', lifecycle='ACTIVE', expected_revision=latest.revision,
                   reason='ΔΟΚΙΜΑΣΤΙΚΗ ΑΛΛΑΓΗ ΠΡΙΝ ΑΠΟ ΧΡΕΩΣΗ')
        with self.assertRaisesMessage(ValidationError, 'Οι όροι άλλαξαν'):
            save_terms(self.member, stale, billing_mode='ONE_OFF', lifecycle='ACTIVE', expected_revision=latest.revision,
                       reason='ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΙΑ ΥΠΟΒΟΛΗ')
        self.assertEqual(self.agreement.terms_versions.count(), 3)
        charge = post_charge(self.member, **self.values())
        self.assertEqual(charge.source_key, f'agreement:{self.agreement.pk}:one-off')

    def test_posted_terms_cannot_be_reclassified_or_repriced(self):
        self.review()
        charge = post_charge(self.member, **self.values())
        self.agreement.refresh_from_db()
        before = self.agreement.terms_versions.count()
        with self.assertRaises(ValidationError):
            self.review(mode='MONTHLY')
        changed = copy.copy(self.agreement)
        changed.total_amount = Decimal('200.00')
        with self.assertRaises(ValidationError):
            save_terms(self.member, changed, billing_mode='ONE_OFF', lifecycle='ACTIVE', expected_revision=charge.terms.revision,
                       reason='ΑΠΟΠΕΙΡΑ ΑΛΛΑΓΗΣ ΚΑΤΑΧΩΡΙΣΜΕΝΩΝ ΟΡΩΝ')
        self.assertEqual(self.agreement.terms_versions.count(), before)
        charge.refresh_from_db()
        self.assertEqual(charge.amount, Decimal('100.00'))

    def test_old_cash_completed_projection_cannot_change_contract_lifecycle(self):
        self.review()
        post_cash(self.member, idempotency_key=str(uuid.uuid4()), amount='100.00', transaction_date=DAY,
                  transaction_type='INCOME', cash_account=self.account, entity=self.customer, agreement=self.agreement,
                  description='ΔΟΚΙΜΑΣΤΙΚΗ ΠΛΗΡΗΣ ΠΑΛΑΙΑ ΕΙΣΠΡΑΞΗ')
        self.agreement.refresh_from_db()
        self.assertEqual(self.agreement.status, 'COMPLETED')
        self.assertEqual(self.agreement.terms_versions.first().lifecycle, 'ACTIVE')
        self.assertEqual(Charge.objects.count(), 0)

    def test_charge_and_terms_immutable_through_orm_and_sql(self):
        terms = self.review()
        charge = post_charge(self.member, **self.values())
        for action in (lambda: Charge.objects.filter(pk=charge.pk).update(amount='200.00'),
                       lambda: Charge.objects.filter(pk=charge.pk).delete(),
                       lambda: AgreementTermsVersion.objects.filter(pk=terms.pk).update(agreed_amount='200.00'),
                       lambda: AgreementTermsVersion.objects.filter(pk=terms.pk).delete()):
            with self.assertRaises(IntegrityError), transaction.atomic():
                action()
        with self.assertRaises(ValidationError):
            charge.save()
        with self.assertRaises(ValidationError):
            terms.save()

    def test_sql_cannot_forge_source_or_cross_office_or_snapshot_price(self):
        terms = self.review()
        charge = post_charge(self.member, **self.values())
        fields = {field.attname: getattr(charge, field.attname) for field in charge._meta.concrete_fields}
        settings = ('accounting.s18_actor', 'accounting.s18_reason', 'accounting.s18_command',
                    'accounting.s22_billing_mode', 'accounting.s22_lifecycle')
        def context_values():
            with connection.cursor() as cursor:
                cursor.execute('SELECT ' + ','.join('current_setting(%s,true)' for _ in settings), settings)
                return tuple(value or '' for value in cursor.fetchone())
        original_context = context_values()
        for changes in ({'source_key': 'scheduler:another-source'}, {'office_id': self.foreign.pk}, {'amount': Decimal('99.00')},
                        {'entity_id': self.supplier.pk}, {'terms_id': 999999999}):
            values = fields | {'id': uuid.uuid4(), 'key_digest': 'sha256:' + uuid.uuid4().hex * 2} | changes
            columns = list(values)
            with self.assertRaises(IntegrityError) as rejected, transaction.atomic(), terms_context('ONE_OFF', 'ACTIVE'), audit_context(self.member, charge.reason):
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO accounting_charge (' + ','.join(connection.ops.quote_name(name) for name in columns) +
                                   ') VALUES (' + ','.join(['%s'] * len(columns)) + ')', [values[name] for name in columns])
            self.assertEqual(getattr(rejected.exception.__cause__, 'sqlstate', None), '23514')
            self.assertFalse(connection.needs_rollback)
            self.assertEqual(context_values(), original_context)
        # Domain validation does not abort PostgreSQL: ordinary cleanup must
        # still restore both nested contexts without leaking actor authority.
        with self.assertRaises(ValidationError), terms_context('ONE_OFF', 'ACTIVE'), audit_context(self.member, charge.reason):
            raise ValidationError('ΔΟΚΙΜΑΣΤΙΚΗ ΑΚΥΡΩΣΗ ΕΠΙΒΕΒΑΙΩΣΗΣ')
        self.assertEqual(context_values(), original_context)
        self.assertEqual(Charge.objects.count(), 1)

    def test_charge_post_csrf_and_missing_membership_are_denied(self):
        self.review()
        csrf = Client(enforce_csrf_checks=True)
        staff_client_login(csrf, self.member)
        url = reverse('agreement-charge-add', args=[self.agreement.pk])
        self.assertEqual(csrf.post(url, {}).status_code, 403)
        self.assertEqual(Client().get(url).status_code, 302)
        self.assertEqual(Charge.objects.count(), 0)


class ChargeConcurrencyTests(ChargeSupport, TransactionTestCase):
    def setUp(self):
        self.seed()
        self.review()
        if connection.vendor != 'postgresql' or connection.pg_version // 10000 != 17:
            raise AssertionError('S22 requires PostgreSQL 17 independent transactions')

    def race(self, functions):
        barrier, pids, guard = threading.Barrier(len(functions)), [], threading.Lock()
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
                    return ('ok', function(get_user_model().objects.get(pk=self.member.pk)))
                except (ValidationError, PermissionDenied, IntegrityError) as error:
                    return ('denied', type(error).__name__)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(worker, function) for function in functions]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(len(set(pids)), len(functions))
        return results

    def test_independent_same_request_posts_one_charge_and_returns_one_id(self):
        values = self.values()
        result = self.race([lambda actor: post_charge(actor, **values).pk for _ in range(2)])
        self.assertTrue(all(row[0] == 'ok' for row in result))
        self.assertEqual(result[0][1], result[1][1])
        self.assertEqual((Charge.objects.count(), Transaction.objects.count()), (1, 0))

    def test_different_requests_racing_same_source_have_only_one_winner(self):
        first, second = self.values(), self.values()
        result = self.race([lambda actor: post_charge(actor, **first).pk, lambda actor: post_charge(actor, **second).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(Charge.objects.count(), 1)

    def test_same_request_racing_changed_due_date_has_only_one_winner(self):
        first = self.values()
        second = first | {'due_date': DAY + timedelta(days=20)}
        result = self.race([lambda actor: post_charge(actor, **first).pk, lambda actor: post_charge(actor, **second).pk])
        self.assertEqual(sorted(row[0] for row in result), ['denied', 'ok'])
        self.assertEqual(Charge.objects.count(), 1)


class ChargeMigrationTests(TransactionTestCase):
    old = ('accounting', '0014_cash_workspace_guards')
    current = ('accounting', '0016_agreement_charge_guards')

    def migrate(self, target):
        executor = MigrationExecutor(connection)
        executor.migrate([target])
        return executor.loader.project_state([target]).apps

    def setUp(self):
        apps = self.migrate(self.old)
        self.office = apps.get_model('accounting', 'Office').objects.create(name='ΔΟΚΙΜΑΣΤΙΚΗ ΑΝΑΒΑΘΜΙΣΗ S22')
        self.entity = apps.get_model('accounting', 'Entity').objects.create(office_id=self.office.pk, name='ΠΑΛΑΙΟΣ ΠΕΛΑΤΗΣ S22',
                         entity_type='CUSTOMER', is_customer=True, is_supplier=False, legal_kind='UNREVIEWED', vat_key='')
        model = apps.get_model('accounting', 'Agreement')
        self.agreement = model.objects.create(office_id=self.office.pk, entity_id=self.entity.pk, agreement_type='RECEIVABLE',
                                              description='ΠΑΛΑΙΑ ΟΛΟΚΛΗΡΩΜΕΝΗ ΣΥΜΦΩΝΙΑ S22', total_amount='125.37', start_date=DAY, status='COMPLETED')

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_upgrade_preserves_all_old_agreement_fields_and_generates_no_obligation(self):
        self.agreement.refresh_from_db()
        before = {field.attname: getattr(self.agreement, field.attname) for field in self.agreement._meta.concrete_fields}
        self.migrate(self.current)
        agreement = Agreement.objects.get(pk=self.agreement.pk)
        self.assertEqual({name: getattr(agreement, name) for name in before}, before)
        terms = agreement.terms_versions.get()
        self.assertEqual((terms.billing_mode, terms.lifecycle, terms.origin, terms.revision), ('UNREVIEWED', 'UNREVIEWED', 'legacy', 0))
        self.assertEqual(terms.agreed_amount, Decimal('125.37'))
        self.assertIsNone(terms.actor_id)
        self.assertEqual(Charge.objects.count(), 0)
        self.migrate(self.current)
        self.assertEqual(agreement.terms_versions.count(), 1)

    def test_reviewed_history_blocks_unsafe_downgrade(self):
        self.migrate(self.current)
        from .membership import create_accountant_profile
        actor = get_user_model().objects.create_user('s22-migration-operator')
        create_accountant_profile(user_id=actor.pk, office_id=self.office.pk, role='accountant')
        agreement = Agreement.objects.get(pk=self.agreement.pk)
        save_terms(actor, agreement, billing_mode='ONE_OFF', lifecycle='ACTIVE', expected_revision=0,
                   reason='ΔΟΚΙΜΑΣΤΙΚΗ ΕΠΙΒΕΒΑΙΩΣΗ ΠΑΛΑΙΩΝ ΟΡΩΝ')
        with self.assertRaisesMessage(Exception, 'unsafe downgrade denied'):
            self.migrate(self.old)
        self.assertEqual(agreement.terms_versions.count(), 2)
