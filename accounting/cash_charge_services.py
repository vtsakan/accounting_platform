"""One atomic cash entry, one chosen charge, and immutable initial-selection proof."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from .cash_entry_selectors import settlement_capacity
from .finance_money import money
from .finance_services import audit_context,canonical,fingerprint,post_cash,scoped_lock
from .models import CashChargeSelection,Charge,ChargeReversal,FinanceCommand,Transaction
from .office_access import locked_office
from .settlement_selectors import business_day
from .settlement_services import allocate_cash,cash_key,event_key


@transaction.atomic
def post_charge_cash(user,*,charge,idempotency_key,transaction_type,**inputs):
    office=locked_office(user,'finance.write')
    if transaction_type not in {'INCOME','EXPENSE'}:raise ValidationError('Επιλέξτε έσοδο ή έξοδο.')
    if not isinstance(idempotency_key,str) or not 8<=len(idempotency_key)<=160 or any(ord(c)<33 for c in idempotency_key):
        raise ValidationError('Ανανεώστε τη φόρμα για έγκυρη ταυτότητα καταχώρισης.')
    key=event_key(charge);day=business_day(inputs.get('transaction_date'));amount=money(inputs.get('amount'))
    original=FinanceCommand.objects.filter(office=office,operation='cash.post',key_digest=fingerprint(idempotency_key),state='completed').first()
    if original:
        old=Transaction.objects.get(office=office,command=original)
        receipt=CashChargeSelection.objects.filter(office=office,source_cash=old).first()
        if receipt is None or receipt.charge_id!=key or receipt.actor_id!=user.pk:
            raise ValidationError({'charge':'Η ίδια ταυτότητα υποβολής αφορά διαφορετική αρχική επιλογή. Επαναλάβετε ακριβώς την αρχική υποβολή.'})
        if not inputs.get('description'):inputs['description']=old.description
        entry=post_cash(user,idempotency_key=idempotency_key,transaction_type=transaction_type,**inputs)
        expected=fingerprint(canonical({'cash_payload':original.payload_digest,'charge':str(key),'actor':user.pk}))
        if receipt.payload_sha256!=expected:raise ValidationError('Η αρχική επιλογή δεν συμφωνεί με το διατηρημένο ιστορικό.')
        return entry,Decimal('0.00'),True
    chosen=scoped_lock(Charge,office,key)
    if not inputs.get('entity') or cash_key(inputs['entity'])!=chosen.entity_id:
        raise ValidationError({'entity':'Η χρέωση πρέπει να ανήκει στον επιλεγμένο συναλλασσόμενο.'})
    if not inputs.get('agreement') or cash_key(inputs['agreement'])!=chosen.agreement_id:
        raise ValidationError({'agreement':'Επιλέξτε τη συμφωνία της συγκεκριμένης χρέωσης.'})
    if chosen.direction!=('RECEIVABLE' if transaction_type=='INCOME' else 'PAYABLE'):
        raise ValidationError({'charge':'Η χρέωση δεν αντιστοιχεί στην κατεύθυνση της είσπραξης ή πληρωμής.'})
    if chosen.effective_date>day or ChargeReversal.objects.filter(office=office,charge=chosen).exists():
        raise ValidationError({'charge':'Η χρέωση έχει αντιλογιστεί ή είναι μεταγενέστερη της κίνησης.'})
    capacity=next((available for charge_id,available in settlement_capacity(office.pk,chosen.agreement_id,day) if charge_id==key),Decimal('0.00'))
    if capacity<=0:raise ValidationError({'charge':'Η χρέωση έχει ήδη εξοφληθεί ή δεν έχει διαθέσιμο υπόλοιπο για την ημερομηνία αυτή. Ανανεώστε τις επιλογές.'})
    if not inputs.get('description'):
        prefix='Είσπραξη για συμφωνία: ' if transaction_type=='INCOME' else 'Πληρωμή για συμφωνία: '
        inputs['description']=(prefix+chosen.description)[:255]
    entry=post_cash(user,idempotency_key=idempotency_key,transaction_type=transaction_type,**inputs)
    allocated=min(amount,capacity)
    why='Αντιστοίχιση νέας κίνησης στη συγκεκριμένη επιλεγμένη χρέωση'
    command=allocate_cash(user,source_cash=entry.pk,lines=[{'charge':key,'amount':allocated}],effective_date=day,
        reason=why,idempotency_key='selected-charge:'+str(entry.pk))
    digest=fingerprint(canonical({'cash_payload':entry.command.payload_digest,'charge':str(key),'actor':user.pk}))
    with audit_context(user,why):
        CashChargeSelection.objects.create(office=office,source_cash=entry,charge=chosen,settlement=command,
            actor=user,allocated_amount=allocated,payload_sha256=digest)
    return entry,allocated,False
