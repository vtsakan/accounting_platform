"""Operator contracts: explicit charge choice, excess credit, replay and Greek errors."""
from datetime import timedelta
from decimal import Decimal
import uuid
from unittest.mock import patch

from django.core.exceptions import PermissionDenied,ValidationError
from django.db import IntegrityError,transaction,connection
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .agreement_selectors import agreement_projection
from .cash_charge_services import post_charge_cash
from .cash_entry_selectors import receipt_charges
from .correction_services import close_period
from .finance_services import audit_context,post_cash
from .forms import IncomeForm
from .models import AccountantProfile,Agreement,CashAllocation,CashChargeSelection,Charge,Entity,Transaction
from .settlement_selectors import cash_sources
from .settlement_services import release_allocation
from .tests_auth_support import staff_client_login
from .tests_demand_charges import DemandSupport,WHY
from .tests_finance_posting import DAY


class SelectedChargeContracts(DemandSupport,TestCase):
    def test_receipt_targets_the_chosen_second_charge_instead_of_fifo(self):
        first=self.charge('200.00');second=self.charge('300.00',day=DAY+timedelta(days=1))
        entry,allocated,replay=self.cash(second,'150.00',day=DAY+timedelta(days=1))
        self.assertFalse(replay);self.assertEqual(allocated,Decimal('150.00'))
        self.assertEqual(CashAllocation.objects.get(source_cash=entry).charge_id,second.pk)
        self.assertEqual(agreement_projection(self.target)['remaining_obligation'],Decimal('350.00'))
        self.assertFalse(CashAllocation.objects.filter(charge=first).exists())

    def test_overpayment_remains_credit_and_does_not_spill_to_another_charge(self):
        first=self.charge('150.00');second=self.charge('350.00')
        entry,allocated,_=self.cash(first,'200.00')
        self.assertEqual((entry.amount,allocated),(Decimal('200.00'),Decimal('150.00')))
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit,Decimal('50.00'))
        self.assertFalse(CashAllocation.objects.filter(charge=second).exists())
        self.assertEqual(CashChargeSelection.objects.get(source_cash=entry).allocated_amount,Decimal('150.00'))

    def test_partial_and_full_receipts_update_only_the_selected_debt(self):
        row=self.charge('300.00');self.cash(row,'100.00');self.cash(row,'200.00')
        self.assertEqual((CashChargeSelection.objects.count(),CashAllocation.objects.count()),(2,2))
        self.assertEqual(agreement_projection(self.target)['remaining_obligation'],Decimal('0.00'))

    def test_supplier_payment_uses_payable_charge_and_keeps_excess_as_advance(self):
        agreement=self.contract(entity=self.supplier,direction='PAYABLE');row=self.charge('150.00',agreement=agreement)
        entry,allocated,_=self.cash(row,'200.00',transaction_type='EXPENSE',entity=self.supplier,agreement=agreement)
        self.assertEqual((entry.transaction_type,allocated),('EXPENSE',Decimal('150.00')))
        self.assertEqual(cash_sources(self.member).get(pk=entry.pk).available_credit,Decimal('50.00'))

    def test_existing_unallocated_credit_is_not_spent_by_new_receipt(self):
        row=self.charge('300.00')
        old=post_cash(self.member,idempotency_key=str(uuid.uuid4()),amount='70.00',transaction_date=DAY,
            transaction_type='INCOME',cash_account=self.account,entity=self.customer,description='Παλαιότερη αδιάθετη πίστωση')
        self.cash(row,'100.00')
        self.assertEqual(cash_sources(self.member).get(pk=old.pk).available_credit,Decimal('70.00'))

    def test_fully_paid_selected_charge_requires_refresh_without_creating_more_cash(self):
        row=self.charge('100.00');self.cash(row,'100.00');self.rejected(lambda:self.cash(row,'1.00'))

    def test_reversed_charge_cannot_receive_a_new_backdated_receipt(self):
        row=self.charge('100.00');self.correct(row,day=DAY+timedelta(days=2))
        self.rejected(lambda:self.cash(row,'50.00'))

    def test_receipt_before_charge_date_is_rejected(self):
        row=self.charge('100.00',day=DAY+timedelta(days=1));self.rejected(lambda:self.cash(row,'50.00'))

    def test_wrong_customer_agreement_and_direction_are_rejected(self):
        row=self.charge('100.00');other=self.contract()
        for changes in ({'entity':self.supplier},{'agreement':other},{'transaction_type':'EXPENSE'}):
            with self.subTest(changes=changes):self.rejected(lambda:self.cash(row,**changes))

    def test_foreign_charge_is_rejected_without_writes(self):
        import secrets
        from django.contrib.auth import get_user_model
        from .membership import create_accountant_profile
        from .manual_agreement_creation import create_manual
        from .charge_services import post_charge
        member=get_user_model().objects.create_user('cr012-foreign-accountant',password=secrets.token_urlsafe(32))
        create_accountant_profile(user_id=member.pk,office_id=self.foreign.pk,role='accountant')
        foreign=Entity.objects.create(office=self.foreign,name='Ξένος δοκιμαστικός πελάτης',entity_type='CUSTOMER')
        agreement,_=create_manual(member,Agreement(entity=foreign,agreement_type='RECEIVABLE',description=WHY,total_amount='500.00',start_date=DAY,status='ACTIVE'),
            billing_mode='ON_DEMAND',reason=WHY,creation_key=uuid.uuid4())
        charge=post_charge(member,agreement_id=agreement.pk,terms_revision=1,amount='100.00',effective_date=DAY,due_date=DAY,
            reason=WHY,idempotency_key=str(uuid.uuid4()))
        self.rejected(lambda:self.cash(charge))
        self.assertFalse(CashChargeSelection.objects.exists());self.assertNotEqual(foreign.office_id,self.office.pk)

    def test_invalid_money_and_request_identity_leave_no_cash_or_receipt(self):
        row=self.charge('100.00')
        for changes in ({'amount':'0.00'},{'amount':'-1.00'},{'amount':'1.001'},{'idempotency_key':'bad'},
                {'charge':'not-a-charge'},{'transaction_type':'TRANSFER'}):
            with self.subTest(changes=changes):
                amount=changes.get('amount','10.00');rest={k:v for k,v in changes.items() if k not in {'amount','charge'}}
                self.rejected(lambda:self.cash(changes.get('charge',row),amount,**rest))

    def test_allocation_failure_rolls_back_cash_command_and_audit(self):
        row=self.charge('100.00')
        with patch('accounting.cash_charge_services.allocate_cash',side_effect=ValidationError('Δοκιμαστική αποτυχία αντιστοίχισης')):
            self.rejected(lambda:self.cash(row,'50.00'))

    def test_receipt_failure_rolls_back_cash_and_completed_allocation(self):
        row=self.charge('100.00')
        with patch('accounting.cash_charge_services.CashChargeSelection.objects.create',side_effect=ValidationError('Δοκιμαστική αποτυχία καταγραφής')):
            self.rejected(lambda:self.cash(row,'50.00'))

    def test_identical_retry_creates_one_cash_allocation_and_selection(self):
        row=self.charge('100.00');key=str(uuid.uuid4());first,_,_=self.cash(row,'100.00',idempotency_key=key)
        before=self.state();again,allocated,replayed=self.cash(row,'100.00',idempotency_key=key)
        self.assertEqual((again.pk,allocated,replayed),(first.pk,Decimal('0.00'),True));self.assertEqual(self.state(),before)

    def test_changed_choice_under_same_posting_key_is_rejected(self):
        first=self.charge('100.00');second=self.charge('100.00');key=str(uuid.uuid4());self.cash(first,'50.00',idempotency_key=key)
        self.rejected(lambda:self.cash(second,'50.00',idempotency_key=key))

    def test_changed_amount_under_same_posting_key_is_rejected(self):
        row=self.charge('100.00');key=str(uuid.uuid4());self.cash(row,'50.00',idempotency_key=key)
        self.rejected(lambda:self.cash(row,'49.00',idempotency_key=key))

    def test_old_cash_only_key_cannot_be_retroactively_given_a_charge_selection(self):
        row=self.charge('100.00');key=str(uuid.uuid4())
        post_cash(self.member,idempotency_key=key,amount='50.00',transaction_date=DAY,transaction_type='INCOME',
            cash_account=self.account,entity=self.customer,agreement=self.target,description='Αρχική αυτόνομη είσπραξη')
        self.rejected(lambda:self.cash(row,'50.00',idempotency_key=key,description='Αρχική αυτόνομη είσπραξη'))

    def test_replay_after_reversal_does_not_restore_old_allocation(self):
        row=self.charge('100.00');key=str(uuid.uuid4());entry,_,_=self.cash(row,'50.00',idempotency_key=key)
        self.correct(row,day=DAY+timedelta(days=1));before=self.state()
        repeated,_,replay=self.cash(row,'50.00',idempotency_key=key)
        self.assertTrue(replay);self.assertEqual(repeated.pk,entry.pk);self.assertEqual(self.state(),before)

    def test_retry_retains_original_generated_description_after_amendment(self):
        row=self.charge('100.00');key=str(uuid.uuid4());entry,_,_=self.cash(row,'50.00',idempotency_key=key)
        self.amend('600.00');again,_,_=self.cash(row,'50.00',idempotency_key=key)
        self.assertEqual(again.description,entry.description)

    def test_revoked_user_cannot_post_or_replay_selection(self):
        row=self.charge('100.00');key=str(uuid.uuid4());self.cash(row,'50.00',idempotency_key=key)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        self.rejected(lambda:self.cash(row,'50.00',idempotency_key=key),error=PermissionDenied)

    def test_receipt_cannot_be_retargeted_or_deleted_by_sql(self):
        row=self.charge('100.00');entry,_,_=self.cash(row,'50.00')
        for sql in ('UPDATE accounting_cashchargeselection SET allocated_amount=1 WHERE source_cash_id=%s',
                    'DELETE FROM accounting_cashchargeselection WHERE source_cash_id=%s'):
            with self.subTest(sql=sql):
                with self.assertRaises(IntegrityError),transaction.atomic(),connection.cursor() as cursor:cursor.execute(sql,[entry.pk])
        self.assertEqual(CashChargeSelection.objects.get().allocated_amount,Decimal('50.00'))

    def test_closed_period_rejects_receipt_without_partial_cash(self):
        row=self.charge('100.00');request=self.owner_request()
        close_period(request,closed_through=DAY,password=self.password,reason=WHY,idempotency_key=str(uuid.uuid4()))
        self.rejected(lambda:self.cash(row,'50.00'))


