"""Bounded, transactional DB-only adapters with an after-commit durable outbox.

The only S26 adapter is an inert client-scoped probe. Future external effects
must implement their own durable intent/uncertainty protocol before registration.
"""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import logging
import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction, OperationalError
from django.db.models import Count, F
from django.utils import timezone
from .capabilities import require_capability
from .membership import require_office_profile
from .models import Office, Entity
from .job_models import BackgroundJob, BackgroundPulse, JobEvent, JobProbeEffect, JobState

LOG = logging.getLogger(__name__)
KIND = 'client-probe.v1'
CAPABILITY = 'clients.read'
TERMINAL = frozenset({JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED, JobState.BLOCKED})
OWNER = uuid.uuid4()


class RetryableJobError(Exception):
    """Explicit transient adapter failure; exception text is never persisted."""


def _key(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Το αναγνωριστικό εργασίας δεν είναι έγκυρο.') from None


def _payload(value):
    if not isinstance(value, dict) or set(value) != {'failures'} or type(value['failures']) is not int or not 0 <= value['failures'] <= 2:
        raise ValidationError('Τα στοιχεία της δοκιμαστικής εργασίας δεν είναι έγκυρα.')
    return dict(value)


def _digest(actor_id, entity_id, payload):
    data = json.dumps([actor_id, entity_id, payload], sort_keys=True, separators=(',', ':')).encode()
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def _event(job, code):
    JobEvent.objects.create(job=job, office_id=job.office_id, state=job.state, code=code, attempt=job.attempts)
    LOG.info('job=%s correlation=%s state=%s code=%s', job.pk, job.correlation_id, job.state, code)


def _finish(job, state, code):
    job.state, job.last_code = state, code
    job.lease_token = job.lease_until = None
    job.finished_at = timezone.now() if state in TERMINAL else None
    job.updated_at = timezone.now()
    job.save()
    _event(job, code)


@contextmanager
def _locked(job_id):
    """One order shared with revocation: office, actor, entity, then job.

    Untrusted message data supplies only an opaque job ID. Its stored office
    is an expected boundary, never authority. Fresh authority follows the wait.
    """
    with transaction.atomic():
        snapshot = BackgroundJob.objects.filter(pk=_key(job_id)).first()
        if snapshot is None:
            yield None, False
            return
        Office.objects.select_for_update().get(pk=snapshot.office_id)
        user = get_user_model().objects.select_for_update().get(pk=snapshot.actor_id)
        entity = Entity.objects.select_for_update().get(pk=snapshot.entity_id)
        job = BackgroundJob.objects.select_for_update().get(pk=snapshot.pk)
        try:
            profile = require_capability(user, CAPABILITY)
            allowed = (profile.office_id == job.office_id == entity.office_id and not entity.is_archived and job.kind == KIND)
        except PermissionDenied:
            allowed = False
        yield job, allowed


@transaction.atomic
def enqueue_probe(user, *, entity_id, key, failures=0):
    """No actor/office/capability value is accepted from a broker payload."""
    payload = _payload({'failures': failures})
    from .office_access import locked_office
    office = locked_office(user, CAPABILITY)
    try:
        entity = Entity.objects.select_for_update().get(pk=entity_id, office=office, is_archived=False)
    except (Entity.DoesNotExist, ValueError, TypeError):
        raise PermissionDenied('Ο συναλλασσόμενος δεν είναι διαθέσιμος στο γραφείο.') from None
    key, digest = _key(key), _digest(user.pk, entity.pk, payload)
    job = BackgroundJob.objects.filter(office=office, kind=KIND, key=key).first()
    if job is not None:
        if job.payload_digest != digest or job.actor_id != user.pk or job.entity_id != entity.pk:
            raise ValidationError('Το αναγνωριστικό έχει ήδη χρησιμοποιηθεί με διαφορετικά στοιχεία.')
        return job
    job = BackgroundJob.objects.create(office=office, actor=user, entity=entity, kind=KIND, key=key,
        payload=payload, payload_digest=digest)
    _event(job, 'accepted')
    # robust preserves the committed durable intent if broker publication fails.
    transaction.on_commit(lambda: dispatch_job(job.pk), robust=True)
    return job


def jobs_for_user(user):
    profile = require_capability(user, CAPABILITY)
    return BackgroundJob.objects.filter(office_id=profile.office_id)


def cancel_job(user, job_id):
    from .office_access import locked_office
    with transaction.atomic():
        office = locked_office(user, CAPABILITY)
        job = BackgroundJob.objects.select_for_update().filter(pk=_key(job_id), office=office).first()
        if job is None or job.actor_id != user.pk:
            raise PermissionDenied('Δεν έχετε πρόσβαση στην εργασία.')
        if job.state not in TERMINAL:
            # A protected effect holding these locks completes before cancellation.
            _finish(job, JobState.CANCELLED, 'cancelled_by_actor')
        return job


def dispatch_job(job_id, *, publisher=None):
    """Durable redelivery after failed send, lost Redis or lost worker/ack.

    A publish/commit gap may duplicate an ID. The DB effect+success transaction
    and unique source identity make that delivery harmless.
    """
    if not settings.BACKGROUND_JOBS_ENABLED:
        return False
    with transaction.atomic():
        now = timezone.now()
        job = BackgroundJob.objects.select_for_update(skip_locked=True).filter(pk=_key(job_id)).first()
        if job is None or job.state not in {JobState.QUEUED, JobState.RETRY} or job.available_at > now or job.dispatch_after > now:
            return False
        try:
            if publisher is None:
                from core.celery import app
                publisher = app.send_task
            publisher('accounting.run_job', args=[str(job.pk)], task_id=str(job.pk),
                headers={'correlation_id': str(job.correlation_id)}, argsrepr='[<job-id>]', kwargsrepr='{}',
                queue='accounting', ignore_result=True, retry=False)
        except Exception:
            job.last_code = 'broker_unavailable'
            job.dispatch_after = now + timedelta(seconds=min(60, 2 ** min(job.dispatch_tries + 1, 6)))
            job.dispatch_tries += 1
            job.updated_at = now
            job.save()
            _event(job, 'broker_unavailable')
            return False
        job.dispatched_at = now
        job.dispatch_after = now + timedelta(seconds=settings.BACKGROUND_REDELIVERY_SECONDS)
        job.dispatch_tries += 1
        job.last_code = ''
        job.updated_at = now
        job.save()
        return True


def recover_jobs(*, publisher=None, limit=100):
    """Can also be called directly when the broker/scheduler is unavailable."""
    now = timezone.now()
    expired = list(BackgroundJob.objects.filter(state=JobState.RUNNING, lease_until__lte=now)
        .order_by('lease_until').values_list('pk', flat=True)[:limit])
    for key in expired:
        with _locked(key) as (job, allowed):
            if job is None or job.state != JobState.RUNNING or job.lease_until > timezone.now():
                continue
            if not allowed:
                _finish(job, JobState.BLOCKED, 'authority_revoked')
            elif job.attempts >= job.max_attempts:
                _finish(job, JobState.FAILED, 'retry_exhausted')
            else:
                job.available_at = job.dispatch_after = timezone.now()
                _finish(job, JobState.RETRY, 'worker_lost')
    keys = list(BackgroundJob.objects.filter(state__in=[JobState.QUEUED, JobState.RETRY], available_at__lte=timezone.now(),
        dispatch_after__lte=timezone.now()).order_by('dispatch_after').values_list('pk', flat=True)[:limit])
    return sum(dispatch_job(key, publisher=publisher) for key in keys)


def claim_job(job_id):
    if not settings.BACKGROUND_JOBS_ENABLED:
        return None
    with _locked(job_id) as (job, allowed):
        if job is None or job.state in TERMINAL or job.state == JobState.RUNNING or job.available_at > timezone.now():
            return None
        if not allowed:
            _finish(job, JobState.BLOCKED, 'authority_revoked')
            return None
        if job.attempts >= job.max_attempts:
            _finish(job, JobState.FAILED, 'retry_exhausted')
            return None
        job.state, job.attempts = JobState.RUNNING, job.attempts + 1
        job.lease_token = uuid.uuid4()
        job.lease_until = timezone.now() + timedelta(seconds=settings.BACKGROUND_LEASE_SECONDS)
        job.updated_at = timezone.now()
        job.save()
        _event(job, 'started')
        return job.lease_token


def _probe(job):
    if job.attempts <= _payload(job.payload)['failures']:
        raise RetryableJobError()
    JobProbeEffect.objects.get_or_create(job=job, defaults={
        'office_id': job.office_id, 'actor_id': job.actor_id, 'entity_id': job.entity_id})


def complete_claim(job_id, lease_token):
    """Effect and terminal receipt commit together under fresh authority locks."""
    try:
        with _locked(job_id) as (job, allowed):
            if job is None or job.state != JobState.RUNNING or job.lease_token != lease_token:
                return
            if not allowed:
                _finish(job, JobState.BLOCKED, 'authority_revoked')
                return
            if job.lease_until <= timezone.now():
                return  # Recovery fences this old claimant with a fresh token.
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('accounting.s26_job',%s,true),set_config('accounting.s26_lease',%s,true)",
                    [str(job.pk), str(lease_token)])
            _probe(job)
            _finish(job, JobState.SUCCEEDED, 'completed')
    except Exception as error:
        # Never persist exception messages, payloads, credentials or tracebacks.
        LOG.warning('job=%s failure_type=%s', job_id, type(error).__name__)
        transient = isinstance(error, (RetryableJobError, OperationalError))
        with _locked(job_id) as (job, allowed):
            if job is None or job.state != JobState.RUNNING or job.lease_token != lease_token:
                return
            if not allowed:
                _finish(job, JobState.BLOCKED, 'authority_revoked')
            elif transient and job.attempts < job.max_attempts:
                job.available_at = job.dispatch_after = timezone.now() + timedelta(seconds=2 ** job.attempts)
                _finish(job, JobState.RETRY, 'transient_failure')
            else:
                _finish(job, JobState.FAILED, 'retry_exhausted' if transient else 'execution_failed')


