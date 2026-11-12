"""S18 posting/correction boundary; current agreements are a legacy settlement bridge.

Charges, independent allocations, credit/refunds and dated opening administration
remain their assigned S19/S22–S24 stages. No hidden model-save posting logic.
"""
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
import hashlib,json,uuid
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import connection,transaction
from django.db.models import Case,When,F,Sum,Value,DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from core.redaction import redact_text
from .models import Agreement,CashAccount,Category,Entity,Transaction,FinanceCommand
from .finance_money import money,IMMUTABLE
from .office_access import locked_office


def legacy_settlement(prefix=''):
    return Coalesce(Sum(Case(When(**{prefix+'posting_kind':'REVERSAL'},then=-F(prefix+'amount')),
        default=F(prefix+'amount'),output_field=DecimalField())),Value(Decimal('0.00')),output_field=DecimalField())


def scoped_lock(model,office,key,*,active=False):
    try:
        query=model.objects.select_for_update().filter(office=office)
        if active:
            query=query.filter(is_archived=False) if model is Entity else query.filter(is_active=True)
        return query.get(pk=key)
    except (model.DoesNotExist,ValueError,TypeError):
        if model is Entity and isinstance(key,(int,str)) and str(key).isdigit() and model.objects.filter(pk=key,office=office,is_archived=True).exists():
            from .counterparty_services import ARCHIVED
            raise ValidationError(ARCHIVED) from None
        raise ValidationError('Η συνδεδεμένη εγγραφή δεν είναι διαθέσιμη στο λογιστικό γραφείο.') from None


def clean_reason(value):
    if not isinstance(value,str) or not value.strip() or len(value)>500 or any(ord(c)<32 for c in value):
        raise ValidationError('Απαιτείται σύντομη αιτιολογία χωρίς μη επιτρεπόμενους χαρακτήρες.')
    result=redact_text(value.strip())
    if len(result.replace('[REDACTED]','').strip())<4:
        raise ValidationError('Η αιτιολογία πρέπει να εξηγεί την ενέργεια χωρίς διαπιστευτήρια.')
    return result[:500]


@contextmanager
def audit_context(user,reason,command=None):
    names=('accounting.s18_actor','accounting.s18_reason','accounting.s18_command')
    with connection.cursor() as cursor:
        cursor.execute('SELECT '+','.join('current_setting(%s,true)' for _ in names),names);before=cursor.fetchone()
        for key,value in zip(names,(str(user.pk),clean_reason(reason),str(command.pk) if command else '')):
            cursor.execute('SELECT set_config(%s,%s,true)',[key,value])
    try:yield
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                for key,value in zip(names,before):cursor.execute('SELECT set_config(%s,%s,true)',[key,value or ''])


def canonical(values):
    return json.dumps(values,sort_keys=True,ensure_ascii=False,separators=(',',':'))


def fingerprint(value):return 'sha256:'+hashlib.sha256(value.encode()).hexdigest()


def command_for(user,office,operation,key,payload,reason):
    if not isinstance(key,str) or not 8<=len(key)<=160 or any(ord(c)<33 for c in key):
        raise ValidationError('Απαιτείται έγκυρη ταυτότητα αιτήματος καταχώρισης.')
    key_hash,payload_hash=fingerprint(key),fingerprint(canonical(payload))
    existing=FinanceCommand.objects.select_for_update().filter(office=office,operation=operation,key_digest=key_hash).first()
    if existing:
        if existing.payload_digest!=payload_hash or existing.state!='completed':
            raise ValidationError('Η ταυτότητα αιτήματος χρησιμοποιήθηκε με διαφορετικά ή μη ολοκληρωμένα στοιχεία.')
        return existing,True
    return FinanceCommand.objects.create(office=office,actor=user,operation=operation,key_digest=key_hash,
        payload_digest=payload_hash,reason=clean_reason(reason)),False


def complete(command):
    command.state='completed';command.completed_at=timezone.now();command.save(update_fields=['state','completed_at'])


def cash_values(*,amount,transaction_date,transaction_type,cash_account,category=None,entity=None,agreement=None,description='',remarks=''):
    amount=money(amount)
    if type(transaction_date) is not date or transaction_date>timezone.localdate():raise ValidationError('Επιλέξτε έγκυρη ημερομηνία κίνησης έως σήμερα.')
    if transaction_type not in {'INCOME','EXPENSE'}:raise ValidationError('Ο τύπος της κίνησης δεν είναι έγκυρος.')
    if not isinstance(description,str) or not description.strip() or len(description)>255 or not isinstance(remarks,str) or len(remarks)>10000:
        raise ValidationError('Συμπληρώστε έγκυρη περιγραφή και παρατηρήσεις.')
    key=lambda value:getattr(value,'pk',value)
    values=dict(amount=amount,transaction_date=transaction_date,transaction_type=transaction_type,cash_account_id=key(cash_account),
        category_id=key(category),entity_id=key(entity),agreement_id=key(agreement),description=description,remarks=remarks)
    payload={k:(str(v) if isinstance(v,Decimal) else v.isoformat() if isinstance(v,date) else v) for k,v in values.items()}
    # Free text is not copied to command/audit payloads; only its exact digest.
    for name in ('description','remarks'):payload[name+'_digest']=fingerprint(payload.pop(name))
    return values,payload