class DemandHttpContracts(DemandSupport,TestCase):
    def setUp(self):
        super().setUp();staff_client_login(self.client,self.member)

    def data(self,row,**changes):
        return {'posting_key':str(uuid.uuid4()),'transaction_date':DAY.isoformat(),'amount':'50,00',
            'cash_account':str(self.account.pk),'category':'','entity':str(self.customer.pk),
            'settle_agreement':'on','agreement':str(self.target.pk),'charge':str(row.pk),'description':'','remarks':''}|changes

    def test_new_agreement_form_exposes_on_demand_choice(self):
        response=self.client.get(reverse('add-agreement'))
        self.assertContains(response,'Χρεώσεις κατά περίπτωση')

    def test_charge_page_separates_agreed_and_remaining_billing_amount(self):
        self.charge('200.00');response=self.client.get(reverse('agreement-charge-add',args=[self.target.pk]))
        self.assertContains(response,'300,00');self.assertContains(response,'Καταχωρισμένες χρεώσεις')

    def test_charge_above_budget_is_a_greek_field_error_without_writes(self):
        before=self.state();response=self.client.post(reverse('agreement-charge-add',args=[self.target.pk]),{
            'posting_key':str(uuid.uuid4()),'terms_revision':'1','amount':'500,01','effective_date':DAY.isoformat(),
            'due_date':DAY.isoformat(),'period':'','reason':WHY})
        self.assertEqual(response.status_code,200);self.assertIn('amount',response.context['form'].errors)
        self.assertContains(response,'συμφωνημένο όριο');self.assertEqual(self.state(),before)

    def test_receipt_form_requires_specific_charge(self):
        row=self.charge('100.00');before=self.state()
        response=self.client.post(reverse('add-income'),self.data(row,charge=''))
        self.assertEqual(response.status_code,200);self.assertIn('charge',response.context['form'].errors);self.assertEqual(self.state(),before)

    def test_income_form_posts_selected_charge_and_reports_excess_credit(self):
        row=self.charge('150.00');self.charge('350.00')
        response=self.client.post(reverse('add-income'),self.data(row,amount='200,00'),follow=True)
        self.assertEqual(response.status_code,200);self.assertContains(response,'50,00')
        self.assertEqual(CashAllocation.objects.get().charge_id,row.pk)
        self.assertEqual(cash_sources(self.member).get().available_credit,Decimal('50.00'))

    def test_exact_post_retry_after_full_payment_is_accepted(self):
        row=self.charge('100.00');data=self.data(row,amount='100,00')
        self.assertEqual(self.client.post(reverse('add-income'),data).status_code,302)
        before=self.state();self.assertEqual(self.client.post(reverse('add-income'),data).status_code,302)
        self.assertEqual(self.state(),before)

    def test_new_request_for_paid_charge_returns_error_instead_of_extra_cash(self):
        row=self.charge('100.00');self.cash(row,'100.00');before=self.state()
        response=self.client.post(reverse('add-income'),self.data(row))
        self.assertEqual(response.status_code,200);self.assertIn('charge',response.context['form'].errors);self.assertEqual(self.state(),before)

    def test_changing_charge_under_same_key_returns_error_instead_of_retargeting(self):
        first=self.charge('100.00');second=self.charge('100.00');data=self.data(first)
        self.assertEqual(self.client.post(reverse('add-income'),data).status_code,302);before=self.state()
        response=self.client.post(reverse('add-income'),data|{'charge':str(second.pk)})
        self.assertEqual(response.status_code,200);self.assertIn('charge',response.context['form'].errors);self.assertEqual(self.state(),before)

    def test_duplicate_amount_parameters_are_rejected(self):
        row=self.charge('100.00');data=QueryDict('',mutable=True)
        for key,value in self.data(row).items():data[key]=value
        data.setlist('amount',['50,00','100,00']);before=self.state()
        response=self.client.post(reverse('add-income'),data.urlencode(),content_type='application/x-www-form-urlencoded')
        self.assertEqual(response.status_code,200);self.assertIn('amount',response.context['form'].errors);self.assertEqual(self.state(),before)

    def test_options_show_only_unpaid_charges_of_the_selected_agreement(self):
        first=self.charge('100.00');paid=self.charge('100.00');self.cash(paid,'100.00');other=self.contract();outside=self.charge('100.00',agreement=other)
        before=self.state();response=self.client.get(reverse('cash-charge-options'),{'entity_id':self.customer.pk,'agreement_id':self.target.pk,'direction':'INCOME','transaction_date':DAY.isoformat()})
        self.assertEqual(response.status_code,200);self.assertEqual([r['value'] for r in response.json()['options']],[str(first.pk)])
        self.assertNotContains(response,str(outside.pk));self.assertEqual(self.state(),before)

    def test_bad_date_or_direction_options_are_clear_client_errors(self):
        args={'entity_id':self.customer.pk,'agreement_id':self.target.pk}
        for changes in ({'transaction_date':'bad-date'},{'transaction_date':(timezone.localdate()+timedelta(days=1)).isoformat()},{'direction':'TRANSFER'}):
            with self.subTest(changes=changes):self.assertEqual(self.client.get(reverse('cash-charge-options'),args|changes).status_code,400)

    def test_backdated_options_do_not_spend_capacity_already_used_by_later_receipt(self):
        row=self.charge('100.00');self.cash(row,'100.00',day=DAY+timedelta(days=1));before=self.state()
        response=self.client.get(reverse('cash-charge-options'),{'entity_id':self.customer.pk,'agreement_id':self.target.pk,
            'direction':'INCOME','transaction_date':DAY.isoformat()})
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['options'],[]);self.assertEqual(self.state(),before)

    def test_foreign_option_request_is_denied_without_names(self):
        foreign=Entity.objects.create(office=self.foreign,name='Ιδιωτικό όνομα άλλου γραφείου',entity_type='CUSTOMER')
        response=self.client.get(reverse('cash-charge-options'),{'entity_id':foreign.pk,'agreement_id':self.target.pk})
        self.assertEqual(response.status_code,404);self.assertNotContains(response,foreign.name,status_code=404)

    def test_error_dictionary_with_no_matching_field_is_rendered_as_form_error(self):
        row=self.charge('100.00')
        with patch('accounting.movement_views.post_charge_cash',side_effect=ValidationError({'unknown_reference':'Ελέγξτε τη συνδεδεμένη χρέωση.'})):
            response=self.client.post(reverse('add-income'),self.data(row))
        self.assertEqual(response.status_code,200);self.assertContains(response,'Ελέγξτε τη συνδεδεμένη χρέωση.')

    def test_owner_lowering_budget_gets_message_and_no_partial_version(self):
        self.charge('400.00');staff_client_login(self.client,self.owner);before=self.state()
        response=self.client.post(reverse('agreement-amend',args=[self.target.pk]),{'posting_key':str(uuid.uuid4()),
            'expected_revision':'1','description':'Νέοι ελεγμένοι όροι','amount':'300,00','lifecycle':'ACTIVE',
            'effective_date':timezone.localdate().isoformat(),'password':self.password,'reason':WHY})
        self.assertEqual(response.status_code,200);self.assertContains(response,'συμφωνημένο όριο');self.assertEqual(self.state(),before)


