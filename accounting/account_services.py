"""S19 exact opening boundary, immutable adjustments and scoped reference maintenance."""
from datetime import date
from decimal import Decimal
import hashlib,json
from django.core import signing
from django.core.exceptions import ValidationError,PermissionDenied
from django.db import transaction,IntegrityError
from django.http import Http404
from django.utils import timezone
from .models import CashAccount,Category,CashAdjustment,Transaction
from .capabilities import require_capability
from .office_access import locked_office
from .finance_money import money
from .finance_services import scoped_lock,audit_context,clean_reason,fingerprint,canonical

STALE='Τα στοιχεία άλλαξαν. Ανανεώστε τη σελίδα και ελέγξτε ξανά την ενέργεια.'
OPENING_PENDING='Το ταμείο χρειάζεται επιβεβαίωση αρχικού υπολοίπου και ημερομηνίας από τον υπεύθυνο.'
SALT='accounting.s19.opening-review'


def require_version(value,current):
    if type(value) is not int or value!=current:raise ValidationError(STALE)


def validated_name(value):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>100:raise ValidationError({'name':'Συμπληρώστε όνομα έως 100 χαρακτήρες.'})
    return value.strip()


def validate_account_date(account,day):
    if account.opening_date is None:raise ValidationError(OPENING_PENDING)
    if day<account.opening_date:raise ValidationError('Η κίνηση δεν μπορεί να προηγείται της ημερομηνίας αρχικού υπολοίπου.')


def inventory(account,day):
    digest=hashlib.sha256();before_count=after_count=0;before_total=after_total=Decimal('0.00');earliest=None
    rows=Transaction.objects.filter(office_id=account.office_id,cash_account=account).order_by('pk').values('id','amount','transaction_date','transaction_type','transfer_id','posting_kind')
    for row in rows.iterator(chunk_size=1000):
        payload={key:str(value) for key,value in row.items()};digest.update((canonical(payload)+'\n').encode())
        earliest=min(earliest,row['transaction_date']) if earliest else row['transaction_date']
        signed=row['amount'] if row['transaction_type']=='INCOME' else -row['amount'] if row['transaction_type']=='EXPENSE' else Decimal('0.00')
        if row['transaction_date']<day:before_count+=1;before_total+=signed
        else:after_count+=1;after_total+=signed
    return {'digest':'sha256:'+digest.hexdigest(),'excluded_count':before_count,'included_count':after_count,
        'excluded_net':str(before_total),'included_net':str(after_total),'earliest':earliest.strftime('%d/%m/%Y') if earliest else None}


def preview_opening(user,*,account_id,amount,effective_date):
    profile=require_capability(user,'finance.opening')
    account=CashAccount.objects.filter(pk=account_id,office_id=profile.office_id).first()
    if account is None:raise Http404('Το ταμείο δεν βρέθηκε.')
    if account.opening_date:raise ValidationError('Το αρχικό υπόλοιπο έχει ήδη εγκριθεί. Χρησιμοποιήστε προσαρμογή.')
    amount=money(amount,signed=True)
    if type(effective_date) is not date or effective_date>timezone.localdate():raise ValidationError('Επιλέξτε έγκυρη ημερομηνία αρχικού υπολοίπου έως σήμερα.')
    if account.legacy_opening and amount!=account.opening_balance:raise ValidationError('Το διατηρημένο παλαιό ποσό δεν αλλάζει κατά την επιβεβαίωση ημερομηνίας.')
    plan={'office':str(profile.office_id),'account':account.pk,'amount':str(amount),'date':effective_date.isoformat(),
        'version':account.record_version,'legacy':account.legacy_opening,'inventory':inventory(account,effective_date)}
    return plan,signing.dumps(plan,salt=SALT,compress=True)


def proof(request,office,password):
    if not isinstance(password,str) or not password:raise ValidationError('Απαιτείται κωδικός πρόσβασης και πρόσφατη επαλήθευση MFA.')
    from .office_services import prove_actor
    return prove_actor(request,office,password,'finance.opening')


