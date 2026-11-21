"""CR-004 PostgreSQL contracts. Supplied for operator execution, not agent-run."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from threading import Barrier, Event
import uuid
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.http import Http404
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .counterparty_journal_forms import JournalForm, NoteForm
from .counterparty_journal_selectors import JournalRows, journal_page
from .counterparty_note_services import add_note
from .counterparty_services import archive_counterparty
from .models import (AccountantProfile, Agreement, AgreementTermsVersion,
    AllocationRelease, CashAllocation, Charge, CounterpartyNote, Entity,
    FinanceAuditEvent, FinanceCommand, Office, SettlementCommand, Transaction)
from .tests_auth_support import staff_client_login
from .tests_cash_agreement_entry import DAY, ReceiptSupport
from .cash_entry_services import post_agreement_cash
from .finance_services import post_cash


class JournalSupport(ReceiptSupport):
    def seed_journal(self):
        self.seed_receipt()
        self.foreign_entity = Entity.objects.create(office=self.foreign,
            entity_type='CUSTOMER', name='ΞΕΝΗ ΚΑΡΤΕΛΑ CR004')

    def note(self, *, user=None, entity=None, body='Επικοινωνία για τη συμφωνία', key=None):
        return add_note(user or self.member, (entity or self.customer).pk,
            body=body, request_key=key or uuid.uuid4())

    def financial_counts(self):
        return tuple(model.objects.count() for model in (Transaction, FinanceCommand,
            FinanceAuditEvent, Charge, CashAllocation, AllocationRelease, SettlementCommand, AgreementTermsVersion))

    def archive_customer(self):
        self.customer.refresh_from_db()
        return archive_counterparty(self.owner, self.customer.pk,
            version=self.customer.record_version, archive=True)

    def rows(self, *, entity=None, **filters):
        return JournalRows(entity or self.customer, filters)[:100]


class NoteContractTests(JournalSupport, TestCase):
    def setUp(self):
        self.seed_journal()

    def test_note_records_server_time_actor_office_and_no_financial_effect(self):
        before = self.financial_counts(); start = timezone.now()
        note, replay = self.note()
        self.assertFalse(replay)
        self.assertEqual((note.office_id, note.entity_id, note.actor_id),
            (self.office.pk, self.customer.pk, self.member.pk))
        self.assertEqual(note.actor_label, self.member.username)
        self.assertGreaterEqual(note.created_at, start)
        self.assertLessEqual(note.created_at, timezone.now())
        self.assertEqual(self.financial_counts(), before)

    def test_plaintext_note_preserves_paragraphs_and_normalises_line_endings(self):
        note, _ = self.note(body='  Πρώτη γραμμή\r\nΔεύτερη γραμμή\rΤρίτη γραμμή  ')
        self.assertEqual(note.body, 'Πρώτη γραμμή\nΔεύτερη γραμμή\nΤρίτη γραμμή')

    def test_invalid_body_and_key_leave_no_note(self):
        for text in ('', ' \t\n', 'x' * 5001, 'κείμενο\x00', None):
            with self.subTest(text=repr(text)[:20]), self.assertRaises(ValidationError):
                self.note(body=text)
        for key in ('invalid', None, ''):
            with self.assertRaises(ValidationError):
                add_note(self.member, self.customer.pk, body='Δοκιμή', request_key=key)
        self.assertEqual(CounterpartyNote.objects.count(), 0)

    def test_same_submission_returns_one_original_note(self):
        key = uuid.uuid4(); first, _ = self.note(key=key)
        second, replay = self.note(key=key)
        self.assertTrue(replay)
        self.assertEqual((first.pk, first.created_at), (second.pk, second.created_at))
        self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_reused_key_cannot_change_body_entity_or_actor(self):
        key = uuid.uuid4(); self.note(key=key)
        another = Entity.objects.create(office=self.office, entity_type='CUSTOMER', name='Άλλη καρτέλα')
        for changes in ({'body':'Αλλαγμένο κείμενο'}, {'entity':another}, {'user':self.owner}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValidationError):
                self.note(key=key, **changes)
        self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_foreign_and_missing_entities_are_not_found(self):
        for key in (self.foreign_entity.pk, 2147483647):
            with self.assertRaises(Http404):
                add_note(self.member, key, body='Δοκιμή', request_key=uuid.uuid4())
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_archive_blocks_new_notes_but_original_retry_is_read_only(self):
        key = uuid.uuid4(); first, _ = self.note(key=key)
        self.archive_customer()
        with self.assertRaises(ValidationError): self.note(body='Νέα εργασία')
        saved, replay = self.note(key=key)
        self.assertTrue(replay); self.assertEqual(first.pk, saved.pk)
        self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_revoked_membership_blocks_cached_user(self):
        self.note(); AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied): self.note(body='Μη επιτρεπτή')
        self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_disabled_user_and_office_block_writes(self):
        get_user_model().objects.filter(pk=self.member.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied): self.note()
        get_user_model().objects.filter(pk=self.member.pk).update(is_active=True)
        Office.objects.filter(pk=self.office.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied): self.note()
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_username_snapshot_survives_later_rename(self):
        note, _ = self.note(); name = note.actor_label
        get_user_model().objects.filter(pk=self.member.pk).update(username='renamed-cr004')
        note.refresh_from_db()
        self.assertEqual(note.actor_label, name)
        self.assertEqual(next(r for r in self.rows() if r['kind']=='note')['actor_label'], name)

    def test_model_and_sql_cannot_rewrite_or_delete_note(self):
        note, _ = self.note(); note.body = 'Αλλαγμένη'
        with self.assertRaises(ValidationError): note.save()
        with self.assertRaises(ValidationError): note.delete()
        for statement, params in (
                ('UPDATE accounting_counterpartynote SET body=%s WHERE id=%s', ['Αλλαγμένη', note.pk]),
                ('DELETE FROM accounting_counterpartynote WHERE id=%s', [note.pk])):
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor: cursor.execute(statement, params)
        note.refresh_from_db(); self.assertEqual(note.body, 'Επικοινωνία για τη συμφωνία')

    def test_database_insert_overrides_forged_label_and_timestamp(self):
        start = timezone.now()
        note = CounterpartyNote(office=self.office, entity=self.customer, actor=self.member,
            actor_label='Πλαστό όνομα', created_at=start-timedelta(days=90),
            request_key=uuid.uuid4(), body='Απόδοση από τη βάση')
        CounterpartyNote.objects.bulk_create([note]); note.refresh_from_db()
        self.assertEqual(note.actor_label, self.member.username)
        self.assertGreaterEqual(note.created_at, start)

    def test_database_insert_rejects_foreign_entity_and_actor(self):
        outsider = get_user_model().objects.create_user('unassigned-cr004')
        for entity, user in ((self.foreign_entity, self.member), (self.customer, outsider)):
            with self.assertRaises(IntegrityError), transaction.atomic():
                CounterpartyNote.objects.bulk_create([CounterpartyNote(office=self.office,
                    entity=entity, actor=user, actor_label='', request_key=uuid.uuid4(), body='Ξένη σύνδεση')])
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_database_insert_rejects_archived_and_oversized_notes(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            CounterpartyNote.objects.bulk_create([CounterpartyNote(office=self.office,
                entity=self.customer, actor=self.member, actor_label='', request_key=uuid.uuid4(), body='x'*5001)])
        self.archive_customer()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CounterpartyNote.objects.bulk_create([CounterpartyNote(office=self.office,
                entity=self.customer, actor=self.member, actor_label='', request_key=uuid.uuid4(), body='Νέα')])

    def test_note_author_cannot_be_deleted_with_history(self):
        self.note()
        with self.assertRaises(ProtectedError): self.member.delete()


class JournalHTTPTests(JournalSupport, TestCase):
    def setUp(self):
        self.seed_journal(); staff_client_login(self.client, self.member)

    def journal(self, **params):
        return self.client.get(reverse('entity-journal', args=[self.customer.pk]), params)

    def test_card_has_summary_notes_editor_journal_and_three_colour_legend(self):
        note, _ = self.note()
        response = self.client.get(reverse('entity-detail', args=[self.customer.pk]))
        self.assertEqual(response.status_code, 200)
        for text in ('Επισκόπηση', 'Ημερολόγιο καρτέλας', 'Πρόσφατη δραστηριότητα',
                     'Σημειώσεις καρτέλας', 'client-badge--green', 'client-badge--red', 'client-badge--blue'):
            self.assertContains(response, text)
        self.assertEqual(response.context['card_stats']['notes'], 1)
        self.assertEqual(response.context['settlements']['receivable_remaining'], Decimal('400.00'))

    def test_customer_receipt_and_supplier_payment_use_their_own_colours(self):
        entry, _, _ = post_agreement_cash(self.member, **self.values())
        self.note()
        payable, _ = self.target(entity=self.supplier, direction='PAYABLE')
        post_agreement_cash(self.member, **self.values(transaction_type='EXPENSE',
            entity=self.supplier, agreement=payable))
        customer = self.rows(); supplier = self.rows(entity=self.supplier)
        self.assertTrue(all(r['tone']=='green' for r in customer if r['kind'] in ('agreement','charge','cash','allocation')))
        self.assertTrue(all(r['tone']=='red' for r in supplier))
        self.assertEqual(next(r['tone'] for r in customer if r['kind']=='note'), 'blue')

    def test_dual_role_party_retains_both_directions_and_separate_debts(self):
        Entity.objects.filter(pk=self.customer.pk).update(is_supplier=True)
        self.target(entity=self.customer, direction='PAYABLE', amount='80.00')
        response = self.journal()
        tones = {r['tone'] for r in response.context['journal_page']}
        self.assertEqual(tones, {'green','red'})
        response = self.client.get(reverse('entity-detail', args=[self.customer.pk]))
        self.assertEqual(response.context['settlements']['receivable_remaining'], Decimal('400.00'))
        self.assertEqual(response.context['settlements']['payable_remaining'], Decimal('80.00'))

    def test_note_post_ignores_forged_office_actor_and_date(self):
        response = self.client.post(reverse('entity-note-add', args=[self.customer.pk]),
            {'request_key':str(uuid.uuid4()), 'body':'Σημείωση από το έντυπο', 'office_id':str(self.foreign.pk),
             'entity':self.foreign_entity.pk, 'actor':self.owner.pk, 'created_at':'2000-01-01', 'actor_label':'Πλαστό'})
        self.assertEqual(response.status_code, 302)
        note = CounterpartyNote.objects.get()
        self.assertEqual((note.entity_id, note.office_id, note.actor_id), (self.customer.pk, self.office.pk, self.member.pk))
        self.assertEqual(note.actor_label, self.member.username)
        self.assertEqual(note.created_at.date(), timezone.now().date())

    def test_invalid_note_post_keeps_body_and_shows_greek_error(self):
        response = self.client.post(reverse('entity-note-add', args=[self.customer.pk]), {'body':'Κείμενο χωρίς αναγνωριστικό'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('request_key', response.context['form'].errors)
        self.assertContains(response, 'Κείμενο χωρίς αναγνωριστικό')
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_note_form_and_journal_escape_html(self):
        payload = '<script>alert("cr004")</script>\nΔεύτερη γραμμή'
        self.note(body=payload)
        response = self.journal(kind='note')
        self.assertNotContains(response, '<script>alert(')
        self.assertContains(response, '&lt;script&gt;')
        self.assertContains(response, 'Δεύτερη γραμμή')

    def test_foreign_and_missing_journal_or_note_urls_are_not_found(self):
        before = CounterpartyNote.objects.count()
        for name in ('entity-journal', 'entity-note-add'):
            for key in (self.foreign_entity.pk, 2147483647):
                response = self.client.get(reverse(name, args=[key]))
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, self.foreign_entity.name, status_code=404)
        response = self.client.post(reverse('entity-note-add', args=[self.foreign_entity.pk]),
            {'request_key':str(uuid.uuid4()), 'body':'Μη επιτρεπτή'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(CounterpartyNote.objects.count(), before)

    def test_journal_get_cannot_change_records_and_post_is_not_allowed(self):
        self.note(); before = self.financial_counts(); notes = list(CounterpartyNote.objects.values())
        self.assertEqual(self.journal().status_code, 200)
        self.assertEqual(self.client.post(reverse('entity-journal', args=[self.customer.pk])).status_code, 405)
        self.assertEqual(self.financial_counts(), before)
        self.assertEqual(list(CounterpartyNote.objects.values()), notes)

    def test_repeated_note_http_submission_is_idempotent(self):
        data = {'request_key':str(uuid.uuid4()), 'body':'Διπλό πάτημα αποθήκευσης'}
        url = reverse('entity-note-add', args=[self.customer.pk])
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_missing_csrf_is_denied(self):
        client = Client(enforce_csrf_checks=True); staff_client_login(client, self.member)
        client.get(reverse('entity-detail', args=[self.customer.pk]))
        response = client.post(reverse('entity-note-add', args=[self.customer.pk]),
            {'request_key':str(uuid.uuid4()), 'body':'Χωρίς απόδειξη φόρμας'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_anonymous_and_revoked_users_cannot_read_notes(self):
        self.note(body='Προστατευμένη σημείωση CR004')
        anonymous = Client().get(reverse('entity-journal', args=[self.customer.pk]))
        self.assertEqual(anonymous.status_code, 302)
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        response = self.journal()
        self.assertEqual(response.status_code, 403)
        self.assertNotContains(response, 'Προστατευμένη σημείωση CR004', status_code=403)

    def test_archived_card_retains_notes_and_disables_new_note_form(self):
        self.note(body='Πριν από αρχειοθέτηση'); self.archive_customer()
        response = self.journal(kind='note')
        self.assertContains(response, 'Πριν από αρχειοθέτηση')
        response = self.client.get(reverse('entity-note-add', args=[self.customer.pk]))
        self.assertContains(response, 'disabled', status_code=409)

    def test_all_notes_are_paged_without_duplicates_or_a_silent_cutoff(self):
        for number in range(31): self.note(body=f'Σημείωση σελίδας {number:02}')
        first = self.journal(kind='note'); second = self.journal(kind='note', page=2)
        one = first.context['journal_page']; two = second.context['journal_page']
        self.assertEqual((one.paginator.count, len(one), len(two)), (31,25,6))
        self.assertFalse({r['event_id'] for r in one} & {r['event_id'] for r in two})
        self.assertEqual(len({r['event_id'] for r in one} | {r['event_id'] for r in two}), 31)

    def test_filters_separate_notes_cash_agreements_and_direction(self):
        self.note(); post_agreement_cash(self.member, **self.values())
        for kind in ('note','cash','agreement','charge','allocation'):
            response = self.journal(kind=kind)
            self.assertTrue(response.context['journal_page'].paginator.count)
            self.assertTrue(all(r['kind']==kind for r in response.context['journal_page']))
        self.assertTrue(all(r['kind']=='note' for r in self.journal(direction='NOTE').context['journal_page']))
        self.assertEqual(self.journal(direction='PAYABLE').context['journal_page'].paginator.count, 0)

    def test_invalid_date_month_kind_and_duplicate_filters_show_errors(self):
        for values in ({'start_date':'not-a-date'}, {'month':'2026-13'}, {'kind':'unknown'},
                       {'start_date':'2026-03-02','end_date':'2026-01-01'}, {'kind':['note','cash']}):
            with self.subTest(values=values):
                response = self.journal(**values)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['filter_form'].errors)
                self.assertEqual(response.context['journal_page'].paginator.count, 0)

    def test_date_filters_are_inclusive_and_note_day_is_athens_time(self):
        note, _ = self.note(); day = note.created_at.astimezone(ZoneInfo('Europe/Athens')).date()
        response = self.journal(kind='note', start_date=day.isoformat(), end_date=day.isoformat())
        self.assertEqual(response.context['journal_page'].paginator.count, 1)
        self.assertEqual(response.context['journal_page'][0]['event_day'], day)
        self.assertEqual(self.journal(kind='note', end_date=(day-timedelta(days=1)).isoformat()).context['journal_page'].paginator.count, 0)

    def test_note_search_treats_wildcards_and_sql_text_as_literal_text(self):
        self.note(body='Ποσοστό 25% και κωδικός Α_Β')
        for query in ('25%', 'Α_Β'):
            self.assertEqual(self.journal(kind='note', q=query).context['journal_page'].paginator.count, 1)
        self.assertEqual(self.journal(q="' OR 1=1 --").context['journal_page'].paginator.count, 0)

    def test_month_calendar_counts_all_notes_beyond_the_current_page(self):
        for number in range(28): self.note(body=f'Ημερολόγιο {number}')
        month = timezone.localdate().strftime('%Y-%m')
        response = self.journal(view='month', month=month, kind='note')
        calendar = response.context['journal_calendar']
        total = sum(cell['counts'].get('blue',0) for week in calendar['weeks'] for cell in week if cell)
        self.assertEqual(total, 28)
        self.assertEqual(len(response.context['journal_page']), 25)
        self.assertContains(response, 'Μηνιαίο ημερολόγιο')

    def test_calendar_leap_year_and_year_boundaries_are_valid(self):
        response = self.journal(view='month', month='2024-02')
        days = [cell['number'] for week in response.context['journal_calendar']['weeks'] for cell in week if cell]
        self.assertEqual(days, list(range(1,30)))
        self.assertEqual(self.journal(view='month', month='1900-01').context['journal_calendar']['previous'], '')
        self.assertEqual(self.journal(view='month', month='2200-12').context['journal_calendar']['next'], '')

    def test_month_filter_and_day_links_keep_type_and_direction(self):
        self.note(); response = self.journal(view='month', kind='note', direction='NOTE')
        calendar = response.context['journal_calendar']
        cell = next(cell for week in calendar['weeks'] for cell in week if cell and cell['counts'].get('blue'))
        follow = self.client.get(reverse('entity-journal', args=[self.customer.pk]) + cell['url'])
        self.assertEqual(follow.context['journal_page'].paginator.count, 1)
        self.assertTrue(all(r['kind']=='note' for r in follow.context['journal_page']))

    def test_all_cash_rows_include_standalone_and_linked_payments(self):
        entry, _, _ = post_agreement_cash(self.member, **self.values())
        standalone = post_cash(self.member, **self.values(agreement=None, description='Αυτοτελής είσπραξη'))
        response = self.journal(kind='cash')
        self.assertEqual({r['cash_id'] for r in response.context['journal_page']}, {entry.pk,standalone.pk})

    def test_summary_counts_cash_once_and_never_adds_agreement_charge_or_allocation(self):
        post_agreement_cash(self.member, **self.values()); self.note()
        response = self.client.get(reverse('entity-detail', args=[self.customer.pk]))
        self.assertEqual(response.context['card_stats']['total_income'], Decimal('100.00'))
        self.assertEqual(response.context['card_stats']['total_expense'], Decimal('0.00'))
        self.assertEqual(response.context['settlements']['receivable_remaining'], Decimal('300.00'))

    def test_dual_role_party_uses_event_direction_and_notes_stay_blue(self):
        Entity.objects.filter(pk=self.customer.pk).update(is_supplier=True)
        self.customer.refresh_from_db()
        payable, _ = self.target(entity=self.customer, direction='PAYABLE')
        post_agreement_cash(self.member, **self.values(transaction_type='EXPENSE', agreement=payable, amount='75.00'))
        post_agreement_cash(self.member, **self.values())
        self.note()
        rows = self.rows()
        self.assertTrue(any(r['kind']=='cash' and r['tone']=='red' for r in rows))
        self.assertTrue(any(r['kind']=='cash' and r['tone']=='green' for r in rows))
        self.assertTrue(all(r['tone']=='blue' for r in rows if r['kind']=='note'))
        self.assertTrue(all(r['tone']=='red' for r in rows if r['agreement_id']==payable.pk))

    def test_journal_retains_released_allocations_and_charge_reversal(self):
        from .settlement_services import release_allocation
        from .correction_services import correct_charge
        post_agreement_cash(self.member, **self.values())
        allocation = CashAllocation.objects.get(charge=self.charge)
        release_allocation(self.request(), allocation=allocation, effective_date=DAY+timedelta(days=1),
            password=self.password, reason='Δοκιμαστική αποδέσμευση ημερολογίου', idempotency_key=str(uuid.uuid4()))
        correct_charge(self.request(), charge_id=self.charge.pk, effective_date=DAY+timedelta(days=2),
            password=self.password, reason='Δοκιμαστικός αντιλογισμός ημερολογίου', idempotency_key=str(uuid.uuid4()))
        before = self.financial_counts()
        rows = self.rows()
        for kind in ('allocation','release','correction','cash','charge'):
            self.assertTrue(any(r['kind']==kind for r in rows), kind)
        self.assertEqual(self.financial_counts(), before)
        self.assertTrue(CashAllocation.objects.filter(pk=allocation.pk).exists())

    def test_agreement_amendment_does_not_rewrite_original_journal_terms(self):
        from .correction_services import amend_agreement
        original = AgreementTermsVersion.objects.get(agreement=self.target_agreement, revision=1)
        amend_agreement(self.request(), agreement_id=self.target_agreement.pk, expected_revision=1,
            description='Νεότερο κείμενο συμφωνίας', amount='450.00', lifecycle='ACTIVE',
            password=self.password, effective_date=timezone.localdate()+timedelta(days=1),
            reason='Δοκιμαστική αλλαγή όρων ημερολογίου', idempotency_key=str(uuid.uuid4()))
        entries = [r for r in self.rows() if r['kind']=='agreement' and r['agreement_id']==self.target_agreement.pk]
        self.assertEqual(len(entries), 2)
        self.assertEqual(next(r for r in entries if r['event_id']==f'terms:{original.pk}')['title'], original.description)
        self.assertTrue(any(r['title']=='Νεότερο κείμενο συμφωνίας' for r in entries))


class NoteRaceTests(JournalSupport, TransactionTestCase):
    def setUp(self): self.seed_journal()

    def test_concurrent_duplicate_submission_keeps_one_note(self):
        barrier = Barrier(2); key = uuid.uuid4()
        def submit():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.member.pk); barrier.wait(timeout=10)
                note, replay = add_note(user, self.customer.pk, body='Μία ταυτόχρονη σημείωση', request_key=key)
                return note.pk, replay
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _:submit(), range(2)))
        self.assertEqual(len({item[0] for item in outcomes}), 1)
        self.assertEqual(sorted(item[1] for item in outcomes), [False,True])
        self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_concurrent_changed_payload_has_one_winner(self):
        barrier = Barrier(2); key = uuid.uuid4()
        def submit(body):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.member.pk); barrier.wait(timeout=10)
                try: add_note(user, self.customer.pk, body=body, request_key=key)
                except ValidationError: return 'denied'
                return 'saved'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(submit, ('Πρώτη εκδοχή', 'Δεύτερη εκδοχή')))
        self.assertEqual(sorted(outcomes), ['denied','saved'])
        self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_note_waiting_behind_revocation_rechecks_membership(self):
        started = Event()
        def submit():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.member.pk); started.set()
                try: add_note(user, self.customer.pk, body='Μετά από ανάκληση', request_key=uuid.uuid4())
                except PermissionDenied: return 'denied'
                return 'saved'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Office.objects.select_for_update().get(pk=self.office.pk)
                get_user_model().objects.select_for_update().get(pk=self.member.pk)
                future = pool.submit(submit); self.assertTrue(started.wait(timeout=10))
                AccountantProfile.objects.filter(user=self.member).update(is_active=False)
            self.assertEqual(future.result(timeout=15), 'denied')
        self.assertFalse(CounterpartyNote.objects.exists())


class NoteMigrationTests(JournalSupport, TransactionTestCase):
    def setUp(self):
        MigrationExecutor(connection).migrate([('accounting','0026_fee_generation_guards')])
        self.seed_journal()

    def tearDown(self):
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())
        super().tearDown()

    def test_forward_adds_empty_note_table_and_preserves_all_preexisting_rows(self):
        with connection.cursor() as cursor:
            tables = [name for name in connection.introspection.table_names(cursor) if name!='django_migrations']
            before = {}
            for name in tables:
                cursor.execute('SELECT * FROM ' + connection.ops.quote_name(name))
                before[name] = sorted(cursor.fetchall(), key=repr)
        MigrationExecutor(connection).migrate([('accounting','0028_counterparty_note_guards')])
        with connection.cursor() as cursor:
            for name in tables:
                cursor.execute('SELECT * FROM ' + connection.ops.quote_name(name))
                self.assertEqual(sorted(cursor.fetchall(), key=repr), before[name], name)
        self.assertFalse(CounterpartyNote.objects.exists())
        self.note(); self.assertEqual(CounterpartyNote.objects.count(), 1)

    def test_downgrade_with_notes_refuses_to_erase_history(self):
        MigrationExecutor(connection).migrate([('accounting','0028_counterparty_note_guards')])
        note, _ = self.note()
        from django.db import DatabaseError
        with self.assertRaises(DatabaseError):
            MigrationExecutor(connection).migrate([('accounting','0026_fee_generation_guards')])
        self.assertEqual(CounterpartyNote.objects.get(pk=note.pk).body, note.body)
