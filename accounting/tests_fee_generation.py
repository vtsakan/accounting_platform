"""Operator-run PG contracts. Synthetic fixtures; APPLY never executes these."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from decimal import Decimal
import io,json,uuid
from threading import Barrier
from unittest.mock import patch
from django.contrib import admin
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError,close_old_connections,connection,transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase,TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from .tests_fees import FeeFixtures,WHY
from .fee_generation_models import FeeAutomationVersion,FeeGenerationRun
from .fee_generation_services import configure_automation,enqueue_period,complete_period,payload,reconciliation,schedule_due_fees
from .fee_services import create_schedule,next_month
from .charge_services import save_terms
from .correction_services import close_period,correct_charge
from .job_services import execute_job,claim_job,complete_claim,cancel_job
from .membership import change_membership
from .models import Agreement,BackgroundJob,Charge,Transaction


class GenerationFixtures(FeeFixtures):
    @classmethod
    def setUpClass(cls):
        MigrationExecutor(connection).migrate([('accounting','0026_fee_generation_guards')])
        super().setUpClass()

    def setUp(self):
        super().setUp()
        self.publisher=patch('accounting.job_services.dispatch_job',return_value=False)
        self.publisher.start();self.addCleanup(self.publisher.stop)
        self.plan=self.schedule()

    def enqueue(self,**changes):
        return enqueue_period(self.member,**(dict(schedule_id=self.plan.pk,period=self.period,
            request_key=uuid.uuid4(),reason=WHY)|changes))

    def execute(self,**changes):
        job=self.enqueue(**changes);execute_job(job.pk);job.refresh_from_db();return job

    def policy(self,enabled=True,**changes):
        latest=self.plan.automations.first()
        return configure_automation(self.request(),**(dict(schedule_id=self.plan.pk,
            expected_revision=latest.revision if latest else 0,enabled=enabled,password=self.password,reason=WHY)|changes))


@override_settings(BACKGROUND_JOBS_ENABLED=True,FEE_AUTOMATION_ENABLED=True)
class GenerationContracts(GenerationFixtures,TestCase):
    def test_generation_posts_one_obligation_without_cash(self):
        before=self.snapshot();job=self.execute()
        self.assertEqual((job.state,job.fee_run.outcome),('succeeded','generated'))
        self.assertEqual((Charge.objects.count(),Transaction.objects.count()),(1,0));self.assertEqual(self.snapshot(),before)
        self.assertEqual(Charge.objects.get().source_key,f'agreement:{self.monthly.pk}:month:{self.period:%Y-%m}')

    def test_same_request_returns_the_same_durable_intent(self):
        key=uuid.uuid4();first=self.enqueue(request_key=key);second=self.enqueue(request_key=key)
        self.assertEqual(first.pk,second.pk);self.assertEqual(FeeGenerationRun.objects.count(),1)

    def test_changed_request_payload_is_denied_without_writes(self):
        key=uuid.uuid4();self.enqueue(request_key=key)
        with self.assertRaises(ValidationError):self.enqueue(request_key=key,reason='Διαφορετικός ελεγχόμενος λόγος')
        self.assertEqual((BackgroundJob.objects.count(),Charge.objects.count()),(1,0))

    def test_two_distinct_requests_have_one_charge(self):
        one=self.execute();two=self.execute()
        self.assertEqual((one.fee_run.outcome,two.fee_run.outcome),('generated','existing'))
        self.assertEqual(one.fee_run.charge_id,two.fee_run.charge_id);self.assertEqual(Charge.objects.count(),1)

    def test_redelivery_after_committed_effect_is_harmless(self):
        job=self.execute();before=(Charge.objects.count(),job.fee_run.charge_id)
        execute_job(job.pk);execute_job(job.pk)
        self.assertEqual((Charge.objects.count(),job.fee_run.charge_id),before)

    def test_manual_existing_charge_uses_the_same_source(self):
        charge=self.post_month();job=self.execute()
        self.assertEqual((job.fee_run.outcome,job.fee_run.charge_id),('existing',charge.pk))
        self.assertEqual(Charge.objects.count(),1)

    def test_reversal_does_not_reopen_a_consumed_occurrence(self):
        charge=self.post_month()
        correct_charge(self.request(),charge_id=charge.pk,password=self.password,effective_date=timezone.localdate(),reason=WHY,idempotency_key=str(uuid.uuid4()))
        job=self.execute();self.assertEqual(job.fee_run.outcome,'existing');self.assertEqual(Charge.objects.count(),1)

    def test_closed_month_is_explained_and_not_posted(self):
        close_period(self.request(),closed_through=self.period,password=self.password,reason=WHY,idempotency_key=str(uuid.uuid4()))
        job=self.execute();self.assertEqual(job.fee_run.outcome,'closed');self.assertEqual(Charge.objects.count(),0)

    def test_future_month_is_denied_before_intent(self):
        with self.assertRaises(ValidationError):self.enqueue(period=next_month(self.period))
        self.assertEqual(BackgroundJob.objects.count(),0)

    def test_cross_office_schedule_cannot_be_queued(self):
        with self.assertRaises((PermissionDenied,ValidationError)):
            enqueue_period(self.foreign_owner,schedule_id=self.plan.pk,period=self.period,request_key=uuid.uuid4(),reason=WHY)
        self.assertEqual(BackgroundJob.objects.count(),0)

    def test_revocation_after_enqueue_blocks_effect(self):
        job=self.enqueue();change_membership(user_id=self.member.pk,office_id=self.office.pk,role='accountant',is_active=False)
        execute_job(job.pk);job.refresh_from_db();self.assertEqual(job.state,'blocked');self.assertEqual(Charge.objects.count(),0)

    def test_cancelled_delivery_has_no_charge(self):
        job=self.enqueue();cancel_job(self.member,job.pk);execute_job(job.pk)
        job.refresh_from_db();self.assertEqual(job.state,'cancelled');self.assertEqual(Charge.objects.count(),0)

    def test_failure_after_charge_insert_rolls_back_every_business_write(self):
        job=self.enqueue()
        with patch.object(FeeGenerationRun,'save',side_effect=RuntimeError('synthetic failure after charge')):execute_job(job.pk)
        job.refresh_from_db();self.assertEqual(job.state,'failed');self.assertEqual(job.fee_run.outcome,'pending')
        self.assertEqual(Charge.objects.count(),0)

    def test_direct_effect_without_running_lease_is_denied(self):
        job=self.enqueue()
        with self.assertRaises(IntegrityError),transaction.atomic():complete_period(job)
        self.assertEqual(Charge.objects.count(),0)

    def test_completed_receipt_cannot_be_modified_or_deleted(self):
        run=self.execute().fee_run
        with self.assertRaises(IntegrityError),transaction.atomic():FeeGenerationRun.objects.filter(pk=run.pk).update(outcome='pending',charge=None)
        with self.assertRaises(IntegrityError),transaction.atomic():FeeGenerationRun.objects.filter(pk=run.pk).delete()

    def test_explicit_policy_is_required_before_scheduling(self):
        self.assertEqual(schedule_due_fees(),0);self.assertEqual(BackgroundJob.objects.count(),0)

    def test_owner_policy_discovers_current_month_once(self):
        self.policy();self.assertEqual(schedule_due_fees(),1);self.assertEqual(schedule_due_fees(),0)
        job=BackgroundJob.objects.get();execute_job(job.pk);self.assertEqual(Charge.objects.count(),1)

    def test_policy_change_stops_old_queued_work(self):
        self.policy();schedule_due_fees();job=BackgroundJob.objects.get();self.policy(enabled=False)
        execute_job(job.pk);self.assertEqual(job.fee_run.outcome,'superseded');self.assertEqual(Charge.objects.count(),0)

    def test_accountant_cannot_enable_automation(self):
        with self.assertRaises(PermissionDenied):configure_automation(self.request(self.member),schedule_id=self.plan.pk,
            expected_revision=0,enabled=True,password=self.password,reason=WHY)
        self.assertEqual(FeeAutomationVersion.objects.count(),0)

    def test_owner_password_and_recent_mfa_are_required(self):
        with self.assertRaises(ValidationError):self.policy(password='')
        self.assertEqual(FeeAutomationVersion.objects.count(),0)

    def test_stale_policy_revision_is_rejected(self):
        self.policy()
        with self.assertRaises(ValidationError):self.policy(expected_revision=0)
        self.assertEqual(FeeAutomationVersion.objects.count(),1)

    def test_policy_history_is_immutable(self):
        policy=self.policy()
        with self.assertRaises(IntegrityError),transaction.atomic():FeeAutomationVersion.objects.filter(pk=policy.pk).update(enabled=False)

    @override_settings(FEE_AUTOMATION_ENABLED=False)
    def test_global_automation_switch_prevents_discovery(self):
        self.policy();self.assertEqual(schedule_due_fees(),0);self.assertEqual(BackgroundJob.objects.count(),0)

    def test_manual_generation_does_not_require_auto_policy(self):
        with override_settings(FEE_AUTOMATION_ENABLED=False):job=self.execute()
        self.assertEqual(job.fee_run.outcome,'generated')

    def test_reconciliation_is_read_only_and_office_scoped(self):
        self.execute();before=(BackgroundJob.objects.count(),Charge.objects.count(),Transaction.objects.count())
        result=reconciliation(self.member,period=self.period)
        self.assertEqual((result['posted_gross'],result['cash_created']),(Decimal('100.00'),'0.00'))
        self.assertEqual(reconciliation(self.foreign_owner,period=self.period)['rows'],[])
        self.assertEqual((BackgroundJob.objects.count(),Charge.objects.count(),Transaction.objects.count()),before)

    def test_cli_defaults_to_dry_run_without_business_writes(self):
        output=io.StringIO();call_command('generate_fees',user_id=self.member.pk,office_id=self.office.pk,stdout=output)
        self.assertTrue(json.loads(output.getvalue())['dry_run']);self.assertEqual((Charge.objects.count(),BackgroundJob.objects.count()),(0,0))

    def test_cli_requires_explicit_reason_and_request_identity(self):
        with self.assertRaises(CommandError):call_command('generate_fees','run',user_id=self.member.pk,office_id=self.office.pk,stdout=io.StringIO())
        self.assertEqual(BackgroundJob.objects.count(),0)

    def test_cli_rejects_a_foreign_expected_office(self):
        with self.assertRaises(CommandError):call_command('generate_fees',user_id=self.member.pk,office_id=self.foreign.pk,stdout=io.StringIO())

    def test_invalid_payload_types_are_rejected(self):
        base={'schedule':str(self.plan.pk),'period':self.period.strftime('%Y-%m'),'automation':None,'reason':WHY}
        for change in ({'automation':True},{'period':'2026-13'},{'office':self.office.pk},{'schedule':'invalid'}):
            with self.subTest(change=change),self.assertRaises(ValidationError):payload(base|change)

    def test_generation_records_are_not_generic_admin_models(self):
        self.assertNotIn(FeeGenerationRun,admin.site._registry);self.assertNotIn(FeeAutomationVersion,admin.site._registry)

    def test_greek_reconciliation_get_is_private_and_read_only(self):
        client=self.client_for(self.member);response=client.get(reverse('fee-reconciliation'))
        self.assertContains(response,'Συμφωνία μηνιαίων χρεώσεων');self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual((Charge.objects.count(),BackgroundJob.objects.count()),(0,0))

    def test_reviewed_catchup_across_year_boundary_uses_distinct_sources(self):
        # Two explicit past calendar months, independent of today's day/month.
        first=date(timezone.localdate().year-1,12,1)
        agreement=Agreement(entity=self.customer,agreement_type='RECEIVABLE',description='Ελεγμένη αναπλήρωση',total_amount='100.00',start_date=first)
        save_terms(self.member,agreement,billing_mode='MONTHLY',lifecycle='ACTIVE',reason=WHY)
        schedule=create_schedule(self.member,agreement_id=agreement.pk,start_period=first,reason=WHY)
        for period in (first,next_month(first)):
            job=self.enqueue(schedule_id=schedule.pk,period=period);execute_job(job.pk)
        charges=Charge.objects.filter(agreement=agreement)
        self.assertEqual(charges.count(),2);self.assertEqual(len(set(charges.values_list('source_key',flat=True))),2)
        self.assertEqual(Transaction.objects.count(),0)


@override_settings(BACKGROUND_JOBS_ENABLED=True,FEE_AUTOMATION_ENABLED=True)
class GenerationConcurrency(GenerationFixtures,TransactionTestCase):
    def test_concurrent_requests_create_one_canonical_obligation(self):
        barrier=Barrier(2)
        def work():
            close_old_connections()
            try:
                barrier.wait(timeout=10);job=self.enqueue();execute_job(job.pk);return str(job.pk)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(work) for _ in range(2)];ids=[f.result(timeout=40) for f in futures]
        self.assertEqual(Charge.objects.count(),1);self.assertEqual(FeeGenerationRun.objects.filter(job_id__in=ids).count(),2)
        self.assertEqual(Transaction.objects.count(),0)

    def test_old_lease_cannot_complete_after_recovery(self):
        job=self.enqueue();old=claim_job(job.pk)
        BackgroundJob.objects.filter(pk=job.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        from .job_services import recover_jobs
        recover_jobs(publisher=lambda *a,**k:None);fresh=claim_job(job.pk)
        complete_claim(job.pk,old);self.assertEqual(Charge.objects.count(),0)
        complete_claim(job.pk,fresh);self.assertEqual(Charge.objects.count(),1)