def request_key(value):
    if not isinstance(value,str) or not 8<=len(value)<=160 or any(ord(c)<33 for c in value):raise ValidationError('Απαιτείται έγκυρη ταυτότητα αιτήματος.')
    return fingerprint(value)


@transaction.atomic
def approve_opening(request,*,account_id,review_token,amount,effective_date,reason,review_reference,password,idempotency_key,acknowledged):
    office=locked_office(request.user,'finance.opening');proof(request,office,password)
    account=scoped_lock(CashAccount,office,account_id)
    if type(effective_date) is not date or effective_date>timezone.localdate():raise ValidationError('Επιλέξτε έγκυρη ημερομηνία έως σήμερα.')
    amount=money(amount,signed=True);reason=clean_reason(reason);reference=clean_reason(review_reference)
    if len(reference)>250:raise ValidationError('Η αναφορά ελέγχου περιορίζεται σε 250 χαρακτήρες.')
    if len(reason)+len(reference)>497:raise ValidationError('Η συνολική αιτιολογία και αναφορά περιορίζονται σε 500 χαρακτήρες.')
    try:plan=signing.loads(review_token,salt=SALT,max_age=900)
    except (signing.BadSignature,TypeError):raise ValidationError('Η προεπισκόπηση έληξε ή δεν είναι έγκυρη. Δημιουργήστε νέα προεπισκόπηση.') from None
    if (plan.get('office'),plan.get('account'),plan.get('amount'),plan.get('date'))!=(str(office.pk),account.pk,str(amount),effective_date.isoformat()):
        raise ValidationError('Η προεπισκόπηση αφορά διαφορετικά στοιχεία. Ελέγξτε ξανά την ημερομηνία και το ποσό.')
    if acknowledged is not True:raise ValidationError('Επιβεβαιώστε ρητά την έναρξη και την εξαίρεση των προγενέστερων κινήσεων.')
    key=request_key(idempotency_key)
    payload=fingerprint(canonical({'plan':plan,'reason':reason,'reference':reference}))
    if CashAccount.objects.filter(office=office,opening_key_digest=key).exclude(pk=account.pk).exists():raise ValidationError('Η ταυτότητα αιτήματος ανήκει σε άλλο ταμείο.')
    if account.opening_date is not None:
        if account.opening_key_digest==key and account.opening_payload_digest==payload:return account
        raise ValidationError('Το αρχικό υπόλοιπο έχει εγκριθεί και δεν αντικαθίσταται. Χρησιμοποιήστε προσαρμογή.')
    require_version(plan.get('version'),account.record_version)
    if plan.get('inventory')!=inventory(account,effective_date):raise ValidationError(STALE)
    if account.legacy_opening and amount!=account.opening_balance:raise ValidationError('Το διατηρημένο ποσό δεν αλλάζει κατά την επιβεβαίωση.')
    account.opening_balance=amount;account.opening_date=effective_date
    account.opening_key_digest=key;account.opening_payload_digest=payload
    with audit_context(request.user,reason+' · '+reference):
        account.save(update_fields=['opening_balance','opening_date','opening_key_digest','opening_payload_digest'])
    account.refresh_from_db();return account


