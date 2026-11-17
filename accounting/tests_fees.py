"""Operator-run PostgreSQL S27 contracts; never executed by APPLY."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
import time
import uuid
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from .charge_services import post_charge, save_terms
from .correction_services import amend_agreement, correct_charge, close_period
from .fee_forms import ScheduleForm
from .fee_models import ServiceItem, ServicePrice, FeeSchedule, FeeScheduleVersion
from .fee_services import create_schedule, save_price, price_on, change_schedule, next_month, preview
from .finance_services import audit_context
from .membership import create_accountant_profile, change_membership
from .models import Agreement, Charge, Transaction
from .tests_finance_posting import Fixtures
from .tests_auth_support import staff_client_login

WHY = 'Επιβεβαίωση συνθετικών αμοιβών S27'


class FeeFixtures(Fixtures):
    def setUp(self):
        super().setUp()
        self.seed()
        self.period = timezone.localdate().replace(day=1)
        self.monthly = Agreement(entity=self.customer, agreement_type='RECEIVABLE', description='Μηνιαία λογιστική υποστήριξη',
            total_amount='100.00', start_date=self.period)
        save_terms(self.member, self.monthly, billing_mode='MONTHLY', lifecycle='ACTIVE', reason=WHY)
        self.foreign_owner = get_user_model().objects.create_user('s27-foreign')
        create_accountant_profile(user_id=self.foreign_owner.pk, office_id=self.foreign.pk, role='owner')

    def price(self, **changes):
        values = dict(code='S27-SERVICE', description='Λογιστική υποστήριξη', amount='100.00',
            effective_date=timezone.localdate(), reason=WHY)
        values.update(changes)
        return save_price(self.owner, **values)

    def schedule(self, **changes):
        values = dict(agreement_id=self.monthly.pk, start_period=self.period, reason=WHY)
        values.update(changes)
        return create_schedule(self.member, **values)

    def client_for(self, user):
        client = Client();staff_client_login(client, user)
        return client

    def amend_rate(self, period, amount='150.00', description='Μελλοντική μηνιαία αμοιβή'):
        return amend_agreement(self.request(), agreement_id=self.monthly.pk,
            expected_revision=self.monthly.terms_versions.first().revision, description=description, amount=amount,
            lifecycle='ACTIVE', password=self.password, effective_date=period, reason=WHY, idempotency_key=str(uuid.uuid4()))

    def change(self, schedule, **changes):
        values = dict(schedule_id=schedule.pk, expected_revision=schedule.versions.first().revision,
            effective_period=next_month(self.period), due_day=20, password=self.password, reason=WHY)
        values.update(changes)
        return change_schedule(self.request(), **values)

    def post_month(self):
        return post_charge(self.member, agreement_id=self.monthly.pk,
            terms_revision=self.monthly.terms_versions.first().revision, amount='100.00',
            effective_date=self.period, due_date=self.period.replace(day=15), period=self.period,
            reason=WHY, idempotency_key=str(uuid.uuid4()))


class FeeContracts(FeeFixtures, TestCase):
    def test_owner_price_change_retains_old_snapshot(self):
        first = self.price()
        new = self.price(service_id=first.service_id, expected_revision=1, amount='125.00', description='Νέα περιγραφή')
        first.refresh_from_db()
        self.assertEqual((first.amount, first.description), (Decimal('100.00'), 'Λογιστική υποστήριξη'))
        self.assertEqual(price_on(first.service).pk, new.pk)

    def test_accountant_can_read_but_cannot_maintain_prices(self):
        first = self.price()
        client = self.client_for(self.member)
        self.assertEqual(client.get(reverse('service-catalogue')).status_code, 200)
        self.assertEqual(client.get(reverse('service-price-edit', args=[first.service_id])).status_code, 403)
        with self.assertRaises(PermissionDenied):
            save_price(self.member, code='FORGED', description='Δοκιμή', amount='1.00', effective_date=timezone.localdate(), reason=WHY)

    def test_cross_office_price_service_denied(self):
        row = self.price()
        with self.assertRaises(ValidationError):
            save_price(self.foreign_owner, service_id=row.service_id, expected_revision=1, description='Ξένη αλλαγή',
                amount='2.00', effective_date=timezone.localdate(), reason=WHY)

    def test_price_rejects_overprecision_zero_negative_and_bool(self):
        for amount in ('1.001','0.00','-2.00',True):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):self.price(amount=amount)
        self.assertEqual(ServiceItem.objects.count(), 0)

    def test_stale_price_revision_has_no_writes(self):
        row = self.price()
        with self.assertRaises(ValidationError):self.price(service_id=row.service_id, expected_revision=0)
        self.assertEqual(ServicePrice.objects.count(), 1)

    def test_duplicate_service_code_has_no_extra_version(self):
        self.price()
        with self.assertRaises(ValidationError):self.price()
        self.assertEqual((ServiceItem.objects.count(), ServicePrice.objects.count()), (1,1))

    def test_future_catalogue_price_applies_only_from_effective_day(self):
        row = self.price();day = timezone.localdate()+timedelta(days=3)
        later = self.price(service_id=row.service_id, expected_revision=1, effective_date=day, amount='120.00')
        self.assertEqual(price_on(row.service).pk, row.pk)
        self.assertEqual(price_on(row.service, day).pk, later.pk)

    def test_catalogue_price_cannot_be_backdated_or_reordered(self):
        row = self.price(effective_date=timezone.localdate()+timedelta(days=5))
        for day in (timezone.localdate()-timedelta(days=1), timezone.localdate()):
            with self.subTest(day=day), self.assertRaises(ValidationError):
                self.price(service_id=row.service_id, expected_revision=1, effective_date=day)

    def test_catalogue_retirement_preserves_quote(self):
        row = self.price()
        self.price(service_id=row.service_id, expected_revision=1, is_active=False)
        self.assertFalse(price_on(row.service).is_active)
        self.assertEqual(row.amount, Decimal('100.00'))

    def test_create_schedule_writes_configuration_without_charges_or_cash(self):
        before = (Charge.objects.count(), Transaction.objects.count())
        schedule = self.schedule()
        self.assertEqual(schedule.versions.first().terms_snapshot.agreed_amount, Decimal('100.00'))
        self.assertEqual((Charge.objects.count(), Transaction.objects.count()), before)

    def test_one_schedule_per_agreement_prevents_overlap_and_replay(self):
        self.schedule()
        for period in (self.period, next_month(self.period)):
            with self.subTest(period=period), self.assertRaises(ValidationError):self.schedule(start_period=period)
        self.assertEqual((FeeSchedule.objects.count(), FeeScheduleVersion.objects.count()), (1,1))

    def test_cross_office_schedule_reference_denied(self):
        with self.assertRaises(ValidationError):
            create_schedule(self.foreign_owner, agreement_id=self.monthly.pk, start_period=self.period, reason=WHY)

    def test_unreviewed_and_nonmonthly_agreements_rejected(self):
        with self.assertRaises(ValidationError):self.schedule(agreement_id=self.agreement.pk)

    def test_archived_client_cannot_receive_new_schedule(self):
        from .counterparty_services import archive_counterparty
        self.customer.refresh_from_db()
        archive_counterparty(self.member, self.customer.pk, version=self.customer.record_version, archive=True)
        with self.assertRaises(ValidationError):self.schedule()

    def test_due_rule_requires_day_one_to_twenty_eight(self):
        for day in (0,29,True):
            with self.subTest(day=day), self.assertRaises(ValidationError):self.schedule(due_day=day)

    def test_end_period_cannot_precede_start(self):
        with self.assertRaises(ValidationError):self.schedule(start_period=next_month(self.period), end_period=self.period)

    def test_schedule_cannot_start_before_agreement(self):
        with self.assertRaises(ValidationError):self.schedule(start_period=self.period-timedelta(days=1))

    def test_first_partial_month_requires_reviewed_amount(self):
        agreement = Agreement(entity=self.customer, agreement_type='RECEIVABLE', description='Μερικός πρώτος μήνας',
            total_amount='100.00', start_date=self.period.replace(day=20))
        save_terms(self.member, agreement, billing_mode='MONTHLY', lifecycle='ACTIVE', reason=WHY)
        with self.assertRaises(ValidationError):self.schedule(agreement_id=agreement.pk, due_next_month=True)
        schedule = self.schedule(agreement_id=agreement.pk, first_amount='45.00', due_next_month=True)
        rows = preview(self.member, schedule.pk, start_period=self.period, months=2)
        self.assertEqual([row['amount'] for row in rows], [Decimal('45.00'), Decimal('100.00')])
        self.assertEqual(rows[0]['effective_date'], agreement.start_date)

    def test_partial_first_due_cannot_precede_start(self):
        agreement = Agreement(entity=self.customer, agreement_type='RECEIVABLE', description='Μερικός πρώτος μήνας',
            total_amount='100.00', start_date=self.period.replace(day=20))
        save_terms(self.member, agreement, billing_mode='MONTHLY', lifecycle='ACTIVE', reason=WHY)
        with self.assertRaises(ValidationError):self.schedule(agreement_id=agreement.pk, first_amount='45.00', due_day=15)

    def test_full_month_cannot_use_partial_first_override(self):
        with self.assertRaises(ValidationError):self.schedule(first_amount='1.00')

    def test_future_terms_rate_changes_only_stated_period(self):
        schedule = self.schedule();future = next_month(self.period)
        self.amend_rate(future)
        rows = preview(self.member, schedule.pk, start_period=self.period, months=2)
        self.assertEqual([r['amount'] for r in rows], [Decimal('100.00'), Decimal('150.00')])
        self.assertNotEqual(rows[0]['terms_revision'], rows[1]['terms_revision'])

    def test_changed_catalogue_and_future_terms_never_rewrite_posted_charge(self):
        price = self.price();schedule = self.schedule();charge = self.post_month()
        self.price(service_id=price.service_id, expected_revision=1, amount='999.00', description='Νέα προσφορά')
        self.amend_rate(next_month(self.period))
        charge.refresh_from_db()
        row = preview(self.member, schedule.pk, start_period=self.period, months=1)[0]
        self.assertEqual((charge.amount, row['amount'], row['due_date']), (Decimal('100.00'), Decimal('100.00'), charge.due_date))
        self.assertEqual(row['state'], 'posted')
        self.assertEqual(row['description'], charge.description)

    def test_reversed_charge_identity_is_not_offered_again(self):
        schedule = self.schedule();charge = self.post_month()
        correct_charge(self.request(), charge_id=charge.pk, password=self.password, effective_date=timezone.localdate(),
            reason=WHY, idempotency_key=str(uuid.uuid4()))
        row = preview(self.member, schedule.pk, start_period=self.period, months=1)[0]
        self.assertEqual(row['state'], 'reversed')
        self.assertEqual(row['source_key'], charge.source_key)

    def test_preview_preserves_canonical_source_across_plan_versions(self):
        schedule = self.schedule();future = next_month(self.period)
        before = preview(self.member, schedule.pk, start_period=future, months=1)[0]
        self.change(schedule)
        after = preview(self.member, schedule.pk, start_period=future, months=1)[0]
        self.assertEqual(before['source_key'], after['source_key'])
        self.assertNotEqual(before['due_date'], after['due_date'])

    def test_cancellation_stops_future_plan_and_keeps_posted_debt(self):
        schedule = self.schedule();charge = self.post_month()
        self.change(schedule, cancelled=True)
        rows = preview(self.member, schedule.pk, start_period=self.period, months=2)
        self.assertEqual([r['state'] for r in rows], ['posted','outside'])
        self.assertTrue(Charge.objects.filter(pk=charge.pk, amount='100.00').exists())

    def test_cancelled_plan_cannot_be_reactivated(self):
        schedule = self.schedule();self.change(schedule, cancelled=True)
        with self.assertRaises(ValidationError):self.change(schedule, effective_period=next_month(next_month(self.period)))

    def test_accountant_cannot_change_existing_plan(self):
        schedule = self.schedule()
        with self.assertRaises(PermissionDenied):
            change_schedule(self.request(self.member), schedule_id=schedule.pk, expected_revision=1,
                effective_period=next_month(self.period), password=self.password, reason=WHY)

    def test_plan_change_requires_current_password_and_recent_mfa(self):
        schedule = self.schedule()
        with self.assertRaises(ValidationError):self.change(schedule, password=str(uuid.uuid4()))
        request = self.request();request.session['s13_mfa_at'] = 0
        with self.assertRaises(ValidationError):
            change_schedule(request, schedule_id=schedule.pk, expected_revision=1,
                effective_period=next_month(self.period), password=self.password, reason=WHY)
        self.assertEqual(schedule.versions.count(), 1)

    def test_plan_change_rejects_current_period_and_stale_revision(self):
        schedule = self.schedule()
        for values in ({'effective_period':self.period}, {'expected_revision':0}):
            with self.subTest(values=values), self.assertRaises(ValidationError):self.change(schedule, **values)

    def test_preview_end_and_next_month_due_rule(self):
        schedule = self.schedule(end_period=self.period, due_next_month=True, due_day=28)
        rows = preview(self.member, schedule.pk, start_period=self.period, months=2)
        self.assertEqual([r['state'] for r in rows], ['ready','outside'])
        self.assertEqual(rows[0]['due_date'], next_month(self.period).replace(day=28))

    def test_preview_requires_manual_review_for_midmonth_term_change(self):
        schedule = self.schedule();future = next_month(self.period)
        self.amend_rate(future.replace(day=20))
        self.assertEqual(preview(self.member, schedule.pk, start_period=future, months=1)[0]['state'], 'review')

    def test_closed_period_is_visible_not_silently_postable(self):
        schedule = self.schedule()
        close_period(self.request(), closed_through=self.period, password=self.password, reason=WHY, idempotency_key=str(uuid.uuid4()))
        self.assertEqual(preview(self.member, schedule.pk, start_period=self.period, months=1)[0]['state'], 'closed')

    def test_preview_is_read_only_and_bounded(self):
        schedule = self.schedule();before = (FeeScheduleVersion.objects.count(), Charge.objects.count(), Transaction.objects.count())
        preview(self.member, schedule.pk, start_period=self.period, months=24)
        self.assertEqual((FeeScheduleVersion.objects.count(), Charge.objects.count(), Transaction.objects.count()), before)
        for count in (0,25,True):
            with self.subTest(count=count), self.assertRaises(ValidationError):preview(self.member, schedule.pk, months=count)

    def test_forms_and_detail_do_not_disclose_other_office(self):
        schedule = self.schedule();form = ScheduleForm(user=self.foreign_owner)
        self.assertFalse(form.fields['agreement'].queryset.filter(pk=self.monthly.pk).exists())
        client = self.client_for(self.foreign_owner)
        self.assertEqual(client.get(reverse('fee-schedule-detail', args=[schedule.pk])).status_code, 404)

    def test_new_models_are_not_exposed_through_generic_admin(self):
        for model in (ServiceItem,ServicePrice,FeeSchedule,FeeScheduleVersion):self.assertNotIn(model,admin.site._registry)

    def test_sql_cannot_retarget_or_delete_configuration(self):
        price = self.price();schedule = self.schedule()
        for queryset, change in [(ServiceItem.objects.filter(pk=price.service_id), {'code':'FORGED'}),
            (ServicePrice.objects.filter(pk=price.pk), {'amount':'1.00'}),
            (FeeSchedule.objects.filter(pk=schedule.pk), {'office_id':self.foreign.pk}),
            (schedule.versions.all(), {'due_day':2})]:
            with self.subTest(change=change), self.assertRaises(IntegrityError), transaction.atomic():queryset.update(**change)
        with self.assertRaises(IntegrityError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('DELETE FROM accounting_serviceprice WHERE id=%s',[price.pk])

    def test_sql_insert_requires_fresh_owner_audit_for_catalogue(self):
        row = self.price()
        with self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.member, WHY):
            ServicePrice.objects.bulk_create([ServicePrice(office=self.office, service=row.service, revision=2,
                description='Ανεπίτρεπτη τιμή', amount='2.00', effective_date=timezone.localdate(), actor=self.member, reason=WHY)])

    def test_sql_cross_office_schedule_version_and_revision_gap_rejected(self):
        schedule = self.schedule();terms = self.monthly.terms_versions.first()
        for office, revision in ((self.foreign,2),(self.office,5)):
            with self.subTest(office=office.pk,revision=revision), self.assertRaises(IntegrityError), transaction.atomic(), audit_context(self.owner, WHY):
                FeeScheduleVersion.objects.bulk_create([FeeScheduleVersion(office=office,schedule=schedule,revision=revision,
                    effective_period=next_month(self.period),due_day=15,terms_snapshot=terms,actor=self.owner,reason=WHY)])

    def test_greek_detail_includes_preview_and_no_mutation_on_get(self):
        schedule = self.schedule();client=self.client_for(self.member)
        before=(Charge.objects.count(),FeeScheduleVersion.objects.count())
        response=client.get(reverse('fee-schedule-detail',args=[schedule.pk]),{'months':'2','start_period':self.period.strftime('%Y-%m')},HTTP_ACCEPT_LANGUAGE='en')
        self.assertContains(response,'Προγραμματισμένη')
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual((Charge.objects.count(),FeeScheduleVersion.objects.count()),before)

    def test_catalogue_quote_creates_reviewed_terms_without_charges(self):
        price=self.price();client=self.client_for(self.member)
        response=client.post(reverse('service-agreement-add',args=[price.service_id]),{
            'price_version':price.pk,'entity':self.customer.pk,'agreement_type':'RECEIVABLE','description':price.description,
            'total_amount':'100.00','start_date':self.period.isoformat(),'status':'ACTIVE',
            'billing_mode':'MONTHLY','lifecycle':'ACTIVE','terms_revision':'0','reason':WHY})
        self.assertEqual(response.status_code,302)
        terms=Agreement.objects.order_by('-pk').first().terms_versions.first()
        self.assertEqual((terms.agreed_amount,terms.description),(price.amount,price.description))
        self.assertEqual(Charge.objects.count(),0)


class FeeConcurrency(FeeFixtures, TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        MigrationExecutor(connection).migrate([('accounting','0024_fee_configuration_guards')])
        super().setUpClass()

    def test_concurrent_schedule_creation_has_one_obligation_source(self):
        barrier=Barrier(2)
        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:self.schedule();return 'created'
                except ValidationError:return 'duplicate'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=30) for f in futures),['created','duplicate'])
        self.assertEqual((FeeSchedule.objects.count(),FeeScheduleVersion.objects.count(),Charge.objects.count()),(1,1,0))

    def test_revocation_committed_while_configuration_writer_waits_denies_write(self):
        entered=Event()
        def run():
            close_old_connections()
            try:
                with connection.cursor() as cursor:cursor.execute("SET application_name='s27-revoke-wait'")
                entered.set()
                try:self.schedule();return 'created'
                except PermissionDenied:return 'denied'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                type(self.office).objects.select_for_update().get(pk=self.office.pk)
                future=pool.submit(run);self.assertTrue(entered.wait(timeout=5))
                waiting=False
                for _ in range(100):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name='s27-revoke-wait' AND wait_event_type='Lock')")
                        waiting=cursor.fetchone()[0]
                    if waiting:break
                    time.sleep(.01)
                self.assertTrue(waiting)
                change_membership(user_id=self.member.pk,office_id=self.office.pk,role='accountant',is_active=False)
            self.assertEqual(future.result(timeout=30),'denied')
        self.assertEqual(FeeSchedule.objects.count(),0)