class LegacyCashCompatibilityContracts(DemandSupport,TestCase):
    def setUp(self):
        super().setUp();staff_client_login(self.client,self.member)

    def legacy_data(self,**changes):
        # This is the real pre-control payload, without either modern selector.
        return {'posting_key':str(uuid.uuid4()),'transaction_date':DAY.isoformat(),'amount':'25,00',
            'cash_account':str(self.account.pk),'category':'','entity':str(self.customer.pk),
            'agreement':str(self.agreement.pk),'description':'Δοκιμαστική παλιά σύνδεση κίνησης','remarks':''}|changes

    def test_unreviewed_uncharged_receipt_and_completed_uuid_replay_preserve_no_obligations(self):
        data=self.legacy_data(amount='100,00')
        self.assertEqual(self.client.post(reverse('add-income'),data).status_code,302)
        self.agreement.refresh_from_db();self.assertEqual(self.agreement.status,'COMPLETED')
        self.assertEqual((Charge.objects.count(),CashAllocation.objects.count(),CashChargeSelection.objects.count()),(0,0,0))
        before=self.state();self.assertEqual(self.client.post(reverse('add-income'),data).status_code,302)
        self.assertEqual(self.state(),before);self.assertEqual(Transaction.objects.count(),1)

    def test_unreviewed_uncharged_supplier_payment_preserves_original_link_without_allocating(self):
        row=Agreement.objects.create(office=self.office,entity=self.supplier,agreement_type='PAYABLE',
            description='Δοκιμαστική παλιά συμφωνία προμηθευτή',total_amount='100.00',start_date=DAY)
        response=self.client.post(reverse('add-expense'),self.legacy_data(entity=str(self.supplier.pk),agreement=str(row.pk),amount='40,00'))
        self.assertEqual(response.status_code,302);entry=Transaction.objects.get()
        self.assertEqual((entry.transaction_type,entry.agreement_id,entry.entity_id,entry.amount),('EXPENSE',row.pk,self.supplier.pk,Decimal('40.00')))
        self.assertEqual((Charge.objects.count(),CashAllocation.objects.count(),CashChargeSelection.objects.count()),(0,0,0))

    def test_old_shaped_payload_cannot_skip_selection_on_reviewed_agreement_with_or_without_charges(self):
        for charged in (False,True):
            with self.subTest(charged=charged):
                if charged:self.charge('100.00')
                before=self.state();response=self.client.post(reverse('add-income'),self.legacy_data(agreement=str(self.target.pk)))
                self.assertEqual(response.status_code,200);self.assertIn('charge',response.context['form'].errors)
                self.assertEqual(self.state(),before)

    def test_modern_empty_selection_is_not_accepted_as_legacy_even_on_unreviewed_agreement(self):
        for changes in ({'charge':''},{'settle_agreement':'on'},{'charge':'','settle_agreement':''}):
            with self.subTest(changes=changes):
                before=self.state();response=self.client.post(reverse('add-income'),self.legacy_data(**changes))
                self.assertEqual(response.status_code,200);self.assertIn('charge',response.context['form'].errors)
                self.assertEqual(self.state(),before)

    def test_locked_service_rechecks_legacy_eligibility_after_form_validation(self):
        before=self.state()
        with patch('accounting.cash_entry_forms.legacy_unbilled_agreement',return_value=True):
            response=self.client.post(reverse('add-income'),self.legacy_data(agreement=str(self.target.pk)))
        self.assertEqual(response.status_code,200);self.assertIn('charge',response.context['form'].errors)
        self.assertContains(response,'ελεγμένους όρους');self.assertEqual(self.state(),before)

    def test_changed_legacy_uuid_payload_does_not_add_cash_or_allocations(self):
        data=self.legacy_data();self.assertEqual(self.client.post(reverse('add-income'),data).status_code,302)
        before=self.state();response=self.client.post(reverse('add-income'),data|{'amount':'26,00'})
        self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
        self.assertEqual(self.state(),before);self.assertEqual(Transaction.objects.get().amount,Decimal('25.00'))
