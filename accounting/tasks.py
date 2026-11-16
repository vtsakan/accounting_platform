"""Broker messages contain one opaque ID; DB services establish authority."""
from core.celery import app


@app.task(name='accounting.run_job', ignore_result=True)
def run_job(job_id):
    from .job_services import execute_job
    execute_job(job_id)


@app.task(name='accounting.recover_jobs', ignore_result=True)
def recover_jobs():
    from .job_services import recover_jobs as recover, worker_pulse
    recover()
    worker_pulse()
