"""Operator PostgreSQL contracts: finite budgets, dated corrections and raw writers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
import uuid
from unittest.mock import patch

from django.core.exceptions import PermissionDenied,ValidationError
from django.db import IntegrityError,close_old_connections,connection,transaction
from django.test import TestCase,TransactionTestCase
from django.utils import timezone

from .agreement_selectors import agreement_projection
from .cash_charge_services import post_charge_cash
from .charge_services import post_charge,save_terms,source_identity
from .correction_selectors import terms_on
from .correction_services import amend_agreement,correct_charge
from .finance_services import audit_context,fingerprint
from .manual_agreement_creation import create_manual
from .models import (Agreement,AgreementChange,AgreementTermsVersion,CashAllocation,CashChargeSelection,Charge,
    ChargeReversal,FinanceAuditEvent,FinanceCommand,FinanceCorrection,SettlementCommand,Transaction)
from .schema_test_support import restore_current_test_schema
from .settlement_selectors import cash_sources
from .tests_finance_posting import Fixtures,DAY

WHY='Δοκιμαστικός έλεγχος συνολικού ορίου και συγκεκριμένης χρέωσης'


class DemandSupport(Fixtures):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema();super().setUpClass()

    def setUp(self):
        self.seed();self.target=self.contract();self._owner_request=None

    def contract(self,*,amount='500.00',mode='ON_DEMAND',entity=None,direction='RECEIVABLE',start=DAY):
        row=Agreement(entity=entity or self.customer,agreement_type=direction,description='ΦΠΑ δοκιμαστικής χρήσης',
            total_amount=amount,start_date=start,status='ACTIVE')
        return create_manual(self.member,row,billing_mode=mode,reason=WHY,creation_key=uuid.uuid4())[0]

    def charge(self,amount='100.00',*,agreement=None,day=DAY,**changes):
        agreement=agreement or self.target;terms=terms_on(agreement,day) or agreement.terms_versions.first()
        args={'agreement_id':agreement.pk,'terms_revision':terms.revision,'amount':amount,
            'effective_date':day,'due_date':day+timedelta(days=5),'reason':WHY,'idempotency_key':str(uuid.uuid4())}
        return post_charge(self.member,**(args|changes))

    def owner_request(self):
        if self._owner_request is None:self._owner_request=self.request()
        return self._owner_request

    def amend(self,amount,*,day=None,agreement=None,**changes):
        row=agreement or self.target
        args={'agreement_id':row.pk,'expected_revision':row.terms_versions.first().revision,
            'description':'Επανελεγμένοι όροι δοκιμαστικής συμφωνίας','amount':amount,'lifecycle':'ACTIVE',
            'password':self.password,'effective_date':day or timezone.localdate(),'reason':WHY,'idempotency_key':str(uuid.uuid4())}
        return amend_agreement(self.owner_request(),**(args|changes))

    def correct(self,charge,*,day=DAY,amount=None,**changes):
        args={'charge_id':charge.pk,'password':self.password,'effective_date':day,'reason':WHY,
            'idempotency_key':str(uuid.uuid4()),'replacement_amount':amount,
            'replacement_due_date':day+timedelta(days=5) if amount is not None else None}
        return correct_charge(self.owner_request(),**(args|changes))

    def cash(self,charge,amount='100.00',*,day=DAY,**changes):
        args={'charge':getattr(charge,'pk',charge),'idempotency_key':str(uuid.uuid4()),'transaction_type':'INCOME',
            'transaction_date':day,'amount':amount,'cash_account':self.account,'entity':self.customer,
            'agreement':self.target,'description':'','remarks':''}
        return post_charge_cash(self.member,**(args|changes))

    def state(self):
        models=(Agreement,AgreementTermsVersion,AgreementChange,Charge,ChargeReversal,FinanceCorrection,
            Transaction,FinanceCommand,SettlementCommand,CashAllocation,CashChargeSelection,FinanceAuditEvent)
        return tuple(tuple(model.objects.order_by('pk').values_list()) for model in models)

    def rejected(self,operation,*,error=ValidationError):
        before=self.state()
        with self.assertRaises(error):operation()
        self.assertEqual(self.state(),before)

    def raw_charge(self,amount,*,day=DAY,**changes):
        terms=terms_on(self.target,day);key=fingerprint(str(uuid.uuid4()))
        values={'office':self.office,'agreement':self.target,'terms':terms,'entity':self.customer,'direction':'RECEIVABLE',
            'amount':amount,'currency':'EUR','effective_date':day,'due_date':day+timedelta(days=5),'period':None,
            'source_key':source_identity(self.target.pk,'ON_DEMAND',request_digest=key),'key_digest':key,
            'payload_digest':fingerprint('synthetic-reviewed-raw-charge'),'description':terms.description,'actor':self.member,'reason':WHY}
        with transaction.atomic(),audit_context(self.member,WHY):return Charge.objects.create(**(values|changes))


class DemandBudgetContracts(DemandSupport,TestCase):
    def test_terms_only_do_not_create_debt_or_cash(self):
        self.assertEqual((Charge.objects.count(),Transaction.objects.count()),(0,0))
        self.assertEqual(agreement_projection(self.target)['remaining_obligation'],Decimal('0.00'))

    def test_arbitrary_dates_and_amounts_can_exhaust_the_total_budget(self):
        first=self.charge('200.00');second=self.charge('300.00',day=DAY+timedelta(days=17))
        self.assertNotEqual(first.source_key,second.source_key)
        self.assertEqual(agreement_projection(self.target)['charge_total'],Decimal('500.00'))
        self.assertEqual(Transaction.objects.count(),0)

    def test_two_legitimate_charges_on_the_same_date_have_distinct_sources(self):
        self.charge('150.00');self.charge('150.00')
        self.assertEqual(Charge.objects.values('source_key').distinct().count(),2)

    def test_single_charge_over_total_budget_is_rejected_without_writes(self):
        self.rejected(lambda:self.charge('500.01'))

    def test_sum_of_charges_over_budget_is_rejected_without_writes(self):
        self.charge('300.00');self.rejected(lambda:self.charge('200.01'))

    def test_exact_remaining_cent_is_accepted(self):
        self.charge('499.99');self.charge('0.01')
        self.assertEqual(agreement_projection(self.target)['charge_total'],Decimal('500.00'))

    def test_payment_does_not_reopen_the_agreed_billing_budget(self):
        row=self.charge('500.00');self.cash(row,'500.00')
        self.rejected(lambda:self.charge('0.01'))
        self.assertEqual(agreement_projection(self.target)['remaining_obligation'],Decimal('0.00'))

    def test_partial_payment_does_not_reopen_the_billing_budget(self):
        row=self.charge('500.00');self.cash(row,'150.00')
        self.rejected(lambda:self.charge('1.00'))

    def test_reversal_frees_budget_only_from_its_effective_date(self):
        row=self.charge('500.00');self.correct(row,day=DAY+timedelta(days=5))
        self.rejected(lambda:self.charge('1.00',day=DAY+timedelta(days=4)))
        self.charge('500.00',day=DAY+timedelta(days=5))

    def test_later_reversal_cannot_hide_a_historical_budget_breach(self):
        row=self.charge('500.00');self.correct(row,day=DAY+timedelta(days=8))
        self.rejected(lambda:self.charge('100.00',day=DAY+timedelta(days=7)))

    def test_replacement_within_budget_releases_only_its_original_capacity(self):
        row=self.charge('200.00');self.charge('300.00');action=self.correct(row,amount='150.00')
        self.assertEqual(action.charge_replacement.replacement.amount,Decimal('150.00'))
        self.assertEqual(agreement_projection(self.target)['charge_total'],Decimal('450.00'))

    def test_replacement_cannot_exceed_budget_after_other_charges(self):
        row=self.charge('200.00');self.charge('300.00');self.owner_request()
        self.rejected(lambda:self.correct(row,amount='250.00'))

    def test_replacement_cannot_exceed_agreement_even_if_original_was_paid(self):
        row=self.charge('500.00');self.cash(row,'500.00');self.owner_request()
        self.rejected(lambda:self.correct(row,amount='500.01'))

    def test_terms_cannot_be_lowered_below_already_posted_charges(self):
        self.charge('350.00');self.owner_request();self.rejected(lambda:self.amend('349.99'))

    def test_terms_cannot_be_lowered_below_paid_charges(self):
        row=self.charge('500.00');self.cash(row,'500.00');self.owner_request()
        self.rejected(lambda:self.amend('400.00'))

    def test_terms_equal_to_already_posted_charges_are_accepted(self):
        self.charge('350.00');self.amend('350.00')
        self.assertEqual(terms_on(self.target).agreed_amount,Decimal('350.00'))

    def test_budget_increase_must_be_effective_before_new_charging(self):
        self.charge('500.00');future=timezone.localdate()+timedelta(days=1)
        self.amend('600.00',day=future);self.rejected(lambda:self.charge('1.00',day=timezone.localdate()))

    def test_effective_increase_allows_additional_charging(self):
        self.charge('500.00');self.amend('600.00');self.charge('100.00',day=timezone.localdate())
        self.assertEqual(agreement_projection(self.target)['charge_total'],Decimal('600.00'))

    def test_pending_lower_limit_prevents_a_new_charge_that_would_break_it(self):
        self.charge('100.00');self.amend('200.00',day=timezone.localdate()+timedelta(days=10))
        self.rejected(lambda:self.charge('150.00',day=timezone.localdate()))

    def test_full_reversal_before_reducing_terms_retains_original_history(self):
        row=self.charge('500.00');self.correct(row);self.amend('300.00')
        row.refresh_from_db();self.assertEqual(row.amount,Decimal('500.00'))
        self.assertEqual(terms_on(self.target).agreed_amount,Decimal('300.00'))

    def test_same_key_replays_once_and_changed_payload_is_rejected(self):
        key=str(uuid.uuid4());first=self.charge('200.00',idempotency_key=key)
        self.assertEqual(self.charge('200.00',idempotency_key=key).pk,first.pk)
        self.rejected(lambda:self.charge('199.00',idempotency_key=key))

    def test_nonpositive_nonfinite_and_fractional_cent_amounts_are_rejected(self):
        for amount in ('0.00','-1.00','NaN','Infinity','1.001'):
            with self.subTest(amount=amount):self.rejected(lambda:self.charge(amount))

    def test_bad_dates_period_and_stale_revision_are_rejected(self):
        for changes in ({'day':timezone.localdate()+timedelta(days=1)}, {'day':DAY-timedelta(days=1)},
                {'due_date':DAY-timedelta(days=1)}, {'period':'2026-01'}, {'terms_revision':0}):
            with self.subTest(changes=changes):self.rejected(lambda:self.charge(**changes))

    def test_cancelled_agreement_cannot_receive_new_charges(self):
        self.amend('500.00',lifecycle='CANCELLED')
        self.rejected(lambda:self.charge(day=timezone.localdate()))

    def test_revoked_accountant_cannot_post_or_replay(self):
        from .models import AccountantProfile
        key=str(uuid.uuid4());self.charge(idempotency_key=key)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        self.rejected(lambda:self.charge(idempotency_key=key),error=PermissionDenied)

    def test_monthly_price_is_not_an_annual_or_lifetime_budget(self):
        row=self.contract(amount='100.00',mode='MONTHLY',start=DAY.replace(day=1))
        self.charge('100.00',agreement=row,day=DAY.replace(day=1),period='2026-01')
        self.charge('100.00',agreement=row,day=DAY.replace(month=2,day=1),period='2026-02')
        self.assertEqual(Charge.objects.filter(agreement=row).count(),2)

    def test_partial_first_month_cannot_exceed_its_reviewed_monthly_price(self):
        row=self.contract(amount='100.00',mode='MONTHLY')
        self.rejected(lambda:self.charge('100.01',agreement=row,period='2026-01'))

    def test_existing_one_off_remains_one_full_charge(self):
        row=self.contract(mode='ONE_OFF')
        self.rejected(lambda:self.charge('100.00',agreement=row))
        self.charge('500.00',agreement=row);self.rejected(lambda:self.charge('500.00',agreement=row))

    def test_posted_terms_use_explicit_history_instead_of_plain_edit(self):
        self.charge('100.00');self.target.total_amount='50.00'
        self.rejected(lambda:save_terms(self.member,self.target,billing_mode='ON_DEMAND',lifecycle='ACTIVE',
            expected_revision=1,reason=WHY))

    def test_raw_sql_writer_cannot_exceed_remaining_budget(self):
        self.charge('450.00');self.rejected(lambda:self.raw_charge('50.01'),error=IntegrityError)

    def test_database_blocks_lower_terms_when_application_precheck_is_bypassed(self):
        self.charge('400.00');self.owner_request()
        with patch('accounting.agreement_budget.require_capacity'):
            self.rejected(lambda:self.amend('300.00'),error=IntegrityError)

    def test_database_blocks_oversized_replacement_without_partial_release(self):
        row=self.charge('500.00');self.cash(row,'100.00');self.owner_request()
        with patch('accounting.agreement_budget.replacement_capacity'):
            self.rejected(lambda:self.correct(row,amount='600.00'),error=IntegrityError)

    def test_demand_source_is_derived_from_the_request_not_the_calendar(self):
        self.rejected(lambda:self.raw_charge('100.00',source_key='agreement:'+str(self.target.pk)+':one-off'),error=IntegrityError)

    def test_raw_fractional_charge_is_denied_without_numeric_rounding(self):
        self.rejected(lambda:self.raw_charge('1.001'),error=IntegrityError)


class DemandConcurrencyContracts(DemandSupport,TransactionTestCase):
    reset_sequences=True

    def race(self,operations):
        barrier=Barrier(len(operations))
        def run(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                try:return ('ok',operation())
                except ValidationError:return ('rejected',None)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:return list(pool.map(run,operations))

    def test_concurrent_charges_cannot_overrun_the_total_budget(self):
        result=self.race([lambda:self.charge('300.00').pk,lambda:self.charge('300.00').pk])
        self.assertEqual(sorted(row[0] for row in result),['ok','rejected'])
        self.assertEqual(Charge.objects.filter(agreement=self.target).count(),1)

    def test_two_distinct_charges_within_budget_both_commit(self):
        result=self.race([lambda:self.charge('250.00').pk,lambda:self.charge('250.00').pk])
        self.assertTrue(all(row[0]=='ok' for row in result))
        self.assertEqual(agreement_projection(self.target)['charge_total'],Decimal('500.00'))

    def test_concurrent_identical_charge_key_commits_one_charge(self):
        key=str(uuid.uuid4());result=self.race([lambda:self.charge('200.00',idempotency_key=key).pk,
            lambda:self.charge('200.00',idempotency_key=key).pk])
        self.assertTrue(all(row[0]=='ok' for row in result));self.assertEqual(result[0][1],result[1][1])
        self.assertEqual(Charge.objects.filter(agreement=self.target).count(),1)

    def test_concurrent_identical_selected_receipt_has_one_effect(self):
        row=self.charge('150.00');key=str(uuid.uuid4())
        result=self.race([lambda:self.cash(row,'100.00',idempotency_key=key)[0].pk,
            lambda:self.cash(row,'100.00',idempotency_key=key)[0].pk])
        self.assertTrue(all(x[0]=='ok' for x in result));self.assertEqual(result[0][1],result[1][1])
        self.assertEqual((Transaction.objects.count(),CashChargeSelection.objects.count(),CashAllocation.objects.count()),(1,1,1))

    def test_concurrent_distinct_receipts_keep_overpayment_as_credit(self):
        row=self.charge('150.00');result=self.race([lambda:self.cash(row,'100.00')[0].pk,lambda:self.cash(row,'100.00')[0].pk])
        self.assertTrue(all(x[0]=='ok' for x in result))
        self.assertEqual(sum(CashAllocation.objects.values_list('amount',flat=True)),Decimal('150.00'))
        self.assertEqual(sum(cash_sources(self.member).values_list('available_credit',flat=True)),Decimal('50.00'))

    def test_concurrent_changed_charge_choice_under_one_key_has_one_winner(self):
        first=self.charge('100.00');second=self.charge('100.00');key=str(uuid.uuid4())
        result=self.race([lambda:self.cash(first,'50.00',idempotency_key=key)[0].pk,
            lambda:self.cash(second,'50.00',idempotency_key=key)[0].pk])
        self.assertEqual(sorted(x[0] for x in result),['ok','rejected'])
        self.assertEqual((Transaction.objects.count(),CashAllocation.objects.count(),CashChargeSelection.objects.count()),(1,1,1))