@transaction.atomic
def save_reference(instance,user,*,expected_version=None):
    if type(instance) not in {CashAccount,Category}:raise PermissionDenied('Ο τύπος εγγραφής δεν υποστηρίζεται.')
    office=locked_office(user,'finance.write')
    if instance.office_id and str(instance.office_id)!=str(office.pk):raise PermissionDenied('Δεν έχετε πρόσβαση στην εγγραφή.')
    instance.office_id=office.pk;instance.name=validated_name(instance.name)
    if type(instance.is_active) is not bool:raise ValidationError('Η κατάσταση πρέπει να είναι ενεργή ή ανενεργή.')
    old=scoped_lock(type(instance),office,instance.pk) if instance.pk else None
    if old:require_version(expected_version if expected_version is not None else instance.record_version,old.record_version)
    if isinstance(instance,CashAccount):
        instance.opening_balance=money(instance.opening_balance,signed=True)
        if old:
            for field in ('opening_balance','opening_date','opening_approved_at','legacy_opening','opening_key_digest','opening_payload_digest'):
                if getattr(instance,field)!=getattr(old,field):raise ValidationError('Τα αρχικά οικονομικά στοιχεία αλλάζουν μόνο με έγκριση ή τεκμηριωμένη προσαρμογή.')
        elif instance.opening_balance!=0 or instance.opening_date is not None or instance.legacy_opening or instance.opening_key_digest:
            raise ValidationError('Το νέο ταμείο δημιουργείται σε αναμονή έγκρισης αρχικού υπολοίπου.')
    else:
        instance.validate_hierarchy()
        if old and old.is_active and not instance.is_active and Category.objects.filter(office=office,parent=old,is_active=True).exists():
            raise ValidationError('Αποσύρετε πρώτα τις ενεργές υποκατηγορίες ή μετακινήστε τες σε ενεργή κατηγορία.')
    try:
        with transaction.atomic(),audit_context(user,'Ενημέρωση ταμείου ή κατηγορίας'):
            if old:instance.save(update_fields=['name','is_active']+(['parent'] if isinstance(instance,Category) else []))
            else:instance.save(force_insert=True)
    except IntegrityError as error:
        if getattr(error.__cause__,'sqlstate',None) in {'23505','23514'}:raise ValidationError('Τα στοιχεία συγκρούονται με υπάρχουσα εγγραφή ή κανόνα ιεραρχίας. Ελέγξτε τα και δοκιμάστε ξανά.') from None
        raise
    instance.refresh_from_db();return instance


@transaction.atomic
def adjust_opening(request,*,account_id,amount,effective_date,reason,review_reference,password,idempotency_key,reversal_of_id=None):
    office=locked_office(request.user,'finance.opening');proof(request,office,password)
    account=scoped_lock(CashAccount,office,account_id)
    if type(effective_date) is not date or effective_date!=timezone.localdate():raise ValidationError('Οι προσαρμογές καταχωρίζονται με σημερινή ημερομηνία ώστε να διατηρούνται τα προηγούμενα ημερήσια υπόλοιπα.')
    validate_account_date(account,effective_date)
    reason=clean_reason(reason);reference=clean_reason(review_reference)
    if len(reference)>250:raise ValidationError('Η αναφορά ελέγχου περιορίζεται σε 250 χαρακτήρες.')
    if len(reason)+len(reference)>497:raise ValidationError('Η συνολική αιτιολογία και αναφορά περιορίζονται σε 500 χαρακτήρες.')
    original=None
    if reversal_of_id is not None:
        original=CashAdjustment.objects.select_for_update().filter(pk=reversal_of_id,office=office,account=account).first()
        if original is None:raise ValidationError('Η αρχική προσαρμογή δεν είναι διαθέσιμη στο ταμείο.')
        amount=-original.amount
    amount=money(amount,signed=True)
    if not amount:raise ValidationError('Η προσαρμογή πρέπει να διαφέρει από το μηδέν.')
    key=request_key(idempotency_key)
    payload=fingerprint(canonical({'account':account.pk,'amount':str(amount),'date':effective_date.isoformat(),
        'reason':reason,'reference':reference,'reversal_of':original.pk if original else None}))
    previous=CashAdjustment.objects.filter(office=office,key_digest=key).first()
    if previous:
        if previous.payload_digest==payload:return previous
        raise ValidationError('Η ταυτότητα αιτήματος χρησιμοποιήθηκε με διαφορετικά στοιχεία.')
    if original and (original.reversal_of_id or CashAdjustment.objects.filter(reversal_of=original).exists()):raise ValidationError('Η προσαρμογή έχει ήδη αντιλογιστεί ή αποτελεί αντιλογισμό.')
    with audit_context(request.user,reason+' · '+reference):
        return CashAdjustment.objects.create(office=office,account=account,actor=request.user,amount=amount,effective_date=effective_date,
            reason=reason,review_reference=reference,key_digest=key,payload_digest=payload,reversal_of=original)
