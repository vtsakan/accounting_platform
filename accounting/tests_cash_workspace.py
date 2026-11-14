"""S19 exact dated accounts, owner approval, category retirement and real PG races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from decimal import Decimal
import copy,hashlib,json,secrets,threading,time
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import connections,connection,transaction,IntegrityError,DatabaseError
from django.db.migrations.executor import MigrationExecutor
from django.http import Http404
from django.test import TestCase,TransactionTestCase,Client
from django.urls import reverse
from django.utils import timezone
from core.redaction import register_secret
from .models import Office,CashAccount,Category,CashAdjustment,FinanceAuditEvent,FinanceCommand,Transaction,AccountantProfile
from .tests_finance_posting import Fixtures,DAY
from .tests_auth_support import staff_client_login
from .cash_selectors import cash_accounts
from .account_services import approve_opening,preview_opening,adjust_opening,save_reference
from .finance_services import post_cash,post_transfer,reverse_cash,fingerprint
from .membership import create_accountant_profile

class Support(Fixtures):
    def pending(self,**changes):
        return CashAccount.objects.create(office=self.office,name='ΔΟΚΙΜΑΣΤΙΚΟ ΑΡΧΙΚΟ '+secrets.token_hex(3),**changes)
    def proposal(self,account,amount='100.00',day=DAY):
        return preview_opening(self.owner,account_id=account.pk,amount=amount,effective_date=day)
    def approve(self,account,*,request=None,token=None,key=None,amount='100.00',day=DAY,**changes):
        if token is None:_,token=self.proposal(account,amount,day)
        values=dict(account_id=account.pk,review_token=token,amount=amount,effective_date=day,reason='Έλεγχος δοκιμαστικού αρχικού υπολοίπου',
            review_reference='Δοκιμαστική κατάσταση ταμείου',password=self.password,idempotency_key=key or secrets.token_hex(16),acknowledged=True)
        values.update(changes);return approve_opening(request or self.request(),**values)
    def adjustment(self,*,request=None,account=None,**changes):
        values=dict(account_id=(account or self.account).pk,amount='10.00',effective_date=timezone.localdate(),reason='Διόρθωση αρχικού βάσει ελέγχου',
            review_reference='Δοκιμαστικό στοιχείο αρχικού υπολοίπου',password=self.password,idempotency_key=secrets.token_hex(16))
        values.update(changes);return adjust_opening(request or self.request(),**values)
    def balance(self,account=None,day=None):
        return cash_accounts(self.member,as_of=day,include_inactive=True).get(pk=(account or self.account).pk).current_balance
    def snapshot(self):
        return (list(CashAccount.objects.order_by('pk').values()),list(Category.objects.order_by('pk').values()),
            list(Transaction.objects.order_by('pk').values()),list(CashAdjustment.objects.order_by('pk').values()),list(FinanceAuditEvent.objects.order_by('pk').values()))
    def login(self,user=None):
        from .auth_policy import state_for
        user=user or self.owner
        state=state_for(user);state.enrolled_at=timezone.now();state.save(update_fields=['enrolled_at'])
        client=Client();staff_client_login(client,user);return client
    def raw_adjust(self,amount,day=DAY,**extra):
        return CashAdjustment.objects.create(office=self.office,account=self.account,amount=amount,effective_date=day,
            reason='Δοκιμαστική τεκμηριωμένη προσαρμογή χειριστή',review_reference='Δοκιμαστικό στοιχείο ελέγχου',
            key_digest=fingerprint(secrets.token_hex(16)),payload_digest=fingerprint(secrets.token_hex(16)),**extra)

class DatedBalanceTests(Support,TestCase):
    def setUp(self):self.seed()
    def test_empty_income_only_expense_only_use_exact_zero_aggregates(self):
        self.assertEqual(self.balance(),Decimal('100.00'))
        self.post(amount='50.00',agreement=None);self.assertEqual(self.balance(),Decimal('150.00'))
        self.assertEqual(self.balance(self.other),Decimal('0.00'))
        post_cash(self.member,idempotency_key=secrets.token_hex(16),**self.values(amount='20.00',transaction_type='EXPENSE',entity=self.supplier,agreement=None,cash_account=self.other))
        self.assertEqual(self.balance(self.other),Decimal('-20.00'))
    def test_same_day_is_included_and_prior_as_of_is_unestablished(self):
        self.assertIsNone(self.balance(day=DAY-timedelta(days=1)))
        self.post(amount='50.00',agreement=None);self.assertEqual(self.balance(day=DAY),Decimal('150.00'))
    def test_pending_opening_is_not_invented_zero_and_blocks_new_cash(self):
        account=self.pending();self.assertIsNone(self.balance(account))
        before=self.snapshot()
        with self.assertRaises(ValidationError):self.post(cash_account=account)
        self.assertEqual(self.snapshot(),before)
    def test_future_and_invalid_as_of_are_greek_validation_errors(self):
        for value in (timezone.localdate()+timedelta(days=1),'2026-01-15',False):
            with self.subTest(value=value),self.assertRaises(ValidationError):cash_accounts(self.member,as_of=value)
    def test_no_cartesian_multiplication_with_cash_and_multiple_adjustments(self):
        self.post(amount='40.00',agreement=None);self.post(amount='10.00',agreement=None)
        self.raw_adjust('7.00');self.raw_adjust('-2.00')
        row=cash_accounts(self.member).get(pk=self.account.pk)
        self.assertEqual((row.total_income,row.total_expense,row.adjustment_total,row.current_balance),
            (Decimal('50.00'),Decimal('0.00'),Decimal('5.00'),Decimal('155.00')))
    def test_as_of_keeps_original_until_its_reversal_date(self):
        entry=self.post(amount='50.00',agreement=None)
        reverse_cash(self.request(),entry_id=entry.pk,password=self.password,reason='Δοκιμή χρονολογικού αντιλογισμού',
            effective_date=DAY+timedelta(days=1),idempotency_key=secrets.token_hex(16))
        self.assertEqual(self.balance(day=DAY),Decimal('150.00'))
        self.assertEqual(self.balance(day=DAY+timedelta(days=1)),Decimal('100.00'))
    def test_adjustment_and_inverse_are_dated_separate_from_operating_cash(self):
        original=self.raw_adjust('7.00',DAY+timedelta(days=1))
        self.raw_adjust('-7.00',DAY+timedelta(days=2),reversal_of=original)
        self.assertEqual(self.balance(day=DAY),Decimal('100.00'))
        self.assertEqual(self.balance(day=DAY+timedelta(days=1)),Decimal('107.00'))
        self.assertEqual(self.balance(day=DAY+timedelta(days=2)),Decimal('100.00'))
        self.assertEqual(Transaction.objects.count(),0);self.assertEqual(FinanceCommand.objects.count(),0)
    def test_transfer_changes_accounts_but_not_total_office_cash(self):
        post_transfer(self.member,from_account=self.account,to_account=self.other,amount='20.00',transfer_date=DAY,
            description='Δοκιμαστική μεταφορά',idempotency_key=secrets.token_hex(16))
        self.assertEqual(self.balance(),Decimal('80.00'));self.assertEqual(self.balance(self.other),Decimal('20.00'))
    def test_inactive_history_remains_available_but_new_work_is_denied(self):
        entry=self.post(agreement=None);self.account.refresh_from_db();self.account.is_active=False;save_reference(self.account,self.member)
        self.assertEqual(self.balance(),Decimal('125.00'));self.assertFalse(cash_accounts(self.member).filter(pk=self.account.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=entry.pk).exists())
        with self.assertRaises(ValidationError):self.post(agreement=None)
    def test_selectors_never_return_foreign_office_accounts(self):
        self.assertFalse(cash_accounts(self.owner,include_inactive=True).filter(pk=self.foreign_account.pk).exists())
        with self.assertRaises(PermissionDenied):cash_accounts(get_user_model().objects.create_user('s19-no-profile'))
    def test_preopening_cash_is_denied_in_service_and_sql(self):
        before=self.snapshot()
        with self.assertRaises(ValidationError):self.post(transaction_date=DAY-timedelta(days=1))
        with self.assertRaises(IntegrityError),transaction.atomic():
            Transaction.objects.bulk_create([Transaction(office=self.office,cash_account=self.account,amount='5.00',transaction_type='INCOME',
                transaction_date=DAY-timedelta(days=1),description='ΔΟΚΙΜΑΣΤΙΚΗ ΠΡΟΓΕΝΕΣΤΕΡΗ ΚΙΝΗΣΗ')])
        self.assertEqual(self.snapshot(),before)
    def test_dashboard_and_detail_share_same_selector_values(self):
        self.post(amount='50.00',agreement=None);client=self.login(self.member)
        dash=client.get('/');detail=client.get(reverse('cash-account-detail',args=[self.account.pk]))
        self.assertEqual(dash.status_code,200);self.assertEqual(detail.status_code,200)
        row=next(a for a in dash.context['cash_accounts'] if a.pk==self.account.pk)
        self.assertEqual(row.current_balance,detail.context['account'].current_balance)
        self.assertContains(detail,'150,00 €')

class OpeningApprovalTests(Support,TestCase):
    def setUp(self):self.seed();self.account_pending=self.pending()
    def test_creation_is_pending_and_owner_approval_sets_one_reviewed_opening(self):
        account=save_reference(CashAccount(name='Νέο δοκιμαστικό ταμείο'),self.member)
        self.assertIsNone(account.opening_date);self.assertEqual(account.opening_balance,Decimal('0.00'))
        result=self.approve(account)
        self.assertEqual((result.opening_date,result.opening_balance),(DAY,Decimal('100.00')))
        self.assertIsNotNone(result.opening_approved_at);self.assertEqual(self.balance(account),Decimal('100.00'))
        event=FinanceAuditEvent.objects.filter(target_model='cashaccount',target_id=account.pk,operation='account.opening.approve').get()
        self.assertEqual(event.actor_id,self.owner.pk);self.assertEqual(event.after['opening_date'],DAY.isoformat())
    def test_signed_negative_opening_is_approved_exactly_and_not_an_expense(self):
        account=self.approve(self.account_pending,amount='-12.34')
        self.assertEqual(self.balance(account),Decimal('-12.34'));self.assertEqual(Transaction.objects.count(),0)
    def test_zero_opening_is_approved_without_fake_receipt(self):
        self.approve(self.account_pending,amount='0.00');self.assertEqual(self.balance(self.account_pending),Decimal('0.00'))
        self.assertEqual(Transaction.objects.count(),0)
    def test_approval_requires_owner_password_recent_mfa_and_explicit_acknowledgement(self):
        _,token=self.proposal(self.account_pending);before=self.snapshot()
        with self.assertRaises(PermissionDenied):self.approve(self.account_pending,request=self.request(self.member),token=token)
        with self.assertRaises(ValidationError):self.approve(self.account_pending,token=token,password='incorrect')
        with self.assertRaises(ValidationError):self.approve(self.account_pending,token=token,acknowledged=False)
        stale=self.request();stale.session['s13_mfa_at']=0
        with self.assertRaises(ValidationError):self.approve(self.account_pending,request=stale,token=token)
        self.assertEqual(self.snapshot(),before)
    def test_approval_retry_is_exact_and_changed_request_cannot_overwrite(self):
        _,token=self.proposal(self.account_pending);key=secrets.token_hex(16)
        first=self.approve(self.account_pending,token=token,key=key);before=self.snapshot()
        second=self.approve(self.account_pending,token=token,key=key)
        self.assertEqual(first.pk,second.pk);self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ValidationError):self.approve(self.account_pending,token=token,key=key,amount='99.00')
        self.assertEqual(self.snapshot(),before)
    def test_tampered_stale_expired_and_foreign_review_tokens_fail_without_writes(self):
        _,token=self.proposal(self.account_pending);before=self.snapshot()
        with self.assertRaises(ValidationError):self.approve(self.account_pending,token=token+'x')
        other=self.pending();_,other_token=self.proposal(other)
        with self.assertRaises(ValidationError):self.approve(self.account_pending,token=other_token)
        plan,_=self.proposal(self.account_pending)
        with patch('django.core.signing.time.time',return_value=time.time()-1000):
            expired=signing.dumps(plan,salt='accounting.s19.opening-review',compress=True)
        with self.assertRaisesMessage(ValidationError,'έληξε'):self.approve(self.account_pending,token=expired)
        self.account_pending.name='Δοκιμαστική αλλαγή μετά την προεπισκόπηση';save_reference(self.account_pending,self.member)
        before=self.snapshot()
        with self.assertRaises(ValidationError):self.approve(self.account_pending,token=token)
        self.assertEqual(self.snapshot(),before)
    def test_legacy_amount_cannot_be_rewritten_when_reviewing_date(self):
        account=self.pending(opening_balance='100.00',legacy_opening=True)
        with self.assertRaises(ValidationError):self.proposal(account,amount='99.00')
        self.approve(account,amount='100.00');account.refresh_from_db()
        self.assertEqual(account.opening_balance,Decimal('100.00'));self.assertTrue(account.legacy_opening)
    def test_approved_opening_cannot_change_by_service_model_bulk_or_sql(self):
        account=self.approve(self.account_pending)
        account.opening_balance=Decimal('99.00')
        with self.assertRaises(ValidationError):save_reference(account,self.owner)
        for changes in ({'opening_balance':'99.00'},{'opening_date':DAY+timedelta(days=1)},{'opening_date':None},{'legacy_opening':True}):
            with self.subTest(changes=changes),self.assertRaises(IntegrityError),transaction.atomic():CashAccount.objects.filter(pk=account.pk).update(**changes)
    def test_approval_audit_failure_rolls_back_its_account_change(self):
        _,token=self.proposal(self.account_pending);before=self.snapshot()
        # Audit observes an inactive actor and must reject the entire approval.
        from .finance_services import audit_context
        def rejected(*args,**kwargs):
            get_user_model().objects.filter(pk=self.owner.pk).update(is_active=False)
            return audit_context(*args,**kwargs)
        with patch('accounting.account_services.audit_context',side_effect=rejected),self.assertRaises(IntegrityError),transaction.atomic():self.approve(self.account_pending,token=token)
        self.assertEqual(self.snapshot(),before);self.owner.refresh_from_db();self.assertTrue(self.owner.is_active)
    def test_account_names_are_unique_per_office_and_stale_edits_fail(self):
        with self.assertRaises(ValidationError):save_reference(CashAccount(name=self.account.name),self.member)
        left=CashAccount.objects.get(pk=self.account.pk);right=CashAccount.objects.get(pk=self.account.pk)
        left.name='Νέο όνομα δοκιμαστικού ταμείου';save_reference(left,self.member)
        right.name='Παλιό αίτημα αλλαγής'
        with self.assertRaises(ValidationError):save_reference(right,self.member)
    def test_used_account_cannot_be_deleted_in_model_queryset_or_sql(self):
        entry=self.post()
        with self.assertRaises(ValidationError):self.account.delete()
        with self.assertRaises(IntegrityError),transaction.atomic():CashAccount.objects.filter(pk=self.account.pk).delete()
        with self.assertRaises(IntegrityError),transaction.atomic():
            with connection.cursor() as cursor:cursor.execute('DELETE FROM accounting_cashaccount WHERE id=%s',[self.account.pk])
        self.assertTrue(Transaction.objects.filter(pk=entry.pk).exists())
    def test_normal_staff_and_admin_cannot_submit_an_opening_through_metadata(self):
        with self.assertRaises(ValidationError):save_reference(CashAccount(name='Ανεπίτρεπτη αρχική έγκριση',opening_balance='10.00',opening_date=DAY),self.member)
        client=self.login(self.member)
        response=client.post(reverse('cash-account-add'),{'name':'Νέο μέσω HTTP','is_active':'on','version':0,'opening_balance':'999,00','opening_date':'2026-01-01','office_id':str(self.foreign.pk)})
        self.assertEqual(response.status_code,302);account=CashAccount.objects.get(name='Νέο μέσω HTTP')
        self.assertEqual(account.office_id,self.office.pk);self.assertEqual(account.opening_balance,Decimal('0.00'));self.assertIsNone(account.opening_date)

class AdjustmentTests(Support,TestCase):
    def setUp(self):self.seed()
    def test_raw_sql_rejects_zero_overprecision_and_out_of_range_adjustments(self):
        for amount in ('0','0.001','12.345','10000000000.00'):
            with self.subTest(amount=amount),self.assertRaises(IntegrityError),transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO accounting_cashadjustment (office_id,account_id,amount,effective_date,reason,review_reference,key_digest,payload_digest,recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())',
                        [self.office.pk,self.account.pk,Decimal(amount),DAY,'Δοκιμαστική προσαρμογή SQL','Δοκιμαστικό στοιχείο',fingerprint(secrets.token_hex(16)),fingerprint(secrets.token_hex(16))])
        self.assertEqual(CashAdjustment.objects.count(),0)
    def test_signed_adjustment_is_attributable_and_keeps_original_cash_columns(self):
        self.account.refresh_from_db();original=(self.account.opening_balance,self.account.opening_date)
        entry=self.adjustment(amount='-7.34');self.account.refresh_from_db()
        self.assertEqual((self.account.opening_balance,self.account.opening_date),original)
        self.assertEqual(self.balance(),Decimal('92.66'));self.assertEqual(Transaction.objects.count(),0)
        event=FinanceAuditEvent.objects.get(target_model='cashadjustment',target_id=entry.pk)
        self.assertEqual(event.actor_id,self.owner.pk);self.assertEqual(event.effective_date,timezone.localdate());self.assertEqual(event.after['amount'],'-7.34')
    def test_adjustment_retry_has_one_row_and_changed_payload_conflicts(self):
        key=secrets.token_hex(16);first=self.adjustment(idempotency_key=key);before=self.snapshot()
        self.assertEqual(self.adjustment(idempotency_key=key).pk,first.pk);self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ValidationError):self.adjustment(idempotency_key=key,amount='11.00')
        self.assertEqual(self.snapshot(),before)
    def test_adjustment_reversal_is_exact_linked_single_use_and_retryable(self):
        original=self.adjustment(amount='12.34');key=secrets.token_hex(16)
        inverse=self.adjustment(reversal_of_id=original.pk,amount='999.00',idempotency_key=key)
        self.assertEqual(inverse.amount,Decimal('-12.34'));self.assertEqual(self.balance(),Decimal('100.00'))
        self.assertEqual(self.adjustment(reversal_of_id=original.pk,idempotency_key=key).pk,inverse.pk)
        with self.assertRaises(ValidationError):self.adjustment(reversal_of_id=original.pk)
        with self.assertRaises(ValidationError):self.adjustment(reversal_of_id=inverse.pk)
    def test_owner_recent_mfa_and_review_reference_are_required_for_adjustment(self):
        before=self.snapshot()
        with self.assertRaises(PermissionDenied):self.adjustment(request=self.request(self.member))
        with self.assertRaises(ValidationError):self.adjustment(password='incorrect')
        with self.assertRaises(ValidationError):self.adjustment(review_reference='')
        stale=self.request();stale.session['s13_mfa_at']=0
        with self.assertRaises(ValidationError):self.adjustment(request=stale)
        self.assertEqual(self.snapshot(),before)
    def test_no_historical_or_future_ordinary_adjustment_can_restate_prior_days(self):
        before=self.snapshot()
        for day in (DAY,timezone.localdate()+timedelta(days=1)):
            with self.subTest(day=day),self.assertRaises(ValidationError):self.adjustment(effective_date=day)
        self.assertEqual(self.snapshot(),before)
    def test_zero_float_overprecision_and_nonfinite_adjustments_fail(self):
        before=self.snapshot()
        for amount in ('0','0.001','NaN','Infinity',1.0,True):
            with self.subTest(amount=amount),self.assertRaises(ValidationError):self.adjustment(amount=amount)
        self.assertEqual(self.snapshot(),before)
    def test_adjustment_is_immutable_even_for_operator_and_sql(self):
        entry=self.adjustment()
        with self.assertRaises(ValidationError):entry.save()
        with self.assertRaises(ValidationError):entry.delete()
        for action in (lambda:CashAdjustment.objects.filter(pk=entry.pk).update(amount='1.00'),lambda:CashAdjustment.objects.filter(pk=entry.pk).delete()):
            with self.assertRaises(IntegrityError),transaction.atomic():action()
    def test_adjustment_foreign_account_source_or_actor_never_cross_office(self):
        before=self.snapshot()
        with self.assertRaises(ValidationError):self.adjustment(account=self.foreign_account)
        entry=self.raw_adjust('2.00')
        with self.assertRaises(ValidationError):self.adjustment(account=self.other,reversal_of_id=entry.pk)
        self.assertEqual(CashAdjustment.objects.count(),1)
    def test_adjustment_secret_values_are_redacted_from_source_and_audit(self):
        canary=secrets.token_urlsafe(32);register_secret(canary)
        entry=self.adjustment(reason='Διόρθωση με password='+canary,review_reference='Αναφορά token='+canary)
        text=json.dumps(list(CashAdjustment.objects.values()),default=str)+json.dumps(list(FinanceAuditEvent.objects.filter(target_id=entry.pk,target_model='cashadjustment').values()),default=str)
        self.assertNotIn(canary,text);self.assertIn('[REDACTED]',text)
    def test_adjustment_audit_write_failure_rolls_back_every_effect(self):
        before=self.snapshot()
        with patch('accounting.account_services.audit_context'),self.assertRaises(IntegrityError),transaction.atomic():self.adjustment()
        self.assertEqual(self.snapshot(),before)

class CategoryHierarchyTests(Support,TestCase):
    def setUp(self):self.seed()
    def test_depth_ceiling_is_the_same_for_model_validation_and_raw_sql(self):
        parent=self.category
        for level in range(2,65):
            parent=Category.objects.create(office=self.office,parent=parent,name='Δοκιμαστικό επίπεδο '+str(level))
        with self.assertRaises(ValidationError):Category.objects.create(office=self.office,parent=parent,name='Υπερβολικό βάθος')
        with self.assertRaises(IntegrityError),transaction.atomic():
            Category.objects.bulk_create([Category(office=self.office,parent=parent,name='Υπερβολικό βάθος SQL')])
    def test_parent_is_same_office_and_cycle_is_rejected_by_service_and_sql(self):
        child=Category.objects.create(office=self.office,name='Δοκιμαστική υποκατηγορία',parent=self.category)
        self.category.parent=child
        with self.assertRaises(ValidationError):save_reference(self.category,self.member)
        with self.assertRaises(IntegrityError),transaction.atomic():Category.objects.filter(pk=self.category.pk).update(parent=child)
        with self.assertRaises(IntegrityError),transaction.atomic():Category.objects.filter(pk=child.pk).update(parent_id=child.pk)
    def test_foreign_parent_fails_even_on_bulk_sql_insertion(self):
        foreign=Category.objects.create(office=self.foreign,name='Ξένη δοκιμαστική κατηγορία')
        with self.assertRaises(ValidationError):save_reference(Category(office=self.office,name='Λάθος γονική',parent=foreign),self.member)
        with self.assertRaises(IntegrityError),transaction.atomic():Category.objects.bulk_create([Category(office=self.office,name='Απορριπτέα κατηγορία',parent=foreign)])
    def test_retire_children_first_then_parent_keep_history_and_allow_safe_restore(self):
        child=Category.objects.create(office=self.office,name='Δοκιμαστικό παιδί',parent=self.category)
        self.category.is_active=False
        with self.assertRaises(ValidationError):save_reference(self.category,self.member)
        child.is_active=False;save_reference(child,self.member);save_reference(self.category,self.member)
        child.is_active=True
        with self.assertRaises(ValidationError):save_reference(child,self.member)
        self.category.is_active=True;save_reference(self.category,self.member);save_reference(child,self.member)
        self.assertTrue(Category.objects.get(pk=child.pk).is_active)
    def test_retired_category_is_excluded_from_forms_admin_and_new_cash_but_reversal_keeps_reference(self):
        original=self.post();self.category.is_active=False;save_reference(self.category,self.member)
        client=self.login(self.member);response=client.get('/income/add/')
        self.assertFalse(response.context['form'].fields['category'].queryset.filter(pk=self.category.pk).exists())
        with self.assertRaises(ValidationError):self.post()
        reverse_cash(self.request(),entry_id=original.pk,password=self.password,reason='Δοκιμή διατηρημένης παλιάς κατηγορίας',effective_date=DAY,idempotency_key=secrets.token_hex(16))
        self.assertEqual(Transaction.objects.filter(category=self.category).count(),2)
    def test_category_rename_and_reparent_never_change_money_or_transaction_link(self):
        entry=self.post();before=(entry.amount,entry.category_id,entry.agreement_id)
        parent=Category.objects.create(office=self.office,name='Νέα δοκιμαστική γονική')
        self.category.name='Νέα δοκιμαστική ονομασία';self.category.parent=parent;save_reference(self.category,self.member)
        entry.refresh_from_db();self.assertEqual((entry.amount,entry.category_id,entry.agreement_id),before)
        audit=FinanceAuditEvent.objects.filter(target_model='category',target_id=self.category.pk,origin='user').first()
        self.assertEqual(audit.actor_id,self.member.pk);self.assertEqual(audit.after['parent_id'],parent.pk)
    def test_hierarchy_identity_is_retained_by_model_and_database(self):
        with self.assertRaises(ValidationError):self.category.delete()
        with self.assertRaises(IntegrityError),transaction.atomic():Category.objects.filter(pk=self.category.pk).delete()
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())
    def test_root_and_sibling_names_are_unique_per_office(self):
        with self.assertRaises(IntegrityError),transaction.atomic():Category.objects.bulk_create([Category(office=self.office,name=self.category.name)])
        Category.objects.create(office=self.foreign,name=self.category.name)
        parent=Category.objects.create(office=self.office,name='Δοκιμαστική γονική')
        Category.objects.create(office=self.office,name='Κοινό όνομα παιδιού',parent=parent)
        with self.assertRaises(IntegrityError),transaction.atomic():Category.objects.bulk_create([Category(office=self.office,name='Κοινό όνομα παιδιού',parent=parent)])
    def test_stale_category_update_cannot_overwrite_newer_metadata(self):
        left=Category.objects.get(pk=self.category.pk);right=Category.objects.get(pk=self.category.pk)
        left.name='Νεότερη δοκιμαστική ονομασία';save_reference(left,self.member)
        right.name='Παλιό αίτημα'
        with self.assertRaises(ValidationError):save_reference(right,self.member)
        self.assertEqual(Category.objects.get(pk=self.category.pk).name,left.name)

class WorkspaceHTTPTests(Support,TestCase):
    def setUp(self):self.seed()
    def test_greek_navigation_lists_and_pending_opening_do_not_display_fabricated_zero(self):
        pending=self.pending();client=self.login(self.member)
        response=client.get('/');self.assertEqual(response.status_code,200)
        self.assertContains(response,'Ταμεία');self.assertContains(response,'Κατηγορίες');self.assertContains(response,'Αναμονή αρχικού υπολοίπου')
        response=client.get(reverse('cash-account-list'));self.assertEqual(response.headers['Content-Language'],'el')
        self.assertContains(response,pending.name);self.assertNotContains(response,self.foreign_account.name)
    def test_metadata_edit_version_and_foreign_ids_are_enforced(self):
        client=self.login(self.member);url=reverse('cash-account-edit',args=[self.account.pk])
        response=client.post(url,{'name':'Ταμείο δοκιμαστικής αλλαγής','is_active':'on','version':0,'office_id':str(self.foreign.pk)})
        self.assertEqual(response.status_code,302);self.account.refresh_from_db();self.assertEqual(self.account.office_id,self.office.pk)
        response=client.post(url,{'name':'Παλιό αίτημα','is_active':'on','version':0});self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
        for route in ('cash-account-detail','cash-account-edit','cash-account-opening','cash-account-adjustment'):
            for user in (self.owner,self.member):
                response=self.login(user).get(reverse(route,args=[self.foreign_account.pk]))
                self.assertEqual(response.status_code,403 if user.pk==self.member.pk and route in {'cash-account-opening','cash-account-adjustment'} else 404)
    def test_opening_preview_is_read_only_and_confirm_uses_bound_review_with_real_mfa(self):
        account=self.pending();client=self.login();url=reverse('cash-account-opening',args=[account.pk])
        form=client.get(url).context['form']
        values={'amount':'100,00','effective_date':DAY.isoformat(),'reason':'Αρχική δοκιμαστική επιβεβαίωση','review_reference':'Δοκιμαστική κατάσταση',
            'idempotency_key':str(form['idempotency_key'].value()),'action':'preview'}
        before=self.snapshot();response=client.post(url,values);self.assertEqual(response.status_code,200);self.assertIsNotNone(response.context['proposal'])
        self.assertContains(response,'0,00 €');self.assertIsInstance(response.context['proposal']['excluded_net_amount'],Decimal)
        self.assertEqual(self.snapshot(),before)
        values.update(action='confirm',password=self.password,acknowledged='on',review_token=response.context['form']['review_token'].value())
        response=client.post(url,values);self.assertEqual(response.status_code,302)
        account.refresh_from_db();self.assertEqual(account.opening_balance,Decimal('100.00'));self.assertEqual(account.opening_date,DAY)
        before=self.snapshot();self.assertEqual(client.post(url,values).status_code,302);self.assertEqual(self.snapshot(),before)
    def test_opening_confirm_rejects_changed_amount_or_forged_office_context(self):
        account=self.pending();client=self.login();_,token=self.proposal(account)
        before=self.snapshot();response=client.post(reverse('cash-account-opening',args=[account.pk]),{
            'amount':'999,00','effective_date':DAY.isoformat(),'reason':'Δοκιμή αλλαγής ορίου','review_reference':'Δοκιμαστική κατάσταση','password':self.password,
            'idempotency_key':str(__import__('uuid').uuid4()),'action':'confirm','acknowledged':'on','review_token':token,'office_id':str(self.foreign.pk)})
        self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors);self.assertEqual(self.snapshot(),before)
    def test_adjustment_and_reversal_http_use_owner_proof_and_separate_source(self):
        client=self.login();url=reverse('cash-account-adjustment',args=[self.account.pk]);form=client.get(url).context['form']
        values={'amount':'5,00','effective_date':timezone.localdate().isoformat(),'reason':'Διόρθωση δοκιμαστικού αρχικού','review_reference':'Δοκιμαστική κατάσταση',
            'password':self.password,'idempotency_key':str(form['idempotency_key'].value())}
        self.assertEqual(client.post(url,values).status_code,302);entry=CashAdjustment.objects.get()
        form=client.get(url,{'reverse':entry.pk}).context['form'];values.update(amount='999,00',reversal_of_id=entry.pk,idempotency_key=str(form['idempotency_key'].value()))
        self.assertEqual(client.post(url,values).status_code,302);self.assertEqual(self.balance(),Decimal('100.00'))
        self.assertEqual(Transaction.objects.count(),0)
    def test_category_create_retire_stale_version_and_scoped_choices(self):
        client=self.login(self.member);foreign=Category.objects.create(office=self.foreign,name='Ξένη κατηγορία HTTP')
        response=client.get(reverse('category-add'));self.assertFalse(response.context['form'].fields['parent'].queryset.filter(pk=foreign.pk).exists())
        response=client.post(reverse('category-add'),{'name':'Υποκατηγορία HTTP','parent':self.category.pk,'is_active':'on','version':0})
        self.assertEqual(response.status_code,302);child=Category.objects.get(name='Υποκατηγορία HTTP')
        self.assertEqual(child.office_id,self.office.pk)
        url=reverse('category-retire',args=[child.pk]);self.assertEqual(client.get(url).status_code,200);self.assertTrue(Category.objects.get(pk=child.pk).is_active)
        self.assertEqual(client.post(url,{'version':0,'active':''}).status_code,302)
        self.assertFalse(Category.objects.get(pk=child.pk).is_active)
        response=client.post(url,{'version':0,'active':'on'});self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
    def test_unsafe_parent_choice_and_guessed_adjustment_id_do_not_leak(self):
        child=Category.objects.create(office=self.office,name='Δοκιμαστική θυγατρική',parent=self.category)
        client=self.login(self.member)
        form=client.get(reverse('category-edit',args=[self.category.pk])).context['form']
        self.assertFalse(form.fields['parent'].queryset.filter(pk__in=[self.category.pk,child.pk]).exists())
        response=self.login().get(reverse('cash-account-adjustment',args=[self.account.pk]),{'reverse':'not-an-id'})
        self.assertEqual(response.status_code,404)
    def test_bad_dates_and_state_filters_return_greek_errors_without_mutation(self):
        client=self.login(self.member);before=self.snapshot()
        response=client.get(reverse('cash-account-detail',args=[self.account.pk]),{'as_of':'2026-02-30'})
        self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
        response=client.get(reverse('cash-account-list'),{'state':'injected'});self.assertEqual(response.status_code,200);self.assertContains(response,'δεν είναι έγκυρη')
        self.assertEqual(self.snapshot(),before)
    def test_workspace_posts_require_csrf_and_anonymous_or_inactive_members_are_denied(self):
        client=Client(enforce_csrf_checks=True);staff_client_login(client,self.member)
        before=self.snapshot();self.assertEqual(client.post(reverse('cash-account-add'),{'name':'Ανεπίτρεπτη καταχώριση','version':0}).status_code,403)
        self.assertEqual(Client().get(reverse('cash-account-list')).status_code,302)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        self.assertEqual(client.get(reverse('category-list')).status_code,403);self.assertEqual(self.snapshot(),before)

class WorkspaceConcurrencyTests(Support,TransactionTestCase):
    def setUp(self):self.seed()
    def race(self,functions):
        barrier=threading.Barrier(len(functions));pids=[];lock=threading.Lock()
        def worker(fn):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'");cursor.execute('SELECT pg_backend_pid()')
                    with lock:pids.append(cursor.fetchone()[0])
                barrier.wait(timeout=6)
                try:return ('ok',fn())
                except (ValidationError,PermissionDenied,IntegrityError) as error:return ('denied',type(error).__name__)
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            results=[future.result(timeout=15) for future in [pool.submit(worker,fn) for fn in functions]]
        self.assertEqual(len(set(pids)),len(functions));return results
    def test_same_opening_retry_in_independent_connections_creates_one_approval(self):
        account=self.pending();_,token=self.proposal(account);key=secrets.token_hex(16)
        requests=[self.request(),self.request()]
        results=self.race([lambda r=r:self.approve(account,request=r,token=token,key=key).pk for r in requests])
        self.assertEqual([status for status,_ in results],['ok','ok']);self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(FinanceAuditEvent.objects.filter(target_model='cashaccount',target_id=account.pk,operation='account.opening.approve').count(),1)
    def test_same_adjustment_retry_and_changed_payload_race_are_exact(self):
        key=secrets.token_hex(16);requests=[self.request(),self.request()]
        results=self.race([lambda r=r:self.adjustment(request=r,idempotency_key=key).pk for r in requests])
        self.assertEqual([status for status,_ in results],['ok','ok']);self.assertEqual(results[0][1],results[1][1])
        self.assertEqual(CashAdjustment.objects.count(),1)
        key=secrets.token_hex(16)
        results=self.race([lambda i=i:self.adjustment(request=requests[i],idempotency_key=key,amount=str(11+i)+'.00').pk for i in range(2)])
        self.assertEqual(sorted(status for status,_ in results),['denied','ok']);self.assertEqual(CashAdjustment.objects.count(),2)
        self.assertEqual(FinanceAuditEvent.objects.filter(target_model='cashadjustment').count(),2)
    def test_two_independent_inverse_requests_create_only_one_linked_inverse(self):
        original=self.adjustment();requests=[self.request(),self.request()]
        results=self.race([lambda r=r:self.adjustment(request=r,reversal_of_id=original.pk).pk for r in requests])
        self.assertEqual(sorted(status for status,_ in results),['denied','ok'])
        self.assertEqual(CashAdjustment.objects.filter(reversal_of=original).count(),1);self.assertEqual(self.balance(),Decimal('100.00'))
    def test_stale_metadata_requests_do_not_silently_overwrite(self):
        left=CashAccount.objects.get(pk=self.account.pk);right=CashAccount.objects.get(pk=self.account.pk)
        left.name='Δοκιμαστική ταυτόχρονη αλλαγή Α';right.name='Δοκιμαστική ταυτόχρονη αλλαγή Β'
        results=self.race([lambda a=a:save_reference(a,self.member).pk for a in (left,right)])
        self.assertEqual(sorted(status for status,_ in results),['denied','ok'])
        self.account.refresh_from_db();self.assertEqual(self.account.record_version,1)
    def cycle_race(self,isolation):
        left=Category.objects.create(office=self.office,name='Ανεξάρτητη ρίζα Α')
        right=Category.objects.create(office=self.office,name='Ανεξάρτητη ρίζα Β')
        barrier=threading.Barrier(2);pids=[];lock=threading.Lock()
        def update(source,target):
            connections.close_all()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL '+isolation)
                        cursor.execute("SET LOCAL lock_timeout='8s'")
                        cursor.execute('SELECT pg_backend_pid(),count(*) OVER() FROM accounting_category LIMIT 1')
                        with lock:pids.append(cursor.fetchone()[0])
                        barrier.wait(timeout=6)
                        cursor.execute('UPDATE accounting_category SET parent_id=%s WHERE id=%s',[target,source])
                return 'ok'
            except DatabaseError as error:
                self.assertIn(getattr(error.__cause__,'sqlstate',None),{'23514','40001','40P01'})
                return 'denied'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(update,left.pk,right.pk),pool.submit(update,right.pk,left.pk)]
            result=[f.result(timeout=15) for f in futures]
        self.assertEqual(len(set(pids)),2);self.assertEqual(sorted(result),['denied','ok'])
        left.refresh_from_db();right.refresh_from_db();self.assertFalse(left.parent_id==right.pk and right.parent_id==left.pk)
    def test_raw_sql_hierarchy_write_skew_is_prevented_at_read_committed(self):self.cycle_race('READ COMMITTED')
    def test_raw_sql_hierarchy_write_skew_is_prevented_at_repeatable_read(self):self.cycle_race('REPEATABLE READ')
    def wait_blocked(self,pid):
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT cardinality(pg_blocking_pids(%s))',[pid])
                if cursor.fetchone()[0]:return
            time.sleep(.02)
        self.fail('Independent PostgreSQL writer did not enter a real lock wait')
    def test_owner_revocation_while_waiting_blocks_adjustment_and_its_audit(self):
        backup=get_user_model().objects.create_user('s19-second-owner')
        create_accountant_profile(user_id=backup.pk,office_id=self.office.pk,role='owner')
        request=self.request();before=self.snapshot();held=threading.Event();release=threading.Event();ready=threading.Event();pids=[]
        def revoke():
            connections.close_all()
            try:
                with transaction.atomic():
                    Office.objects.select_for_update().get(pk=self.office.pk)
                    AccountantProfile.objects.filter(user=self.owner).update(is_active=False)
                    held.set()
                    if not release.wait(8):raise AssertionError('Release not signalled')
            finally:connections.close_all()
        def adjust():
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'");cursor.execute('SELECT pg_backend_pid()');pids.append(cursor.fetchone()[0]);ready.set()
                try:self.adjustment(request=request)
                except PermissionDenied:return 'denied'
                return 'created'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoker=pool.submit(revoke)
            try:
                self.assertTrue(held.wait(6));writer=pool.submit(adjust);self.assertTrue(ready.wait(6));self.wait_blocked(pids[0])
            finally:release.set()
            revoker.result(timeout=8);self.assertEqual(writer.result(timeout=8),'denied')
        self.assertEqual(self.snapshot(),before)
    def test_retirement_committed_while_cash_waits_blocks_new_category_use(self):
        held=threading.Event();release=threading.Event();ready=threading.Event();pids=[]
        def retire():
            connections.close_all()
            try:
                with transaction.atomic():
                    Category.objects.filter(pk=self.category.pk).update(is_active=False);held.set()
                    if not release.wait(8):raise AssertionError('Release not signalled')
            finally:connections.close_all()
        def cash():
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'");cursor.execute('SELECT pg_backend_pid()');pids.append(cursor.fetchone()[0]);ready.set()
                try:
                    with transaction.atomic():self.sql_clone(agreement=None)
                except IntegrityError:return 'denied'
                return 'created'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(retire)
            try:
                self.assertTrue(held.wait(6));second=pool.submit(cash);self.assertTrue(ready.wait(6));self.wait_blocked(pids[0])
            finally:release.set()
            first.result(timeout=8);self.assertEqual(second.result(timeout=8),'denied')
        self.assertEqual(Transaction.objects.count(),0)
    def test_adjustment_deferred_audit_guard_denies_a_real_commit_without_event(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE accounting_cashadjustment DISABLE TRIGGER s19_adjust_audit')
                self.raw_adjust('2.00')
                # The failed COMMIT rolls back the temporary fault-injection
                # DDL too, so the audit trigger is restored automatically.
        self.assertEqual(CashAdjustment.objects.count(),0);self.assertEqual(FinanceAuditEvent.objects.filter(target_model='cashadjustment').count(),0)
        self.raw_adjust('3.00')
        self.assertEqual(FinanceAuditEvent.objects.filter(target_model='cashadjustment').count(),1)
    def test_rolling_back_outer_transaction_keeps_cash_adjustments_and_audit_together(self):
        before=self.snapshot()
        with self.assertRaisesMessage(RuntimeError,'rollback'):
            with transaction.atomic():
                self.adjustment();raise RuntimeError('rollback')
        self.assertEqual(self.snapshot(),before)

class WorkspaceMigrationTests(Support,TransactionTestCase):
    old=('accounting','0012_financial_database_guards')
    current=('accounting','0014_cash_workspace_guards')
    def migrate(self,target):
        executor=MigrationExecutor(connection);executor.migrate([target]);return executor.loader.project_state([target]).apps
    def setUp(self):
        apps=self.migrate(self.old)
        self.office=apps.get_model('accounting','Office').objects.create(name='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΝΑΣΤΕΥΣΗ S19')
        self.account=apps.get_model('accounting','CashAccount').objects.create(office_id=self.office.pk,name='ΠΑΛΑΙΟ ΤΑΜΕΙΟ S19',opening_balance='100.00')
        self.category=apps.get_model('accounting','Category').objects.create(office_id=self.office.pk,name='ΠΑΛΑΙΑ ΚΑΤΗΓΟΡΙΑ S19')
        model=apps.get_model('accounting','Transaction')
        self.earlier=model.objects.create(office_id=self.office.pk,cash_account_id=self.account.pk,category_id=self.category.pk,
            amount='30.00',transaction_type='INCOME',transaction_date=DAY-timedelta(days=1),description='ΔΟΚΙΜΑΣΤΙΚΗ ΠΡΟΓΕΝΕΣΤΕΡΗ')
        self.same_day=model.objects.create(office_id=self.office.pk,cash_account_id=self.account.pk,category_id=self.category.pk,
            amount='50.00',transaction_type='INCOME',transaction_date=DAY,description='ΔΟΚΙΜΑΣΤΙΚΗ ΙΔΙΑΣ ΗΜΕΡΑΣ')
    def tearDown(self):
        executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()
    def test_upgrade_keeps_original_columns_ids_and_explicit_cutoff_avoids_double_counting(self):
        before={model._meta.model_name:list(model.objects.order_by('pk').values()) for model in (type(self.account),type(self.category),type(self.earlier))}
        audits=list(FinanceAuditEvent.objects.order_by('pk').values())
        self.migrate(self.current)
        for name,rows in before.items():
            model={'cashaccount':CashAccount,'category':Category,'transaction':Transaction}[name]
            for row in rows:
                self.assertEqual(model.objects.filter(pk=row['id']).values(*row.keys()).get(),row)
        self.assertEqual(list(FinanceAuditEvent.objects.order_by('pk').values()),audits)
        self.account=CashAccount.objects.get(pk=self.account.pk)
        self.assertIsNone(self.account.opening_date);self.assertTrue(self.account.legacy_opening)
        self.password=secrets.token_urlsafe(32);self.owner=get_user_model().objects.create_user('s19-migration-owner',password=self.password)
        create_accountant_profile(user_id=self.owner.pk,office_id=self.office.pk,role='owner');self.member=self.owner
        self.assertIsNone(self.balance())
        plan,token=self.proposal(self.account)
        self.assertEqual((plan['inventory']['excluded_count'],plan['inventory']['included_count']),(1,1))
        self.approve(self.account,token=token)
        self.assertEqual(self.balance(day=DAY),Decimal('150.00'));self.assertIsNone(self.balance(day=DAY-timedelta(days=1)))
        self.assertEqual(Transaction.objects.count(),2);self.assertEqual(Transaction.objects.get(pk=self.earlier.pk).amount,Decimal('30.00'))
        self.migrate(self.current);self.assertEqual(self.balance(day=DAY),Decimal('150.00'))
    def test_invalid_legacy_cycle_stops_before_new_schema_and_preserves_records(self):
        with connection.cursor() as cursor:cursor.execute('UPDATE accounting_category SET parent_id=id WHERE id=%s',[self.category.pk])
        try:
            with self.assertRaisesMessage(Exception,'legacy category cycle'):self.migrate(self.current)
            with connection.cursor() as cursor:
                cursor.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='accounting_cashaccount' AND column_name='opening_date')")
                self.assertFalse(cursor.fetchone()[0])
                cursor.execute('SELECT parent_id FROM accounting_category WHERE id=%s',[self.category.pk]);self.assertEqual(cursor.fetchone()[0],self.category.pk)
        finally:
            with connection.cursor() as cursor:cursor.execute('UPDATE accounting_category SET parent_id=NULL WHERE id=%s',[self.category.pk])
    def test_duplicate_legacy_root_names_stop_without_merging_ids(self):
        model=type(self.category);duplicate=model.objects.create(office_id=self.office.pk,name=self.category.name)
        try:
            with self.assertRaisesMessage(Exception,'duplicate root categories'):self.migrate(self.current)
            self.assertEqual(model.objects.filter(office_id=self.office.pk,name=self.category.name).count(),2)
        finally:duplicate.delete()
    def test_approved_opening_blocks_unsafe_downgrade_and_preserves_audit(self):
        self.migrate(self.current);CashAccount.objects.filter(pk=self.account.pk).update(opening_date=DAY)
        before=list(FinanceAuditEvent.objects.order_by('pk').values())
        with self.assertRaisesMessage(Exception,'preservation plan'):self.migrate(self.old)
        self.assertEqual(CashAccount.objects.get(pk=self.account.pk).opening_balance,Decimal('100.00'))
        self.assertEqual(list(FinanceAuditEvent.objects.order_by('pk').values()),before)
