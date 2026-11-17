"""Operator-run S29 reconciliation, scope and repeatable read contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from decimal import Decimal
import uuid
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError,close_old_connections,connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase,TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from .tests_settlements import SettlementSupport,WHY
from .tests_finance_posting import DAY
from .tests_auth_support import staff_client_login
from .account_services import adjust_opening
from .charge_services import post_charge,save_terms
from .correction_services import amend_agreement,correct_charge,correct_cash,refund_credit,reverse_refund
from .finance_services import post_cash,post_transfer
from .membership import create_accountant_profile,change_membership
from .models import Agreement,CashAccount,CashAllocation,Charge,Entity,Office,Transaction
from .report_forms import PeriodReportForm,StatementForm,AnnualReportForm
from .report_selectors import period_report,annual_report,dashboard_report,read_snapshot
from .settlement_services import allocate_cash,release_allocation


class ReportFixtures(SettlementSupport):
    def setUp(self):self.seed()

    def scenario(self):
        charge=self.obligation();source=self.cash()
        cmd=allocate_cash(self.member,**self.allocation_values(source,charge))
        return charge,source,cmd.allocations.get()

    def report(self,**changes):
        values={'start_date':DAY.replace(day=1).isoformat(),'end_date':DAY.isoformat(),'as_of':DAY.isoformat()}|changes
        return period_report(self.member,PeriodReportForm(values,user=self.member))

    def annual(self,**changes):
        values={'year':str(DAY.year),'month':'1','as_of':DAY.isoformat(),'entity':str(self.customer.pk)}|changes
        return annual_report(self.member,AnnualReportForm(values,user=self.member))

    def statement(self,**changes):
        values={'as_of':DAY.isoformat()}|changes
        return period_report(self.member,StatementForm(values,user=self.member,entity=self.customer),statement=True)

    def client_for(self,user=None):
        from django.test import Client
        client=Client();staff_client_login(client,user or self.member);return client


class ReportContracts(ReportFixtures,TestCase):
    def test_period_cash_totals_match_paged_rows_before_pagination(self):
        for _ in range(26):self.cash(amount='1.00')
        result=self.report(page_size='25')
        self.assertEqual(result['total_income'],Decimal('26.00'));self.assertEqual(result['cash_page'].paginator.count,26)
        self.assertEqual(len(result['cash_page']),25)

    def test_cash_bridge_reconciles_known_opening_and_every_leg(self):
        self.cash();post_transfer(self.member,from_account=self.account,to_account=self.other,amount='5.00',
            transfer_date=DAY,description=WHY,idempotency_key=str(uuid.uuid4()))
        result=self.report();self.assertEqual(result['total_income'],Decimal('120.00'))
        self.assertTrue(all(r['difference']==0 for r in result['cash_bridge']['rows']))
        self.assertEqual(result['cash_bridge']['known_closing_total'],Decimal('220.00'))

    def test_one_account_transfer_filter_has_zero_operating_effect(self):
        post_transfer(self.member,from_account=self.account,to_account=self.other,amount='5.00',transfer_date=DAY,description=WHY,idempotency_key=str(uuid.uuid4()))
        result=self.report(cash_account=str(self.account.pk))
        self.assertEqual((result['total_income'],result['total_expense'],result['net_for_period']),(0,0,0))
        self.assertEqual(result['cash_bridge']['rows'][0]['closing'],Decimal('95.00'))

    def test_unknown_opening_is_not_displayed_as_zero_balance(self):
        pending=CashAccount.objects.create(office=self.office,name='Ανεπιβεβαίωτο S29',opening_balance='500.00')
        result=self.report();row=next(r for r in result['cash_bridge']['rows'] if r['account'].pk==pending.pk)
        self.assertFalse(row['known']);self.assertIsNone(row['closing']);self.assertEqual(result['cash_bridge']['unknown_count'],1)

    def test_signed_adjustment_is_in_bridge_but_not_income(self):
        adjust_opening(self.request(),account_id=self.account.pk,amount='10.00',effective_date=DAY,reason=WHY,
            review_reference='Συνθετικός έλεγχος αρχικού υπολοίπου S29',password=self.password,idempotency_key=str(uuid.uuid4()))
        result=self.report(cash_account=str(self.account.pk));row=result['cash_bridge']['rows'][0]
        self.assertEqual((row['adjustments'],row['closing'],row['difference']),(Decimal('10.00'),Decimal('110.00'),0))
        self.assertEqual(result['total_income'],0)

    def test_opening_inside_period_is_included_once(self):
        result=self.report(start_date=DAY.replace(day=1).isoformat(),cash_account=str(self.account.pk))
        row=result['cash_bridge']['rows'][0];self.assertEqual((row['opening'],row['closing'],row['difference']),(100,100,0))

    def test_cash_period_and_debt_asof_have_separate_validated_cutoffs(self):
        self.cash(amount='10.00');self.cash(amount='20.00',day=DAY+timedelta(days=2))
        result=self.report(as_of=(DAY+timedelta(days=3)).isoformat())
        self.assertEqual(result['total_income'],Decimal('10.00'))
        self.assertEqual(result['customer_credit'],Decimal('30.00'))

    def test_empty_and_invalid_filters_do_not_broaden_report(self):
        self.cash();result=self.report(start_date='invalid')
        self.assertFalse(result['report_ready']);self.assertEqual(result['total_income'],0)

    def test_duplicate_asof_filter_is_denied(self):
        from django.http import QueryDict
        values=QueryDict('as_of=2026-01-15&as_of=2026-01-16')
        form=PeriodReportForm(values,user=self.member);self.assertFalse(form.is_valid());self.assertIn('as_of',form.errors)

    def test_future_asof_is_denied(self):
        for kind in (PeriodReportForm,AnnualReportForm):
            with self.subTest(kind=kind.__name__):
                form=kind({'as_of':(timezone.localdate()+timedelta(days=1)).isoformat(),'start_date':DAY.isoformat()},user=self.member)
                self.assertFalse(form.is_valid());self.assertIn('as_of',form.errors)

    def test_asof_cannot_precede_cash_period_end(self):
        form=PeriodReportForm({'as_of':DAY.isoformat(),'end_date':(DAY+timedelta(days=1)).isoformat()},user=self.member)
        self.assertFalse(form.is_valid());self.assertIn('as_of',form.errors)

    def test_entity_scope_applies_to_totals_and_every_detail_basis(self):
        charge,source,_=self.scenario();self.cash(amount='90.00',entity=self.supplier,direction='EXPENSE')
        result=self.report(entity=str(self.customer.pk))
        self.assertEqual((result['total_expense'],result['receivable_remaining'],result['customer_credit']),(0,75,95))
        self.assertEqual({r.entity_id for r in result['cash_page']},{self.customer.pk})
        self.assertEqual({r.pk for r in result['charge_page']},{charge.pk});self.assertEqual({r.pk for r in result['credit_page']},{source.pk})

    def test_category_cash_filters_do_not_relabel_unallocated_credit(self):
        self.scenario();result=self.report(category=str(self.category.pk))
        self.assertEqual(result['total_income'],0);self.assertEqual(result['customer_credit'],95)

    def test_statement_and_report_share_exact_dated_balances(self):
        self.scenario();a=self.report(entity=str(self.customer.pk));b=self.statement()
        for key in ('posted_receivable_total','receivable_allocated','receivable_remaining','customer_credit'):self.assertEqual(a[key],b[key])

    def test_allocation_release_is_dated_and_history_has_both_events(self):
        _,_,allocation=self.scenario()
        release_allocation(self.request(),**self.release_values(allocation,effective_date=DAY+timedelta(days=2)))
        before=self.statement(as_of=(DAY+timedelta(days=1)).isoformat());after=self.statement(as_of=(DAY+timedelta(days=3)).isoformat())
        self.assertEqual((before['receivable_remaining'],before['customer_credit']),(75,95))
        self.assertEqual((after['receivable_remaining'],after['customer_credit']),(100,120))
        self.assertEqual(sum(r['amount'] for r in after['event_page']),0)

    def test_release_of_an_older_allocation_is_visible_in_selected_period(self):
        _,_,allocation=self.scenario();day=DAY+timedelta(days=2)
        release_allocation(self.request(),**self.release_values(allocation,effective_date=day))
        result=self.statement(start_date=day.isoformat(),end_date=day.isoformat(),as_of=day.isoformat())
        self.assertEqual([r['amount'] for r in result['event_page']],[Decimal('-25.00')])

    def test_charge_reversal_preserves_original_and_dated_snapshot(self):
        charge,_,_=self.scenario();day=DAY+timedelta(days=2)
        correct_charge(self.request(),charge_id=charge.pk,password=self.password,effective_date=day,reason=WHY,idempotency_key=str(uuid.uuid4()))
        before=self.statement(as_of=DAY.isoformat());after=self.statement(as_of=day.isoformat())
        self.assertEqual(before['posted_receivable_total'],100);self.assertEqual(after['posted_receivable_total'],0)
        self.assertEqual(after['charge_page'][0].amount,100);self.assertTrue(after['charge_page'][0].reversed_by_day)

    def test_cancellation_retains_posted_debt(self):
        self.scenario();latest=self.agreement.terms_versions.first()
        amend_agreement(self.request(),agreement_id=self.agreement.pk,expected_revision=latest.revision,description=self.agreement.description,
            amount='100.00',lifecycle='CANCELLED',password=self.password,effective_date=timezone.localdate(),reason=WHY,idempotency_key=str(uuid.uuid4()))
        result=self.statement(as_of=timezone.localdate().isoformat());self.assertEqual(result['receivable_remaining'],75)

    def test_refund_and_refund_reversal_keep_business_direction(self):
        _,source,_=self.scenario();day=DAY+timedelta(days=1)
        action=refund_credit(self.request(),source_cash=source.pk,cash_account=self.account.pk,amount='20.00',password=self.password,
            effective_date=day,reason=WHY,idempotency_key=str(uuid.uuid4()))
        result=self.report(end_date=day.isoformat(),as_of=day.isoformat())
        self.assertEqual((result['total_income'],result['total_expense'],result['customer_credit']),(100,0,75))
        reverse_refund(self.request(),entry_id=action.refund_record.entry_id,password=self.password,effective_date=day+timedelta(days=1),reason=WHY,idempotency_key=str(uuid.uuid4()))
        result=self.report(end_date=(day+timedelta(days=1)).isoformat(),as_of=(day+timedelta(days=1)).isoformat())
        self.assertEqual((result['total_income'],result['customer_credit']),(120,95))

    def test_cash_reversal_releases_allocation_and_preserves_original(self):
        _,source,_=self.scenario();day=DAY+timedelta(days=1)
        correct_cash(self.request(),entry_id=source.pk,password=self.password,effective_date=day,reason=WHY,idempotency_key=str(uuid.uuid4()))
        result=self.report(end_date=day.isoformat(),as_of=day.isoformat())
        self.assertEqual((result['total_income'],result['receivable_remaining'],result['customer_credit']),(0,100,0))
        self.assertEqual(Transaction.objects.filter(pk=source.pk).count(),1)

    def test_annual_grid_has_twelve_actual_months_and_separate_receipts(self):
        self.scenario();result=self.annual();january=result['monthly_rows'][0]
        self.assertEqual(len(result['monthly_rows']),12)
        self.assertEqual((january['net'],january['receipts'],january['allocated'],january['remaining'],january['credit']),(100,120,25,75,95))
        self.assertTrue(all(row['gross']==0 for row in result['monthly_rows'][1:]))

    def test_annual_totals_trace_to_every_month(self):
        self.scenario();result=self.annual()
        for key,value in result['annual_totals'].items():self.assertEqual(value,sum((row[key] for row in result['monthly_rows']),Decimal('0.00')))

    def test_outside_year_bucket_reconciles_with_statement(self):
        self.scenario();older=date(DAY.year-1,12,1)
        agreement=Agreement(entity=self.customer,agreement_type='RECEIVABLE',description='Παλαιότερη αμοιβή S29',total_amount='50.00',start_date=older)
        save_terms(self.member,agreement,billing_mode='ONE_OFF',lifecycle='ACTIVE',reason=WHY)
        post_charge(self.member,agreement_id=agreement.pk,terms_revision=agreement.terms_versions.first().revision,amount='50.00',
            effective_date=older,due_date=older+timedelta(days=10),reason=WHY,idempotency_key=str(uuid.uuid4()))
        account=CashAccount.objects.create(office=self.office,name='Παλαιότερο ταμείο S29',opening_balance='0.00',opening_date=older)
        post_cash(self.member,idempotency_key=str(uuid.uuid4()),amount='20.00',transaction_date=older,transaction_type='INCOME',
            cash_account=account,entity=self.customer,description=WHY)
        result=self.annual();statement=self.statement()
        for key,snapshot_key in [('net','posted_receivable_total'),('allocated','receivable_allocated'),('remaining','receivable_remaining'),('credit','customer_credit')]:
            self.assertEqual(result['annual_totals'][key]+result['outside_year'][key],statement[snapshot_key])
        self.assertEqual((result['outside_year']['remaining'],result['outside_year']['credit']),(50,20))

    def test_annual_month_detail_matches_monthly_charge_and_credit_totals(self):
        self.scenario();result=self.annual();row=result['monthly_rows'][0]
        self.assertEqual(sum(c.net_amount for c in result['charge_page']),row['net'])
        self.assertEqual(sum(c.available_credit for c in result['credit_page']),row['credit'])
        self.assertEqual(sum(t.report_income for t in result['cash_page']),row['receipts'])

    def test_foreign_office_never_enters_report_or_annual(self):
        user=get_user_model().objects.create_user('s29-foreign');create_accountant_profile(user_id=user.pk,office_id=self.foreign.pk,role='owner')
        post_cash(user,idempotency_key=str(uuid.uuid4()),amount='999.00',transaction_date=DAY,transaction_type='INCOME',cash_account=self.foreign_account,description='Ξένη κίνηση S29')
        self.cash(amount='10.00');self.assertEqual(self.report()['total_income'],10);self.assertEqual(self.annual()['annual_totals']['receipts'],10)

    def test_foreign_filter_identifier_is_404(self):
        response=self.client_for().get(reverse('summary-report'),{'cash_account':self.foreign_account.pk})
        self.assertEqual(response.status_code,404)

    def test_foreign_statement_route_is_404(self):
        foreign=Entity.objects.create(office=self.foreign,name='Ξένη καρτέλα S29',entity_type='CUSTOMER')
        self.assertEqual(self.client_for().get(reverse('client-statement',args=[foreign.pk])).status_code,404)

    def test_statement_cannot_switch_to_another_own_entity(self):
        self.scenario();form=StatementForm({'entity':str(self.supplier.pk)},user=self.member,entity=self.customer)
        self.assertFalse(form.is_valid());self.assertIn('entity',form.errors)

    def test_dashboard_uses_the_same_posted_unpaid_balances(self):
        self.scenario();result=dashboard_report(self.member)
        self.assertEqual(result['snapshot_totals']['receivable_remaining'],75)
        self.assertEqual(result['unpaid_clients'],[{'entity_id':self.customer.pk,'entity__name':self.customer.name,'remaining':Decimal('75.00')}])

    def test_archived_clients_keep_historical_statement(self):
        self.scenario()
        from .counterparty_services import archive_counterparty
        archive_counterparty(self.member,self.customer.pk,version=0,archive=True)
        response=self.client_for().get(reverse('client-statement',args=[self.customer.pk]))
        self.assertEqual(response.status_code,200);self.assertEqual(response.context['receivable_remaining'],75)

    def test_greek_get_reports_are_private_and_write_no_financial_records(self):
        self.scenario();before=self.snapshot();counts=(Charge.objects.count(),CashAllocation.objects.count(),Transaction.objects.count())
        for name,args,text in [('summary-report',[],'Οικονομική αναφορά'),('client-statement',[self.customer.pk],'Οικονομική καρτέλα'),('fees-overview',[],'Δωδεκάμηνη εικόνα')]:
            response=self.client_for().get(reverse(name,args=args),HTTP_ACCEPT_LANGUAGE='en')
            self.assertContains(response,text);self.assertIn('no-store',response.headers['Cache-Control']);self.assertEqual(response['Content-Language'],'el')
        self.assertEqual(self.snapshot(),before);self.assertEqual((Charge.objects.count(),CashAllocation.objects.count(),Transaction.objects.count()),counts)

    def test_post_to_report_is_denied(self):
        response=self.client_for().post(reverse('fees-overview'),{})
        self.assertEqual(response.status_code,405)

    def test_revocation_denies_next_report_action(self):
        client=self.client_for();change_membership(user_id=self.member.pk,office_id=self.office.pk,role='accountant',is_active=False)
        self.assertIn(client.get(reverse('fees-overview')).status_code,(302,403))

    def test_pagination_preserves_entity_and_asof(self):
        for _ in range(26):self.cash(amount='1.00')
        response=self.client_for().get(reverse('summary-report'),{'entity':str(self.customer.pk),'as_of':DAY.isoformat(),'page_size':'25'})
        self.assertContains(response,'page=2');self.assertContains(response,'as_of=2026-01-15');self.assertEqual(response.context['total_income'],26)


class SnapshotContracts(ReportFixtures,TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        MigrationExecutor(connection).migrate([('accounting','0026_fee_generation_guards')]);super().setUpClass()

    def test_normal_snapshot_is_read_only_in_postgresql(self):
        original=self.office.name
        with self.assertRaises(DatabaseError):
            with read_snapshot(self.member):Office.objects.filter(pk=self.office.pk).update(name='Απαγορευμένη αλλαγή S29')
        self.office.refresh_from_db();self.assertEqual(self.office.name,original)

    def test_concurrent_committed_cash_does_not_split_report_snapshot(self):
        def writer():
            close_old_connections()
            try:return self.cash(amount='10.00').pk
            finally:close_old_connections()
        with read_snapshot(self.member):
            before=Transaction.objects.filter(office=self.office).count()
            with ThreadPoolExecutor(max_workers=1) as pool:key=pool.submit(writer).result(timeout=30)
            self.assertEqual(Transaction.objects.filter(office=self.office).count(),before)
        self.assertTrue(Transaction.objects.filter(pk=key).exists())
