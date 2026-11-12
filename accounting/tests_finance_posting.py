"""S18 contract tests on PostgreSQL: money, immutability, audit, retry, real commits.

Synthetic people/devices only. Correct legacy assertions remain in the strict
runner; owner correction proof uses the real password/MFA policy.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date,timedelta
from decimal import Decimal
import copy,json,secrets,threading,time,uuid
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import connection,connections,IntegrityError,transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client,SimpleTestCase,TestCase,TransactionTestCase
from django.utils import timezone
from core.redaction import register_secret
from .models import Office,AccountantProfile,Entity,CashAccount,Category,Agreement,Transaction,FinanceCommand,FinanceAuditEvent
from .membership import create_office,create_accountant_profile
from .finance_money import money,rounded_line,MAX
from .finance_services import post_cash,post_transfer,reverse_cash,finance_history,save_master,audit_context,command_for,complete
from .tests_auth_support import staff_client_login

DAY=date(2026,1,15)

class Fixtures:
    def seed(self):
        self.office=create_office(name='ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ ΟΙΚΟΝΟΜΙΚΩΝ S18')
        self.foreign=create_office(name='ΔΟΚΙΜΑΣΤΙΚΟ ΞΕΝΟ ΓΡΑΦΕΙΟ S18')
        self.password=secrets.token_urlsafe(32)
        self.owner=get_user_model().objects.create_user('s18-owner',password=self.password)
        self.member=get_user_model().objects.create_user('s18-accountant',password=secrets.token_urlsafe(32))
        create_accountant_profile(user_id=self.owner.pk,office_id=self.office.pk,role='owner')
        create_accountant_profile(user_id=self.member.pk,office_id=self.office.pk,role='accountant')
        self.customer=Entity.objects.create(office=self.office,name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ',entity_type='CUSTOMER')
        self.supplier=Entity.objects.create(office=self.office,name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΡΟΜΗΘΕΥΤΗΣ',entity_type='SUPPLIER')
        self.account=CashAccount.objects.create(office=self.office,name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ Α',opening_balance='100.00')
        self.other=CashAccount.objects.create(office=self.office,name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ Β',opening_balance='0.00')
        self.foreign_account=CashAccount.objects.create(office=self.foreign,name='ΔΟΚΙΜΑΣΤΙΚΟ ΞΕΝΟ ΤΑΜΕΙΟ')
        self.category=Category.objects.create(office=self.office,name='ΔΟΚΙΜΑΣΤΙΚΗ ΚΑΤΗΓΟΡΙΑ')
        self.agreement=Agreement.objects.create(office=self.office,entity=self.customer,agreement_type='RECEIVABLE',
            description='ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΜΦΩΝΙΑ',total_amount='100.00',start_date=DAY)
    def values(self,**changes):
        return dict(amount='25.00',transaction_date=DAY,transaction_type='INCOME',cash_account=self.account,
            entity=self.customer,agreement=self.agreement,category=self.category,description='ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ',**{})|changes
    def post(self,**changes):
        return post_cash(self.member,idempotency_key=secrets.token_hex(16),**self.values(**changes))
    def request(self,user=None):
        client=Client();staff_client_login(client,user or self.owner)
        return client.get('/office/settings/' if user is None else '/').wsgi_request
    def reverse(self,entry,**changes):
        return reverse_cash(self.request(),entry_id=entry.pk,password=self.password,reason='Διόρθωση δοκιμαστικής καταχώρισης',
            effective_date=DAY,idempotency_key=secrets.token_hex(16),**changes)
    def snapshot(self):
        return tuple(model.objects.count() for model in (Transaction,FinanceCommand,FinanceAuditEvent))
    def sql_clone(self,**changes):
        values=self.values(**changes)
        return Transaction.objects.bulk_create([Transaction(office=self.office,**values)])[0]

class MoneyContractTests(SimpleTestCase):
    def test_cents_limits_and_signed_opening(self):
        for source in ('0.01','25','9999999999.99',Decimal('12.30'),1):
            self.assertEqual(money(source),Decimal(source).quantize(Decimal('.01')))
        self.assertEqual(money('-9999999999.99',signed=True),-MAX)
        self.assertEqual(money('0',signed=True),Decimal('0.00'))
    def test_rejects_nonpositive_overprecision_nonfinite_and_binary_float(self):
        for source in ('0','-1','1.001','99999999999','NaN','Infinity','1e2',1.0,True,None,[],Decimal('NaN'),Decimal('Infinity')):
            with self.subTest(value=repr(source)),self.assertRaises(ValidationError):money(source)
    def test_half_up_per_derived_line_then_sum(self):
        self.assertEqual(rounded_line('10.005','1'),Decimal('10.01'))
        self.assertEqual(rounded_line('10.004','1'),Decimal('10.00'))
        self.assertEqual(sum(rounded_line('0.005','1') for _ in range(3)),Decimal('.03'))
        for price,count in ((0.1,1),('1','NaN'),('-1','1'),('1','0'),('9999999999.99','2')):
            with self.subTest(price=price,count=count),self.assertRaises(ValidationError):rounded_line(price,count)

class PostingContractTests(Fixtures,TestCase):
    def setUp(self):self.seed()
    def test_one_command_cash_and_attributable_allowlisted_audit(self):
        entry=self.post();event=entry.finance_audit
        self.assertEqual((event.office_id,event.actor_id,event.origin),(self.office.pk,self.member.pk,'user'))
        self.assertEqual(event.command_id,entry.command_id);self.assertEqual(Decimal(event.after['amount']),Decimal('25.00'))
        self.assertEqual(event.after['agreement_id'],self.agreement.pk);self.assertEqual(event.effective_date,DAY)
        self.assertTrue(event.database_actor);self.assertEqual(event.before,{})
        self.assertEqual(entry.command.state,'completed');self.assertEqual(FinanceCommand.objects.count(),1)
        self.assertNotIn('description',event.after);self.assertNotIn('remarks',event.after)
    def test_identical_retry_returns_same_identifiers_without_new_audit(self):
        key=secrets.token_hex(16);first=post_cash(self.member,idempotency_key=key,**self.values());before=self.snapshot()
        second=post_cash(self.member,idempotency_key=key,**self.values())
        self.assertEqual(second.pk,first.pk);self.assertEqual(self.snapshot(),before)
    def test_changed_payload_or_wrong_amount_retry_has_no_partial_effect(self):
        key=secrets.token_hex(16);post_cash(self.member,idempotency_key=key,**self.values());before=self.snapshot()
        for changes in ({'amount':'26.00'},{'remarks':'Διαφορετική αιτιολογία'},{'cash_account':self.other}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):post_cash(self.member,idempotency_key=key,**self.values(**changes))
            self.assertEqual(self.snapshot(),before)
    def test_invalid_keys_rejected_and_not_stored(self):
        for key in ('','x','invalid key','x'*161):
            with self.subTest(key=key),self.assertRaises(ValidationError):post_cash(self.member,idempotency_key=key,**self.values())
        self.assertEqual(FinanceCommand.objects.count(),0)
    def test_replay_rechecks_revoked_actor(self):
        key=secrets.token_hex(16);post_cash(self.member,idempotency_key=key,**self.values());before=self.snapshot()
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):post_cash(self.member,idempotency_key=key,**self.values())
        self.assertEqual(self.snapshot(),before)
    def test_foreign_account_and_cross_counterparty_fail_without_command_or_event(self):
        other=Entity.objects.create(office=self.office,name='ΑΛΛΟΣ ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ',entity_type='CUSTOMER')
        before=self.snapshot()
        for changes in ({'cash_account':self.foreign_account},{'entity':other},{'entity':self.supplier},
                        {'transaction_type':'EXPENSE'},{'transaction_date':timezone.localdate()+timedelta(days=1)}):
            with self.subTest(changes=changes),self.assertRaises(ValidationError):self.post(**changes)
            self.assertEqual(self.snapshot(),before)
    def test_inactive_account_or_cancelled_agreement_fail_closed(self):
        CashAccount.objects.filter(pk=self.account.pk).update(is_active=False)
        with self.assertRaises(ValidationError):self.post()
        CashAccount.objects.filter(pk=self.account.pk).update(is_active=True)
        Agreement.objects.filter(pk=self.agreement.pk).update(status='CANCELLED')
        with self.assertRaises(ValidationError):self.post()
        self.assertEqual(Transaction.objects.count(),0)
    def test_failure_after_cash_insert_rolls_back_ledger_command_and_audit(self):
        before=self.snapshot()
        with patch('accounting.finance_services.project_agreement',side_effect=RuntimeError('synthetic-failure')):
            with self.assertRaises(RuntimeError):self.post()
        self.assertEqual(self.snapshot(),before)
    def test_audit_failure_rolls_back_cash_and_command(self):
        before=self.snapshot()
        # A stale actor context cannot silently produce an unaudited cash row.
        with patch('accounting.finance_services.audit_context'):
            with self.assertRaises(IntegrityError),transaction.atomic():self.post()
        self.assertEqual(self.snapshot(),before)
    def test_model_and_sql_updates_deletes_denied_including_free_text(self):
        entry=self.post();before=self.snapshot();original=copy.deepcopy(entry.__dict__)
        entry.amount=Decimal('5.00')
        with self.assertRaises(ValidationError):entry.save()
        with self.assertRaises(ValidationError):entry.delete()
        for action in (lambda:Transaction.objects.filter(pk=entry.pk).update(description='ΔΟΚΙΜΗ'),lambda:Transaction.objects.filter(pk=entry.pk).delete()):
            with self.assertRaises(IntegrityError),transaction.atomic():action()
        entry.refresh_from_db();self.assertEqual(entry.amount,original['amount']);self.assertEqual(self.snapshot(),before)
    def test_harmless_model_resave_does_not_project_or_append_audit(self):
        entry=self.post();before=self.snapshot()
        with patch('accounting.finance_services.project_agreement',side_effect=AssertionError('hidden side effect')):entry.save()
        self.assertEqual(self.snapshot(),before)
    def test_sql_amount_precision_positive_finite_bound_constraints(self):
        before=self.snapshot()
        for amount in ('0','-1','0.001','1.005','10000000000','NaN','Infinity','-Infinity'):
            with self.subTest(amount=amount),self.assertRaises(IntegrityError),transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('''INSERT INTO accounting_transaction(office_id,transaction_date,transaction_type,amount,description,cash_account_id,
                        entity_id,agreement_id,transfer_id,remarks,created_at,updated_at,posting_kind)
                        VALUES(%s,%s,'INCOME',%s::numeric,'synthetic',%s,%s,%s,%s,'',now(),now(),'LEGACY')''',
                        [self.office.pk,DAY,amount,self.account.pk,self.customer.pk,self.agreement.pk,uuid.uuid4()])
            self.assertEqual(self.snapshot(),before)
    def test_sql_references_cannot_link_another_counterparty_or_office(self):
        for changes in ({'entity':self.supplier},{'cash_account':self.foreign_account},{'entity':None}):
            with self.subTest(changes=changes),self.assertRaises(IntegrityError),transaction.atomic():self.sql_clone(**changes)
    def test_database_operator_insert_is_explicitly_attributed_not_a_human(self):
        entry=self.sql_clone();event=entry.finance_audit
        self.assertIsNone(event.actor_id);self.assertIsNone(event.command_id)
        self.assertEqual(event.origin,'database');self.assertTrue(event.database_actor)
    def test_audit_is_append_only_even_with_querysets_and_direct_insert(self):
        event=self.post().finance_audit
        with self.assertRaises(PermissionDenied):event.save()
        with self.assertRaises(PermissionDenied):event.delete()
        for action in (lambda:FinanceAuditEvent.objects.filter(pk=event.pk).update(reason='Αλλαγή'),lambda:FinanceAuditEvent.objects.filter(pk=event.pk).delete(),
                       lambda:FinanceAuditEvent.objects.bulk_create([FinanceAuditEvent(office=self.office,database_actor='fake',origin='database',operation='fake',target_model='transaction',target_id=1,reason='fake')])):
            with self.assertRaises(IntegrityError),transaction.atomic():action()
    def test_completed_command_cannot_be_edited_deleted_or_reopened(self):
        command=self.post().command
        for action in (lambda:FinanceCommand.objects.filter(pk=command.pk).update(state='pending'),lambda:FinanceCommand.objects.filter(pk=command.pk).update(reason='Διαφορετική αιτιολογία'),lambda:FinanceCommand.objects.filter(pk=command.pk).delete()):
            with self.assertRaises(IntegrityError),transaction.atomic():action()
    def test_secrets_free_text_and_password_are_excluded_or_redacted(self):
        canary=secrets.token_urlsafe(40);register_secret(canary)
        entry=post_cash(self.member,idempotency_key=canary,reason='Διόρθωση με password='+canary,
            **self.values(description=canary,remarks='token='+canary))
        serialized=json.dumps(list(FinanceAuditEvent.objects.filter(command=entry.command).values()),default=str)
        serialized+=json.dumps(list(FinanceCommand.objects.values()),default=str)
        self.assertNotIn(canary,serialized);self.assertIn('[REDACTED]',serialized)
        self.assertEqual(Transaction.objects.get(pk=entry.pk).description,canary) # Original user content retained.
    def test_sql_cash_date_uses_greek_day_independent_of_session_timezone(self):
        today=timezone.localdate()
        for zone in ('Pacific/Kiritimati','Etc/GMT+12'):
            with self.subTest(zone=zone),transaction.atomic():
                with connection.cursor() as cursor:cursor.execute("SELECT set_config('TimeZone',%s,true)",[zone])
                entry=self.sql_clone(transaction_date=today)
                self.assertEqual(entry.transaction_date,today)
                with self.assertRaises(IntegrityError),transaction.atomic():
                    self.sql_clone(transaction_date=today+timedelta(days=1))

    def test_owner_history_reader_scopes_office_and_denies_accountant(self):
        entry=self.post();events=finance_history(self.owner,target_model='transaction',target_id=entry.pk)
        self.assertEqual([e.pk for e in events],[entry.finance_audit.pk])
        with self.assertRaises(PermissionDenied):finance_history(self.member,target_model='transaction',target_id=entry.pk)
        foreign_owner=get_user_model().objects.create_user('s18-foreign-owner')
        create_accountant_profile(user_id=foreign_owner.pk,office_id=self.foreign.pk,role='owner')
        self.assertEqual(finance_history(foreign_owner,target_model='transaction',target_id=entry.pk),[])
    def test_master_change_is_audited_and_used_amount_opening_edits_denied(self):
        entry=self.post();self.agreement.total_amount=Decimal('101.00')
        with self.assertRaises(ValidationError):save_master(self.agreement,self.member)
        self.account.opening_balance=Decimal('101.00')
        with self.assertRaises(ValidationError):save_master(self.account,self.member)
        self.category.name='ΝΕΑ ΔΟΚΙΜΑΣΤΙΚΗ ΚΑΤΗΓΟΡΙΑ';save_master(self.category,self.member)
        # Only approved structural/financial fields, not names, are in the audit.
        self.account.refresh_from_db();self.account.is_active=False;save_master(self.account,self.member)
        event=FinanceAuditEvent.objects.filter(target_model='cashaccount',target_id=self.account.pk).first()
        self.assertEqual(event.actor_id,self.member.pk);self.assertEqual(event.after['is_active'],False)
    def test_transfer_is_atomic_and_retry_preserves_two_ids(self):
        key=secrets.token_hex(16);kwargs=dict(from_account=self.account,to_account=self.other,amount='20.00',transfer_date=DAY,description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ',idempotency_key=key)
        pair=post_transfer(self.member,**kwargs);before=self.snapshot();retry=post_transfer(self.member,**kwargs)
        self.assertEqual([e.pk for e in retry],[e.pk for e in pair]);self.assertEqual(self.snapshot(),before)
        self.assertEqual(pair[0].transfer_id,pair[1].transfer_id);self.assertEqual({e.transaction_type for e in pair},{'INCOME','EXPENSE'})
        self.assertEqual(len({e.command_id for e in pair}),1);self.assertTrue(all(e.finance_audit.actor_id==self.member.pk for e in pair))
    def test_second_transfer_leg_failure_leaves_no_first_leg_or_audit(self):
        before=self.snapshot();create=Transaction.objects.create;calls=0
        def failed(**values):
            nonlocal calls
            calls+=1
            if calls==2:raise RuntimeError('synthetic-second-leg')
            return create(**values)
        with patch('accounting.finance_services.Transaction.objects.create',side_effect=failed),self.assertRaises(RuntimeError):
            post_transfer(self.member,from_account=self.account,to_account=self.other,amount='20.00',transfer_date=DAY,description='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ',idempotency_key=secrets.token_hex(16))
        self.assertEqual(calls,2);self.assertEqual(self.snapshot(),before)
    def test_full_reversal_keeps_original_and_reopens_legacy_settlement(self):
        original=self.post(amount='100.00');pair=self.reverse(original);original.refresh_from_db();self.agreement.refresh_from_db()
        self.assertEqual(original.amount,Decimal('100.00'));self.assertEqual(pair[0].reversal_of_id,original.pk)
        self.assertEqual(pair[0].amount,original.amount);self.assertEqual(pair[0].transaction_type,'EXPENSE');self.assertEqual(self.agreement.status,'ACTIVE')
        self.assertEqual(pair[0].finance_audit.actor_id,self.owner.pk)
    def test_reversal_replacement_is_atomic_and_replayable(self):
        original=self.post(amount='100.00');request=self.request();key=secrets.token_hex(16)
        args=dict(entry_id=original.pk,password=self.password,reason='Διόρθωση ποσού δοκιμής',effective_date=DAY,idempotency_key=key,replacement=self.values(amount='25.00'))
        result=reverse_cash(request,**args);before=self.snapshot();again=reverse_cash(request,**args)
        self.assertEqual([e.pk for e in result],[e.pk for e in again]);self.assertEqual(self.snapshot(),before)
        from .finance_services import legacy_settlement
        self.assertEqual(Transaction.objects.filter(agreement=self.agreement).aggregate(v=legacy_settlement())['v'],Decimal('25.00'))
    def test_replacement_validation_rolls_back_entire_correction(self):
        original=self.post();before=self.snapshot()
        with self.assertRaises(ValidationError):self.reverse(original,replacement=self.values(cash_account=self.foreign_account))
        self.assertEqual(self.snapshot(),before);self.assertFalse(Transaction.objects.filter(reversal_of=original).exists())
    def test_reversal_requires_owner_correct_password_and_recent_real_mfa(self):
        original=self.post();before=self.snapshot()
        common=dict(entry_id=original.pk,password='incorrect',reason='Δοκιμή προστασίας διόρθωσης',effective_date=DAY,idempotency_key=secrets.token_hex(16))
        with self.assertRaises(PermissionDenied):reverse_cash(self.request(self.member),**common)
        with self.assertRaises(ValidationError):reverse_cash(self.request(),**common)
        request=self.request()
        request.session['s13_mfa_at']=0;common['password']=self.password
        with self.assertRaises(ValidationError):reverse_cash(request,**common)
        self.assertEqual(self.snapshot(),before)
    def test_duplicate_recursive_foreign_transfer_and_predated_reversals_denied(self):
        original=self.post();reversal=self.reverse(original)[0];before=self.snapshot()
        for entry in (original,reversal):
            with self.subTest(entry=entry.pk),self.assertRaises(ValidationError):self.reverse(entry)
        with self.assertRaises(ValidationError):reverse_cash(self.request(),entry_id=original.pk,password=self.password,reason='Δοκιμή πρόωρης διόρθωσης',effective_date=DAY-timedelta(days=1),idempotency_key=secrets.token_hex(16))
        self.assertEqual(self.snapshot(),before)
        pair=post_transfer(self.member,from_account=self.account,to_account=self.other,amount='5.00',transfer_date=DAY,description='ΔΟΚΙΜΗ',idempotency_key=secrets.token_hex(16))
        with self.assertRaises(ValidationError):self.reverse(pair[0])
    def test_reversal_of_archived_history_is_allowed_but_new_work_stays_denied(self):
        original=self.post()
        from .counterparty_services import archive_counterparty
        archive_counterparty(self.owner,self.customer.pk,version=0,archive=True)
        result=self.reverse(original);self.assertEqual(result[0].entity_id,self.customer.pk)
        with self.assertRaises(ValidationError):self.post()
    def test_http_uuid_retry_and_legacy_tokenless_retry_do_not_double_post(self):
        client=Client();staff_client_login(client,self.member)
        response=client.get('/income/add/');key=response.context['form']['posting_key'].value()
        self.assertContains(response,'type="hidden"');data=dict(amount='25,00',transaction_date=DAY.isoformat(),cash_account=self.account.pk,
            entity=self.customer.pk,agreement=self.agreement.pk,category=self.category.pk,description='ΔΟΚΙΜΗ HTTP',posting_key=str(key))
        first=client.post('/income/add/',data);self.assertEqual(first.status_code,302)
        before=self.snapshot();self.assertEqual(client.post('/income/add/',data).status_code,302);self.assertEqual(self.snapshot(),before)
        data.pop('posting_key');data['description']='ΔΟΚΙΜΗ ΠΑΛΙΟΥ ΑΙΤΗΜΑΤΟΣ'
        self.assertEqual(client.post('/income/add/',data).status_code,302);before=self.snapshot()
        self.assertEqual(client.post('/income/add/',data).status_code,302);self.assertEqual(self.snapshot(),before)
    def test_readonly_admin_rejects_posted_original_change(self):
        from django.contrib.auth.models import Permission
        self.owner.is_staff=True;self.owner.save(update_fields=['is_staff'])
        self.owner.user_permissions.add(*Permission.objects.filter(content_type__app_label='accounting',codename__in=['view_transaction','change_transaction']))
        client=Client();staff_client_login(client,self.owner);entry=self.post();before=self.snapshot()
        response=client.get(f'/admin/accounting/transaction/{entry.pk}/change/');self.assertEqual(response.status_code,200)
        self.assertNotIn('amount',response.context['adminform'].form.fields)
        self.assertEqual(client.post(f'/admin/accounting/transaction/{entry.pk}/change/',{'amount':'1.00'}).status_code,403)
        self.assertEqual(self.snapshot(),before)

    def test_admin_new_post_retry_uses_explicit_uuid_without_duplicate_audit(self):
        self.owner.is_staff=True;self.owner.is_superuser=True;self.owner.save(update_fields=['is_staff','is_superuser'])
        client=Client();staff_client_login(client,self.owner)
        form=client.get('/admin/accounting/transaction/add/').context['adminform'].form
        self.assertIn('posting_key',form.fields)
        data=dict(transaction_date=DAY.isoformat(),transaction_type='INCOME',amount='25,00',description='ΔΟΚΙΜΗ ADMIN',
            cash_account=self.account.pk,entity=self.customer.pk,category=self.category.pk,agreement=self.agreement.pk,
            posting_key=str(form['posting_key'].value()),remarks='',_save='Αποθήκευση')
        response=client.post('/admin/accounting/transaction/add/',data)
        self.assertEqual(response.status_code,302,response.context['adminform'].form.errors if response.status_code==200 else '')
        before=self.snapshot();self.assertEqual(client.post('/admin/accounting/transaction/add/',data).status_code,302)
        self.assertEqual(self.snapshot(),before)

class PostingCommitTests(Fixtures,TransactionTestCase):
    def setUp(self):self.seed()
    def test_pending_or_empty_command_cannot_commit(self):
        before=self.snapshot()
        for finished in (False,True):
            with self.subTest(finished=finished),self.assertRaises(IntegrityError):
                with transaction.atomic():
                    command,_=command_for(self.member,self.office,'cash.post',secrets.token_hex(16),{'amount':'1.00'},'Δοκιμή μη ολοκληρωμένης ενέργειας')
                    if finished:complete(command)
            self.assertEqual(self.snapshot(),before)
    def test_unbalanced_or_incomplete_transfer_cannot_commit(self):
        before=self.snapshot()
        for amounts in (('10.00',),('10.00','9.99')):
            with self.subTest(amounts=amounts),self.assertRaises(IntegrityError):
                with transaction.atomic():
                    command,_=command_for(self.member,self.office,'cash.transfer',secrets.token_hex(16),{'pair':'synthetic'},'Δοκιμή μη ισοσκελισμένης μεταφοράς')
                    group=uuid.uuid4()
                    with audit_context(self.member,'Δοκιμή μη ισοσκελισμένης μεταφοράς',command):
                        for i,amount in enumerate(amounts):
                            Transaction.objects.create(office=self.office,command=command,posting_kind='TRANSFER',transfer_id=group,
                                amount=amount,cash_account=self.account if i==0 else self.other,transaction_type='EXPENSE' if i==0 else 'INCOME',
                                transaction_date=DAY,description='ΔΟΚΙΜΑΣΤΙΚΟ ΣΚΕΛΟΣ')
                        complete(command)
            self.assertEqual(self.snapshot(),before)
    def test_deferred_checks_allow_complete_group_at_real_commit(self):
        result=self.post();self.assertEqual(Transaction.objects.get(pk=result.pk).command.state,'completed')
        with connection.cursor() as cursor:cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.assertEqual(FinanceAuditEvent.objects.filter(entry=result).count(),1)
    def test_forged_reversal_cannot_override_archive_exception(self):
        original=self.post();before=self.snapshot()
        with self.assertRaises(IntegrityError),transaction.atomic():
            command,_=command_for(self.owner,self.office,'cash.reverse',secrets.token_hex(16),{'source':original.pk},'Δοκιμή πλαστού αντιλογισμού')
            with audit_context(self.owner,'Δοκιμή πλαστού αντιλογισμού',command):
                Transaction.objects.bulk_create([Transaction(office=self.office,command=command,posting_kind='REVERSAL',reversal_of=original,
                    cash_account=self.other,amount=original.amount,transaction_type='EXPENSE',transaction_date=DAY,description='ΔΟΚΙΜΗ')])
                complete(command)
        self.assertEqual(self.snapshot(),before)
    def race(self,functions):
        barrier=threading.Barrier(len(functions));pids=[];pid_lock=threading.Lock()
        def worker(function):
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'");cursor.execute('SELECT pg_backend_pid()')
                    with pid_lock:pids.append(cursor.fetchone()[0])
                barrier.wait(timeout=6)
                try:return ('ok',function())
                except (ValidationError,PermissionDenied) as error:return ('denied',type(error).__name__)
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures=[pool.submit(worker,fn) for fn in functions]
            results=[future.result(timeout=15) for future in futures]
        self.assertEqual(len(set(pids)),len(functions))
        return results
    def test_independent_same_key_race_creates_one_cash_command_and_event(self):
        key=secrets.token_hex(16);before=self.snapshot()
        def post():return post_cash(get_user_model().objects.get(pk=self.member.pk),idempotency_key=key,**self.values()).pk
        results=self.race([post,post]);self.assertTrue(all(r[0]=='ok' for r in results));self.assertEqual(results[0][1],results[1][1])
        after=self.snapshot();self.assertEqual((after[0]-before[0],after[1]-before[1]),(1,1))
        self.assertEqual(FinanceAuditEvent.objects.filter(entry_id=results[0][1]).count(),1)
    def test_independent_changed_payload_same_key_race_conflicts_once(self):
        key=secrets.token_hex(16)
        def post(amount):return lambda:post_cash(get_user_model().objects.get(pk=self.member.pk),idempotency_key=key,**self.values(amount=amount)).pk
        results=self.race([post('24.00'),post('25.00')]);self.assertEqual(sorted(r[0] for r in results),['denied','ok'])
        self.assertEqual((Transaction.objects.count(),FinanceCommand.objects.count()),(1,1))
    def test_independent_reversal_race_keeps_one_inverse(self):
        original=self.post();first=self.request();second=self.request()
        def reverse(request):return lambda:[e.pk for e in reverse_cash(request,entry_id=original.pk,password=self.password,
            reason='Δοκιμή ταυτόχρονου αντιλογισμού',effective_date=DAY,idempotency_key=secrets.token_hex(16))]
        results=self.race([reverse(first),reverse(second)]);self.assertEqual(sorted(r[0] for r in results),['denied','ok'])
        self.assertEqual(Transaction.objects.filter(reversal_of=original).count(),1)
        self.assertEqual(FinanceCommand.objects.count(),2)
    def test_revocation_before_posting_lock_wait_denies_new_command_and_audit(self):
        before=self.snapshot();held=threading.Event();release=threading.Event();ready=threading.Event();pid=[]
        def revoke():
            connections.close_all()
            try:
                with transaction.atomic():
                    Office.objects.select_for_update().get(pk=self.office.pk)
                    AccountantProfile.objects.filter(user=self.member).update(is_active=False)
                    held.set()
                    if not release.wait(8):raise AssertionError('Release not signalled')
            finally:connections.close_all()
        def write():
            connections.close_all()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout='8s'");cursor.execute('SELECT pg_backend_pid()');pid.append(cursor.fetchone()[0]);ready.set()
                try:self.post()
                except PermissionDenied:return 'denied'
                return 'created'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoker=pool.submit(revoke)
            try:
                self.assertTrue(held.wait(6));writer=pool.submit(write);self.assertTrue(ready.wait(6))
                deadline=time.monotonic()+6;blocked=False
                while time.monotonic()<deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT cardinality(pg_blocking_pids(%s))',[pid[0]])
                        if cursor.fetchone()[0]:blocked=True;break
                    time.sleep(.02)
                self.assertTrue(blocked,'Real PostgreSQL lock wait must be observed')
            finally:release.set()
            revoker.result(timeout=8);self.assertEqual(writer.result(timeout=8),'denied')
        self.assertEqual(self.snapshot(),before)

class PostingMigrationTests(TransactionTestCase):
    old=('accounting','0010_counterparty_database_guards')
    current=('accounting','0012_financial_database_guards')
    def migrate(self,target):
        executor=MigrationExecutor(connection);executor.migrate([target]);return executor.loader.project_state([target]).apps
    def setUp(self):
        apps=self.migrate(self.old)
        self.office=apps.get_model('accounting','Office').objects.create(name='ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΝΑΣΤΕΥΣΗ S18')
        self.account=apps.get_model('accounting','CashAccount').objects.create(office_id=self.office.pk,name='ΠΑΛΑΙΟ ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ',opening_balance='-12.34')
        self.customer=apps.get_model('accounting','Entity').objects.create(office_id=self.office.pk,entity_type='CUSTOMER',is_customer=True,is_supplier=False,
            name='ΠΑΛΑΙΟΣ ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ',vat_key='',legal_kind='UNREVIEWED')
        self.agreement=apps.get_model('accounting','Agreement').objects.create(office_id=self.office.pk,entity_id=self.customer.pk,
            agreement_type='RECEIVABLE',description='ΠΑΛΑΙΑ ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΜΦΩΝΙΑ',total_amount='100.00',start_date=DAY)
        self.entry=apps.get_model('accounting','Transaction').objects.create(office_id=self.office.pk,entity_id=self.customer.pk,agreement_id=self.agreement.pk,
            cash_account_id=self.account.pk,transaction_type='INCOME',amount='12.34',transaction_date=DAY,description='ΠΑΛΑΙΑ ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ',transfer_id=uuid.uuid4())
    def tearDown(self):
        self.migrate(self.current)
        super().tearDown()
    def test_upgrade_preserves_all_original_columns_and_baselines_unknown_human(self):
        self.entry.refresh_from_db();before={f.attname:getattr(self.entry,f.attname) for f in self.entry._meta.concrete_fields}
        self.migrate(self.current);entry=Transaction.objects.get(pk=self.entry.pk)
        for field,value in before.items():self.assertEqual(getattr(entry,field),value)
        self.assertEqual(entry.posting_kind,'LEGACY');self.assertIsNone(entry.command_id);self.assertIsNone(entry.reversal_of_id)
        event=entry.finance_audit;self.assertEqual(event.origin,'legacy');self.assertIsNone(event.actor_id)
        self.assertEqual(event.operation,'legacy.baseline');self.assertEqual(Decimal(event.after['amount']),Decimal('12.34'))
        self.assertEqual(CashAccount.objects.get(pk=self.account.pk).opening_balance,Decimal('-12.34'))
        self.assertEqual(FinanceAuditEvent.objects.count(),3)
        self.migrate(self.current);self.assertEqual(FinanceAuditEvent.objects.count(),3)
    def test_invalid_legacy_amount_stops_before_schema_or_values_change(self):
        with connection.cursor() as cursor:cursor.execute('UPDATE accounting_transaction SET amount=0 WHERE id=%s',[self.entry.pk])
        with self.assertRaises(Exception) as error:self.migrate(self.current)
        self.assertIn('invalid historical money',str(error.exception))
        with connection.cursor() as cursor:
            cursor.execute('SELECT amount FROM accounting_transaction WHERE id=%s',[self.entry.pk]);self.assertEqual(cursor.fetchone()[0],0)
            cursor.execute("SELECT to_regclass('accounting_financecommand')");self.assertIsNone(cursor.fetchone()[0])
            cursor.execute('UPDATE accounting_transaction SET amount=12.34 WHERE id=%s',[self.entry.pk])
        self.migrate(self.current)
    def test_posted_history_blocks_unsafe_downgrade(self):
        self.migrate(self.current)
        user=get_user_model().objects.create_user('s18-migration-operator')
        create_accountant_profile(user_id=user.pk,office_id=self.office.pk,role='accountant')
        entry=post_cash(user,idempotency_key=secrets.token_hex(16),amount='1.00',transaction_date=DAY,transaction_type='INCOME',
            cash_account=self.account.pk,description='ΔΟΚΙΜΑΣΤΙΚΗ ΝΕΑ ΚΙΝΗΣΗ')
        with self.assertRaises(Exception) as error:self.migrate(self.old)
        self.assertIn('preservation plan',str(error.exception));self.assertTrue(Transaction.objects.filter(pk=entry.pk).exists())
        self.assertTrue(FinanceAuditEvent.objects.filter(entry_id=entry.pk).exists())

    def test_new_database_operator_audit_also_blocks_unsafe_downgrade(self):
        self.migrate(self.current)
        CashAccount.objects.filter(pk=self.account.pk).update(is_active=False)
        self.assertTrue(FinanceAuditEvent.objects.filter(origin='database').exists())
        with self.assertRaises(Exception) as error:self.migrate(self.old)
        self.assertIn('preservation plan',str(error.exception))
        self.assertTrue(FinanceAuditEvent.objects.filter(origin='database').exists())
