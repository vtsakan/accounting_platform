"""Operator-only Celery harness: kill this synthetic child after committed work."""
import os,re,signal
from django.conf import settings
from redis import Redis
from core.celery import app


def isolated():
    identity=os.environ.get('S28_VERIFY_ID','')
    if not re.fullmatch(r'[a-f0-9]{20}',identity) or settings.DATABASES['default']['NAME']!='s26_'+identity:
        raise RuntimeError('S28 ack probe requires the fresh isolated gate database')


@app.task(name='accounting.s28_ack_probe',ignore_result=True,acks_late=True,reject_on_worker_lost=True)
def commit_then_lose_ack(job_id):
    isolated()
    from accounting.job_services import execute_job
    from accounting.job_models import BackgroundJob
    with Redis.from_url(app.conf.broker_url,socket_timeout=3,socket_connect_timeout=3) as broker:
        deliveries=broker.incr('s28-ack-deliveries:'+str(job_id))
    execute_job(job_id)
    if BackgroundJob.objects.get(pk=job_id).state!='succeeded':raise RuntimeError('Synthetic generation did not commit')
    if deliveries==1:
        os.kill(os.getpid(),signal.SIGKILL)
