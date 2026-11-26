"""Terms-only creation and retained subject/pending workflow, operator-run only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, close_old_connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from .client_task_selectors import dashboard_tasks, today
from .client_task_services import add_work_note, change_task, convert_note
from .counterparty_journal_forms import JournalForm
from .counterparty_journal_selectors import journal_page
from .counterparty_note_services import add_note
from .counterparty_services import archive_counterparty
from .cr010_models import AgreementCreationReceipt
from .finance_services import audit_context
from .manual_agreement_creation import create_manual
from .models import Charge, ClientTask, CounterpartyNote
from .schema_test_support import restore_current_test_schema
from .tests_agreement_creation import CreationSupport
from .tests_client_tasks import TaskSupport


class ManualCreationContracts(CreationSupport, TestCase):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema(); super().setUpClass()

    def setUp(self):
        self.seed()

    def create(self, **changes):
        intent = self.intent(**changes); intent.pop('due_date', None)
        return create_manual(self.member, self.candidate(), **intent)

    def test_new_one_off_and_monthly_agreements_have_terms_without_charges(self):
        for mode in ('ONE_OFF', 'MONTHLY'):
            item, replay = self.create(billing_mode=mode)
            self.assertFalse(replay); self.assertEqual(item.terms_versions.order_by('-revision').first().billing_mode, mode)
            self.assertFalse(Charge.objects.filter(agreement=item).exists())

    def test_same_manual_request_replays_terms_even_after_later_charge(self):
        key = uuid.uuid4(); first, _ = self.create(creation_key=key)
        from .charge_services import post_charge
        terms = first.terms_versions.order_by('-revision').first()
        post_charge(self.member, agreement_id=first.pk, terms_revision=terms.revision, amount='400.00',
            effective_date=first.start_date, due_date=first.start_date, reason='Χειροκίνητη δοκιμαστική χρέωση', idempotency_key=str(uuid.uuid4()))
        second, replay = self.create(creation_key=key)
        self.assertEqual(first.pk, second.pk); self.assertTrue(replay); self.assertEqual(Charge.objects.count(), 1)

    def test_changed_payload_under_same_nonce_is_rejected(self):
        key = uuid.uuid4(); self.create(creation_key=key)
        with self.assertRaises(ValidationError): self.create(creation_key=key, reason='Διαφορετικοί όροι υποβολής')
        self.assertEqual(AgreementCreationReceipt.objects.count(), 1)

    def test_legacy_charged_submission_cannot_create_second_manual_agreement(self):
        from .agreement_creation import create_with_charge
        key = uuid.uuid4(); original, charge, _ = create_with_charge(self.member, self.candidate(), **self.intent(creation_key=key))
        with self.assertRaises(ValidationError): self.create(creation_key=key)
        charge.refresh_from_db(); self.assertEqual(charge.agreement_id, original.pk)

    def test_receipt_failure_rolls_back_terms_and_agreement(self):
        from unittest.mock import patch
        before = self.counts()
        with patch('accounting.manual_agreement_creation.AgreementCreationReceipt.objects.create', side_effect=ValidationError('synthetic')):
            with self.assertRaises(ValidationError): self.create()
        self.assertEqual(self.counts(), before)

    def test_creation_receipt_cannot_be_rewritten_by_sql(self):
        self.create()
        with self.assertRaises(DatabaseError), transaction.atomic(), audit_context(self.member, 'Δοκιμαστική αλλαγή'):
            AgreementCreationReceipt.objects.update(payload_sha256='sha256:'+'0'*64)


class SubjectPendingContracts(TaskSupport, TestCase):
    def setUp(self):
        self.seed_tasks()

    def test_note_and_new_task_have_separate_subject_and_body_and_default_open(self):
        note, task, _ = self.create(subject='Φορολογική δήλωση', body='Έλεγχος δικαιολογητικών')
        self.assertEqual((note.subject, task.subject), ('Φορολογική δήλωση', 'Φορολογική δήλωση'))
        self.assertEqual((note.body, task.body, task.status), ('Έλεγχος δικαιολογητικών', 'Έλεγχος δικαιολογητικών', 'OPEN'))

    def test_subject_change_under_original_request_is_not_a_replay(self):
        key = uuid.uuid4(); self.create(subject='Πρώτο θέμα', request_key=key)
        with self.assertRaises(ValidationError): self.create(subject='Άλλο θέμα', request_key=key)

    def test_task_subject_edit_keeps_original_note_and_attribution_unchanged(self):
        note, task, _ = self.create(subject='Αρχικό θέμα'); original = CounterpartyNote.objects.filter(pk=note.pk).values().get()
        self.change(task, subject='Νέο θέμα', body='Άλλο κείμενο')
        task.refresh_from_db(); self.assertEqual(task.subject, 'Νέο θέμα')
        self.assertEqual(CounterpartyNote.objects.filter(pk=note.pk).values().get(), original)
        self.assertEqual(task.activities.order_by('-task_version').first().after['subject'], 'Νέο θέμα')

    def test_converting_existing_note_inherits_subject(self):
        note, _ = add_note(self.member, self.person.pk, subject='Δικαιολογητικά', body='Κείμενο', request_key=uuid.uuid4())
        task, _ = convert_note(self.member, self.person.pk, note.pk, body=note.body, due_date=today(), assignee=self.member, request_key=uuid.uuid4())
        self.assertEqual(task.subject, note.subject)

    def test_pending_remains_visible_in_due_order_and_blocks_archive(self):
        _, first, _ = self.create(subject='Πρώτη', due_date=today()-timedelta(days=1))
        _, second, _ = self.create(subject='Δεύτερη', due_date=today()+timedelta(days=2))
        self.change(first, action='PENDING'); first.refresh_from_db()
        self.assertEqual(first.status, 'WAIT'); self.assertIsNone(first.completed_at)
        self.assertEqual([row.pk for row in dashboard_tasks(self.member)['my_tasks']], [first.pk, second.pk])
        with self.assertRaises(ValidationError): self.archive()

    def test_pending_can_resume_complete_and_reopen_with_history(self):
        _, task, _ = self.create()
        for action, status in (('PENDING', 'WAIT'), ('RESUME', 'OPEN'), ('PENDING', 'WAIT'), ('COMPLETE', 'DONE'), ('REOPEN', 'OPEN')):
            self.change(task, action=action); task.refresh_from_db(); self.assertEqual(task.status, status)
        self.assertEqual(list(task.activities.order_by('task_version').values_list('action', flat=True)),
            ['CREATE', 'PENDING', 'RESUME', 'PENDING', 'COMPLETE', 'REOPEN'])

    def test_status_changes_have_no_financial_effects(self):
        before = self.money(); _, task, _ = self.create(subject='Εργασία')
        self.change(task, action='PENDING'); self.change(task, action='COMPLETE')
        self.assertEqual(self.money(), before)

    def test_unrelated_accountant_cannot_set_pending(self):
        _, task, _ = self.create()
        with self.assertRaises(PermissionDenied): self.change(task, user=self.reader, action='PENDING')
        task.refresh_from_db(); self.assertEqual(task.status, 'OPEN')

    def test_pending_status_and_subject_are_searchable_in_client_journal(self):
        _, task, _ = self.create(subject='Μοναδικό θέμα αναζήτησης', body='Σώμα')
        self.change(task, action='PENDING')
        result = journal_page(self.member, self.person.pk, JournalForm({'q': 'Μοναδικό θέμα'}))
        self.assertGreaterEqual(result['journal_page'].paginator.count, 2)

    def test_sql_archive_veto_includes_pending_tasks(self):
        _, task, _ = self.create(); self.change(task, action='PENDING')
        from django.utils import timezone
        from .models import Entity
        with self.assertRaises(DatabaseError), transaction.atomic():
            Entity.objects.filter(pk=self.person.pk).update(is_archived=True, archived_at=timezone.now(), archived_by=self.member)

    def test_pending_http_is_post_only_and_csrf_protected(self):
        _, task, _ = self.create(); client = self.login(csrf=True); url = reverse('task-pending', args=[task.pk])
        self.assertEqual(client.get(url).status_code, 405)
        self.assertEqual(client.post(url, {'request_key': uuid.uuid4(), 'version': 0}).status_code, 403)
        task.refresh_from_db(); self.assertEqual(task.status, 'OPEN')


class ManualCreationConcurrency(CreationSupport, TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema(); super().setUpClass()

    def test_two_simultaneous_manual_submissions_commit_one_terms_only_agreement(self):
        self.seed(); key = uuid.uuid4(); barrier = Barrier(2); user_id = self.member.pk; customer_id = self.customer.pk
        from .models import Agreement
        before = Agreement.objects.count()
        def run():
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                candidate = Agreement(entity_id=customer_id, agreement_type='RECEIVABLE', description='Ταυτόχρονη συμφωνία', total_amount='400.00', start_date=self.agreement.start_date)
                barrier.wait(timeout=10)
                result, _ = create_manual(user, candidate, billing_mode='ONE_OFF', reason='Δοκιμαστική ταυτόχρονη δημιουργία', creation_key=key)
                return result.pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(results[0], results[1]); self.assertEqual(Agreement.objects.count(), before+1)
        self.assertFalse(Charge.objects.exists()); self.assertEqual(AgreementCreationReceipt.objects.count(), 1)


class SubjectMigrationContracts(CreationSupport, TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema(); super().setUpClass()

    def tearDown(self):
        restore_current_test_schema(); super().tearDown()

    def test_existing_note_values_actor_and_clock_survive_additive_upgrade(self):
        self.seed()
        executor = MigrationExecutor(connection)
        executor.migrate([('accounting', '0036_attachment_guards')])
        old = executor.loader.project_state([('accounting', '0036_attachment_guards')]).apps.get_model('accounting', 'CounterpartyNote')
        note = old.objects.create(office_id=self.office.pk, entity_id=self.customer.pk,
            actor_id=self.member.pk, actor_label='', request_key=uuid.uuid4(), body='Ιστορική σημείωση χωρίς θέμα')
        before = old.objects.filter(pk=note.pk).values().get()
        counts = (Charge.objects.count(), self.agreement.terms_versions.count())
        restore_current_test_schema()
        after = CounterpartyNote.objects.filter(pk=note.pk).values().get()
        self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual(after['subject'], '')
        self.assertEqual((Charge.objects.count(), self.agreement.terms_versions.count()), counts)