def execute_job(job_id):
    lease = claim_job(job_id)
    if lease is not None:
        complete_claim(job_id, lease)
    worker_pulse()


def worker_pulse():
    BackgroundPulse.objects.update_or_create(service='worker', defaults={'owner': OWNER, 'last_seen_at': timezone.now()})


def queue_health(*, broker_probe=None):
    """Operator-only, data-free operational view; not a public readiness route."""
    now = timezone.now()
    from core.celery import app
    try:
        if broker_probe is None:
            from redis import Redis
            with Redis.from_url(app.conf.broker_url, socket_timeout=2, socket_connect_timeout=2) as client:
                broker = bool(client.ping())
        else:
            broker = bool(broker_probe())
    except Exception:
        broker = False
    pulses = {p.service: (now - p.last_seen_at).total_seconds() < 45 for p in BackgroundPulse.objects.all()}
    counts = {r['state']: r['count'] for r in BackgroundJob.objects.values('state').annotate(count=Count('pk'))}
    due = BackgroundJob.objects.filter(state__in=[JobState.QUEUED, JobState.RETRY], available_at__lte=now)
    oldest = due.order_by('available_at').values_list('available_at', flat=True).first()
    stale = BackgroundJob.objects.filter(state=JobState.RUNNING, lease_until__lte=now).count()
    overdue = oldest is not None and (now - oldest).total_seconds() > 120
    healthy = settings.BACKGROUND_JOBS_ENABLED and broker and all(pulses.get(k, False) for k in ('worker', 'scheduler')) and not stale and not overdue
    return {'status': 'ok' if healthy else 'unavailable', 'broker': broker,
        'worker': pulses.get('worker', False), 'scheduler': pulses.get('scheduler', False),
        'states': counts, 'expired_leases': stale, 'oldest_due_seconds': max(0, int((now - oldest).total_seconds())) if oldest else 0}
