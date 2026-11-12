"""S15 outcomes on PostgreSQL: workspace, history, migration and actual races."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from decimal import Decimal
from importlib import import_module
import json
import secrets
from queue import Queue
from threading import Barrier, Event
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .counterparty_services import archive_counterparty, save_counterparty
from .counterparty_validation import SPACES, afm_key
from .forms import AgreementForm, EntityForm, ExpenseForm, IncomeForm
from .membership import create_accountant_profile, change_membership
from .models import AccountantProfile, Agreement, CashAccount, Category, CounterpartyEvent, Entity, Office, Transaction
from .tests_auth_support import staff_client_login

A = '00000000-0000-4000-8000-00000000000a'
B = '00000000-0000-4000-8000-00000000000b'
DAY = date(2026, 1, 15)
LATEST = '0010_counterparty_database_guards'


def values(**changes):
    return {'name':'ΔΟΚΙΜΑΣΤΙΚΗ ΕΤΑΙΡΕΙΑ Ωμέγα', 'is_customer':True, 'is_supplier':True,
        'legal_kind':'BUSINESS', 'vat_number':'000000201', 'tax_office':'ΔΟΚΙΜΑΣΤΙΚΗ Δ.Ο.Υ.',
        'address':'Οδός Δοκιμής 12', 'city':'Αθήνα', 'postal_code':'115 27',
        'phone_number':'+30 210 1234567', 'email':'synthetic@example.invalid', **changes}


def actor(username, office=A, **flags):
    user = get_user_model().objects.create_user(username, username+'@example.invalid', secrets.token_urlsafe(32), **flags)
    create_accountant_profile(user_id=user.pk, office_id=office, role='accountant')
    return user


class CounterpartySyntaxTests(SimpleTestCase):
    def test_equivalent_afms_keep_leading_zeroes(self):
        for text in ('000000201', 'el 000-000-201', ' ００００００２０１ ', 'EL\u00a0000\u202f000\t201'):
            with self.subTest(text=text):self.assertEqual(afm_key(text), '000000201')

    def test_blank_and_bad_syntax_are_distinct(self):
        for value in (None, '', ' \t\u00a0 '):self.assertEqual(afm_key(value), '')
        for value in ('123', '1234567890', '01234567x', '+000000201', 'GR000000201','EL'):
            with self.subTest(value=value),self.assertRaises(ValidationError):afm_key(value)

    def test_frozen_migration_and_runtime_normalisation_agree(self):
        frozen = import_module('accounting.migrations.0009_counterparty_workspace')
        for value in ('EL 000-000-201', None, '', '００００００２０１', *[f'000{space}000201' for space in SPACES]):
            self.assertEqual(frozen.normalise(value), afm_key(value))


class CounterpartyWorkspaceTests(TestCase):
    fixtures = ['s11_offices']

    @classmethod
    def setUpTestData(cls):
        cls.user = actor('s15-accountant')
        cls.other = actor('s15-other', B)
        cls.entity = Entity.objects.create(office_id=A, entity_type='CUSTOMER', name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ Α', vat_number='000000101')
        cls.foreign = Entity.objects.create(office_id=B, entity_type='SUPPLIER', name='ΑΠΟΡΡΗΤΟ ΓΡΑΦΕΙΟΥ Β', vat_number='000000101')
        cls.cash = CashAccount.objects.create(office_id=A, name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ', opening_balance='100.00')
        cls.category = Category.objects.create(office_id=A, name='ΔΟΚΙΜΑΣΤΙΚΗ ΚΑΤΗΓΟΡΙΑ')

    def setUp(self):
        staff_client_login(self.client, self.user)

    def create(self, **changes):
        return save_counterparty(self.user, values(**changes))

    def history(self, entity=None):
        entity = entity or self.entity
        agreement = Agreement.objects.create(office_id=A, entity=entity, agreement_type='RECEIVABLE', description='ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΜΦΩΝΙΑ', total_amount=Decimal('1234.56'), start_date=DAY)
        payment = Transaction.objects.create(office_id=A, entity=entity, agreement=agreement, cash_account=self.cash,
            transaction_type='INCOME', amount=Decimal('12.34'), transaction_date=DAY, description='ΔΟΚΙΜΑΣΤΙΚΗ ΕΙΣΠΡΑΞΗ')
        return agreement, payment

    def archive(self, entity=None):
        entity = entity or self.entity
        return archive_counterparty(self.user, entity.pk, version=entity.record_version, archive=True)

    def test_create_both_roles_is_one_office_owned_identity(self):
        response = self.client.post('/entity/add/', {**values(), 'version':0, 'office':B, 'office_id':B,
            'entity_type':'SUPPLIER', 'is_archived':True, 'is_staff':True})
        self.assertEqual(response.status_code,302)
        item = Entity.objects.get(vat_key='000000201',office_id=A)
        self.assertTrue(item.is_customer and item.is_supplier)
        self.assertFalse(item.is_archived)
        self.assertEqual(item.legal_kind,'BUSINESS')
        self.assertEqual(CounterpartyEvent.objects.get(entity=item).actor,self.user)
        self.assertEqual(Entity.objects.filter(vat_key='000000201').count(),1)

    def test_both_roles_appear_in_each_list_with_same_primary_key(self):
        item=self.create()
        for route in ('/customers/','/suppliers/','/counterparties/?role=both'):
            response=self.client.get(route)
            self.assertContains(response,item.name)
            self.assertIn(item.pk,[r.pk for r in response.context['counterparties']])
        self.assertEqual(Entity.objects.filter(vat_key=item.vat_key,office_id=A).count(),1)

    def test_new_record_requires_explicit_person_or_business(self):
        for kind in ('','UNREVIEWED','UNKNOWN'):
            response=self.client.post('/entity/add/',{**values(legal_kind=kind),'version':0})
            self.assertEqual(response.status_code,200)
            self.assertIn('legal_kind',response.context['form'].errors)
        self.assertFalse(Entity.objects.filter(vat_key='000000201').exists())

    def test_legacy_classification_is_not_inferred_from_commercial_role(self):
        self.assertEqual(self.entity.legal_kind,'UNREVIEWED')
        response=self.client.get(reverse('entity-detail',args=[self.entity.pk]))
        self.assertContains(response,'Επιβεβαιώστε αν η εγγραφή')

    def test_missing_name_and_missing_roles_have_visible_errors(self):
        for changes, field in (({'name':'   '},'name'),({'is_customer':False,'is_supplier':False},'__all__')):
            response=self.client.post('/entity/add/',{**values(**changes),'version':0})
            self.assertEqual(response.status_code,200)
            self.assertIn(field,response.context['form'].errors)
            self.assertContains(response,'role="alert"')

    def test_invalid_identity_contacts_return_field_errors_without_writes(self):
        for field,text in (('vat_number','12x'),('email','not-an-email'),('phone_number','+30 call me'),('postal_code','<script>'),('name','name\x01')):
            with self.subTest(field=field):
                response=self.client.post('/entity/add/',{**values(**{field:text}),'version':0})
                self.assertEqual(response.status_code,200)
                self.assertIn(field,response.context['form'].errors)
        self.assertFalse(CounterpartyEvent.objects.exists())

    def test_normalised_duplicate_is_rejected_with_field_error(self):
        self.create()
        response=self.client.post('/entity/add/',{**values(vat_number='EL 000-000-201'),'version':0})
        self.assertEqual(response.status_code,200)
        self.assertIn('vat_number',response.context['form'].errors)
        self.assertEqual(Entity.objects.filter(vat_key='000000201',office_id=A).count(),1)

    def test_same_afm_is_independent_in_another_office(self):
        first=self.create()
        other=save_counterparty(self.other,values(vat_number='EL 000-000-201',name='ΔΟΚΙΜΑΣΤΙΚΗ ΑΛΛΗ ΕΓΓΡΑΦΗ'))
        self.assertNotEqual(first.pk,other.pk)
        self.assertNotEqual(first.office_id,other.office_id)
        self.assertNotContains(self.client.get('/counterparties/'),other.name)

    def test_multiple_blank_afms_are_allowed(self):
        self.create(vat_number='')
        self.create(vat_number='',name='ΔΟΚΙΜΑΣΤΙΚΟ ΦΥΣΙΚΟ ΠΡΟΣΩΠΟ',legal_kind='INDIVIDUAL')
        self.assertEqual(Entity.objects.filter(office_id=A,vat_key='').count(),2)

    def test_search_normalised_afm_and_greek_name(self):
        item=self.create()
        for query in ('el 000-000-201','000-201','Ωμέγα'):
            response=self.client.get('/counterparties/',{'q':query})
            self.assertEqual([r.pk for r in response.context['counterparties']],[item.pk])

    def test_role_and_classification_filters(self):
        both=self.create()
        person=self.create(vat_number='000000202',name='ΔΟΚΙΜΑΣΤΙΚΟ ΠΡΟΣΩΠΟ',is_supplier=False,legal_kind='INDIVIDUAL')
        self.assertEqual([r.pk for r in self.client.get('/counterparties/?role=both').context['counterparties']],[both.pk])
        self.assertEqual([r.pk for r in self.client.get('/counterparties/?kind=INDIVIDUAL').context['counterparties']],[person.pk])

    def test_pagination_is_bounded_stable_and_preserves_filters(self):
        for number in range(30):Entity.objects.create(office_id=A,entity_type='CUSTOMER',name=f'ΔΟΚΙΜΑΣΤΙΚΗ ΟΜΑΔΑ {number:02}')
        first=self.client.get('/counterparties/',{'q':'ΟΜΑΔΑ','page':'1'})
        second=self.client.get('/counterparties/',{'q':'ΟΜΑΔΑ','page':'2'})
        self.assertEqual(len(first.context['counterparties']),25)
        self.assertEqual(len(second.context['counterparties']),5)
        self.assertFalse({e.pk for e in first.context['counterparties']} & {e.pk for e in second.context['counterparties']})
        self.assertContains(first,'page=2')
        self.assertContains(first,'q=')
        self.assertEqual(self.client.get('/counterparties/?page=invalid').status_code,200)

    def test_invalid_filters_are_greek_errors_and_do_not_leak_rows(self):
        for query in ({'role':'owner'},{'status':'unknown'},{'kind':'unknown'},{'q':'x'*101}):
            response=self.client.get('/counterparties/',query,HTTP_ACCEPT_LANGUAGE='en')
            self.assertEqual(response.status_code,200)
            self.assertTrue(response.context['form'].errors)
            self.assertEqual(list(response.context['counterparties']),[])
            self.assertNotContains(response,self.foreign.name)

    def test_consolidated_detail_links_contacts_history_and_enabled_work(self):
        item=self.create();agreement,payment=self.history(item)
        response=self.client.get(reverse('entity-detail',args=[item.pk]),HTTP_ACCEPT_LANGUAGE='en')
        for text in (item.name,item.email,item.phone_number,item.tax_office,'15/01/2026','1.234,56 €','12,34 €',agreement.description,payment.description):
            self.assertContains(response,text)
        for name in ('add-income','add-expense','transaction-list','add-agreement'):
            self.assertContains(response,reverse(name))
        self.assertEqual(response.headers['Content-Language'],'el')
        self.assertIn('no-store',response.headers['Cache-Control'])

    def test_history_pages_are_bounded(self):
        for number in range(12):self.history()
        response=self.client.get(reverse('entity-detail',args=[self.entity.pk]))
        self.assertEqual(len(response.context['agreements']),10)
        self.assertEqual(len(response.context['transactions']),10)
        second=self.client.get(reverse('entity-detail',args=[self.entity.pk]),{'agreement_page':2,'movement_page':2})
        self.assertEqual(len(second.context['agreements']),2)
        self.assertEqual(len(second.context['transactions']),2)

    def test_cross_office_detail_edit_archive_and_restore_are_404(self):
        for name in ('entity-detail','edit-entity','archive-entity','restore-entity'):
            for method in (self.client.get,self.client.post):
                response=method(reverse(name,args=[self.foreign.pk]),{**values(),'version':0})
                self.assertEqual(response.status_code,404)
                self.assertNotContains(response,self.foreign.name,status_code=404)

    def test_anonymous_and_inactive_members_cannot_modify(self):
        anonymous=Client()
        self.assertEqual(anonymous.post('/entity/add/',{**values(),'version':0}).status_code,302)
        AccountantProfile.objects.filter(user=self.user).update(is_active=False)
        response=self.client.post('/entity/add/',{**values(),'version':0})
        self.assertEqual(response.status_code,403)
        self.assertFalse(CounterpartyEvent.objects.exists())

    def test_missing_profile_is_denied(self):
        user=get_user_model().objects.create_user('s15-unaffiliated')
        staff_client_login(self.client,user)
        self.assertEqual(self.client.get('/counterparties/').status_code,403)

    def test_csrf_is_required_for_create_and_archive(self):
        client=Client(enforce_csrf_checks=True);staff_client_login(client,self.user)
        for path in ('/entity/add/',reverse('archive-entity',args=[self.entity.pk])):
            self.assertEqual(client.post(path,{**values(),'version':0}).status_code,403)
        self.entity.refresh_from_db();self.assertFalse(self.entity.is_archived)

    def test_stale_edit_cannot_overwrite_a_colleague(self):
        item=self.create()
        saved=save_counterparty(self.user,values(name='ΔΟΚΙΜΑΣΤΙΚΗ ΝΕΑ ΤΙΜΗ'),key=item.pk,version=item.record_version)
        response=self.client.post(reverse('edit-entity',args=[item.pk]),{**values(name='ΠΑΛΑΙΑ ΦΟΡΜΑ'),'version':0})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'άλλαξε από άλλον λογιστή')
        saved.refresh_from_db();self.assertEqual(saved.name,'ΔΟΚΙΜΑΣΤΙΚΗ ΝΕΑ ΤΙΜΗ')

    def test_revocation_between_form_validation_and_save_is_rechecked(self):
        form=EntityForm({**values(),'version':0},user=self.user)
        self.assertTrue(form.is_valid(),form.errors)
        AccountantProfile.objects.filter(user=self.user).update(is_active=False)
        with self.assertRaises(PermissionDenied):form.save()
        self.assertFalse(CounterpartyEvent.objects.exists())

    def test_archive_get_does_not_mutate_and_post_records_actor(self):
        path=reverse('archive-entity',args=[self.entity.pk])
        self.assertEqual(self.client.get(path).status_code,200)
        self.entity.refresh_from_db();self.assertFalse(self.entity.is_archived)
        self.assertEqual(self.client.post(path,{'version':0}).status_code,302)
        self.entity.refresh_from_db()
        self.assertTrue(self.entity.is_archived)
        self.assertEqual(self.entity.archived_by,self.user)
        self.assertIsNotNone(self.entity.archived_at)
        self.assertEqual(CounterpartyEvent.objects.get().action,'archive')

    def test_archive_restore_preserve_financial_ids_and_values(self):
        agreement,payment=self.history()
        original=(agreement.pk,agreement.total_amount,payment.pk,payment.amount,payment.agreement_id,payment.entity_id)
        item=self.archive()
        self.assertEqual(self.client.post(reverse('restore-entity',args=[item.pk]),{'version':item.record_version}).status_code,302)
        item.refresh_from_db();agreement.refresh_from_db();payment.refresh_from_db()
        self.assertFalse(item.is_archived)
        self.assertIsNone(item.archived_at)
        self.assertEqual(original,(agreement.pk,agreement.total_amount,payment.pk,payment.amount,payment.agreement_id,payment.entity_id))
        self.assertEqual(list(CounterpartyEvent.objects.order_by('pk').values_list('action',flat=True)),['archive','restore'])

    def test_archived_is_hidden_by_default_but_searchable_in_history(self):
        item=self.archive()
        self.assertNotContains(self.client.get('/customers/'),item.name)
        for status in ('all','archived'):
            self.assertContains(self.client.get('/customers/',{'status':status,'q':item.vat_number}),item.name)
        response=self.client.get(reverse('entity-detail',args=[item.pk]))
        self.assertContains(response,'Αρχειοθετημένη εγγραφή')
        self.assertNotContains(response,'?entity_id='+str(item.pk))

    def test_archived_edit_and_duplicate_afm_need_restore(self):
        item=self.archive()
        path=reverse('edit-entity',args=[item.pk])
        self.assertEqual(self.client.get(path).status_code,409)
        self.assertEqual(self.client.post(path,{**values(),'version':item.record_version}).status_code,409)
        response=self.client.post('/entity/add/',{**values(vat_number=item.vat_number),'version':0})
        self.assertIn('vat_number',response.context['form'].errors)

    def test_stale_and_repeated_archive_cannot_create_extra_events(self):
        self.archive()
        response=self.client.post(reverse('archive-entity',args=[self.entity.pk]),{'version':0})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(CounterpartyEvent.objects.count(),1)

    def test_archived_counterparties_and_agreements_are_not_new_choices(self):
        agreement,payment=self.history();self.archive()
        for form in (IncomeForm(user=self.user,agreements_queryset=Agreement.objects.all()),ExpenseForm(user=self.user,agreements_queryset=Agreement.objects.all()),AgreementForm(user=self.user)):
            self.assertNotIn(self.entity.pk,form.fields['entity'].queryset.values_list('pk',flat=True))
            if 'agreement' in form.fields:self.assertNotIn(agreement.pk,form.fields['agreement'].queryset.values_list('pk',flat=True))

    def test_forged_new_income_and_agreement_posts_are_rejected(self):
        agreement,payment=self.history();self.archive()
        posting={'transaction_date':DAY.isoformat(),'description':'ΑΠΟΡΡΙΠΤΕΑ ΚΙΝΗΣΗ','amount':'10,00',
            'cash_account':self.cash.pk,'category':self.category.pk,'entity':self.entity.pk,'agreement':agreement.pk}
        before=(Transaction.objects.count(),Agreement.objects.count())
        response=self.client.post('/income/add/',posting)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['form'].errors)
        response=self.client.post('/agreement/add/',{'entity':self.entity.pk,'agreement_type':'RECEIVABLE',
            'description':'ΑΠΟΡΡΙΠΤΕΑ ΣΥΜΦΩΝΙΑ','total_amount':'10,00','start_date':DAY.isoformat(),'status':'ACTIVE'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(before,(Transaction.objects.count(),Agreement.objects.count()))

    def test_archived_history_stays_on_movements_and_reports(self):
        agreement,payment=self.history()
        before=self.client.get('/report/').context['total_income']
        self.archive()
        self.assertContains(self.client.get('/transactions/',{'entity':self.entity.pk}),payment.description)
        self.assertContains(self.client.get(reverse('entity-detail',args=[self.entity.pk])),agreement.description)
        self.assertEqual(self.client.get('/report/').context['total_income'],before)

    def test_event_failure_rolls_back_identity_and_archive(self):
        with patch.object(CounterpartyEvent.objects,'create',side_effect=RuntimeError('Synthetic event failure')):
            with self.assertRaises(RuntimeError):self.create()
            with self.assertRaises(RuntimeError):self.archive()
        self.entity.refresh_from_db();self.assertFalse(self.entity.is_archived)
        self.assertFalse(Entity.objects.filter(vat_key='000000201').exists())

    def test_event_payload_has_only_field_names_and_is_append_only(self):
        item=self.create();event=CounterpartyEvent.objects.get(entity=item)
        self.assertNotIn(item.email,json.dumps(event.changed_fields))
        self.assertIn('email',event.changed_fields)
        for mutation in (lambda:CounterpartyEvent.objects.filter(pk=event.pk).update(action='restore'),
                         lambda:CounterpartyEvent.objects.filter(pk=event.pk).delete()):
            with self.assertRaises(IntegrityError),transaction.atomic():mutation()

    def test_event_and_archiver_database_links_are_same_office(self):
        for target,scope,user in ((self.entity,B,self.other),(self.foreign,A,self.user),(self.entity,A,self.other)):
            with self.assertRaises(IntegrityError),transaction.atomic():
                CounterpartyEvent.objects.create(office_id=scope,entity=target,actor=user,action='update',version=0)
                connection.check_constraints()
        with self.assertRaises(IntegrityError),transaction.atomic():
            Entity.objects.filter(pk=self.entity.pk).update(is_archived=True,archived_at=timezone.now(),archived_by=self.other)
            connection.check_constraints()

    def test_database_normalises_forged_keys_and_blocks_formatted_duplicates(self):
        item=self.create()
        Entity.objects.filter(pk=item.pk).update(vat_number='el 000-000-201',vat_key='999999999')
        item.refresh_from_db();self.assertEqual(item.vat_key,'000000201')
        with self.assertRaises(IntegrityError),transaction.atomic():
            Entity.objects.bulk_create([Entity(office_id=A,entity_type='SUPPLIER',name='ΔΟΚΙΜΑΣΤΙΚΟ ΔΙΠΛΟ',vat_number='００００００２０１')])

    def test_database_rejects_bad_afm_roles_classification_and_legacy_mapping_change(self):
        for changes in ({'vat_number':'invalid'},{'is_customer':False,'is_supplier':False},{'legal_kind':'unknown'},{'entity_type':'SUPPLIER'}):
            with self.subTest(changes=changes),self.assertRaises(IntegrityError),transaction.atomic():
                Entity.objects.filter(pk=self.entity.pk).update(**changes)

    def test_archive_blocks_orm_and_bulk_new_work_including_agreement_only(self):
        agreement,payment=self.history();self.archive()
        ordinary=Agreement(office_id=A,entity=self.entity,agreement_type='RECEIVABLE',description='ΔΟΚΙΜΗ',total_amount='1.00',start_date=DAY)
        with self.assertRaises(ValidationError):ordinary.save()
        with self.assertRaises(IntegrityError),transaction.atomic():Agreement.objects.bulk_create([ordinary])
        for entity in (None,self.entity):
            entry=Transaction(office_id=A,entity=entity,agreement=agreement,cash_account=self.cash,
                transaction_type='INCOME',description='ΔΟΚΙΜΗ',amount='1.00',transaction_date=DAY)
            with self.assertRaises(ValidationError):entry.save()
            with self.assertRaises(IntegrityError),transaction.atomic():Transaction.objects.bulk_create([entry])
        self.assertEqual(Transaction.objects.count(),1)

    def test_historical_reference_stays_valid_but_new_link_to_archive_is_denied(self):
        agreement,payment=self.history();self.archive()
        original_description=payment.description
        with self.assertRaises(IntegrityError),transaction.atomic():
            Transaction.objects.filter(pk=payment.pk).update(description='ΔΟΚΙΜΑΣΤΙΚΟ ΙΣΤΟΡΙΚΟ')
        payment.refresh_from_db();self.assertEqual(payment.description,original_description)
        other=Entity.objects.create(office_id=A,entity_type='CUSTOMER',name='ΔΟΚΙΜΑΣΤΙΚΟ ΕΝΕΡΓΟ')
        entry=Transaction.objects.create(office_id=A,entity=other,cash_account=self.cash,transaction_type='INCOME',
            description='ΔΟΚΙΜΗ',amount='1.00',transaction_date=DAY)
        with self.assertRaises(IntegrityError),transaction.atomic():Transaction.objects.filter(pk=entry.pk).update(entity=self.entity)

    def test_physical_deletion_cannot_remove_identity_and_history(self):
        agreement,payment=self.history()
        with self.assertRaises(IntegrityError),transaction.atomic():Entity.objects.filter(pk=self.entity.pk).delete()
        self.assertTrue(Agreement.objects.filter(pk=agreement.pk).exists())
        self.assertTrue(Transaction.objects.filter(pk=payment.pk).exists())

    def test_admin_is_scoped_and_cannot_mutate_archive_metadata(self):
        admin=actor('s15-admin',is_staff=True,is_superuser=True)
        client=Client();staff_client_login(client,admin)
        self.assertNotContains(client.get('/admin/accounting/entity/'),self.foreign.name)
        item=self.archive()
        self.assertEqual(client.post(f'/admin/accounting/entity/{item.pk}/change/',{**values(),'version':item.record_version}).status_code,403)
        response=client.get(f'/admin/accounting/entity/{self.foreign.pk}/change/')
        self.assertEqual(response.status_code,404)

    def test_admin_creates_both_roles_through_the_same_scoped_service(self):
        admin=actor('s15-creating-admin',is_staff=True,is_superuser=True)
        client=Client();staff_client_login(client,admin)
        response=client.post('/admin/accounting/entity/add/',{**values(),'version':0,'is_archived':True,'office_id':B,'_save':'Αποθήκευση'})
        self.assertEqual(response.status_code,302)
        item=Entity.objects.get(office_id=A,vat_key='000000201')
        self.assertTrue(item.is_customer and item.is_supplier)
        self.assertFalse(item.is_archived)
        self.assertEqual(CounterpartyEvent.objects.get(entity=item).actor,admin)

    def test_stale_admin_edit_is_a_greek_message_without_overwrite(self):
        admin=actor('s15-stale-admin',is_staff=True,is_superuser=True)
        client=Client();staff_client_login(client,admin)
        item=self.create()
        save_counterparty(self.user,values(name='ΔΟΚΙΜΑΣΤΙΚΗ ΤΕΛΕΥΤΑΙΑ ΤΙΜΗ'),key=item.pk,version=0)
        response=client.post(f'/admin/accounting/entity/{item.pk}/change/',{**values(name='ΠΑΛΑΙΑ ΤΙΜΗ'),'version':0,'_save':'Αποθήκευση'},follow=True)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'άλλαξε από άλλον λογιστή')
        item.refresh_from_db();self.assertEqual(item.name,'ΔΟΚΙΜΑΣΤΙΚΗ ΤΕΛΕΥΤΑΙΑ ΤΙΜΗ')

    def test_archive_after_form_validation_is_a_visible_greek_posting_error(self):
        validate=IncomeForm.is_valid
        def concurrent_archive(form):
            valid=validate(form)
            if valid:self.archive()
            return valid
        payload={'transaction_date':DAY.isoformat(),'description':'ΔΟΚΙΜΑΣΤΙΚΗ ΚΙΝΗΣΗ','amount':'10,00',
            'cash_account':self.cash.pk,'category':self.category.pk,'entity':self.entity.pk}
        with patch.object(IncomeForm,'is_valid',concurrent_archive):response=self.client.post('/income/add/',payload)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Η εγγραφή είναι αρχειοθετημένη')
        self.assertEqual(Transaction.objects.count(),0)

    def test_sql_and_python_afm_keys_agree_for_all_supported_spaces(self):
        for text in ('el 000-000-201','００００００２０１',None,'',*[f'000{x}000201' for x in SPACES]):
            with connection.cursor() as cursor:
                cursor.execute('SELECT accounting_s15_afm_key(%s)',[text])
                self.assertEqual(cursor.fetchone()[0],afm_key(text))


class CounterpartyConcurrencyTests(TransactionTestCase):
    fixtures = ['s11_offices']

    def setUp(self):
        self.user=actor('s15-race')
        self.entity=Entity.objects.create(office_id=A,entity_type='CUSTOMER',name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΑΓΩΝΑΣ',vat_number='000000301')
        self.cash=CashAccount.objects.create(office_id=A,name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ ΑΓΩΝΑ')

    def test_parallel_normalised_duplicate_is_one_record(self):
        gate=Barrier(2)
        def worker(text,office):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                Entity.objects.bulk_create([Entity(office_id=office,entity_type='CUSTOMER',name='ΔΟΚΙΜΑΣΤΙΚΗ ΙΔΙΑ ΤΑΥΤΟΤΗΤΑ',vat_number=text)])
                return 'created'
            except IntegrityError:return 'duplicate'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,text,A) for text in ('000000302','EL 000-000-302')]
            self.assertEqual(sorted(f.result(timeout=20) for f in futures),['created','duplicate'])
        self.assertEqual(Entity.objects.filter(office_id=A,vat_key='000000302').count(),1)

    def test_parallel_same_afm_in_two_offices_remains_independent(self):
        gate=Barrier(2)
        def worker(office):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                return Entity.objects.create(office_id=office,entity_type='CUSTOMER',name='ΔΟΚΙΜΗ',vat_number='000000303').pk
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[pool.submit(worker,office) for office in (A,B)]
            self.assertEqual(len({f.result(timeout=20) for f in results}),2)

    def test_two_stale_editors_cannot_overwrite_each_other(self):
        colleague=actor('s15-race-colleague')
        gate=Barrier(2)
        def worker(user):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                save_counterparty(user,values(vat_number=self.entity.vat_number,name='ΔΟΚΙΜΗ '+user.username),key=self.entity.pk,version=0)
                return 'updated'
            except ValidationError as error:
                self.assertIn('άλλαξε από άλλον λογιστή',' '.join(error.messages))
                return 'stale'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,user) for user in (self.user,colleague)]
            self.assertEqual(sorted(f.result(timeout=20) for f in futures),['stale','updated'])
        self.assertEqual(CounterpartyEvent.objects.count(),1)

    def wait_for_database_block(self,pid):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT cardinality(pg_blocking_pids(%s))',[pid])
                if cursor.fetchone()[0]:return
            time.sleep(0.02)
        self.fail('Second independent PG connection did not wait on the protected row')

    def posting(self):
        Transaction.objects.bulk_create([Transaction(office_id=A,entity_id=self.entity.pk,cash_account_id=self.cash.pk,
            transaction_type='INCOME',description='ΔΟΚΙΜΑΣΤΙΚΗ ΤΑΥΤΟΧΡΟΝΗ ΚΙΝΗΣΗ',amount='1.00',transaction_date=DAY)])

    def archive_post_race(self,archive_first):
        locked=Event();release=Event();pids=Queue()
        def first():
            close_old_connections()
            try:
                with transaction.atomic():
                    if archive_first:archive_counterparty(self.user,self.entity.pk,version=0,archive=True)
                    else:self.posting()
                    locked.set()
                    if not release.wait(timeout=15):raise AssertionError('Row hold not released')
                return 'archived' if archive_first else 'posted'
            finally:connection.close()
        def second():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()');pids.put(cursor.fetchone()[0])
                if archive_first:self.posting()
                else:archive_counterparty(self.user,self.entity.pk,version=0,archive=True)
                return 'posted' if archive_first else 'archived'
            except IntegrityError:return 'blocked'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            initial=pool.submit(first)
            try:
                self.assertTrue(locked.wait(timeout=10))
                later=pool.submit(second)
                self.wait_for_database_block(pids.get(timeout=10))
            finally:release.set()
            return initial.result(timeout=20),later.result(timeout=20)

    def test_archive_first_blocks_waiting_new_post_at_database_level(self):
        self.assertEqual(self.archive_post_race(True),('archived','blocked'))
        self.assertEqual(Transaction.objects.count(),0)
        self.entity.refresh_from_db();self.assertTrue(self.entity.is_archived)

    def test_post_first_is_retained_when_archive_follows(self):
        self.assertEqual(self.archive_post_race(False),('posted','archived'))
        self.assertEqual(Transaction.objects.count(),1)
        self.entity.refresh_from_db();self.assertTrue(self.entity.is_archived)


class CounterpartyMigrationTests(TransactionTestCase):
    def migrate(self,target):
        executor=MigrationExecutor(connection)
        executor.migrate([('accounting',target)])
        return executor.loader.project_state([('accounting',target)]).apps

    def setUp(self):
        apps=self.migrate('0008_office_workflow_guards')
        self.legacy=apps.get_model('accounting','Entity')
        for key in (A,B):apps.get_model('accounting','Office').objects.create(pk=key,name='ΔΟΚΙΜΑΣΤΙΚΟ ΓΡΑΦΕΙΟ S15')
        self.user=actor('s15-migrating-user')
        from .auth_models import AuthenticatorDevice
        from core.auth_crypto import cipher
        device=AuthenticatorDevice(user=self.user,name='ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΣΥΣΚΕΥΗ',confirmed=True,setup_expires_at=timezone.now())
        device.encrypted_secret=cipher(self.user.pk,device.secret_salt).encrypt(secrets.token_bytes(20)).decode()
        device.save()
        self.original_mfa=list(AuthenticatorDevice.objects.filter(user=self.user).values())
        self.entity=self.legacy.objects.create(office_id=A,entity_type='CUSTOMER',name='ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΤΑΥΤΟΤΗΤΑ',vat_number='EL 000-000-501',email='preserve@example.invalid')
        self.supplier=self.legacy.objects.create(office_id=B,entity_type='SUPPLIER',name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΑΛΑΙΟΣ ΠΡΟΜΗΘΕΥΤΗΣ',vat_number='000000501')
        self.cash=apps.get_model('accounting','CashAccount').objects.create(office_id=A,name='ΔΟΚΙΜΑΣΤΙΚΟ ΠΑΛΑΙΟ ΤΑΜΕΙΟ',opening_balance='1234.56')
        self.agreement=apps.get_model('accounting','Agreement').objects.create(office_id=A,entity_id=self.entity.pk,agreement_type='RECEIVABLE',description='ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΣΥΜΦΩΝΙΑ',total_amount='100.00',start_date=DAY)
        apps.get_model('accounting','Transaction').objects.create(office_id=A,entity_id=self.entity.pk,agreement_id=self.agreement.pk,
            cash_account_id=self.cash.pk,transaction_type='INCOME',description='ΔΟΚΙΜΑΣΤΙΚΗ ΠΑΛΑΙΑ ΚΙΝΗΣΗ',amount='12.34',transaction_date=DAY)
        self.old_models={name:apps.get_model('accounting',name) for name in ('Entity','Agreement','CashAccount','Category','Transaction')}
        self.original={name:list(model.objects.order_by('pk').values()) for name,model in self.old_models.items()}
        self.original_user=list(get_user_model().objects.filter(pk=self.user.pk).values())

    def tearDown(self):
        # Only the disposable Django test database; never an operator data source.
        self.assertTrue(connection.settings_dict['NAME'].startswith('test_'))
        tables=['accounting_transaction','accounting_agreement','accounting_category','accounting_cashaccount','accounting_entity']
        if 'accounting_counterpartyevent' in connection.introspection.table_names():tables.append('accounting_counterpartyevent')
        with connection.cursor() as cursor:cursor.execute('TRUNCATE '+','.join(tables)+' CASCADE')
        executor=MigrationExecutor(connection);executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_upgrade_preserves_all_original_ids_columns_links_and_user(self):
        apps=self.migrate(LATEST)
        for name,rows in self.original.items():
            fields=[field.name if not field.is_relation else field.attname for field in self.old_models[name]._meta.concrete_fields]
            self.assertEqual(list(apps.get_model('accounting',name).objects.order_by('pk').values(*fields)),rows)
        client=Entity.objects.get(pk=self.entity.pk);supplier=Entity.objects.get(pk=self.supplier.pk)
        self.assertTrue(client.is_customer and not client.is_supplier)
        self.assertTrue(supplier.is_supplier and not supplier.is_customer)
        self.assertEqual(client.legal_kind,'UNREVIEWED')
        self.assertEqual(client.vat_key,'000000501')
        self.assertEqual(client.vat_number,'EL 000-000-501')
        self.assertEqual(list(get_user_model().objects.filter(pk=self.user.pk).values()),self.original_user)
        from .auth_models import AuthenticatorDevice
        self.assertEqual(list(AuthenticatorDevice.objects.filter(user=self.user).values()),self.original_mfa)
        self.assertEqual(CounterpartyEvent.objects.count(),0)

    def test_normalised_legacy_collision_stops_before_schema_or_identity_change(self):
        self.legacy.objects.create(office_id=A,entity_type='SUPPLIER',name='ΔΟΚΙΜΑΣΤΙΚΟ ΔΙΠΛΟ',vat_number='000000501')
        before=list(self.legacy.objects.order_by('pk').values())
        with self.assertRaisesRegex(RuntimeError,'normalised AFM'):self.migrate(LATEST)
        self.assertEqual(list(self.legacy.objects.order_by('pk').values()),before)
        self.assertNotIn(('accounting','0009_counterparty_workspace'),MigrationRecorder(connection).applied_migrations())
        with connection.cursor() as cursor:columns=connection.introspection.get_table_description(cursor,'accounting_entity')
        self.assertNotIn('vat_key',[column.name for column in columns])

    def test_invalid_legacy_afm_stops_without_disclosing_contact_values(self):
        self.legacy.objects.filter(pk=self.entity.pk).update(vat_number='private-invalid')
        with self.assertRaises(RuntimeError) as raised:self.migrate(LATEST)
        self.assertIn('identity review',str(raised.exception))
        self.assertNotIn('private-invalid',str(raised.exception))
        self.assertEqual(self.legacy.objects.get(pk=self.entity.pk).vat_number,'private-invalid')

    def test_unknown_legacy_role_is_not_guessed(self):
        self.legacy.objects.filter(pk=self.entity.pk).update(entity_type='OTHER')
        with self.assertRaisesRegex(RuntimeError,'identity review'):self.migrate(LATEST)
        self.assertEqual(self.legacy.objects.get(pk=self.entity.pk).entity_type,'OTHER')

    def test_blank_legacy_afms_are_retained(self):
        for value in (None,''):
            self.legacy.objects.create(office_id=A,entity_type='CUSTOMER',name='ΔΟΚΙΜΑΣΤΙΚΗ ΚΕΝΗ ΤΑΥΤΟΤΗΤΑ',vat_number=value)
        self.migrate(LATEST)
        self.assertEqual(Entity.objects.filter(office_id=A,vat_key='').count(),2)
        self.assertEqual(Entity.objects.filter(office_id=A,vat_number__isnull=True).count(),1)

    def test_legacy_only_upgrade_can_reverse_without_identity_loss(self):
        self.migrate(LATEST)
        self.migrate('0008_office_workflow_guards')
        self.assertEqual(list(self.legacy.objects.order_by('pk').values()),self.original['Entity'])

    def test_downgrade_refuses_to_discard_new_role_classification_and_events(self):
        self.migrate(LATEST)
        save_counterparty(self.user,values(vat_number='000000503'))
        with self.assertRaises(Exception) as raised:self.migrate('0008_office_workflow_guards')
        self.assertIn('downgrade needs a reviewed',str(raised.exception))
        self.assertIn(('accounting',LATEST),MigrationRecorder(connection).applied_migrations())
        self.assertEqual(CounterpartyEvent.objects.count(),1)
