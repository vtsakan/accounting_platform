"""One canonical obligation per agreement/month; never creates cash entries."""
from collections import Counter
from decimal import Decimal
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery, F
from django.utils import timezone
from .capabilities import require_capability
from .charge_services import post_charge, source_identity
from .fee_models import FeeSchedule
from .fee_services import month, next_month, preview
from .fee_generation_models import FeeAutomationVersion, FeeGenerationRun
from .finance_services import audit_context, clean_reason, scoped_lock
from .job_models import BackgroundJob
from .office_access import locked_office

KIND = 'fee-occurrence.v1'


def payload(values):
    if not isinstance(values,dict) or set(values)!={'schedule','period','automation','reason'}:
        raise ValidationError('Μη έγκυρα στοιχεία μηνιαίας εργασίας.')
    try:
        schedule=str(uuid.UUID(values['schedule']))
    except (ValueError,TypeError,AttributeError):
        raise ValidationError('Μη έγκυρο πρόγραμμα.') from None
    automation=values['automation']
    if automation is not None and (type(automation) is not int or automation<1):
        raise ValidationError('Μη έγκυρη έκδοση εξουσιοδότησης.')
    period=month(values['period'])
    return {'schedule':schedule,'period':period.strftime('%Y-%m'),'automation':automation,'reason':clean_reason(values['reason'])}


@transaction.atomic
def configure_automation(request, *, schedule_id, expected_revision, enabled, password, reason):
    office=locked_office(request.user,'finance.amend')
    from .office_services import prove_actor
    prove_actor(request,office,password,'finance.amend')
    schedule=scoped_lock(FeeSchedule,office,schedule_id)
    latest=schedule.automations.first()
    if type(enabled) is not bool or type(expected_revision) is not int or expected_revision!=(latest.revision if latest else 0):
        raise ValidationError('Η εξουσιοδότηση άλλαξε. Ανανεώστε τη σελίδα.')
    reason=clean_reason(reason)
    with audit_context(request.user,reason):
        return FeeAutomationVersion.objects.create(office=office,schedule=schedule,revision=expected_revision+1,
            enabled=enabled,first_period=max(schedule.start_period,timezone.localdate().replace(day=1)),actor=request.user,reason=reason)


@transaction.atomic
def enqueue_period(user, *, schedule_id, period, request_key, reason, automation_id=None):
    """Trusted actor identity; office is always derived from fresh membership."""
    from .job_services import _key, _digest, _event, dispatch_job
    office=locked_office(user,'finance.write')
    if not settings.BACKGROUND_JOBS_ENABLED:
        raise ValidationError('Η εκτέλεση εργασιών παρασκηνίου είναι ανενεργή.')
    schedule=scoped_lock(FeeSchedule,office,schedule_id)
    period=month(period)
    if period>timezone.localdate().replace(day=1):
        raise ValidationError('Δεν δημιουργούνται χρεώσεις μελλοντικού μήνα.')
    if automation_id is not None:
        policy=schedule.automations.first()
        if policy is None or policy.pk!=automation_id or not policy.enabled or policy.actor_id!=user.pk or period<policy.first_period:
            raise ValidationError('Η αυτόματη εξουσιοδότηση δεν είναι πλέον ενεργή.')
    # Existing customers only; archived entities fail the same SQL/job guard.
    entity=schedule.agreement.entity
    data=payload({'schedule':str(schedule.pk),'period':period.strftime('%Y-%m'),'automation':automation_id,'reason':reason})
    key=uuid.uuid5(_key(request_key),str(schedule.pk)+':'+period.isoformat())
    digest=_digest(user.pk,entity.pk,data)
    job=BackgroundJob.objects.filter(office=office,kind=KIND,key=key).first()
    if job:
        if job.actor_id!=user.pk or job.payload_digest!=digest:
            raise ValidationError('Το αίτημα χρησιμοποιήθηκε με διαφορετικά στοιχεία.')
        return job
    job=BackgroundJob.objects.create(office=office,actor=user,entity=entity,kind=KIND,key=key,payload=data,payload_digest=digest)
    FeeGenerationRun.objects.create(job=job,office=office,schedule=schedule,period=period,automation_id=automation_id,
        source_key=source_identity(schedule.agreement_id,'MONTHLY',period))
    _event(job,'accepted')
    transaction.on_commit(lambda:dispatch_job(job.pk),robust=True)
    return job


