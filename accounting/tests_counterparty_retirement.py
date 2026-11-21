"""CR005 PG17/HTTP/migration/race contracts supplied for operator execution."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier, Event
import time
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.http import Http404
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .agreement_creation import create_with_charge
from .charge_services import save_terms
from .counterparty_note_services import add_note
from .counterparty_retirement_selectors import archive_blockers, has_financial_history
from .counterparty_retirement_services import delete_counterparty
from .counterparty_services import archive_counterparty, save_counterparty
from .finance_services import audit_context, fingerprint, post_cash
from .membership import create_accountant_profile
from .models import (AccountantProfile, Agreement, AgreementTermsVersion, AllocationRelease,
    CashAllocation, Charge, CounterpartyDeletion, CounterpartyEvent, CounterpartyNote,
    Entity, FinanceAuditEvent, FinanceCommand, Office, OfficeAuditEvent, SettlementCommand, Transaction)
from .office_access import records
from .schema_test_support import restore_current_test_schema
from .settlement_services import allocate_cash
from .tests_auth_support import staff_client_login
from .tests_finance_posting import DAY, Fixtures


class RetirementSupport(Fixtures):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema()
        super().setUpClass()

    def seed_retirement(self):
        self.seed()
        self.blank = Entity.objects.create(office=self.office, entity_type='CUSTOMER',
            is_customer=True, is_supplier=True, legal_kind='BUSINESS', name='Καθαρή καρτέλα CR005',
            vat_number='000001505', email='retirement@example.invalid', phone_number='2101234567')

    def archive(self, entity=None):
        item = entity or self.blank; item.refresh_from_db()
        return archive_counterparty(self.member, item.pk, version=item.record_version, archive=True)

    def delete(self, *, user=None, entity=None, version=None, confirmed=True):
        item = entity or self.blank
        if version is None: item.refresh_from_db(); version=item.record_version
        return delete_counterparty(user or self.owner, item.pk, version=version, confirmed=confirmed)

    def target(self, *, mode='ONE_OFF', amount='100.00'):
        candidate = Agreement(entity=self.blank, agreement_type='RECEIVABLE',
            description='Συμφωνία αρχειοθέτησης CR005', total_amount=amount, start_date=DAY)
        agreement, charge, _ = create_with_charge(self.member, candidate, billing_mode=mode,
            reason='Δοκιμαστική συμφωνία CR005', creation_key=str(uuid.uuid4()), due_date=DAY)
        return agreement, charge

    def settle(self, charge, amount='100.00'):
        source=post_cash(self.member, idempotency_key=str(uuid.uuid4()), amount=amount,
            transaction_date=DAY, transaction_type='INCOME', cash_account=self.account,
            entity=self.blank, description='Δοκιμαστική εξόφληση CR005')
        return allocate_cash(self.member, source_cash=source.pk,
            lines=[{'charge':charge.pk,'amount':amount}], effective_date=DAY,
            reason='Δοκιμαστική αντιστοίχιση CR005', idempotency_key=str(uuid.uuid4()))

    def closed(self, lifecycle='ENDED'):
        agreement=Agreement.objects.create(office=self.office,entity=self.blank,
            agreement_type='RECEIVABLE',description='Κλειστή συμφωνία CR005',total_amount='100.00',start_date=DAY)
        save_terms(self.member,agreement,billing_mode='ONE_OFF',lifecycle=lifecycle,
            expected_revision=agreement.terms_versions.first().revision,reason='Ολοκλήρωση δοκιμαστικών όρων CR005')
        return agreement

    def money(self):
        return {m._meta.model_name:list(m.objects.order_by('pk').values()) for m in (
            Agreement, AgreementTermsVersion, Charge, Transaction, FinanceCommand,
            FinanceAuditEvent, SettlementCommand, CashAllocation, AllocationRelease)}

    def client_for(self, user=None, *, csrf=False):
        client=Client(enforce_csrf_checks=csrf);staff_client_login(client,user or self.owner)
        return client


class ArchiveDecisionContracts(RetirementSupport, TestCase):
    def setUp(self): self.seed_retirement()

    def test_empty_client_can_archive_and_restore_with_attribution(self):
        item=self.archive();self.assertTrue(item.is_archived);self.assertEqual(item.archived_by_id,self.member.pk)
        item=archive_counterparty(self.member,item.pk,version=item.record_version,archive=False)
        self.assertFalse(item.is_archived)

    def test_unreviewed_agreement_blocks_archive_without_any_writes(self):
        Agreement.objects.create(office=self.office,entity=self.blank,agreement_type='RECEIVABLE',
            description='Ανοιχτή παλιά συμφωνία',total_amount='100.00',start_date=DAY)
        before=self.money()
        with self.assertRaisesMessage(ValidationError,'ανοιχτή συμφωνία'):self.archive()
        self.blank.refresh_from_db();self.assertFalse(self.blank.is_archived)
        self.assertEqual(self.money(),before);self.assertFalse(CounterpartyEvent.objects.filter(entity=self.blank).exists())

    def test_draft_agreement_is_not_treated_as_settled(self):
        self.closed('DRAFT')
        with self.assertRaises(ValidationError):self.archive()

    def test_legacy_completed_flag_does_not_prove_an_unreviewed_contract_is_settled(self):
        Agreement.objects.create(office=self.office,entity=self.blank,agreement_type='RECEIVABLE',
            description='Παλιά ένδειξη ολοκλήρωσης',total_amount='100.00',start_date=DAY,status='COMPLETED')
        with self.assertRaises(ValidationError):self.archive()

    def test_posted_unpaid_charge_blocks_archive(self):
        self.target()
        with self.assertRaises(ValidationError):self.archive()

    def test_partially_settled_agreement_blocks_archive(self):
        _,charge=self.target();self.settle(charge,'25.00')
        with self.assertRaises(ValidationError):self.archive()
        self.assertEqual(archive_blockers(self.blank)[0]['reason'],'Υπάρχει ανεξόφλητη χρέωση')

    def test_fully_settled_one_off_can_archive_without_changing_finance(self):
        _,charge=self.target();self.settle(charge);before=self.money()
        self.archive();self.assertEqual(self.money(),before)

    def test_active_monthly_is_open_even_when_current_charge_is_paid(self):
        _,charge=self.target(mode='MONTHLY');self.settle(charge)
        with self.assertRaises(ValidationError):self.archive()
        self.assertEqual(archive_blockers(self.blank)[0]['reason'],'Η μηνιαία συμφωνία παραμένει ενεργή')

    def test_ended_or_cancelled_without_obligations_can_archive(self):
        self.closed('ENDED');self.closed('CANCELLED');self.archive()
        self.blank.refresh_from_db();self.assertTrue(self.blank.is_archived)

    def test_cancelled_legacy_flag_does_not_hide_unpaid_posted_charges(self):
        agreement,_=self.target();Agreement.objects.filter(pk=agreement.pk).update(status='CANCELLED')
        with self.assertRaises(ValidationError):self.archive()

    def test_ended_or_cancelled_terms_do_not_hide_unpaid_charges(self):
        from .correction_services import amend_agreement
        for lifecycle in ('ENDED','CANCELLED'):
            agreement,_=self.target()
            amend_agreement(self.request(),agreement_id=agreement.pk,
                expected_revision=agreement.terms_versions.first().revision,
                description=agreement.description,amount=agreement.total_amount,lifecycle=lifecycle,
                password=self.password,effective_date=timezone.localdate(),
                reason='Λήξη δοκιμαστικών όρων με ανεξόφλητη χρέωση',idempotency_key=str(uuid.uuid4()))
        with self.assertRaises(ValidationError):self.archive()
        self.assertTrue(all(row['reason']=='Υπάρχει ανεξόφλητη χρέωση' for row in archive_blockers(self.blank)))

    def test_other_party_and_office_agreements_do_not_block_empty_client(self):
        self.assertTrue(Agreement.objects.filter(entity=self.customer).exists())
        self.archive();self.assertEqual(archive_blockers(self.blank),[])

    def test_get_explains_block_and_links_agreement_without_mutating(self):
        agreement,_=self.target();before=self.money()
        response=self.client_for().get(reverse('archive-entity',args=[self.blank.pk]))
        self.assertContains(response,'Δεν επιτρέπεται η αρχειοθέτηση')
        self.assertContains(response,reverse('agreement-detail',args=[agreement.pk]))
        self.assertNotContains(response,'Επιβεβαίωση αρχειοθέτησης')
        self.assertEqual(self.money(),before)

    def test_forged_archive_post_still_fails_on_server(self):
        self.target();before=self.money()
        response=self.client_for().post(reverse('archive-entity',args=[self.blank.pk]),{'version':0})
        self.assertEqual(response.status_code,200);self.assertTrue(response.context['form'].errors)
        self.blank.refresh_from_db();self.assertFalse(self.blank.is_archived);self.assertEqual(self.money(),before)

    def test_database_archive_update_cannot_bypass_open_agreement_rule(self):
        self.target()
        with self.assertRaises(IntegrityError) as raised,transaction.atomic():
            Entity.objects.filter(pk=self.blank.pk).update(is_archived=True,
                archived_by=self.owner,archived_at=timezone.now())
        self.assertEqual(raised.exception.__cause__.diag.constraint_name,'cr005_archive_open')

    def test_stale_archive_form_cannot_overwrite_new_identity_version(self):
        Entity.objects.filter(pk=self.blank.pk).update(name='Νέα έκδοση καρτέλας')
        with self.assertRaisesMessage(ValidationError,'άλλαξε από άλλον λογιστή'):
            archive_counterparty(self.member,self.blank.pk,version=0,archive=True)

    def test_card_and_lists_expose_archive_and_restore_controls(self):
        client=self.client_for(self.member);url=reverse('archive-entity',args=[self.blank.pk])
        self.assertContains(client.get(reverse('entity-detail',args=[self.blank.pk])),url)
        self.assertContains(client.get(reverse('counterparty-list')),url)
        self.archive()
        response=client.get(reverse('counterparty-list'),{'status':'archived'})
        self.assertContains(response,reverse('restore-entity',args=[self.blank.pk]))

    def test_future_active_terms_prevent_archive_of_currently_paid_contract(self):
        from .correction_services import amend_agreement
        agreement,charge=self.target();self.settle(charge)
        amend_agreement(self.request(),agreement_id=agreement.pk,
            expected_revision=agreement.terms_versions.first().revision,
            description=agreement.description,amount=agreement.total_amount,lifecycle='ACTIVE',
            password=self.password,effective_date=timezone.localdate()+timedelta(days=1),
            reason='Προγραμματισμένοι ενεργοί όροι CR005',idempotency_key=str(uuid.uuid4()))
        with self.assertRaises(ValidationError):self.archive()
        self.assertEqual(archive_blockers(self.blank)[0]['reason'],'Υπάρχει προγραμματισμένη ενεργή συμφωνία')


class OwnerDeletionContracts(RetirementSupport, TestCase):
    def setUp(self): self.seed_retirement()

    def test_owner_deletes_archived_empty_identity_without_financial_writes(self):
        self.archive();before=self.money();marker,replay=self.delete()
        self.assertFalse(replay);self.assertEqual(marker.actor_id,self.owner.pk)
        self.assertEqual(marker.actor_label,self.owner.username);self.assertIsNotNone(marker.created_at)
        self.blank.refresh_from_db();self.assertEqual(self.blank.name,'Διαγραμμένη εγγραφή #'+str(self.blank.pk))
        for name in ('vat_key','address','city','postal_code','phone_number','email','tax_office'):
            self.assertEqual(getattr(self.blank,name),'')
        self.assertIsNone(self.blank.vat_number);self.assertEqual(self.money(),before)
        self.assertEqual(CounterpartyEvent.objects.filter(entity=self.blank,action='delete').count(),1)

    def test_active_client_cannot_be_deleted(self):
        with self.assertRaisesMessage(ValidationError,'Αρχειοθετήστε πρώτα'):self.delete()
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_accountant_cannot_delete_even_with_staff_or_superuser_flags(self):
        self.archive();get_user_model().objects.filter(pk=self.member.pk).update(is_staff=True,is_superuser=True)
        self.member.refresh_from_db();self.assertTrue(self.member.is_superuser)
        with self.assertRaises(PermissionDenied):self.delete(user=self.member)
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_foreign_owner_cannot_delete_another_offices_client(self):
        self.archive();other=get_user_model().objects.create_user('cr005-foreign-owner')
        create_accountant_profile(user_id=other.pk,office_id=self.foreign.pk,role='owner')
        with self.assertRaises(Http404):self.delete(user=other)
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_disabled_or_revoked_owner_is_rechecked(self):
        self.archive();backup=get_user_model().objects.create_user('cr005-revocation-backup')
        create_accountant_profile(user_id=backup.pk,office_id=self.office.pk,role='owner')
        AccountantProfile.objects.filter(user=self.owner).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.delete()
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_confirmation_and_exact_integer_version_are_required(self):
        self.archive()
        for confirmed,version in ((False,1),('on',1),(True,True),(True,-1)):
            with self.subTest(confirmed=confirmed,version=version),self.assertRaises(ValidationError):
                self.delete(confirmed=confirmed,version=version)
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_stale_owner_form_does_not_remove_new_contact_values(self):
        self.archive();old=self.blank.record_version
        Entity.objects.filter(pk=self.blank.pk).update(email='new-contact@example.invalid')
        with self.assertRaisesMessage(ValidationError,'άλλαξε από άλλον λογιστή'):self.delete(version=old)
        self.blank.refresh_from_db();self.assertEqual(self.blank.email,'new-contact@example.invalid')

    def test_closed_agreement_still_counts_as_financial_history(self):
        self.closed();self.archive();before=self.money()
        with self.assertRaisesMessage(ValidationError,'οικονομικό ιστορικό'):self.delete()
        self.assertEqual(self.money(),before);self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_cash_only_history_blocks_deletion(self):
        post_cash(self.member,idempotency_key=str(uuid.uuid4()),amount='10.00',transaction_date=DAY,
            transaction_type='INCOME',cash_account=self.account,entity=self.blank,description='Αυτοτελής είσπραξη')
        self.archive();self.assertTrue(has_financial_history(self.blank))
        with self.assertRaises(ValidationError):self.delete()

    def test_fully_paid_agreement_cannot_be_deleted(self):
        _,charge=self.target();self.settle(charge);self.archive()
        with self.assertRaises(ValidationError):self.delete()
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_notes_keep_exact_body_author_and_time_after_deletion(self):
        note,_=add_note(self.member,self.blank.pk,body='Ιστορική σημείωση',request_key=uuid.uuid4())
        before=list(CounterpartyNote.objects.filter(pk=note.pk).values())
        self.archive();self.delete()
        self.assertEqual(list(CounterpartyNote.objects.filter(pk=note.pk).values()),before)

    def test_duplicate_owner_submission_creates_one_marker_and_audit(self):
        self.archive();version=self.blank.record_version
        first,_=self.delete(version=version);second,replay=self.delete(version=version)
        self.assertEqual(first.pk,second.pk);self.assertTrue(replay)
        self.assertEqual(CounterpartyDeletion.objects.count(),1)
        self.assertEqual(OfficeAuditEvent.objects.filter(action='client.delete').count(),1)

    def test_counterparty_audit_failure_rolls_back_contacts_and_marker(self):
        self.archive();before=list(Entity.objects.filter(pk=self.blank.pk).values())
        with patch('accounting.counterparty_retirement_services.event',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.delete()
        self.assertEqual(list(Entity.objects.filter(pk=self.blank.pk).values()),before)
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_office_audit_failure_rolls_back_the_entire_deletion(self):
        self.archive();before=list(Entity.objects.filter(pk=self.blank.pk).values())
        with patch.object(OfficeAuditEvent.objects,'create',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.delete()
        self.assertEqual(list(Entity.objects.filter(pk=self.blank.pk).values()),before)
        self.assertFalse(CounterpartyDeletion.objects.exists())
        self.assertFalse(CounterpartyEvent.objects.filter(entity=self.blank,action='delete').exists())

    def test_get_confirmation_is_read_only(self):
        self.archive();before=list(Entity.objects.values())
        response=self.client_for().get(reverse('delete-entity',args=[self.blank.pk]))
        self.assertContains(response,'Διαγραφή εγγραφής')
        self.assertEqual(list(Entity.objects.values()),before);self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_only_owner_sees_delete_link_after_archive(self):
        url=reverse('delete-entity',args=[self.blank.pk]);card=reverse('entity-detail',args=[self.blank.pk])
        owner=self.client_for();member=self.client_for(self.member)
        self.assertNotContains(owner.get(card),url)
        self.archive();self.assertContains(owner.get(card),url);self.assertNotContains(member.get(card),url)
        self.assertContains(owner.get(reverse('counterparty-list'),{'status':'archived'}),url)

    def test_accountant_forged_delete_get_and_post_are_denied(self):
        self.archive();client=self.client_for(self.member);url=reverse('delete-entity',args=[self.blank.pk])
        self.assertEqual(client.get(url).status_code,403)
        self.assertEqual(client.post(url,{'version':1,'confirm':'on','actor':self.owner.pk}).status_code,403)
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_delete_post_requires_csrf_even_for_owner(self):
        self.archive();client=self.client_for(csrf=True);url=reverse('delete-entity',args=[self.blank.pk])
        self.assertEqual(client.get(url).status_code,200)
        self.assertEqual(client.post(url,{'version':1,'confirm':'on'}).status_code,403)
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_owner_http_delete_redirects_to_filtered_list(self):
        self.archive();client=self.client_for()
        response=client.post(reverse('delete-entity',args=[self.blank.pk]),{'version':1,'confirm':'on'})
        self.assertRedirects(response,reverse('counterparty-list'))
        self.assertFalse(records(Entity,self.owner).filter(pk=self.blank.pk).exists())

    def test_all_previous_client_urls_are_not_found_after_delete(self):
        self.archive();self.delete();client=self.client_for()
        for name in ('entity-detail','edit-entity','archive-entity','restore-entity',
                     'delete-entity','entity-journal','entity-note-add','entity-settlements','client-statement'):
            with self.subTest(route=name):
                self.assertEqual(client.get(reverse(name,args=[self.blank.pk])).status_code,404)
        for filetype in ('csv','pdf'):
            self.assertEqual(client.get(reverse('client-statement-export',args=[self.blank.pk,filetype])).status_code,404)

    def test_deleted_identity_is_hidden_even_from_all_and_archived_filters(self):
        self.archive();self.delete();client=self.client_for()
        for status in ('all','archived','active'):
            response=client.get(reverse('counterparty-list'),{'status':status})
            self.assertNotIn(self.blank.pk,[item.pk for item in response.context['counterparties']])

    def test_deleted_identity_is_not_a_financial_filter_choice(self):
        from .movement_forms import CashMovementFilterForm
        self.archive();self.delete()
        form=CashMovementFilterForm(user=self.member)
        self.assertNotIn(self.blank.pk,form.fields['entity'].queryset.values_list('pk',flat=True))

    def test_archived_identity_with_history_remains_in_financial_filters(self):
        from .movement_forms import CashMovementFilterForm
        self.closed();self.archive()
        form=CashMovementFilterForm(user=self.member)
        self.assertIn(self.blank.pk,form.fields['entity'].queryset.values_list('pk',flat=True))

    def test_deleted_note_retry_cannot_reopen_the_hidden_card(self):
        key=uuid.uuid4();note,_=add_note(self.member,self.blank.pk,body='Διατηρημένη σημείωση',request_key=key)
        self.archive();self.delete()
        with self.assertRaises(Http404):add_note(self.member,self.blank.pk,body=note.body,request_key=key)
        self.assertEqual(CounterpartyNote.objects.get(pk=note.pk).body,note.body)

    def test_database_cannot_restore_or_edit_deleted_identity(self):
        self.archive();self.delete()
        for values in ({'is_archived':False,'archived_at':None,'archived_by':None},{'email':'revived@example.invalid'}):
            with self.subTest(values=values),self.assertRaises(IntegrityError) as raised,transaction.atomic():
                Entity.objects.filter(pk=self.blank.pk).update(**values)
            self.assertEqual(raised.exception.__cause__.diag.constraint_name,'cr005_deleted_retained')

    def test_deletion_attribution_is_immutable_at_model_and_sql_boundaries(self):
        self.archive();marker,_=self.delete()
        with self.assertRaises(ValidationError):marker.save()
        with self.assertRaises(ValidationError):marker.delete()
        for operation in (lambda:CounterpartyDeletion.objects.filter(pk=marker.pk).update(actor_label='Άλλος'),
                          lambda:CounterpartyDeletion.objects.filter(pk=marker.pk).delete()):
            with self.assertRaises(IntegrityError),transaction.atomic():operation()

    def test_raw_deletion_marker_requires_owner_and_actor_context(self):
        self.archive()
        for actor,context in ((self.member,True),(self.owner,False)):
            with self.subTest(actor=actor.pk,context=context),self.assertRaises(IntegrityError),transaction.atomic():
                if context:
                    with audit_context(actor,'Δοκιμή μη επιτρεπτής διαγραφής'):
                        CounterpartyDeletion.objects.bulk_create([CounterpartyDeletion(office=self.office,
                            entity=self.blank,actor=actor,actor_label='',confirmed_version=0,contact_digest=fingerprint('fixture'))])
                else:
                    CounterpartyDeletion.objects.bulk_create([CounterpartyDeletion(office=self.office,
                        entity=self.blank,actor=actor,actor_label='',confirmed_version=0,contact_digest=fingerprint('fixture'))])
        self.assertFalse(CounterpartyDeletion.objects.exists())

    def test_afm_can_be_used_for_a_new_identity_without_reusing_old_history(self):
        afm=self.blank.vat_number;old_id=self.blank.pk
        self.archive();self.delete()
        other=Entity.objects.create(office=self.office,entity_type='CUSTOMER',name='Νέα ανεξάρτητη καρτέλα',vat_number=afm)
        self.assertNotEqual(other.pk,old_id);self.assertFalse(other.workspace_events.exists())
        self.assertEqual(CounterpartyDeletion.objects.get().entity_id,old_id)

    def test_new_financial_entry_for_deleted_identity_is_rejected(self):
        self.archive();self.delete();before=self.money()
        with self.assertRaises(ValidationError):
            post_cash(self.member,idempotency_key=str(uuid.uuid4()),amount='10.00',transaction_date=DAY,
                transaction_type='INCOME',cash_account=self.account,entity=self.blank,description='Μη επιτρεπτή είσπραξη')
        with self.assertRaises(IntegrityError),transaction.atomic():
            Agreement.objects.bulk_create([Agreement(office=self.office,entity=self.blank,
                agreement_type='RECEIVABLE',description='Μη επιτρεπτή συμφωνία',total_amount='10.00',start_date=DAY)])
        self.assertEqual(self.money(),before)

    def test_office_audit_records_the_owner_and_greek_delete_action(self):
        self.archive();marker,_=self.delete()
        audit=OfficeAuditEvent.objects.get(action='client.delete')
        self.assertEqual((audit.actor_id,audit.office_id),(self.owner.pk,self.office.pk))
        self.assertEqual(audit.subject,'entity:'+str(self.blank.pk))
        response=self.client_for().get(reverse('office-audit'))
        self.assertContains(response,'Διαγραφή αρχειοθετημένης εγγραφής')


class RetirementMigrationContracts(RetirementSupport, TransactionTestCase):
    def setUp(self):
        MigrationExecutor(connection).migrate([('accounting','0028_counterparty_note_guards')])
        self.seed_retirement()

    def tearDown(self):
        restore_current_test_schema();super().tearDown()

    def test_upgrade_preserves_existing_archived_open_history_and_people(self):
        # This is a genuine old-schema archive, before the new veto existed.
        archive_counterparty(self.member,self.customer.pk,version=0,archive=True)
        note,_=add_note(self.member,self.blank.pk,body='Πριν από αναβάθμιση',request_key=uuid.uuid4())
        client=self.client_for()
        models=(Entity,CounterpartyEvent,CounterpartyNote,Agreement,AgreementTermsVersion,
            FinanceAuditEvent,OfficeAuditEvent,AccountantProfile,get_user_model())
        before={m._meta.label:list(m.objects.order_by('pk').values()) for m in models}
        restore_current_test_schema()
        self.assertEqual({m._meta.label:list(m.objects.order_by('pk').values()) for m in models},before)
        self.assertFalse(CounterpartyDeletion.objects.exists())
        self.assertTrue(Entity.objects.get(pk=self.customer.pk).is_archived)
        self.assertEqual(client.get(reverse('entity-detail',args=[self.customer.pk])).status_code,200)

    def test_full_current_migration_installs_new_sql_archive_veto(self):
        restore_current_test_schema()
        with self.assertRaises(ValidationError):self.archive(self.customer)
        with connection.cursor() as cursor:
            cursor.execute("SELECT tgenabled FROM pg_trigger WHERE tgname='cr005_entity_guard'")
            self.assertEqual(cursor.fetchone()[0],'O')

    def test_partial_upgrade_without_sql_guards_is_closed_to_app_reads(self):
        MigrationExecutor(connection).migrate([('accounting','0029_counterparty_retirement')])
        with self.assertRaisesMessage(RuntimeError,'δεν έχει ολοκληρωθεί'):
            records(Entity,self.owner)
        restore_current_test_schema()
        self.assertTrue(records(Entity,self.owner).filter(pk=self.blank.pk).exists())

    def test_downgrade_refuses_to_discard_recorded_deletion(self):
        restore_current_test_schema();self.archive();self.delete()
        with self.assertRaisesMessage(DatabaseError,'Retain deletion attribution'):
            MigrationExecutor(connection).migrate([('accounting','0028_counterparty_note_guards')])
        self.assertEqual(CounterpartyDeletion.objects.count(),1)


class RetirementConcurrencyContracts(RetirementSupport, TransactionTestCase):
    def setUp(self):self.seed_retirement()

    def test_two_owner_deletions_create_one_marker_and_one_audit(self):
        self.archive();version=self.blank.record_version;gate=Barrier(2)
        def submit():
            close_old_connections()
            try:
                gate.wait(timeout=10)
                return delete_counterparty(self.owner,self.blank.pk,version=version,confirmed=True)[0].pk
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(submit) for _ in range(2)];ids=[f.result(timeout=30) for f in futures]
        self.assertEqual(ids[0],ids[1]);self.assertEqual(CounterpartyDeletion.objects.count(),1)
        self.assertEqual(OfficeAuditEvent.objects.filter(action='client.delete').count(),1)

    def test_new_agreement_and_archive_cannot_both_commit(self):
        gate=Barrier(2)
        def submit(kind):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                if kind=='archive':self.archive()
                else:self.target()
                return kind
            except (ValidationError,IntegrityError):return 'blocked'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(submit,kind) for kind in ('archive','agreement')]
            results=[f.result(timeout=30) for f in futures]
        self.assertEqual(results.count('blocked'),1)
        self.blank.refresh_from_db()
        self.assertFalse(self.blank.is_archived and bool(archive_blockers(self.blank)))

    def test_waiting_owner_deletion_rechecks_role_after_office_lock(self):
        self.archive();version=self.blank.record_version
        backup=get_user_model().objects.create_user('cr005-backup-owner')
        create_accountant_profile(user_id=backup.pk,office_id=self.office.pk,role='owner')
        started=Event()
        def submit():
            close_old_connections()
            try:
                started.set()
                delete_counterparty(self.owner,self.blank.pk,version=version,confirmed=True)
                return 'deleted'
            except PermissionDenied:return 'denied'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Office.objects.select_for_update().get(pk=self.office.pk)
                future=pool.submit(submit);self.assertTrue(started.wait(timeout=10))
                AccountantProfile.objects.filter(user=self.owner).update(role='accountant')
            self.assertEqual(future.result(timeout=30),'denied')
        self.assertFalse(CounterpartyDeletion.objects.exists())
