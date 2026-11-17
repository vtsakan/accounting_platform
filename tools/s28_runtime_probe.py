"""Only the fresh S28-owned verification database and synthetic Redis broker."""
import json,os,re,secrets,sys,time,uuid
from unittest.mock import patch
import django
django.setup()
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from redis import Redis
from core.celery import app
from accounting.membership import create_office,create_accountant_profile,change_membership
from accounting.models import Entity,Agreement,Charge,Transaction,BackgroundJob
from accounting.charge_services import save_terms
from accounting.fee_services import create_schedule,next_month
from accounting.fee_generation_models import FeeAutomationVersion,FeeGenerationRun
from accounting.fee_generation_services import enqueue_period,reconciliation
from accounting.finance_services import audit_context

identity=os.environ.get('S28_VERIFY_ID','')
if not re.fullmatch(r'[a-f0-9]{20}',identity) or settings.DATABASES['default']['NAME']!='s26_'+identity:
    raise SystemExit('S28 probe accepts only the fresh isolated gate database')
period=timezone.localdate().replace(day=1);reason='Συνθετική επαλήθευση αυτόματης μηνιαίας χρέωσης S28'


def owner():return get_user_model().objects.get(username='s28-owner-'+identity)


def plan(label):
    from accounting.fee_models import FeeSchedule
    return FeeSchedule.objects.get(agreement__description='S28 '+label+' '+identity)


def wait_until(check):
    until=time.monotonic()+150
    while time.monotonic()<until:
        result=check()
        if result:return result
        time.sleep(1)
    raise RuntimeError('S28 synthetic worker did not reach its required receipt')


action=sys.argv[1]
if action=='prepare':
    office=create_office(name='S28 SYNTHETIC '+identity)
    user=get_user_model().objects.create_user('s28-owner-'+identity,password=secrets.token_urlsafe(40))
    create_accountant_profile(user_id=user.pk,office_id=office.pk,role='owner')
    entity=Entity.objects.create(office=office,entity_type='CUSTOMER',is_customer=True,name='S28 SYNTHETIC '+identity)
    plans=[]
    for label in ('automatic','ack'):
        agreement=Agreement(entity=entity,agreement_type='RECEIVABLE',description='S28 '+label+' '+identity,total_amount='100.00',start_date=period)
        save_terms(user,agreement,billing_mode='MONTHLY',lifecycle='ACTIVE',reason=reason)
        plans.append(create_schedule(user,agreement_id=agreement.pk,start_period=period,due_day=28,due_next_month=True,reason=reason))
    # This isolated policy fixture uses fresh owner/audit context; actual password/
    # MFA service denial is covered by the full application contracts.
    with transaction.atomic(),audit_context(user,reason):
        FeeAutomationVersion.objects.create(office=office,schedule=plans[0],revision=1,enabled=True,
            first_period=period,actor=user,reason=reason)
    result={'prepared':True}
elif action=='wait-auto':
    schedule=plan('automatic')
    def automatic():
        run=FeeGenerationRun.objects.filter(schedule=schedule,period=period,outcome='generated',job__state='succeeded').first()
        return {'job_id':str(run.job_id),'charge_id':str(run.charge_id),'scheduler_discovered':True} if run else None
    result=wait_until(automatic)
elif action=='ack-prepare':
    with patch('accounting.job_services.dispatch_job',return_value=False):
        job=enqueue_period(owner(),schedule_id=plan('ack').pk,period=period,request_key=uuid.uuid4(),reason=reason)
    app.send_task('accounting.s28_ack_probe',args=[str(job.pk)],queue='accounting',ignore_result=True,argsrepr='[<job-id>]')
    result={'job_id':str(job.pk)}
elif action=='wait-ack':
    schedule=plan('ack')
    def ack():
        run=FeeGenerationRun.objects.filter(schedule=schedule,outcome='generated',job__state='succeeded').first()
        if run is None:return None
        with Redis.from_url(app.conf.broker_url,socket_timeout=3,socket_connect_timeout=3) as broker:
            deliveries=int(broker.get('s28-ack-deliveries:'+str(run.job_id)) or 0)
        if deliveries<2:return None
        assert Charge.objects.filter(office=run.office,source_key=run.source_key).count()==1
        return {'task_deliveries':deliveries,'charge_count':1,'committed_receipt_survived_child_sigkill':True}
    result=wait_until(ack)
elif action=='final':
    user=owner();office=user.accountant_profile.office_id
    report=reconciliation(user,period=period)
    assert report['states']=={'posted':2} and str(report['posted_gross'])=='200.00'
    assert Charge.objects.filter(office_id=office).count()==2 and Transaction.objects.filter(office_id=office).count()==0
    for schedule in (plan('automatic'),plan('ack')):
        charge=Charge.objects.get(agreement=schedule.agreement,period=period)
        assert charge.due_date==next_month(period).replace(day=28)
    result={'charges':2,'cash_entries':0,'posted_gross':'200.00','following_month_due_dates_matched':True,
        'office_month_reconciled':True}
else:raise SystemExit('Unknown S28 isolated probe')
print(json.dumps(result))
