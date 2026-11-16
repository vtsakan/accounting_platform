"""Only the operator's fresh labelled S26 database may run these probes."""
import json
import os
import re
import sys
import time
import uuid
import django

django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from accounting.job_models import BackgroundJob, BackgroundPulse, JobProbeEffect, JobState
from accounting.job_services import enqueue_probe, cancel_job, queue_health
from accounting.membership import create_office, create_accountant_profile, change_membership
from accounting.models import Entity
from core.celery import app

identity = os.environ.get('S26_VERIFY_ID', '')
if not re.fullmatch(r'[a-f0-9]{20}', identity) or settings.DATABASES['default']['NAME'] != 's26_' + identity:
    raise SystemExit('S26 probe accepts only its fresh isolated verification database')


def actor():
    return get_user_model().objects.get(username='s26-' + identity)


def entity():
    return Entity.objects.get(name='S26 SYNTHETIC ' + identity)


def wait(job_id, state='succeeded'):
    until = time.monotonic() + 180
    while time.monotonic() < until:
        job = BackgroundJob.objects.get(pk=job_id)
        if job.state == state:
            return job
        if job.state in {'failed', 'blocked', 'cancelled'} and job.state != state:
            raise RuntimeError('Unexpected terminal state: ' + job.state + '/' + job.last_code)
        time.sleep(1)
    raise RuntimeError('Timed out waiting for isolated job: ' + job.state)


action = sys.argv[1]
if action == 'prepare':
    office = create_office(name='S26 SYNTHETIC ' + identity)
    owner = get_user_model().objects.create_user('s26-owner-' + identity)
    user = get_user_model().objects.create_user('s26-' + identity)
    create_accountant_profile(user_id=owner.pk, office_id=office.pk, role='owner')
    create_accountant_profile(user_id=user.pk, office_id=office.pk, role='accountant')
    item = Entity.objects.create(office=office, entity_type='CUSTOMER', is_customer=True, name='S26 SYNTHETIC ' + identity)
    job = enqueue_probe(user, entity_id=item.pk, key=uuid.uuid4(), failures=1)
    result = {'job_id': str(job.pk)}
elif action == 'enqueue':
    job = enqueue_probe(actor(), entity_id=entity().pk, key=uuid.uuid4())
    job.refresh_from_db()
    result = {'job_id': str(job.pk), 'last_code': job.last_code}
elif action == 'wait':
    job = wait(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 'succeeded')
    effects = JobProbeEffect.objects.filter(job=job).count()
    assert effects == (1 if job.state == 'succeeded' else 0)
    result = {'state': job.state, 'attempts': job.attempts, 'effects': effects,
        'seconds': round((timezone.now() - job.created_at).total_seconds(), 3)}
elif action == 'duplicates':
    original = BackgroundJob.objects.get(pk=sys.argv[2])
    for _ in range(4):
        app.send_task('accounting.run_job', args=[str(original.pk)], queue='accounting', ignore_result=True)
    barrier = enqueue_probe(actor(), entity_id=entity().pk, key=uuid.uuid4())
    wait(barrier.pk)
    original.refresh_from_db()
    assert JobProbeEffect.objects.filter(job=original).count() == 1 and original.attempts == 2
    result = {'duplicate_deliveries': 4, 'effect_count': 1, 'barrier_completed': True}
elif action == 'cancel':
    cancel_job(actor(), sys.argv[2])
    result = {'cancelled': True}
elif action == 'revoke':
    user = actor()
    change_membership(user_id=user.pk, office_id=user.accountant_profile.office_id, role='accountant', is_active=False)
    result = {'revoked': True}
elif action == 'scheduler-owner':
    result = {'owner': str(BackgroundPulse.objects.get(service='scheduler').owner)}
elif action == 'health':
    result = queue_health()
elif action == 'final':
    assert not BackgroundJob.objects.exclude(state__in=['succeeded', 'blocked', 'cancelled']).exists()
    assert not JobProbeEffect.objects.exclude(job__state='succeeded').exists()
    result = {'jobs': BackgroundJob.objects.count(), 'effects': JobProbeEffect.objects.count(), 'all_terminal': True}
else:
    raise SystemExit('Unknown isolated S26 probe')
print(json.dumps(result))