def validate_references(values,office):
    scoped_lock(CashAccount,office,values['cash_account_id'],active=True)
    if values['category_id']:scoped_lock(Category,office,values['category_id'])
    agreement=scoped_lock(Agreement,office,values['agreement_id']) if values['agreement_id'] else None
    entity=scoped_lock(Entity,office,values['entity_id'],active=True) if values['entity_id'] else None
    if agreement:
        if entity is None or agreement.entity_id!=entity.pk:raise ValidationError({'agreement':'Η συμφωνία πρέπει να ανήκει στον ίδιο συναλλασσόμενο.'})
        if agreement.agreement_type!=('RECEIVABLE' if values['transaction_type']=='INCOME' else 'PAYABLE'):
            raise ValidationError({'agreement':'Η συμφωνία δεν αντιστοιχεί στην κατεύθυνση της κίνησης.'})
        if agreement.status=='CANCELLED':raise ValidationError({'agreement':'Η συμφωνία έχει ακυρωθεί.'})
    if entity and not (entity.is_customer if values['transaction_type']=='INCOME' else entity.is_supplier):
        raise ValidationError({'entity':'Ο συναλλασσόμενος δεν έχει τον κατάλληλο ρόλο.'})


def project_agreement(key,office):
    if key:
        agreement=scoped_lock(Agreement,office,key)
        if agreement.status=='CANCELLED':return
        settled=Transaction.objects.filter(office=office,agreement=agreement).aggregate(total=legacy_settlement())['total']
        status='COMPLETED' if settled>=agreement.total_amount else 'ACTIVE'
        if agreement.status!=status:
            agreement.status=status;agreement.save(update_fields=['status','updated_at'])


@transaction.atomic
def post_cash(user,*,idempotency_key,reason='Καταχώρηση κίνησης',**inputs):
    office=locked_office(user,'finance.write');values,payload=cash_values(**inputs)
    reason=clean_reason(reason);payload['reason_digest']=fingerprint(reason)
    command,replay=command_for(user,office,'cash.post',idempotency_key,payload,reason)
    if replay:return command.entries.get()
    validate_references(values,office)
    with audit_context(user,reason,command):
        entry=Transaction.objects.create(office=office,command=command,posting_kind='ORDINARY',**values)
        project_agreement(entry.agreement_id,office);complete(command)
    return entry


@transaction.atomic
def post_transfer(user,*,from_account,to_account,amount,transfer_date,description,idempotency_key):
    office=locked_office(user,'finance.write');amount=money(amount)
    if type(transfer_date) is not date or transfer_date>timezone.localdate():raise ValidationError('Επιλέξτε έγκυρη ημερομηνία μεταφοράς έως σήμερα.')
    source_key,dest_key=getattr(from_account,'pk',from_account),getattr(to_account,'pk',to_account)
    if source_key==dest_key:raise ValidationError('Τα ταμεία προέλευσης και προορισμού πρέπει να διαφέρουν.')
    if not isinstance(description,str) or not description.strip() or len(description)>200:raise ValidationError('Συμπληρώστε σύντομη περιγραφή μεταφοράς.')
    command,replay=command_for(user,office,'cash.transfer',idempotency_key,
        {'from':source_key,'to':dest_key,'amount':str(amount),'date':transfer_date.isoformat(),'description_digest':fingerprint(description)},'Εσωτερική μεταφορά')
    if replay:return list(command.entries.order_by('pk'))
    accounts={key:scoped_lock(CashAccount,office,key,active=True) for key in sorted((source_key,dest_key))}
    group=uuid.uuid4()
    with audit_context(user,'Εσωτερική μεταφορά',command):
        entries=[Transaction.objects.create(office=office,command=command,posting_kind='TRANSFER',transfer_id=group,
            transaction_type=direction,transaction_date=transfer_date,amount=amount,cash_account=accounts[key],
            description=label+description) for direction,key,label in (
                ('EXPENSE',source_key,'Μεταφορά προς άλλο ταμείο: '),('INCOME',dest_key,'Μεταφορά από άλλο ταμείο: '))]
        complete(command)
    return entries