@transaction.atomic
def complete_period(job):
    """Called only inside S26's office/actor/entity/job lock and lease fence."""
    data=payload(job.payload)
    run=FeeGenerationRun.objects.select_for_update().get(job=job,office_id=job.office_id)
    if (str(run.schedule_id),run.period.strftime('%Y-%m'),run.automation_id)!=(data['schedule'],data['period'],data['automation']):
        raise ValidationError('Η εργασία δεν αντιστοιχεί στο καταγεγραμμένο πρόγραμμα.')
    outcome=None
    if run.automation_id:
        latest=run.schedule.automations.first()
        if (not latest or latest.pk!=run.automation_id or not latest.enabled or latest.actor_id!=job.actor_id or
                require_capability(job.actor,'finance.write').role!='owner'):
            outcome='superseded'
        elif not settings.FEE_AUTOMATION_ENABLED:
            outcome='paused'
    if outcome is None:
        row=preview(job.actor,run.schedule_id,start_period=run.period,months=1)[0]
        if row['state'] in {'posted','reversed'}:
            run.charge_id=row['charge_id'];outcome='existing'
        elif row['effective_date']>timezone.localdate():
            outcome='future'
        elif row['state']!='ready':
            outcome=row['state']
        else:
            charge=post_charge(job.actor,agreement_id=run.schedule.agreement_id,terms_revision=row['terms_revision'],
                amount=row['amount'],effective_date=row['effective_date'],due_date=row['due_date'],period=run.period,
                reason=data['reason'],idempotency_key='s28:'+run.source_key)
            run.charge=charge;outcome='generated'
    run.outcome=outcome
    run.save(update_fields=['outcome','charge'])


def schedule_due_fees(*, limit=100):
    """Current Athens month only. Historical catch-up is an explicit CLI act."""
    if not settings.BACKGROUND_JOBS_ENABLED or not settings.FEE_AUTOMATION_ENABLED:return 0
    if type(limit) is not int or not 1<=limit<=500:raise ValueError('Invalid dispatch bound')
    today=timezone.localdate();period=today.replace(day=1)
    latest=FeeAutomationVersion.objects.filter(schedule_id=OuterRef('schedule_id')).order_by('-revision').values('pk')[:1]
    policies=FeeAutomationVersion.objects.filter(pk=Subquery(latest),enabled=True,first_period__lte=period,
        office__is_active=True,actor__is_active=True,actor__accountant_profile__is_active=True,
        actor__accountant_profile__role='owner',actor__accountant_profile__office_id=F('office_id'),
        schedule__agreement__start_date__lte=today,schedule__agreement__entity__is_archived=False,
        schedule__agreement__entity__is_customer=True).exclude(runs__period=period).order_by('pk')[:limit]
    count=0
    for policy in policies:
        try:
            enqueue_period(policy.actor,schedule_id=policy.schedule_id,period=period,
                request_key=uuid.uuid5(uuid.NAMESPACE_URL,'accounting:s28:automation:'+str(policy.pk)),
                automation_id=policy.pk,reason=policy.reason)
            count+=1
        except (PermissionDenied,ValidationError):
            continue  # A scope or policy change may commit after discovery.
    return count


def reconciliation(user, *, period, schedule_id=None):
    office=require_capability(user,'finance.read').office_id;period=month(period)
    schedules=FeeSchedule.objects.filter(office_id=office).order_by('pk')
    if schedule_id is not None:schedules=schedules.filter(pk=schedule_id)
    rows=[];totals=Counter();gross=Decimal('0.00');reversed_amount=Decimal('0.00')
    for schedule in schedules:
        row=preview(user,schedule.pk,start_period=period,months=1)[0]
        runs=list(FeeGenerationRun.objects.filter(office_id=office,schedule=schedule,period=period)
            .select_related('job').order_by('recorded_at'))
        totals[row['state']]+=1
        if row['state']=='posted':gross+=row['amount']
        if row['state']=='reversed':reversed_amount+=row['amount']
        rows.append({**row,'schedule_id':str(schedule.pk),'runs':[{'job_id':str(r.job_id),'state':r.job.get_state_display(),
            'outcome':r.get_outcome_display(),'code':r.job.last_code} for r in runs]})
    return {'period':period,'office_id':office,'states':dict(totals),'posted_gross':gross,
        'reversed_gross':reversed_amount,'cash_created':'0.00','rows':rows}
