"""S26 operator-executed PostgreSQL contracts. Never executed by APPLY."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch
import json
import secrets
import time
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from .schema_test_support import restore_current_test_schema
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from core.redaction import redact_text
from .job_models import BackgroundJob, BackgroundPulse, JobEvent, JobProbeEffect, JobState
from .job_services import (enqueue_probe, execute_job, claim_job, complete_claim, cancel_job,
    jobs_for_user, dispatch_job, recover_jobs, queue_health, RetryableJobError)
from .membership import create_accountant_profile, change_membership
from .models import Office, Entity

A = '00000000-0000-4000-8000-00000000000a'
B = '00000000-0000-4000-8000-00000000000b'


class JobFixtures:
    fixtures = ['s11_offices']

    def setUp(self):
        super().setUp()
        self.owner = get_user_model().objects.create_user('s26-owner')
        self.actor = get_user_model().objects.create_user('s26-actor')
        self.foreign = get_user_model().objects.create_user('s26-other')
        for user, office, role in ((self.owner, A, 'owner'), (self.actor, A, 'accountant'), (self.foreign, B, 'owner')):
            create_accountant_profile(user_id=user.pk, office_id=office, role=role)
        self.entity = Entity.objects.create(office_id=A, entity_type='CUSTOMER', is_customer=True, name='ΔΟΚΙΜΗ S26')
        self.other = Entity.objects.create(office_id=B, entity_type='CUSTOMER', is_customer=True, name='ΔΟΚΙΜΗ ΑΛΛΟΥ ΓΡΑΦΕΙΟΥ')
        publish = patch('core.celery.app.send_task')
        publish.start()
        self.addCleanup(publish.stop)

    def enqueue(self, **changes):
        values = dict(entity_id=self.entity.pk, key=uuid.uuid4(), failures=0)
        values.update(changes)
        return enqueue_probe(self.actor, **values)

    def due(self, job):
        BackgroundJob.objects.filter(pk=job.pk).update(available_at=timezone.now() - timedelta(seconds=1),
            dispatch_after=timezone.now() - timedelta(seconds=1))


@override_settings(BACKGROUND_JOBS_ENABLED=True)
class BackgroundJobContracts(JobFixtures, TestCase):
    def test_exact_enqueue_replay_retains_one_intent_and_event(self):
        key = uuid.uuid4()
        job = self.enqueue(key=key)
        self.assertEqual(self.enqueue(key=key).pk, job.pk)
        self.assertEqual(BackgroundJob.objects.count(), 1)
        self.assertEqual(job.events.count(), 1)

    def test_same_key_changed_payload_is_rejected_without_writes(self):
        key = uuid.uuid4()
        self.enqueue(key=key)
        with self.assertRaises(ValidationError):
            self.enqueue(key=key, failures=1)
        self.assertEqual(BackgroundJob.objects.count(), 1)
        self.assertEqual(JobEvent.objects.count(), 1)

    def test_cross_office_enqueue_denied_before_intent(self):
        with self.assertRaises(PermissionDenied):
            self.enqueue(entity_id=self.other.pk)
        self.assertFalse(BackgroundJob.objects.exists())

    def test_untrusted_payloads_are_not_executable(self):
        for failures in (True, -1, 3, '1', {'unexpected': 'field'}):
            with self.subTest(value=failures), self.assertRaises(ValidationError):
                self.enqueue(failures=failures)
        self.assertFalse(BackgroundJob.objects.exists())

    def test_dispatch_runs_only_after_commit(self):
        with patch('accounting.job_services.dispatch_job') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                job = self.enqueue()
                dispatch.assert_not_called()
            dispatch.assert_called_once_with(job.pk)

    def test_outer_rollback_removes_intent_and_after_commit_callback(self):
        with patch('accounting.job_services.dispatch_job') as dispatch:
            with self.captureOnCommitCallbacks(execute=True):
                with self.assertRaises(RuntimeError), transaction.atomic():
                    self.enqueue()
                    raise RuntimeError('rollback')
            dispatch.assert_not_called()
        self.assertFalse(BackgroundJob.objects.exists())

    def test_duplicate_deliveries_have_one_db_effect(self):
        job = self.enqueue()
        execute_job(str(job.pk))
        events = job.events.count()
        execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts), (JobState.SUCCEEDED, 1))
        self.assertEqual(JobProbeEffect.objects.filter(job=job).count(), 1)
        self.assertEqual(job.events.count(), events)

    def test_transient_retry_uses_same_identity_and_backoff(self):
        job = self.enqueue(failures=1)
        execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts), (JobState.RETRY, 1))
        self.assertFalse(JobProbeEffect.objects.exists())
        execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.attempts, 1)
        self.due(job)
        execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts), (JobState.SUCCEEDED, 2))
        self.assertEqual(JobProbeEffect.objects.count(), 1)

    def test_attempts_are_bounded_and_exhaustion_is_visible(self):
        job = self.enqueue()
        with patch('accounting.job_services._probe', side_effect=RetryableJobError()):
            for _ in range(3):
                self.due(job)
                execute_job(str(job.pk))
        execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts, job.last_code), (JobState.FAILED, 3, 'retry_exhausted'))
        self.assertFalse(JobProbeEffect.objects.exists())

    def test_nontransient_failure_never_retries_or_leaks_exception(self):
        job = self.enqueue()
        with patch('accounting.job_services._probe', side_effect=RuntimeError('password=sensitive-value')):
            execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual((job.state, job.last_code), (JobState.FAILED, 'execution_failed'))
        self.assertNotIn('sensitive-value', json.dumps(list(job.events.values()), default=str))

    def test_failure_after_effect_insert_rolls_back_effect_and_success(self):
        from .job_services import _probe
        job = self.enqueue()
        def crash(item):
            _probe(item)
            raise RetryableJobError('injected after effect')
        with patch('accounting.job_services._probe', side_effect=crash):
            execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.state, JobState.RETRY)
        self.assertFalse(JobProbeEffect.objects.exists())
        self.assertFalse(job.events.filter(state=JobState.SUCCEEDED).exists())

    def test_membership_revoked_between_enqueue_and_run_blocks_effect(self):
        job = self.enqueue()
        change_membership(user_id=self.actor.pk, office_id=A, role='accountant', is_active=False)
        execute_job(str(job.pk))
        job.refresh_from_db()
        self.assertEqual(job.state, JobState.BLOCKED)
        self.assertFalse(JobProbeEffect.objects.exists())

    def test_user_deactivation_after_claim_rechecks_fresh_authority(self):
        job = self.enqueue()
        lease = claim_job(job.pk)
        get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
        complete_claim(job.pk, lease)
        job.refresh_from_db()
        self.assertEqual(job.state, JobState.BLOCKED)
        self.assertFalse(JobProbeEffect.objects.exists())

    def test_office_deactivation_blocks_next_execution(self):
        job = self.enqueue()
        Office.objects.filter(pk=A).update(is_active=False)
        execute_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, JobState.BLOCKED)

    def test_client_archival_after_enqueue_blocks_next_effect(self):
        from .counterparty_services import archive_counterparty
        job = self.enqueue()
        archive_counterparty(self.actor, self.entity.pk, version=self.entity.record_version, archive=True)
        execute_job(job.pk)
        job.refresh_from_db()
        self.assertEqual(job.state, JobState.BLOCKED)
        self.assertFalse(JobProbeEffect.objects.exists())

    def test_cancel_before_execution_prevents_any_effect(self):
        job = self.enqueue()
        cancel_job(self.actor, job.pk)
        execute_job(job.pk)
        self.assertFalse(JobProbeEffect.objects.exists())
        self.assertEqual(BackgroundJob.objects.get(pk=job.pk).state, JobState.CANCELLED)

    def test_cancel_between_claim_and_effect_fences_claim(self):
        job = self.enqueue()
        lease = claim_job(job.pk)
        cancel_job(self.actor, job.pk)
        complete_claim(job.pk, lease)
        self.assertFalse(JobProbeEffect.objects.exists())

    def test_foreign_office_cannot_list_or_cancel_job(self):
        job = self.enqueue()
        self.assertFalse(jobs_for_user(self.foreign).exists())
        with self.assertRaises(PermissionDenied):
            cancel_job(self.foreign, job.pk)
        self.assertEqual(BackgroundJob.objects.get(pk=job.pk).state, JobState.QUEUED)

    def test_same_office_colleague_has_no_implicit_cancellation_grant(self):
        job = self.enqueue()
        with self.assertRaises(PermissionDenied):
            cancel_job(self.owner, job.pk)

    def test_broker_failure_retains_recoverable_intent(self):
        job = self.enqueue()
        def fail(*args, **kwargs):
            raise RuntimeError('broker credentials must not leak')
        self.assertFalse(dispatch_job(job.pk, publisher=fail))
        job.refresh_from_db()
        self.assertEqual((job.state, job.attempts, job.dispatch_tries, job.last_code), (JobState.QUEUED, 0, 1, 'broker_unavailable'))
        self.assertGreater(job.dispatch_after, timezone.now())

    def test_lost_dispatch_recovery_sends_only_opaque_id(self):
        job = self.enqueue()
        with patch('core.celery.app.send_task') as send:
            self.assertEqual(recover_jobs(), 1)
        self.assertEqual(send.call_args.args, ('accounting.run_job',))
        self.assertEqual(send.call_args.kwargs['args'], [str(job.pk)])
        self.assertNotIn('entity', str(send.call_args))
        self.assertEqual(send.call_args.kwargs['headers']['correlation_id'], str(job.correlation_id))

    def test_expired_claim_is_recovered_and_old_token_is_fenced(self):
        job = self.enqueue()
        old = claim_job(job.pk)
        BackgroundJob.objects.filter(pk=job.pk).update(lease_until=timezone.now()-timedelta(seconds=1))
        with patch('core.celery.app.send_task'):
            recover_jobs()
        new = claim_job(job.pk)
        self.assertNotEqual(old, new)
        complete_claim(job.pk, old)
        self.assertFalse(JobProbeEffect.objects.exists())
        complete_claim(job.pk, new)
        self.assertEqual(JobProbeEffect.objects.count(), 1)

    def test_sql_cannot_retarget_identity_or_increase_attempt_limit(self):
        job = self.enqueue()
        for changes in ({'office_id':B}, {'actor_id':self.owner.pk}, {'payload':{'failures':1}}, {'kind':'arbitrary-code'}, {'max_attempts':4}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                BackgroundJob.objects.filter(pk=job.pk).update(**changes)

    def test_sql_success_without_effect_is_rejected(self):
        job = self.enqueue()
        with self.assertRaises(IntegrityError), transaction.atomic():
            BackgroundJob.objects.filter(pk=job.pk).update(state='succeeded', finished_at=timezone.now())

    def test_sql_effect_without_claim_fence_is_rejected(self):
        job = self.enqueue()
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobProbeEffect.objects.create(job=job, office_id=A, actor=self.actor, entity=self.entity)

    def test_sql_events_and_effects_remain_immutable(self):
        job = self.enqueue()
        execute_job(job.pk)
        def delete_job():
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM accounting_backgroundjob WHERE id=%s', [job.pk])
        for operation in (lambda: job.events.update(code='changed'), lambda: job.events.all().delete(),
                lambda: JobProbeEffect.objects.filter(job=job).update(value=2), delete_job):
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()

    def test_database_rejects_cross_office_effect_even_with_matching_fence(self):
        job = self.enqueue()
        token = claim_job(job.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('accounting.s26_job',%s,true),set_config('accounting.s26_lease',%s,true)", [str(job.pk), str(token)])
            JobProbeEffect.objects.create(job=job, office_id=B, actor=self.foreign, entity=self.other)

    def test_health_has_no_client_identifiers_and_detects_missing_components(self):
        self.enqueue()
        result = queue_health(broker_probe=lambda:False)
        self.assertEqual(result['status'], 'unavailable')
        self.assertFalse(result['broker'])
        self.assertNotIn(self.entity.name, json.dumps(result))

    @override_settings(BACKGROUND_JOBS_ENABLED=False)
    def test_disabled_execution_keeps_intent_without_effect(self):
        job = self.enqueue()
        execute_job(job.pk)
        self.assertFalse(dispatch_job(job.pk))
        self.assertFalse(JobProbeEffect.objects.exists())
        self.assertEqual(BackgroundJob.objects.get(pk=job.pk).state, JobState.QUEUED)


@override_settings(BACKGROUND_JOBS_ENABLED=True)
class BackgroundConcurrencyContracts(JobFixtures, TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        # Historical migration contracts intentionally finish at their old leaf.
        # Restore the current discovered schema; preserve historical migration targets.
        restore_current_test_schema()
        super().setUpClass()

    def test_concurrent_delivery_commits_one_effect(self):
        job = self.enqueue()
        barrier = Barrier(2)
        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                execute_job(job.pk)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            for future in futures:
                future.result(timeout=20)
        self.assertEqual(JobProbeEffect.objects.filter(job=job).count(), 1)
        self.assertEqual(BackgroundJob.objects.get(pk=job.pk).attempts, 1)

    def test_revoke_committed_while_worker_waits_blocks_execution(self):
        job = self.enqueue()
        entered = Event()
        def run():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET application_name='s26-revocation-wait'")
                entered.set()
                execute_job(job.pk)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Office.objects.select_for_update().get(pk=A)
                future = pool.submit(run)
                self.assertTrue(entered.wait(timeout=5))
                waiting = False
                for _ in range(100):
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name='s26-revocation-wait' AND wait_event_type='Lock')")
                        waiting = cursor.fetchone()[0]
                    if waiting:
                        break
                    time.sleep(0.01)
                self.assertTrue(waiting, 'Independent worker must be observed waiting on the revocation lock')
                change_membership(user_id=self.actor.pk, office_id=A, role='accountant', is_active=False)
            future.result(timeout=20)
        self.assertEqual(BackgroundJob.objects.get(pk=job.pk).state, JobState.BLOCKED)
        self.assertFalse(JobProbeEffect.objects.exists())

    def test_only_one_scheduler_session_can_own_database(self):
        from core.job_scheduler import SchedulerLease, SchedulerAlreadyRunning
        first = SchedulerLease()
        try:
            first.pulse()
            with self.assertRaises(SchedulerAlreadyRunning):
                SchedulerLease()
        finally:
            first.close()
        replacement = SchedulerLease()
        try:
            replacement.pulse()
            self.assertEqual(BackgroundPulse.objects.get(service='scheduler').owner, replacement.owner)
        finally:
            replacement.close()


class BackgroundConfigurationContracts(SimpleTestCase):
    def test_lazy_scheduler_inspection_does_not_claim_ownership(self):
        from celery import Celery
        from core.job_scheduler import SingletonScheduler
        with patch('core.job_scheduler.SchedulerLease') as acquire:
            scheduler = SingletonScheduler(app=Celery('s26-lazy', set_as_current=False, fixups=[]), lazy=True)
            try:
                acquire.assert_not_called()
                self.assertIsNone(scheduler.lease)
            finally:
                scheduler.close()

    def test_transport_uses_json_no_result_backend_and_late_ack(self):
        self.assertEqual(settings.CELERY_ACCEPT_CONTENT, ['json'])
        self.assertIsNone(settings.CELERY_RESULT_BACKEND)
        self.assertTrue(settings.CELERY_TASK_ACKS_LATE)
        self.assertTrue(settings.CELERY_TASK_REJECT_ON_WORKER_LOST)
        self.assertLess(settings.CELERY_TASK_TIME_LIMIT, settings.BACKGROUND_LEASE_SECONDS)

    def test_broker_credentials_are_masked_in_diagnostics(self):
        marker = secrets.token_urlsafe(24)
        for prefix in ('redis', 'rediss'):
            self.assertNotIn(marker, redact_text(prefix+'://user:'+marker+'@redis:6379/0'))