@transaction.atomic
def reverse_cash(request,*,entry_id,password,reason,effective_date,idempotency_key,replacement=None):
    office=locked_office(request.user,'finance.reverse')
    from .office_services import prove_actor
    prove_actor(request,office,password,'finance.reverse')
    reason=clean_reason(reason)
    if type(effective_date) is not date or effective_date>timezone.localdate():raise ValidationError('Επιλέξτε έγκυρη ημερομηνία αντιλογισμού έως σήμερα.')
    replacement_values,replacement_payload=cash_values(**replacement) if replacement else (None,None)
    command,replay=command_for(request.user,office,'cash.correct' if replacement else 'cash.reverse',idempotency_key,
        {'entry':entry_id,'date':effective_date.isoformat(),'reason_digest':fingerprint(reason),'replacement':replacement_payload},reason)
    if replay:return list(command.entries.order_by('pk'))
    original=scoped_lock(Transaction,office,entry_id)
    if effective_date<original.transaction_date:raise ValidationError('Ο αντιλογισμός δεν προηγείται της αρχικής κίνησης.')
    if original.posting_kind=='REVERSAL' or Transaction.objects.filter(reversal_of=original).exists():raise ValidationError('Η κίνηση έχει ήδη αντιλογιστεί ή αποτελεί αντιλογισμό.')
    # Legacy UUIDs also exist on ordinary rows: only an actual peer/pair means transfer.
    if original.posting_kind=='TRANSFER' or Transaction.objects.filter(office=office,transfer_id=original.transfer_id).exclude(pk=original.pk).exists():
        raise ValidationError('Ο αντιλογισμός μεταφοράς απαιτεί ενιαία διόρθωση και των δύο σκελών.')
    if replacement_values:validate_references(replacement_values,office)
    with audit_context(request.user,reason,command):
        reversal=Transaction.objects.create(office=office,command=command,posting_kind='REVERSAL',reversal_of=original,
            amount=original.amount,transaction_date=effective_date,transaction_type='EXPENSE' if original.transaction_type=='INCOME' else 'INCOME',
            cash_account_id=original.cash_account_id,category_id=original.category_id,entity_id=original.entity_id,agreement_id=original.agreement_id,
            description='Αντιλογισμός κίνησης '+str(original.pk))
        entries=[reversal]
        if replacement_values:entries.append(Transaction.objects.create(office=office,command=command,posting_kind='ORDINARY',**replacement_values))
        for key in sorted({e.agreement_id for e in [original,*entries] if e.agreement_id}):project_agreement(key,office)
        complete(command)
    return entries


@transaction.atomic
def save_master(instance,user):
    office=locked_office(user,'finance.write')
    if instance.office_id and instance.office_id!=office.pk:raise PermissionDenied('Δεν έχετε πρόσβαση σε αυτή την εγγραφή.')
    instance.office_id=office.pk
    if isinstance(instance,Agreement):
        instance.total_amount=money(instance.total_amount)
        entity=scoped_lock(Entity,office,instance.entity_id,active=not bool(instance.pk))
        if not (entity.is_customer if instance.agreement_type=='RECEIVABLE' else entity.is_supplier):raise ValidationError('Ο συναλλασσόμενος δεν έχει τον κατάλληλο ρόλο.')
        if instance.pk:
            old=scoped_lock(Agreement,office,instance.pk)
            if old.status!=instance.status and old.status=='CANCELLED':raise ValidationError('Η ακυρωμένη συμφωνία δεν ενεργοποιείται από απλή επεξεργασία.')
            if Transaction.objects.filter(agreement=old).exists() and any(getattr(old,n)!=getattr(instance,n) for n in ('entity_id','agreement_type','total_amount','start_date','status')):
                raise ValidationError('Η συμφωνία έχει καταχωρισμένες κινήσεις. Οι αλλαγές όρων απαιτούν την ειδική διαδικασία ιστορικού.')
    elif isinstance(instance,CashAccount):
        instance.opening_balance=money(instance.opening_balance,signed=True)
        if instance.pk:
            old=scoped_lock(CashAccount,office,instance.pk)
            if old.opening_balance!=instance.opening_balance and Transaction.objects.filter(cash_account=old).exists():
                raise ValidationError('Το αρχικό υπόλοιπο χρησιμοποιούμενου ταμείου διορθώνεται μόνο με τεκμηριωμένη προσαρμογή.')
    with audit_context(user,'Ενημέρωση οικονομικών στοιχείων'):
        instance.save()
    return instance


def submission_key(request,cleaned):
    """HTML carries a fresh UUID. Legacy tokenless retries share a session/payload key."""
    key=cleaned.get('posting_key')
    if key:return str(key)
    from django.utils.crypto import salted_hmac
    if not request.session.session_key:raise ValidationError('Ανανεώστε τη σελίδα πριν από νέα καταχώριση.')
    nonce=salted_hmac('accounting.s18.legacy-submission',request.session.session_key).hexdigest()
    payload={k:str(getattr(v,'pk',v)) for k,v in cleaned.items() if k!='posting_key'}
    return 'legacy-'+hashlib.sha256((nonce+request.path+canonical(payload)).encode()).hexdigest()


def finance_history(user,*,target_model,target_id):
    """Owner-only bounded reader; no global manager is exposed as an endpoint."""
    from .capabilities import require_capability
    from .finance_models import FinanceAuditEvent
    profile=require_capability(user,'office.audit')
    if target_model not in {'transaction','agreement','cashaccount','category'}:
        raise ValidationError('Ο τύπος οικονομικού ιστορικού δεν υποστηρίζεται.')
    return list(FinanceAuditEvent.objects.filter(office_id=profile.office_id,target_model=target_model,target_id=target_id)
        .select_related('actor').order_by('-recorded_at','-pk')[:100])
