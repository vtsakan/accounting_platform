"""CR007 contracts supplied for the operator's isolated production PG17 gate."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import io
import json
import secrets
from threading import Barrier
import uuid
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.management import call_command
from django.db import DatabaseError,IntegrityError,close_old_connections,connection,transaction
from django.db.migrations.executor import MigrationExecutor
from django.http import Http404
from django.test import Client,SimpleTestCase,TestCase,TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from core.taxis_crypto import open_sealed
from .counterparty_retirement_services import delete_counterparty
from .counterparty_services import FIELDS,archive_counterparty
from .counterparty_views import SearchForm
from .entity_profile_forms import EntityProfileForm
from .entity_profile_models import CONTACT_FIELDS,FLAG_LABELS,PERSON_KINDS
from .entity_profile_selectors import financial_summary,profile_installed,spouse_contacts
from .entity_profile_services import PROFILE_FIELDS,profile_context,reveal_credentials,save_profile
from .entity_profile_validation import amka,tags
from .entity_profile_views import directory_document
from .export_renderers import render_csv,render_pdf
from .models import (AccountantProfile,Charge,Entity,EntityProfile,EntityProfileEvent,FinanceAuditEvent,
    TaxisCredential,Transaction)
from .schema_test_support import restore_current_test_schema
from .settlement_services import allocate
from .tests_auth_support import staff_client_login
from .tests_settlements import SettlementSupport


class ProfileSupport(SettlementSupport):
    @classmethod
    def setUpClass(cls):restore_current_test_schema();super().setUpClass()

    def seed_profile(self):
        self.seed()
        self.person=Entity.objects.create(office=self.office,name='ΔΟΚΙΜΑΣΤΙΚΟ ΠΡΟΣΩΠΟ CR007',entity_type='CUSTOMER',is_customer=True,is_supplier=True,
            address='Δοκιμαστική οδός 12',city='Αθήνα',postal_code='11527',phone_number='2101234567',email='profile@example.invalid')
        self.foreign_person=Entity.objects.create(office=self.foreign,name='ΞΕΝΗ ΚΑΡΤΕΛΑ CR007',entity_type='CUSTOMER')

    def core(self,**changes):return {name:getattr(self.person,name) for name in FIELDS}|{'legal_kind':'INDIVIDUAL'}|changes

    def fields(self,**changes):
        base=EntityProfile(office=self.office,entity=self.person)
        return {name:getattr(base,name) for name in PROFILE_FIELDS}|{'person_kind':'INDIVIDUAL'}|changes

    def save(self,*,user=None,core=None,credentials=None,version=None,**changes):
        self.person.refresh_from_db()
        current=EntityProfile.objects.filter(entity=self.person).first()
        values=({name:getattr(current,name) for name in PROFILE_FIELDS} if current else self.fields())|changes
        return save_profile(user or self.member,self.core(**(core or {})),values,credentials or {},key=self.person.pk,
            version=self.person.record_version if version is None else version)

    def credentials(self,subject='main'):
        return {subject+'_taxis_username':secrets.token_urlsafe(16),subject+'_taxis_password':secrets.token_urlsafe(32)}

    def client_for(self,user=None,csrf=False):
        client=Client(enforce_csrf_checks=csrf)
        if csrf:
            client.get('/login/');client.defaults['HTTP_X_CSRFTOKEN']=client.cookies[settings.CSRF_COOKIE_NAME].value
        try:staff_client_login(client,user or self.member)
        finally:client.defaults.pop('HTTP_X_CSRFTOKEN',None)
        return client

    def payload(self,**changes):
        return {**self.core(),**self.fields(),'version':self.person.record_version,'tags':''}|changes

    def spouse(self):return {'spouse_enabled':True,'spouse_first_name':'Δοκιμαστική','spouse_last_name':'Σύζυγος',
        'spouse_person_kind':'INDIVIDUAL','spouse_vat_number':'000000233'}


class ProfileSyntaxContracts(SimpleTestCase):
    def test_amka_preserves_leading_zeroes_and_normalises_full_width(self):
        self.assertEqual(amka('００００００００００１'),'00000000001');self.assertEqual(amka(''),'')

    def test_amka_rejects_non_digits_and_wrong_length(self):
        for value in ('123','0000000000x','+00000000001'):
            with self.assertRaises(ValidationError):amka(value)

    def test_tags_are_bounded_normalised_and_deduplicated(self):
        self.assertEqual(tags(' ΕΠΙΔΟΤΟΥΜΕΝΟΣ, ανήλικα τέκνα; επιδοτουμενοσ '),['επιδοτουμενος','ανήλικα τέκνα'])
        for value in (['x']*26,['x'*41],[1]):
            with self.assertRaises(ValidationError):tags(value)


class ProfileWriteContracts(ProfileSupport,TestCase):
    def setUp(self):self.seed_profile()

    def test_new_profile_has_status_category_server_time_and_attributed_event(self):
        start=timezone.now();self.save(main_amka='00000000001')
        profile=EntityProfile.objects.get(entity=self.person);event=EntityProfileEvent.objects.get(entity=self.person)
        self.assertEqual((profile.contact_status,profile.person_kind),('ACTIVE','INDIVIDUAL'))
        self.assertGreaterEqual(profile.updated_at,start);self.assertEqual(event.actor_id,self.member.pk)
        self.assertEqual(event.actor_label,self.member.username)

    def test_all_six_categories_map_to_retained_coarse_classification(self):
        for key,_ in PERSON_KINDS:
            self.save(person_kind=key);self.person.refresh_from_db()
            self.assertEqual(self.person.legal_kind,'BUSINESS' if key in {'SOLE_TRADER','LEGAL_ENTITY'} else 'INDIVIDUAL')

    def test_missing_contact_status_is_rejected_without_writes(self):
        data=self.payload();data.pop('contact_status')
        form=EntityProfileForm(data,user=self.member,instance=self.person)
        self.assertFalse(form.is_valid());self.assertIn('contact_status',form.errors);self.assertFalse(EntityProfile.objects.exists())

    def test_missing_six_way_category_is_rejected(self):
        data=self.payload();data.pop('person_kind')
        form=EntityProfileForm(data,user=self.member,instance=self.person)
        self.assertFalse(form.is_valid());self.assertIn('person_kind',form.errors)

    def test_inactive_is_independent_of_archive_and_keeps_the_identity(self):
        self.save(contact_status='INACTIVE');self.person.refresh_from_db()
        self.assertFalse(self.person.is_archived);self.assertEqual(self.person.name,'ΔΟΚΙΜΑΣΤΙΚΟ ΠΡΟΣΩΠΟ CR007')

    def test_profile_edit_does_not_post_money_or_change_financial_history(self):
        before={m._meta.label:list(m.objects.values()) for m in (Transaction,Charge,FinanceAuditEvent)}
        self.save(internal_notes='Εσωτερική σημείωση',liable_a21=True)
        self.assertEqual({m._meta.label:list(m.objects.values()) for m in (Transaction,Charge,FinanceAuditEvent)},before)

    def test_all_six_tax_flags_and_tags_are_persisted(self):
        self.save(**{key:True for key in FLAG_LABELS},tags='Ετικέτα Α, Ετικέτα Β')
        profile=EntityProfile.objects.get(entity=self.person)
        self.assertTrue(all(getattr(profile,key) for key in FLAG_LABELS));self.assertEqual(profile.tags,['ετικέτα α','ετικέτα β'])

    def test_spouse_identity_is_separate_and_contacts_inherit_current_primary(self):
        self.save(**self.spouse());profile=EntityProfile.objects.get(entity=self.person)
        self.assertEqual(spouse_contacts(self.person,profile)['address'],self.person.address)
        self.save(core={'address':'Νέα διεύθυνση'})
        self.person.refresh_from_db();self.assertEqual(spouse_contacts(self.person,profile)['address'],'Νέα διεύθυνση')
        self.assertEqual(profile.spouse_address,'')

    def test_spouse_contact_override_does_not_modify_primary_contacts(self):
        self.save(**self.spouse(),spouse_inherit_contacts=False,spouse_address='Άλλη διεύθυνση',spouse_email='other@example.invalid')
        profile=EntityProfile.objects.get(entity=self.person)
        self.assertEqual(spouse_contacts(self.person,profile)['address'],'Άλλη διεύθυνση')
        self.person.refresh_from_db();self.assertEqual(self.person.address,'Δοκιμαστική οδός 12')

    def test_returning_to_inherited_contacts_clears_overrides(self):
        self.save(**self.spouse(),spouse_inherit_contacts=False,spouse_city='Πάτρα')
        self.save(spouse_inherit_contacts=True)
        profile=EntityProfile.objects.get(entity=self.person)
        self.assertEqual(profile.spouse_city,'');self.assertEqual(spouse_contacts(self.person,profile)['city'],'Αθήνα')

    def test_spouse_requires_names_and_explicit_category(self):
        with self.assertRaises(ValidationError):self.save(spouse_enabled=True)
        self.assertFalse(EntityProfile.objects.exists())

    def test_legal_entity_cannot_have_spouse_section(self):
        with self.assertRaises(ValidationError):self.save(**self.spouse(),person_kind='LEGAL_ENTITY')
        self.assertFalse(EntityProfile.objects.exists())

    def test_invalid_spouse_vat_amka_and_override_email_are_field_errors(self):
        for changes in ({'spouse_vat_number':'abc'},{'spouse_amka':'1'},{'spouse_inherit_contacts':False,'spouse_email':'bad'}):
            with self.assertRaises(ValidationError):self.save(**(self.spouse()|changes))
        self.assertFalse(EntityProfile.objects.exists())

    def test_stale_profile_edit_cannot_overwrite_new_values(self):
        self.save(internal_notes='Νεότερο')
        with self.assertRaises(ValidationError):self.save(version=0,internal_notes='Παλαιό')
        self.assertEqual(EntityProfile.objects.get(entity=self.person).internal_notes,'Νεότερο')

    def test_foreign_profile_write_is_not_found(self):
        with self.assertRaises(Http404):save_profile(self.member,self.core(),self.fields(),{},key=self.foreign_person.pk,version=0)

    def test_revoked_member_cannot_edit_or_reveal_credentials(self):
        self.save(credentials=self.credentials());AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.save(internal_notes='Όχι')
        with self.assertRaises(PermissionDenied):reveal_credentials(self.member,self.person.pk,'MAIN')

    def test_raw_profile_update_requires_context_and_new_entity_version(self):
        self.save()
        with self.assertRaises(IntegrityError),transaction.atomic():EntityProfile.objects.filter(entity=self.person).update(internal_notes='Παράκαμψη')
        with self.assertRaises(IntegrityError),transaction.atomic(),profile_context(self.member,'EDIT'):
            EntityProfile.objects.filter(entity=self.person).update(internal_notes='Παράκαμψη')

    def test_audit_contains_field_names_but_no_values_and_is_immutable(self):
        self.save(main_amka='00000000001',internal_notes='ΣΗΜΕΙΩΣΗ ΠΟΥ ΔΕΝ ΑΝΗΚΕΙ ΣΕ AUDIT')
        event=EntityProfileEvent.objects.get(entity=self.person);encoded=json.dumps(event.changed_fields)
        self.assertNotIn('00000000001',encoded);self.assertNotIn('ΣΗΜΕΙΩΣΗ',encoded)
        with self.assertRaises(IntegrityError),transaction.atomic():EntityProfileEvent.objects.filter(pk=event.pk).update(actor_label='Παράκαμψη')


class CredentialContracts(ProfileSupport,TestCase):
    def setUp(self):self.seed_profile()

    def test_both_username_and_password_are_sealed_and_recoverable(self):
        values=self.credentials();self.save(credentials=values);row=TaxisCredential.objects.get(entity=self.person)
        self.assertNotIn(values['main_taxis_username'].encode(),bytes(row.sealed_username))
        self.assertNotIn(values['main_taxis_password'].encode(),bytes(row.sealed_password))
        self.assertEqual(open_sealed(row),(values['main_taxis_username'],values['main_taxis_password']))

    def test_owner_and_active_accountant_can_reveal_with_attributed_audit(self):
        values=self.credentials();self.save(credentials=values)
        for user in (self.owner,self.member):
            self.assertEqual(reveal_credentials(user,self.person.pk,'MAIN')[1],values['main_taxis_password'])
        self.assertEqual(set(EntityProfileEvent.objects.filter(action='REVEAL').values_list('actor_id',flat=True)),{self.owner.pk,self.member.pk})

    def test_spouse_and_primary_have_distinct_sealed_credentials(self):
        first=self.credentials();second=self.credentials('spouse')
        self.save(**self.spouse(),credentials=first|second)
        self.assertEqual(reveal_credentials(self.member,self.person.pk,'SPOUSE')[0],second['spouse_taxis_username'])
        self.assertEqual(reveal_credentials(self.member,self.person.pk,'MAIN')[0],first['main_taxis_username'])

    def test_blank_credential_fields_keep_existing_sealed_bytes(self):
        self.save(credentials=self.credentials());before=list(TaxisCredential.objects.values())
        self.save(internal_notes='Άλλη σημείωση');self.assertEqual(list(TaxisCredential.objects.values()),before)

    def test_explicit_clear_removes_only_selected_subject(self):
        self.save(**self.spouse(),credentials=self.credentials()|self.credentials('spouse'))
        self.save(credentials={'main_taxis_clear':True})
        self.assertFalse(TaxisCredential.objects.filter(subject='MAIN').exists());self.assertTrue(TaxisCredential.objects.filter(subject='SPOUSE').exists())

    def test_partial_credentials_roll_back_the_entire_profile_edit(self):
        with self.assertRaises(ValidationError):self.save(internal_notes='Δεν αποθηκεύεται',credentials={'main_taxis_username':secrets.token_urlsafe(12)})
        self.assertFalse(EntityProfile.objects.exists());self.person.refresh_from_db();self.assertEqual(self.person.record_version,0)

    def test_clear_and_replace_cannot_be_combined(self):
        with self.assertRaises(ValidationError):self.save(credentials=self.credentials()|{'main_taxis_clear':True})
        self.assertFalse(TaxisCredential.objects.exists())

    def test_changing_tax_identity_requires_explicit_credential_replacement_or_clear(self):
        self.save(credentials=self.credentials())
        with self.assertRaises(ValidationError):self.save(core={'vat_number':'000000299'})
        self.save(core={'vat_number':'000000299'},credentials={'main_taxis_clear':True})
        self.assertFalse(TaxisCredential.objects.exists())

    def test_ciphertext_copied_to_different_entity_cannot_be_decrypted(self):
        self.save(credentials=self.credentials());row=TaxisCredential.objects.get()
        row.entity_id=self.customer.pk
        with self.assertRaises(ValidationError):open_sealed(row)

    def test_plaintext_database_insert_is_rejected(self):
        with self.assertRaises(IntegrityError),transaction.atomic(),profile_context(self.member,'EDIT'):
            TaxisCredential.objects.create(office=self.office,entity=self.person,subject='MAIN',salt=secrets.token_bytes(16),
                sealed_username=b'not-sealed',sealed_password=b'not-sealed')

    def test_reveal_get_is_read_only_method_denied_and_post_is_not_cached(self):
        values=self.credentials();self.save(credentials=values);client=self.client_for()
        url=reverse('entity-credentials-reveal',args=[self.person.pk,'MAIN'])
        self.assertEqual(client.get(url).status_code,405)
        response=client.post(url)
        self.assertContains(response,values['main_taxis_username']);self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'],'no-referrer')

    def test_editor_get_and_invalid_post_never_prefill_plaintext_credentials(self):
        values=self.credentials();self.save(credentials=values);client=self.client_for()
        url=reverse('edit-entity',args=[self.person.pk])
        for response in (client.get(url),client.post(url,self.payload(name='')|values)):
            self.assertNotContains(response,values['main_taxis_password']);self.assertNotContains(response,values['main_taxis_username'])

    def test_missing_csrf_denies_reveal_after_real_owner_mfa(self):
        self.save(credentials=self.credentials());client=self.client_for(self.owner,csrf=True)
        response=client.post(reverse('entity-credentials-reveal',args=[self.person.pk,'MAIN']))
        self.assertEqual(response.status_code,403);self.assertFalse(EntityProfileEvent.objects.filter(action='REVEAL').exists())


class ProfileWorkspaceContracts(ProfileSupport,TestCase):
    def setUp(self):self.seed_profile()

    def test_editor_has_four_tabs_and_links_to_statement_and_cash_history(self):
        response=self.client_for().get(reverse('edit-entity',args=[self.person.pk]))
        for title in ('Βασικά στοιχεία','Σύζυγος','Φορολογικά χαρακτηριστικά','Σημειώσεις'):self.assertContains(response,title)
        self.assertContains(response,reverse('client-statement',args=[self.person.pk]));self.assertContains(response,'Οικονομική εικόνα')

    def test_customer_card_keeps_notes_agreements_tasks_and_new_profile(self):
        self.save(**self.spouse(),tags=['ανήλικα τέκνα'],internal_notes='Εσωτερική παρατήρηση')
        response=self.client_for().get(reverse('entity-detail',args=[self.person.pk]))
        for text in ('Συμφωνίες','Εργασίες πελάτη','Σημειώσεις καρτέλας','ανήλικα τέκνα','Εσωτερική παρατήρηση','Δοκιμαστική Σύζυγος'):self.assertContains(response,text)

    def test_inactive_is_hidden_by_default_and_explicitly_searchable(self):
        self.save(contact_status='INACTIVE');client=self.client_for()
        self.assertNotContains(client.get(reverse('counterparty-list')),self.person.name)
        self.assertContains(client.get(reverse('counterparty-list'),{'contact_status':'INACTIVE'}),self.person.name)
        self.assertEqual(client.get(reverse('entity-detail',args=[self.person.pk])).status_code,200)

    def test_tags_and_tax_flags_filter_the_directory(self):
        self.save(tags=['επιδοτούμενος','ανήλικα τέκνα'],liable_a21=True)
        client=self.client_for();url=reverse('counterparty-list')
        response=client.get(url,{'tags':['επιδοτούμενος'],'liable_a21':'on'})
        self.assertContains(response,self.person.name);self.assertNotContains(response,self.customer.name)
        response=client.get(url,{'tags':['ξένη ετικέτα']})
        self.assertContains(response,'έγκυρη επιλογή')

    def test_foreign_tag_choices_and_entity_details_never_leak(self):
        client=self.client_for()
        for route in ('edit-entity','entity-detail'):
            response=client.get(reverse(route,args=[self.foreign_person.pk]));self.assertEqual(response.status_code,404)
        response=client.post(reverse('entity-credentials-reveal',args=[self.foreign_person.pk,'MAIN']))
        self.assertEqual(response.status_code,404)

    def test_internal_notes_and_spouse_names_are_html_escaped(self):
        self.save(**(self.spouse()|{'spouse_first_name':'<script>demo()</script>'}),internal_notes='<script>private()</script>')
        response=self.client_for().get(reverse('entity-detail',args=[self.person.pk]))
        self.assertNotContains(response,'<script>private()');self.assertNotContains(response,'<script>demo()')
        self.assertContains(response,'&lt;script&gt;')

    def test_pdf_and_csv_exclude_all_credentials_amka_spouse_and_internal_notes(self):
        values=self.credentials();self.save(main_amka='00000000001',internal_notes='PRIVATE_NOTE_SENTINEL',credentials=values)
        form=SearchForm({'status':'active'},user=self.member)
        document=directory_document(self.member,form,'csv','none');csv=render_csv(document).decode('utf-8-sig')
        for text in (values['main_taxis_username'],values['main_taxis_password'],'00000000001','PRIVATE_NOTE_SENTINEL'):self.assertNotIn(text,csv)
        self.assertTrue(render_pdf(document).startswith(b'%PDF-'))

    def test_directory_export_uses_all_filtered_rows_and_groups_by_tag(self):
        self.save(tags=['ομάδα α','ομάδα β'])
        form=SearchForm({'status':'active','tags':['ομάδα α']},user=self.member)
        document=directory_document(self.member,form,'csv','tag')
        self.assertEqual([s.title for s in document.sections[:-1]],['ομάδα α','ομάδα β'])
        self.assertTrue(all(len(s.rows)==1 for s in document.sections[:-1]))

    def test_inactive_directory_export_requires_explicit_filter(self):
        self.save(contact_status='INACTIVE');client=self.client_for();url=reverse('counterparty-directory-export',args=['csv'])
        self.assertNotContains(client.get(url),self.person.name)
        self.assertContains(client.get(url,{'contact_status':'INACTIVE'}),self.person.name)

    def test_export_rechecks_live_membership_after_rendering(self):
        client=self.client_for()
        def render_and_revoke(document):
            AccountantProfile.objects.filter(user=self.member).update(is_active=False)
            return b'no-private-values'
        with patch('accounting.entity_profile_views.render_csv',side_effect=render_and_revoke):
            self.assertEqual(client.get(reverse('counterparty-directory-export',args=['csv'])).status_code,403)


class ProfileMoneyContracts(ProfileSupport,TestCase):
    def setUp(self):self.seed_profile()

    def test_unallocated_receipt_is_a_customer_credit_not_a_second_charge(self):
        self.cash('25.00',entity=self.person)
        data=financial_summary(self.member,self.person)
        self.assertEqual(data['customer_balance'],Decimal('-25.00'));self.assertEqual(data['supplier_balance'],Decimal('0.00'))

    def test_charge_minus_allocated_receipt_and_remaining_credit_has_no_double_count(self):
        charge=self.obligation();source=self.cash('120.00')
        allocate(self.member,**self.allocation_values(source,charge,'100.00'))
        data=financial_summary(self.member,self.customer)
        self.assertEqual(data['receivable_charged'],Decimal('100.00'));self.assertEqual(data['customer_payments'],Decimal('120.00'))
        self.assertEqual(data['customer_balance'],Decimal('-20.00'))

    def test_supplier_advance_is_separate_from_customer_receipts(self):
        self.cash('30.00',entity=self.person);self.cash('12.00',entity=self.person,direction='EXPENSE')
        data=financial_summary(self.member,self.person)
        self.assertEqual(data['customer_balance'],Decimal('-30.00'));self.assertEqual(data['supplier_balance'],Decimal('-12.00'))

    def test_financial_summary_uses_requested_day_and_preserves_unposted_terms(self):
        data=financial_summary(self.member,self.customer,as_of=self.agreement.start_date-timedelta(days=1))
        self.assertEqual(data['receivable_charged'],Decimal('0.00'));self.assertEqual(data['customer_balance'],Decimal('0.00'))

    def test_inactive_state_keeps_debt_and_open_agreement_archive_guard(self):
        charge=self.obligation();self.person=self.customer;self.save(contact_status='INACTIVE')
        self.assertEqual(financial_summary(self.member,self.customer)['customer_balance'],Decimal('100.00'))
        self.customer.refresh_from_db()
        with self.assertRaises(ValidationError):archive_counterparty(self.member,self.customer.pk,version=self.customer.record_version,archive=True)

    def test_owner_deletion_removes_new_profile_pii_and_all_sealed_credentials(self):
        self.save(**self.spouse(),main_amka='00000000001',internal_notes='PRIVATE_NOTE_SENTINEL',credentials=self.credentials())
        self.person.refresh_from_db();archive_counterparty(self.member,self.person.pk,version=self.person.record_version,archive=True)
        self.person.refresh_from_db();delete_counterparty(self.owner,self.person.pk,version=self.person.record_version,confirmed=True)
        profile=EntityProfile.objects.get(entity=self.person)
        self.assertEqual((profile.main_amka,profile.internal_notes,profile.spouse_first_name),('','',''))
        self.assertFalse(TaxisCredential.objects.filter(entity=self.person).exists());self.assertTrue(EntityProfileEvent.objects.filter(action='PURGE').exists())


class ProfileMigrationContracts(ProfileSupport,TransactionTestCase):
    def tearDown(self):restore_current_test_schema();super().tearDown()

    def test_upgrade_from_32_keeps_people_and_original_columns(self):
        MigrationExecutor(connection).migrate([('accounting','0032_client_task_guards')]);self.seed_profile()
        before=list(Entity.objects.order_by('pk').values());restore_current_test_schema()
        self.assertEqual(list(Entity.objects.order_by('pk').values()),before);self.assertTrue(profile_installed())
        self.assertFalse(EntityProfile.objects.exists());self.assertFalse(TaxisCredential.objects.exists())

    def test_partial_33_schema_fails_closed(self):
        MigrationExecutor(connection).migrate([('accounting','0033_entity_fiscal_profile')])
        with self.assertRaises(RuntimeError):profile_installed()

    def test_downgrade_with_profile_history_is_refused(self):
        self.seed_profile();self.save()
        with self.assertRaises(DatabaseError):MigrationExecutor(connection).migrate([('accounting','0032_client_task_guards')])
        self.assertEqual(EntityProfile.objects.count(),1)

    def test_all_current_models_have_complete_migration_state(self):
        call_command('makemigrations',check=True,dry_run=True,interactive=False,stdout=io.StringIO())


class ProfileConcurrencyContracts(ProfileSupport,TransactionTestCase):
    def setUp(self):self.seed_profile()

    def test_two_simultaneous_edits_do_not_overwrite_the_same_version(self):
        gate=Barrier(2)
        def edit(note):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                save_profile(self.member,self.core(),self.fields(internal_notes=note),{},key=self.person.pk,version=0)
                return 'saved'
            except ValidationError:return 'stale'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(edit,text) for text in ('Πρώτη παρατήρηση','Δεύτερη παρατήρηση')]
            results=[f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(results),['saved','stale']);self.assertEqual(EntityProfile.objects.count(),1)
        self.assertEqual(EntityProfileEvent.objects.filter(action='UPDATE').count(),1)
