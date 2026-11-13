"""S16 integrated office boundary: real HTTP, ORM/SQL, CLI and lock waits."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import io
import json
import os
import re
from pathlib import Path
from queue import Queue
import secrets
from threading import Event
import time
from types import ModuleType
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.http import Http404, HttpResponse
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import path, reverse
from django.utils import timezone

from .auth_policy import state_for
from .counterparty_services import archive_counterparty
from .membership import create_accountant_profile, change_membership
from .models import AccountantProfile, Agreement, CashAccount, Category, CounterpartyEvent, Entity, Office, Transaction
from .office_models import OfficeAuditEvent, OwnershipHandover, StaffInvitation
from .office_access import execution_record, records, save_for_user
from .tests_auth_support import staff_client_login

A='00000000-0000-4000-8000-00000000000a'
B='00000000-0000-4000-8000-00000000000b'
C='00000000-0000-4000-8000-00000000000c'
DAY=date(2026,1,15)
BUSINESS=(Entity,CashAccount,Category,Agreement,Transaction,CounterpartyEvent,StaffInvitation,OwnershipHandover,OfficeAuditEvent)


def make_actor(name,office=A,role='accountant',**flags):
    user=get_user_model().objects.create_user(name,name+'@example.invalid',secrets.token_urlsafe(32),**flags)
    if office:create_accountant_profile(user_id=user.pk,office_id=office,role=role)
    return user


def snapshot(office):
    result={model._meta.model_name:list(model.objects.filter(office_id=office).order_by('pk').values()) for model in BUSINESS}
    result['office']=list(Office.objects.filter(pk=office).values())
    result['profiles']=list(AccountantProfile.objects.filter(office_id=office).order_by('pk').values())
    result['user_flags']=list(get_user_model().objects.filter(accountant_profile__office_id=office).order_by('pk').values('id','is_active','is_staff','is_superuser'))
    return result


class BoundaryFixtures:
    fixtures=['s11_offices']

    @classmethod
    def seed(cls):
        cls.owner=make_actor('s16-owner-a',role='owner')
        cls.member=make_actor('s16-member-a')
        cls.owner_b=make_actor('s16-owner-b',B,'owner')
        cls.member_b=make_actor('s16-member-b',B)
        cls.staff=make_actor('s16-staff-a',is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label='accounting'))
        cls.staff.user_permissions.add(Permission.objects.get(content_type__app_label='auth',codename='view_user'))
        cls.platform=make_actor('s16-platform-a',role='owner',is_staff=True,is_superuser=True)
        cls.missing=make_actor('s16-missing',None)
        cls.platform_missing=make_actor('s16-platform-missing',None,is_staff=True,is_superuser=True)
        cls.inactive=make_actor('s16-inactive-profile')
        AccountantProfile.objects.filter(user=cls.inactive).update(is_active=False)
        cls.disabled_user=make_actor('s16-disabled-user')
        get_user_model().objects.filter(pk=cls.disabled_user.pk).update(is_active=False)
        Office.objects.create(pk=C,name='ΔΟΚΙΜΑΣΤΙΚΟ ΑΝΕΝΕΡΓΟ ΓΡΑΦΕΙΟ')
        cls.inactive_office=make_actor('s16-inactive-office',C)
        Office.objects.filter(pk=C).update(is_active=False)
        for suffix,office,owner,member in (('a',A,cls.owner,cls.member),('b',B,cls.owner_b,cls.member_b)):
            label='ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ Α ' if suffix=='a' else 'ΞΕΝΟ_ΓΡΑΦΕΙΟ_Β_S16 '
            item=Entity.objects.create(office_id=office,entity_type='CUSTOMER',is_customer=True,is_supplier=True,
                name=label+'ΣΥΝΑΛΛΑΣΣΟΜΕΝΟΣ',vat_number='000000601')
            cash=CashAccount.objects.create(opening_date=DAY,office_id=office,name=label+'ΤΑΜΕΙΟ',opening_balance=Decimal('100.00'))
            second=CashAccount.objects.create(opening_date=DAY,office_id=office,name=label+'ΔΕΥΤΕΡΟ ΤΑΜΕΙΟ')
            category=Category.objects.create(office_id=office,name=label+'ΚΑΤΗΓΟΡΙΑ')
            agreement=Agreement.objects.create(office_id=office,entity=item,agreement_type='RECEIVABLE',description=label+'ΣΥΜΦΩΝΙΑ',total_amount=Decimal('100.00'),start_date=DAY)
            payable=Agreement.objects.create(office_id=office,entity=item,agreement_type='PAYABLE',description=label+'ΠΛΗΡΩΤΕΑ ΣΥΜΦΩΝΙΑ',total_amount=Decimal('100.00'),start_date=DAY)
            movement=Transaction.objects.create(office_id=office,entity=item,cash_account=cash,category=category,
                transaction_type='INCOME',description=label+'ΕΙΣΠΡΑΞΗ',amount=Decimal('25.00'),transaction_date=DAY)
            Transaction.objects.create(office_id=office,entity=item,cash_account=cash,category=category,
                transaction_type='EXPENSE',description=label+'ΠΛΗΡΩΜΗ',amount=Decimal('5.00'),transaction_date=DAY)
            invite=StaffInvitation.objects.create(office_id=office,invited_by=owner,inviter_revision=state_for(owner).revision,
                recipient_email='s16-invite-'+suffix+'@example.invalid',token_digest=hashlib.sha256(secrets.token_bytes(32)).hexdigest(),expires_at=timezone.now()+timedelta(hours=1))
            handover=OwnershipHandover.objects.create(office_id=office,requested_by=owner,recipient=member,
                requester_revision=state_for(owner).revision,expires_at=timezone.now()+timedelta(days=1))
            OfficeAuditEvent.objects.create(office_id=office,actor=owner,action='office.settings',subject=label+'ΙΧΝΟΣ')
            for name,obj in (('entity',item),('cash',cash),('second',second),('category',category),('agreement',agreement),
                             ('payable',payable),('movement',movement),('invite',invite),('handover',handover)):
                setattr(cls,name+'_'+suffix,obj)

    def client_for(self,user):
        client=Client()
        if user is not None:
            # Every positive matrix actor proves MFA through the actual view;
            # ownership acceptance requires it even for an ordinary accountant.
            state=state_for(user)
            state.enrolled_at=timezone.now();state.save(update_fields=['enrolled_at'])
            staff_client_login(client,user)
        return client


class BoundaryGapTests(BoundaryFixtures,TestCase):
    @classmethod
    def setUpTestData(cls):cls.seed()

    def unknown_urlconf(self):
        module=ModuleType('s16_unknown_routes')
        def exposed(request):return HttpResponse(Entity.objects.get(pk=self.entity_b.pk).name)
        exposed.__module__='accounting.future_views'
        from .urls import urlpatterns
        module.urlpatterns=[path('s16-unclassified/',exposed,name='s16-unclassified'),*urlpatterns]
        return module

    def test_new_undeclared_business_route_is_closed_to_anonymous(self):
        with override_settings(ROOT_URLCONF=self.unknown_urlconf()):
            response=Client().get('/s16-unclassified/')
        self.assertEqual(response.status_code,302)
        self.assertNotIn(self.entity_b.name,response.content.decode())
        mark('gap','undeclared-route','anonymous','denied',response.status_code)

    def test_new_undeclared_business_route_is_closed_to_authenticated_staff(self):
        for user in (self.owner,self.member,self.platform):
            client=self.client_for(user)
            with override_settings(ROOT_URLCONF=self.unknown_urlconf()):response=client.get('/s16-unclassified/')
            self.assertEqual(response.status_code,403)
            self.assertNotIn(self.entity_b.name,response.content.decode())
            mark('gap','undeclared-route',user.username.split('-')[1],'denied',response.status_code)

    def test_readonly_business_fk_cannot_query_global_user_autocomplete(self):
        client=self.client_for(self.staff)
        response=client.get('/admin/autocomplete/',{'app_label':'accounting','model_name':'entity',
            'field_name':'archived_by','term':self.owner_b.username})
        self.assertEqual(response.status_code,403)
        self.assertNotIn(self.owner_b.username,response.content.decode())
        mark('gap','readonly-user-autocomplete','limited-staff','denied',response.status_code)

    def test_admin_new_work_choices_exclude_archived_entities_and_agreements(self):
        archive_counterparty(self.member,self.entity_a.pk,version=0,archive=True)
        response=self.client_for(self.staff).get('/admin/accounting/transaction/add/')
        self.assertEqual(response.status_code,200)
        form=response.context['adminform'].form
        self.assertNotIn(self.entity_a.pk,form.fields['entity'].queryset.values_list('pk',flat=True))
        self.assertNotIn(self.agreement_a.pk,form.fields['agreement'].queryset.values_list('pk',flat=True))
        mark('gap','archived-new-work-choices','limited-staff','excluded')

MANIFEST=Path(__file__).with_name('office_boundary_matrix.json')


def matrix():
    return json.loads(MANIFEST.read_text())


def mark(area,route,persona,scenario,actual='passed'):
    """Public evidence contains case metadata only, never response bodies/IDs."""
    destination=os.environ.get('ACCOUNTING_BOUNDARY_REPORT')
    if destination:
        row={'case_id':':'.join((area,route,persona,scenario)),'area':area,'route':route,
            'persona':persona,'scenario':scenario,'observed':actual,'result':'Passed'}
        descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
        with os.fdopen(descriptor,'a') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')


class BoundaryHTTPTests(BoundaryFixtures,TestCase):
    @classmethod
    def setUpTestData(cls):cls.seed()

    def url(self,name,foreign=False):
        suffix='b' if foreign else 'a'
        kwargs={}
        if name in {'entity-detail','edit-entity','archive-entity','restore-entity'}:kwargs={'pk':getattr(self,'entity_'+suffix).pk}
        if name in {'agreement-detail','edit-agreement','agreement-charge-add'}:kwargs={'pk':getattr(self,'agreement_'+suffix).pk}
        if name in {'cash-account-detail','cash-account-edit','cash-account-opening','cash-account-adjustment'}:kwargs={'pk':getattr(self,'cash_'+suffix).pk}
        if name in {'category-edit','category-retire'}:kwargs={'pk':getattr(self,'category_'+suffix).pk}
        if name=='office-invitation-action':kwargs={'key':getattr(self,'invite_'+suffix).pk,'action':'cancel'}
        if name=='office-member-action':kwargs={'user_id':(self.member_b if foreign else self.member).pk,'action':'deactivate'}
        if name=='office-handover-detail':kwargs={'key':getattr(self,'handover_'+suffix).pk}
        return reverse(name,kwargs=kwargs)

    def no_foreign(self,response):
        body=response.content.decode()
        for value in (self.entity_b.name,self.cash_b.name,self.category_b.name,self.agreement_b.description,
                      self.owner_b.username,self.member_b.username):self.assertNotIn(value,body)
        if response.context:
            for context in response.context:
                if 'form' in context:
                    form=context['form']
                    for field in form.fields.values():
                        queryset=getattr(field,'queryset',None)
                        if queryset is not None and hasattr(queryset.model,'office_id'):
                            self.assertFalse(queryset.exclude(office_id=A).exists())

    def personas(self):
        return {'anonymous':None,'owner':self.owner,'accountant':self.member,
            'inactive-profile':self.inactive,'inactive-user':self.disabled_user,'missing-profile':self.missing,
            'inactive-office':self.inactive_office,'platform-no-profile':self.platform_missing}

    def test_all_business_get_routes_role_matrix_no_foreign_values_or_writes(self):
        before_a,before_b=snapshot(A),snapshot(B)
        for persona,user in self.personas().items():
            client=self.client_for(user)
            for row in matrix()['routes']:
                if row['realm']!='office-business':continue
                name=row['route']
                with self.subTest(persona=persona,route=name):
                    if persona in {'anonymous','inactive-user'}:expected=302
                    elif persona not in {'owner','accountant'}:expected=403
                    elif persona=='accountant' and row['capability'] in {'office.settings','staff.manage','office.audit','finance.opening'}:expected=403
                    elif row['methods']==['POST']:expected=405
                    else:expected=200
                    response=client.get(self.url(name))
                    self.assertEqual(response.status_code,expected)
                    self.no_foreign(response)
                    self.assertIn('no-store',response.headers.get('Cache-Control',''))
                    mark('http-get',name,persona,'own-office',response.status_code)
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)

    def test_all_business_post_routes_invalid_membership_denied_without_writes(self):
        before_a,before_b=snapshot(A),snapshot(B)
        for persona,user in self.personas().items():
            if persona in {'owner','accountant'}:continue
            client=self.client_for(user)
            for row in matrix()['routes']:
                if row['realm']!='office-business' or 'POST' not in row['methods']:continue
                with self.subTest(persona=persona,route=row['route']):
                    response=client.post(self.url(row['route']),{'office_id':B,'entity':self.entity_b.pk,'password':'synthetic-invalid-proof'})
                    self.assertEqual(response.status_code,302 if persona in {'anonymous','inactive-user'} else 403)
                    self.no_foreign(response)
                    mark('http-post',row['route'],persona,'invalid-membership',response.status_code)
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)

    def test_foreign_detail_edit_archive_workflow_ids_denied_for_both_roles(self):
        before_a,before_b=snapshot(A),snapshot(B)
        for persona,user in (('owner',self.owner),('accountant',self.member)):
            client=self.client_for(user)
            for name in ('entity-detail','edit-entity','archive-entity','restore-entity','agreement-detail','edit-agreement',
                         'office-invitation-action','office-member-action','office-handover-detail'):
                for method in ('get','post'):
                    with self.subTest(persona=persona,route=name,method=method):
                        response=getattr(client,method)(self.url(name,True),{'version':0,'name':'FORGED_S16','office_id':A,'password':'invalid'})
                        expected=403 if persona=='accountant' and name in {'office-invitation-action','office-member-action'} else 405 if method=='get' and name in {'office-invitation-action','office-member-action'} else 404
                        self.assertEqual(response.status_code,expected)
                        self.no_foreign(response)
                        mark('foreign-id',name,persona,method,response.status_code)
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)

    def money_payload(self,name):
        data={'transaction_date':DAY.isoformat(),'description':'ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ S16','amount':'2,50',
              'cash_account':self.cash_a.pk,'category':self.category_a.pk,'entity':self.entity_a.pk,
              'agreement':(self.payable_a if name=='add-expense' else self.agreement_a).pk}
        if name in {'add-agreement','edit-agreement'}:
            data={'entity':self.entity_a.pk,'description':'ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΜΦΩΝΙΑ S16','agreement_type':'RECEIVABLE',
                  'total_amount':'75,00','start_date':DAY.isoformat(),'due_date':'','status':'OPEN'}
        if name=='add-transfer':data={'transfer_date':DAY.isoformat(),'from_account':self.cash_a.pk,'to_account':self.second_a.pk,'amount':'2,50','description':'ΔΟΚΙΜΑΣΤΙΚΗ ΜΕΤΑΦΟΡΑ S16'}
        return data

    def test_each_foreign_related_choice_denied_on_financial_post(self):
        for persona,user in (('owner',self.owner),('accountant',self.member)):
            client=self.client_for(user)
            for name,fields in {'add-income':('cash_account','category','entity','agreement'),
                    'add-expense':('cash_account','category','entity','agreement'),
                    'add-agreement':('entity',),'edit-agreement':('entity',),
                    'add-transfer':('from_account','to_account')}.items():
                for field in fields:
                    before_a,before_b=snapshot(A),snapshot(B)
                    data=self.money_payload(name)
                    data[field]={'cash_account':self.cash_b,'category':self.category_b,'entity':self.entity_b,
                        'agreement':self.payable_b if name=='add-expense' else self.agreement_b,
                        'from_account':self.cash_b,'to_account':self.second_b}[field].pk
                    with self.subTest(persona=persona,route=name,field=field):
                        response=client.post(self.url(name),data)
                        self.assertEqual(response.status_code,200)
                        self.assertTrue(response.context['form'].errors)
                        self.assertIn(field,response.context['form'].errors)
                        self.no_foreign(response)
                        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
                        mark('foreign-choice',name,persona,field,response.status_code)

    def test_report_and_list_filters_cannot_select_foreign_identifiers(self):
        before_b=snapshot(B)
        for name in ('transaction-list','summary-report','dashboard','agreement-list','counterparty-list'):
            for field,obj in (('entity',self.entity_b),('entity_id',self.entity_b),('cash_account',self.cash_b),('category',self.category_b)):
                response=self.client_for(self.member).get(reverse(name),{field:obj.pk})
                # Only routes using these financial selectors must reject it;
                # other list screens ignore unknown parameters without leaking.
                self.assertIn(response.status_code,(200,404))
                if name in {'transaction-list','summary-report'}:self.assertEqual(response.status_code,404)
                self.no_foreign(response)
                mark('filter',name,'accountant',field,response.status_code)
        self.assertEqual(snapshot(B),before_b)

    def test_regular_accounts_cannot_promote_via_office_or_global_admin_posts(self):
        for persona,user in (('owner',self.owner),('accountant',self.member)):
            client=self.client_for(user);before_a,before_b=snapshot(A),snapshot(B)
            for route in ('office-settings','office-members','office-ownership'):
                response=client.post(reverse(route),{'office':B,'office_id':B,'role':'owner','is_staff':'on','is_superuser':'on'})
                self.assertIn(response.status_code,(200,403))
                self.no_foreign(response)
                mark('role',route,persona,'forged-promotion',response.status_code)
            response=client.post('/admin/auth/user/'+str(self.owner_b.pk)+'/change/',{'is_superuser':'on','is_staff':'on'})
            self.assertIn(response.status_code,(302,403))
            self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
            mark('role','admin-auth-user',persona,'forged-promotion',response.status_code)

    def test_foreign_and_nonexistent_detail_identifiers_are_indistinguishable(self):
        for persona,user in (('owner',self.owner),('accountant',self.member)):
            client=self.client_for(user)
            for name in ('entity-detail','edit-entity','agreement-detail','edit-agreement'):
                foreign=client.get(self.url(name,True))
                missing=client.get(reverse(name,kwargs={'pk':999999999}))
                self.assertEqual(foreign.status_code,404);self.assertEqual(missing.status_code,404)
                # Django masks each CSRF token independently; compare the
                # rendered error after removing that intentional randomness.
                normalise=lambda body:re.sub(r'(name="csrfmiddlewaretoken" value=")[^"]+',r'\1<MASK>',body.decode())
                self.assertEqual(normalise(foreign.content),normalise(missing.content))
                mark('guessed-id',name,persona,'foreign-equals-missing',404)

    def test_two_office_client_demonstration_create_read_archive_restore_and_money(self):
        """Synthetic workflow only; no server is retained or human account created."""
        before_b=snapshot(B)
        client=self.client_for(self.member)
        response=client.post(reverse('add-entity'),{'name':'ΔΟΚΙΜΑΣΤΙΚΟΣ ΣΥΝΑΛΛΑΣΣΟΜΕΝΟΣ G1',
            'is_customer':'on','is_supplier':'on','legal_kind':'BUSINESS','vat_number':'000000602','version':0,'office_id':B})
        self.assertEqual(response.status_code,302)
        item=Entity.objects.get(name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΣΥΝΑΛΛΑΣΣΟΜΕΝΟΣ G1')
        self.assertEqual(str(item.office_id),A);self.assertTrue(item.is_customer and item.is_supplier)
        response=self.client_for(self.owner).get(reverse('entity-detail',args=[item.pk]));self.assertContains(response,item.name)
        data=self.money_payload('add-income');data.update(entity=item.pk,agreement='')
        response=client.post(reverse('add-income'),data);self.assertEqual(response.status_code,302)
        self.assertEqual(Transaction.objects.get(entity=item).amount,Decimal('2.50'))
        response=client.post(reverse('archive-entity',args=[item.pk]),{'version':0});self.assertEqual(response.status_code,302)
        item.refresh_from_db();self.assertTrue(item.is_archived)
        response=client.get(reverse('entity-detail',args=[item.pk]));self.assertContains(response,'2,50')
        response=client.post(reverse('restore-entity',args=[item.pk]),{'version':1});self.assertEqual(response.status_code,302)
        item.refresh_from_db();self.assertFalse(item.is_archived)
        self.assertEqual(list(CounterpartyEvent.objects.filter(entity=item).order_by('pk').values_list('action',flat=True)),['create','archive','restore'])
        self.assertEqual(self.client_for(self.member_b).get(reverse('entity-detail',args=[item.pk])).status_code,404)
        self.assertEqual(snapshot(B),before_b)
        mark('workflow','client-finance-archive-restore','accountant','two-office-demonstration')

class BoundaryAdminTests(BoundaryFixtures,TestCase):
    @classmethod
    def setUpTestData(cls):cls.seed()

    def test_business_admin_object_matrix_never_bypasses_office_for_superuser(self):
        before_a,before_b=snapshot(A),snapshot(B)
        for persona,user in (('limited-staff',self.staff),('platform-with-profile',self.platform)):
            client=self.client_for(user)
            for model in (Entity,CashAccount,Category,Agreement,Transaction):
                name=model._meta.model_name
                own=model.objects.filter(office_id=A).order_by('pk').first()
                foreign=model.objects.filter(office_id=B).order_by('pk').first()
                for action in ('changelist','add'):
                    response=client.get(reverse('admin:accounting_'+name+'_'+action))
                    self.assertEqual(response.status_code,200)
                    self.assertNotIn('ΞΕΝΟ_ΓΡΑΦΕΙΟ_Β_S16',response.content.decode())
                    mark('admin',name,persona,action,response.status_code)
                for action in ('change','history','delete'):
                    for method in ('get','post'):
                        response=getattr(client,method)(reverse('admin:accounting_'+name+'_'+action,args=[foreign.pk]),{'name':'FORGED_S16','office_id':A})
                        self.assertEqual(response.status_code,404)
                        self.assertNotIn('ΞΕΝΟ_ΓΡΑΦΕΙΟ_Β_S16',response.content.decode())
                        mark('admin',name,persona,'foreign-'+action+'-'+method,response.status_code)
                response=client.get(reverse('admin:accounting_'+name+'_history',args=[own.pk]));self.assertEqual(response.status_code,200)
                mark('admin',name,persona,'own-history',response.status_code)
                response=client.post(reverse('admin:accounting_'+name+'_changelist'),{'action':'delete_selected','_selected_action':[own.pk,foreign.pk]})
                self.assertEqual(response.status_code,403)
                mark('admin',name,persona,'bulk-denied',response.status_code)
                response=client.get(reverse('admin:accounting_'+name+'_changelist'),{'office__id__exact':B})
                self.assertEqual(response.status_code,400)
                mark('admin',name,persona,'office-filter-denied',response.status_code)
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)

    def test_business_admin_invalid_profiles_and_regular_accounts_cannot_enter(self):
        before_a,before_b=snapshot(A),snapshot(B)
        for persona,user in (('owner',self.owner),('accountant',self.member),('missing-profile',self.missing),
                             ('platform-no-profile',self.platform_missing),('anonymous',None)):
            client=self.client_for(user)
            for model in matrix()['business_admin_models']:
                response=client.get(reverse('admin:accounting_'+model+'_changelist'))
                self.assertIn(response.status_code,(302,403))
                self.assertNotIn('ΞΕΝΟ_ΓΡΑΦΕΙΟ_Β_S16',response.content.decode())
                mark('admin-entry',model,persona,'denied',response.status_code)
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)

    def test_autocomplete_valid_editable_relations_scoped_and_archive_filtered(self):
        client=self.client_for(self.staff)
        for model,field in (('category','parent'),('agreement','entity'),('transaction','cash_account'),
                             ('transaction','category'),('transaction','entity'),('transaction','agreement')):
            response=client.get('/admin/autocomplete/',{'app_label':'accounting','model_name':model,'field_name':field,'term':''})
            # CashAccountAdmin has no search_fields and Django deliberately
            # disables that autocomplete. Its ordinary dropdown is scoped.
            self.assertEqual(response.status_code,404 if field=='cash_account' else 200)
            self.assertNotIn('ΞΕΝΟ_ΓΡΑΦΕΙΟ_Β_S16',response.content.decode())
            mark('autocomplete',model,'limited-staff',field,response.status_code)
        archive_counterparty(self.member,self.entity_a.pk,version=0,archive=True)
        for field in ('entity','agreement'):
            response=client.get('/admin/autocomplete/',{'app_label':'accounting','model_name':'transaction','field_name':field})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['results'],[])
            mark('autocomplete','transaction','limited-staff','archived-'+field,response.status_code)

    def test_autocomplete_rejects_cross_realm_and_undeclared_sources(self):
        before_b=snapshot(B)
        for persona,user in (('limited-staff',self.staff),('platform-with-profile',self.platform)):
            client=self.client_for(user)
            for model,field in (('entity','archived_by'),('entity','office'),('transaction','office'),
                    ('staffinvitation','invited_by'),('accountantprofile','user'),('entity','name'),('entity','missing'),('missing','entity')):
                response=client.get('/admin/autocomplete/',{'app_label':'accounting','model_name':model,'field_name':field,'term':self.owner_b.username})
                self.assertEqual(response.status_code,403)
                self.assertNotIn(self.owner_b.username,response.content.decode())
                mark('autocomplete-source',model,persona,field,response.status_code)
        self.assertEqual(snapshot(B),before_b)

    def test_autocomplete_requires_source_permission_even_with_remote_view_permission(self):
        self.staff.user_permissions.remove(*Permission.objects.filter(content_type__app_label='accounting',content_type__model='transaction'))
        response=self.client_for(self.staff).get('/admin/autocomplete/',{'app_label':'accounting','model_name':'transaction','field_name':'entity'})
        self.assertEqual(response.status_code,403)
        mark('autocomplete','transaction','limited-staff','no-source-permission',response.status_code)

    def test_admin_post_foreign_relations_is_invalid_without_writes(self):
        client=self.client_for(self.staff)
        for field,target in (('cash_account',self.cash_b),('category',self.category_b),('entity',self.entity_b),('agreement',self.agreement_b)):
            before_a,before_b=snapshot(A),snapshot(B)
            data={'transaction_date':DAY.isoformat(),'description':'ΔΟΚΙΜΑΣΤΙΚΟ ADMIN S16','amount':'2,50','transaction_type':'INCOME',
                'cash_account':self.cash_a.pk,'category':self.category_a.pk,'entity':self.entity_a.pk,'agreement':'','office':B}
            data[field]=target.pk
            response=client.post(reverse('admin:accounting_transaction_add'),data)
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context['adminform'].form.errors)
            self.assertIn(field,response.context['adminform'].form.errors)
            self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
            mark('admin-post','transaction','limited-staff','foreign-'+field,response.status_code)

    def test_admin_valid_post_uses_actor_office_and_global_auth_is_separate(self):
        before_b=snapshot(B)
        response=self.client_for(self.staff).post(reverse('admin:accounting_cashaccount_add'),{
            'name':'ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ ADMIN G1','opening_balance':'12.34','is_active':'on','office_id':B,'_save':'1'})
        self.assertEqual(response.status_code,302, response.context['adminform'].form.errors if response.status_code==200 else '')
        item=CashAccount.objects.get(name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ ADMIN G1')
        self.assertEqual(str(item.office_id),A);self.assertEqual(item.opening_balance,Decimal('0.00'));self.assertIsNone(item.opening_date)  # Untrusted admin amount cannot approve an opening.
        self.assertEqual(snapshot(B),before_b)
        limited=self.client_for(self.staff)
        for target in (reverse('admin:auth_user_changelist'),reverse('admin:auth_user_change',args=[self.owner_b.pk]),
                       reverse('admin:app_list',kwargs={'app_label':'auth'})):
            response=limited.get(target);self.assertEqual(response.status_code,403)
            self.assertNotIn(self.owner_b.username,response.content.decode())
        # A platform operator may manage the auth realm without an office. That
        # privilege never makes an office business query or write unscoped.
        operator=self.client_for(self.platform_missing)
        self.assertEqual(operator.get(reverse('admin:auth_user_changelist')).status_code,200)
        self.assertEqual(operator.get(reverse('admin:accounting_entity_changelist')).status_code,403)
        self.assertEqual(snapshot(B),before_b)
        mark('admin-post','cashaccount','limited-staff','valid-actor-office',302)
        mark('global-auth','auth-user','limited-staff','denied',403)
        mark('global-auth','auth-user','platform-no-profile','operator-only',200)

    def test_historical_admin_link_retained_but_another_archived_choice_denied(self):
        archive_counterparty(self.member,self.entity_a.pk,version=0,archive=True)
        other=Entity.objects.create(office_id=A,name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΑΡΧΕΙΟΘΕΤΗΜΕΝΟΣ S16',vat_number='000000603',entity_type='CUSTOMER')
        archive_counterparty(self.member,other.pk,version=0,archive=True)
        client=self.client_for(self.staff)
        response=client.get(reverse('admin:accounting_transaction_change',args=[self.movement_a.pk]))
        self.assertEqual(response.status_code,200)
        form=response.context['adminform'].form
        self.assertNotIn('entity',form.fields)  # Posted originals are wholly read-only.
        self.assertContains(response,self.entity_a.name)
        self.assertNotContains(response,other.name)
        self.assertNotContains(response,self.entity_b.name)
        self.assertEqual(client.post(reverse('admin:accounting_transaction_change',args=[self.movement_a.pk]),
            {'entity':other.pk,'amount':'999.00'}).status_code,403)
        self.movement_a.refresh_from_db();self.assertEqual(self.movement_a.entity_id,self.entity_a.pk)
        mark('admin-history','transaction','limited-staff','only-existing-archived-link')


class BoundaryDatabaseTests(BoundaryFixtures,TestCase):
    @classmethod
    def setUpTestData(cls):cls.seed()

    def denied(self,label,operation):
        before_a,before_b=snapshot(A),snapshot(B)
        with self.assertRaises(IntegrityError),transaction.atomic():
            operation()
            with connection.cursor() as cursor:cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
        mark('database',label,'operator-sql','denied')

    def test_every_business_foreign_key_rejects_cross_office_sql_update(self):
        for name,obj,field,target in (('category-parent',self.category_a,'parent',self.category_b),
             ('agreement-entity',self.agreement_a,'entity',self.entity_b),
             ('transaction-cashaccount',self.movement_a,'cash_account',self.cash_b),
             ('transaction-category',self.movement_a,'category',self.category_b),
             ('transaction-entity',self.movement_a,'entity',self.entity_b),
             ('transaction-agreement',self.movement_a,'agreement',self.agreement_b)):
            self.denied(name,lambda obj=obj,field=field,target=target:type(obj).objects.filter(pk=obj.pk).update(**{field:target}))

    def test_membership_identity_and_each_business_office_are_database_immutable(self):
        self.denied('one-office-per-user',lambda:AccountantProfile.objects.create(user=self.member,office_id=B,role='accountant'))
        self.denied('profile-office-immutable',lambda:AccountantProfile.objects.filter(user=self.member).update(office_id=B))
        self.denied('profile-user-immutable',lambda:AccountantProfile.objects.filter(user=self.member).update(user=self.missing))
        for model in (Entity,CashAccount,Category,Agreement,Transaction):
            obj=model.objects.filter(office_id=A).first()
            self.denied(model._meta.model_name+'-office-immutable',lambda model=model,obj=obj:model.objects.filter(pk=obj.pk).update(office_id=B))
            self.denied(model._meta.model_name+'-office-required',lambda model=model,obj=obj:model.objects.filter(pk=obj.pk).update(office_id=None))
        self.assertGreaterEqual(AccountantProfile.objects.filter(office_id=A,is_active=True).count(),2)
        mark('database','several-colleagues','operator-sql','allowed')

    def test_staff_workflow_and_counterparty_event_composite_links(self):
        for field in ('invited_by','accepted_by'):
            self.denied('invitation-'+field,lambda field=field:StaffInvitation.objects.filter(pk=self.invite_a.pk).update(**{field:self.member_b}))
        for field in ('requested_by','recipient'):
            self.denied('handover-'+field,lambda field=field:OwnershipHandover.objects.filter(pk=self.handover_a.pk).update(**{field:self.member_b}))
        for field in ('actor','target_user'):
            self.denied('audit-'+field,lambda field=field:OfficeAuditEvent.objects.create(office_id=A,action='office.settings',**{field:self.member_b}))
        self.denied('counterparty-event-entity',lambda:CounterpartyEvent.objects.create(office_id=A,entity=self.entity_b,actor=self.member,action='create',version=0,changed_fields=[]))
        self.denied('counterparty-event-actor',lambda:CounterpartyEvent.objects.create(office_id=A,entity=self.entity_a,actor=self.member_b,action='create',version=0,changed_fields=[]))

    def test_service_and_execution_adapter_refresh_membership_and_expected_office(self):
        for persona,user in (('owner',self.owner),('accountant',self.member),('platform-with-profile',self.platform)):
            self.assertEqual(execution_record(user_id=user.pk,expected_office_id=A,model=Entity,key=self.entity_a.pk).pk,self.entity_a.pk)
            for office,key in ((B,self.entity_b.pk),(B,self.entity_a.pk),(A,self.entity_b.pk)):
                with self.assertRaises((PermissionDenied,Http404)):
                    execution_record(user_id=user.pk,expected_office_id=office,model=Entity,key=key)
            mark('execution-adapter','entity',persona,'scope-refreshed')
        for persona,user in (('inactive-profile',self.inactive),('inactive-user',self.disabled_user),('missing-profile',self.missing),('inactive-office',self.inactive_office),('platform-no-profile',self.platform_missing)):
            with self.assertRaises(PermissionDenied):execution_record(user_id=user.pk,expected_office_id=A,model=Entity,key=self.entity_a.pk)
            with self.assertRaises(PermissionDenied):save_for_user(CashAccount(name='FORGED_S16'),user)
            mark('execution-adapter','entity',persona,'denied')
        with self.assertRaises(PermissionDenied):execution_record(user_id=self.owner.pk,expected_office_id=A,model=Office,key=A)
        with self.assertRaises(PermissionDenied):execution_record(user_id=self.owner.pk,expected_office_id=A,model=Entity,key=self.entity_a.pk,capability='unknown')
        before_a,before_b=snapshot(A),snapshot(B)
        with self.assertRaises(PermissionDenied):save_for_user(CashAccount(office_id=B,name='FORGED_S16'),self.platform)
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
        mark('execution-adapter','unsupported-model-capability','owner','denied')

class BoundaryInventoryTests(TestCase):
    def test_every_current_route_admin_model_and_operator_command_has_a_realm(self):
        from django.contrib import admin
        from . import urls
        from core import urls as root_urls
        from .capabilities import OfficeCapabilityMiddleware, is_business_view
        declared=matrix()
        self.assertEqual({p.name for p in urls.urlpatterns},{r['route'] for r in declared['routes']})
        self.assertEqual({p.name for p in root_urls.urlpatterns if getattr(p,'name',None)},set(declared['public_probes']))
        self.assertEqual(set(admin.site._registry).intersection(BUSINESS),{Entity,CashAccount,Category,Agreement,Transaction})
        self.assertEqual({name for name,app in get_commands().items() if app=='accounting'},set(declared['operator_commands']))
        for row in declared['routes']:
            callback=next(p.callback for p in urls.urlpatterns if p.name==row['route'])
            if row['realm']=='office-business':
                capability=getattr(callback,'office_capability',OfficeCapabilityMiddleware.ROUTES.get(row['route']))
                self.assertTrue(is_business_view(callback,row['route']))
                self.assertEqual(capability,row['capability'])
            else:self.assertFalse(is_business_view(callback,row['route']))
            mark('inventory',row['route'],'review','declared-'+row['realm'])
        for gap in declared['future_pending']:self.assertTrue(declared['future_pending'][gap])

    def test_identity_exemption_requires_both_module_and_name(self):
        from .capabilities import is_business_view
        def future(request):return HttpResponse('synthetic')
        future.__module__='accounting.future_views'
        self.assertTrue(is_business_view(future,'login'))
        future.__module__='accounting.auth_views'
        self.assertTrue(is_business_view(future,'undeclared'))
        self.assertFalse(is_business_view(future,'login'))
        mark('inventory','identity-exemption','review','module-and-name-required')


class BoundaryOperatorTests(BoundaryFixtures,TestCase):
    @classmethod
    def setUpTestData(cls):cls.seed()

    def test_review_template_export_is_private_and_outside_tracked_source(self):
        import tempfile
        before_a,before_b=snapshot(A),snapshot(B)
        with tempfile.TemporaryDirectory(prefix='s16-private-review-') as directory:
            for command in ('backfill_office_records','backfill_accountant_profiles'):
                target=Path(directory)/command
                call_command(command,export_template=target,stdout=io.StringIO())
                self.assertEqual(target.stat().st_mode&0o777,0o600)
                self.assertRaises(CommandError,call_command,command,export_template=target,stdout=io.StringIO())
                self.assertRaises(CommandError,call_command,command,export_template=Path(settings.BASE_DIR)/'s16-do-not-create.json',stdout=io.StringIO())
                self.assertFalse((Path(settings.BASE_DIR)/'s16-do-not-create.json').exists())
                mark('operator',command,'database-operator','private-template')
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)

    def test_operator_apply_requires_reviewed_digest_and_cannot_move_owned_records(self):
        import tempfile
        from .legacy_ownership import template
        from .legacy_membership import fingerprint
        before_a,before_b=snapshot(A),snapshot(B)
        document=template();document.update(reviewed_by='synthetic-operator',reviewed_at=timezone.now().isoformat())
        target=next(r for r in document['assignments'] if r['model']=='entity' and r['id']==self.entity_a.pk)
        target['office_id']=B
        with tempfile.TemporaryDirectory(prefix='s16-ownership-') as directory:
            path=Path(directory)/'review.json';path.write_text(json.dumps(document))
            with self.assertRaises(CommandError):call_command('backfill_office_records',mapping=path,apply=True,stdout=io.StringIO())
            with self.assertRaises(CommandError):call_command('backfill_office_records',mapping=path,apply=True,expected_sha256=fingerprint(document),stdout=io.StringIO())
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
        mark('operator','backfill_office_records','database-operator','review-and-immutable-owner')

    def test_operator_membership_review_cannot_transfer_existing_account(self):
        import tempfile
        from .legacy_membership import template,fingerprint
        before_a,before_b=snapshot(A),snapshot(B)
        document=template();document.update(reviewed_by='synthetic-operator',reviewed_at=timezone.now().isoformat())
        for row in document['mappings']:
            profile=AccountantProfile.objects.filter(user_id=row['user_id']).first()
            if profile:row.update(office_id=str(profile.office_id),role=profile.role)
        next(r for r in document['mappings'] if r['user_id']==self.member.pk)['office_id']=B
        with tempfile.TemporaryDirectory(prefix='s16-membership-') as directory:
            path=Path(directory)/'review.json';path.write_text(json.dumps(document))
            with self.assertRaisesMessage(CommandError,'Το υπάρχον προφίλ διαφέρει'):
                call_command('backfill_accountant_profiles',mapping=path,apply=True,expected_sha256=fingerprint(document),stdout=io.StringIO())
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
        mark('operator','backfill_accountant_profiles','database-operator','cannot-transfer-existing-user')

    def test_seed_and_probe_restrict_profile_and_validate_explicit_uuid(self):
        before_a,before_b=snapshot(A),snapshot(B)
        for command in ('seed_development_data','probe_development_database'):
            with self.assertRaises(CommandError):call_command(command,office=A,stdout=io.StringIO())
            with override_settings(SETTINGS_MODULE='core.settings.local'):
                with self.assertRaises(CommandError):call_command(command,office='invalid-office-uuid',stdout=io.StringIO())
            mark('operator',command,'database-operator','profile-and-explicit-uuid')
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)

    def test_explicit_local_seed_is_idempotent_in_selected_office_only(self):
        before_a=snapshot(A)
        with override_settings(SETTINGS_MODULE='core.settings.local'):
            call_command('seed_development_data',office=B,stdout=io.StringIO())
            selected=snapshot(B)
            call_command('seed_development_data',office=B,stdout=io.StringIO())
            self.assertEqual(snapshot(B),selected)
            output=io.StringIO();call_command('probe_development_database',office=B,stdout=output)
            probe=json.loads(output.getvalue())
            self.assertEqual(str(Entity.objects.get(pk=probe['synthetic_markers']['client_id']).office_id),B)
            self.assertEqual(str(CashAccount.objects.get(pk=probe['synthetic_markers']['account_id']).office_id),B)
        self.assertEqual(snapshot(A),before_a)
        mark('operator','seed_development_data','database-operator','explicit-office-idempotent')
        mark('operator','probe_development_database','database-operator','selected-synthetic-marker-only')

    def test_owner_bootstrap_cannot_reassign_or_promote_existing_account(self):
        before_a,before_b=snapshot(A),snapshot(B)
        with patch('accounting.management.commands.bootstrap_office_owner.getpass') as password:
            with self.assertRaises(CommandError):call_command('bootstrap_office_owner',office=A,
                username=self.member_b.username,email=self.member_b.email,operator='synthetic-operator',stdout=io.StringIO())
            password.assert_not_called()
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
        mark('operator','bootstrap_office_owner','database-operator','existing-account-unchanged')

    def test_auth_cleanup_does_not_modify_office_business_records(self):
        before_a,before_b=snapshot(A),snapshot(B)
        call_command('prune_auth_attempts',stdout=io.StringIO())
        self.assertEqual(snapshot(A),before_a);self.assertEqual(snapshot(B),before_b)
        mark('operator','prune_auth_attempts','database-operator','auth-metadata-only')


class BoundaryConcurrencyTests(BoundaryFixtures,TransactionTestCase):
    def setUp(self):self.seed()

    def pg_pid(self):
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout='8s'")
            cursor.execute('SELECT pg_backend_pid()')
            return cursor.fetchone()[0]

    def wait_blocked(self,pid):
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT cardinality(pg_blocking_pids(%s))',[pid])
                if cursor.fetchone()[0]>0:return
            time.sleep(.02)
        self.fail('Independent PostgreSQL writer did not reach a real lock wait')

    def revoke(self,kind):
        if kind=='profile':change_membership(user_id=self.member.pk,office_id=A,role='accountant',is_active=False)
        elif kind=='office':Office.objects.filter(pk=A).update(is_active=False)
        elif kind=='user':get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)

    def writer(self,mode,client=None):
        user=get_user_model().objects.get(pk=self.member.pk)
        if mode=='helper':
            save_for_user(Transaction(office_id=A,cash_account=self.cash_a,entity=self.entity_a,
                transaction_type='INCOME',amount=Decimal('2.50'),transaction_date=DAY,description='ΔΟΚΙΜΑΣΤΙΚΟΣ ΑΓΩΝΑΣ S16'),user)
            return 'created'
        response=client.post(reverse('add-transfer'),{'transfer_date':DAY.isoformat(),'amount':'2,50',
            'from_account':self.cash_a.pk,'to_account':self.second_a.pk,'description':'ΔΟΚΙΜΑΣΤΙΚΟΣ ΑΓΩΝΑΣ S16'})
        return response.status_code

    def revoke_then_write(self,kind,mode):
        client=self.client_for(self.member) if mode=='transfer' else None
        before_a,before_b=snapshot(A),snapshot(B)
        held,release=Event(),Event();pids=Queue()
        def revoker():
            close_old_connections()
            try:
                with transaction.atomic():
                    Office.objects.select_for_update().get(pk=A)
                    self.revoke(kind);held.set()
                    if not release.wait(8):raise RuntimeError('Revocation release was not signalled')
                return 'revoked'
            finally:connection.close()
        def writer():
            close_old_connections()
            try:
                pids.put(self.pg_pid())
                try:return self.writer(mode,client)
                except PermissionDenied:return 'denied'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            revoke_future=pool.submit(revoker)
            try:
                self.assertTrue(held.wait(6))
                write_future=pool.submit(writer)
                self.wait_blocked(pids.get(timeout=6))
            finally:release.set()
            self.assertEqual(revoke_future.result(timeout=8),'revoked')
            self.assertIn(write_future.result(timeout=8),('denied',403))
        after=snapshot(A)
        for model in BUSINESS:self.assertEqual(after[model._meta.model_name],before_a[model._meta.model_name])
        self.assertEqual(snapshot(B),before_b)
        mark('concurrency',mode,'accountant','revoked-'+kind+'-before-write')

    def test_profile_revocation_wins_before_service_write(self):self.revoke_then_write('profile','helper')
    def test_office_revocation_wins_before_service_write(self):self.revoke_then_write('office','helper')
    def test_user_revocation_wins_before_service_write(self):self.revoke_then_write('user','helper')
    def test_profile_revocation_wins_before_transfer_post(self):self.revoke_then_write('profile','transfer')

    def test_committed_post_precedes_later_revocation_in_other_lock_order(self):
        before=Transaction.objects.count();held,release=Event(),Event();pids=Queue()
        def writer():
            close_old_connections()
            try:
                with transaction.atomic():
                    result=self.writer('helper');held.set()
                    if not release.wait(8):raise RuntimeError('Posting release was not signalled')
                return result
            finally:connection.close()
        def revoker():
            close_old_connections()
            try:
                pids.put(self.pg_pid());self.revoke('profile');return 'revoked'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            post=pool.submit(writer)
            try:
                self.assertTrue(held.wait(6));revoke=pool.submit(revoker)
                self.wait_blocked(pids.get(timeout=6))
            finally:release.set()
            self.assertEqual(post.result(timeout=8),'created');self.assertEqual(revoke.result(timeout=8),'revoked')
        self.assertEqual(Transaction.objects.count(),before+1)
        self.assertFalse(AccountantProfile.objects.get(user=self.member).is_active)
        mark('concurrency','helper','accountant','write-before-later-revocation')
