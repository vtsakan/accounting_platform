"""Owned synthetic PG17 only: real demand charges and selection recovery."""
import json
import secrets
import sys
import uuid
from decimal import Decimal

import cr011_probe as previous
import cr008_probe as retained
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.agreement_selectors import agreement_projection
from accounting.cash_charge_services import post_charge_cash
from accounting.charge_services import post_charge
from accounting.correction_services import amend_agreement
from accounting.manual_agreement_creation import create_manual
from accounting.membership import create_accountant_profile
from accounting.models import Agreement,CashAccount,CashAllocation,CashChargeSelection,Charge,Entity,Transaction
from accounting.settlement_selectors import cash_sources
from accounting.tests_auth_support import staff_client_login
from core.redaction import register_secret

WHY='Συνθετικός έλεγχος χρεώσεων κατά περίπτωση και ανάκτησης'
NAME='cr012-synthetic-owner'


def finance_snapshot():
    return {key:row for key,row in retained.snapshot().items() if key.startswith('accounting_')}


def prepare():
    previous.isolated()
    result=previous.prepare()
    source=get_user_model().objects.get(username='cr008-synthetic-owner')
    office=source.accountant_profile.office;password=secrets.token_urlsafe(48);register_secret(password)
    owner=get_user_model().objects.create_user(NAME,password=password)
    create_accountant_profile(user_id=owner.pk,office_id=office.pk,role='owner')
    client=Client();staff_client_login(client,owner)
    request=client.get(reverse('office-members'),secure=True,HTTP_HOST='cr008.example.invalid').wsgi_request
    day=timezone.localdate()
    entity=Entity.objects.create(office=office,name='Συνθετικός πελάτης χρεώσεων CR012',entity_type='CUSTOMER')
    account=CashAccount.objects.create(office=office,name='Συνθετικό ταμείο CR012',opening_date=day,opening_balance='0.00')
    counts=(Charge.objects.count(),Transaction.objects.count())
    agreement,_=create_manual(owner,Agreement(entity=entity,agreement_type='RECEIVABLE',description=WHY,
        total_amount='500.00',start_date=day,status='ACTIVE'),billing_mode='ON_DEMAND',reason=WHY,creation_key=uuid.uuid4())
    assert (Charge.objects.count(),Transaction.objects.count())==counts
    def charge(amount):
        return post_charge(owner,agreement_id=agreement.pk,terms_revision=1,amount=amount,effective_date=day,due_date=day,
            reason=WHY,idempotency_key=str(uuid.uuid4()))
    first,second=charge('200.00'),charge('300.00');key=str(uuid.uuid4())
    values={'charge':second.pk,'idempotency_key':key,'transaction_type':'INCOME','transaction_date':day,
        'amount':'350.00','cash_account':account,'entity':entity,'agreement':agreement,'description':'','remarks':''}
    entry,allocated,replay=post_charge_cash(owner,**values)
    assert allocated==Decimal('300.00') and not replay
    assert CashAllocation.objects.get(source_cash=entry).charge_id==second.pk
    assert not CashAllocation.objects.filter(charge=first).exists()
    assert cash_sources(owner,entity=entity).get(pk=entry.pk).available_credit==Decimal('50.00')
    before=finance_snapshot()
    for operation in (
        lambda:charge('0.01'),
        lambda:amend_agreement(request,agreement_id=agreement.pk,expected_revision=1,description=WHY,amount='499.99',
            lifecycle='ACTIVE',password=password,effective_date=day,reason=WHY,idempotency_key=str(uuid.uuid4())),
        lambda:post_charge_cash(owner,**(values|{'charge':first.pk})),
    ):
        try:operation()
        except ValidationError:pass
        else:raise RuntimeError('An invalid synthetic financial request was accepted')
        assert finance_snapshot()==before
    repeated,zero,replayed=post_charge_cash(owner,**values)
    assert repeated.pk==entry.pk and zero==0 and replayed and finance_snapshot()==before
    result['charge_workflow']={'terms_do_not_post_cash':True,'arbitrary_charges_respect_gross_budget':True,
        'only_selected_charge_settled':True,'excess_kept_as_credit':True,'lower_terms_rejected':True,
        'changed_choice_rejected':True,'exact_replay_once':True,'invalid_requests_have_no_partial_writes':True}
    result['snapshot']=retained.snapshot()
    return result


def recovered():
    previous.isolated();result=previous.recovered()
    user=get_user_model().objects.get(username=NAME)
    row=CashChargeSelection.objects.select_related('source_cash','charge__agreement').get(actor=user)
    assert row.source_cash.amount==Decimal('350.00') and row.allocated_amount==Decimal('300.00')
    assert row.charge.amount==Decimal('300.00') and row.charge.agreement.terms_versions.first().billing_mode=='ON_DEMAND'
    assert CashAllocation.objects.get(command=row.settlement).charge_id==row.charge_id
    assert agreement_projection(row.charge.agreement)['remaining_obligation']==Decimal('200.00')
    assert cash_sources(user,entity=row.charge.entity_id).get(pk=row.source_cash_id).available_credit==Decimal('50.00')
    result['demand_charges_recovered']=True;result['cash_charge_selection_recovered']=True
    return result


if __name__=='__main__':
    previous.isolated()
    print(json.dumps({'prepare':prepare,'recovered':recovered,'snapshot':retained.snapshot}[sys.argv[1]](),ensure_ascii=False))
