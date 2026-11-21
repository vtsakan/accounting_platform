"""Operator PG17 contracts for manual notes/tasks, authority, history and races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone as dt_timezone
from threading import Barrier
import secrets
import time
import uuid
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.http import Http404
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .client_task_forms import WorkNoteForm
from .client_task_selectors import dashboard_tasks, task_rows, tasks_installed, today
from .client_task_services import add_work_note, change_task, convert_note, task_context
from .counterparty_journal_forms import JournalForm
from .counterparty_journal_selectors import journal_page
from .counterparty_note_services import add_note
from .counterparty_retirement_services import delete_counterparty
from .counterparty_services import archive_counterparty
from .finance_services import canonical, fingerprint
from .membership import create_accountant_profile
from .models import (AccountantProfile, ClientTask, ClientTaskActivity, CounterpartyNote,
    Entity, Office, Transaction, Charge, FinanceAuditEvent, OfficeAuditEvent)
from .schema_test_support import restore_current_test_schema
from .tests_auth_support import staff_client_login
from .tests_finance_posting import Fixtures


def seed_task_routes(cls):
    """Only the explicit new boundary routes need these extra records."""
    for suffix in ('a', 'b'):
        user = cls.owner if suffix == 'a' else cls.owner_b
        assigned = cls.member if suffix == 'a' else cls.member_b
        entity = getattr(cls, 'entity_' + suffix)
        _, task, _ = add_work_note(user, entity.pk, body='ΔΟΚΙΜΑΣΤΙΚΗ ΕΡΓΑΣΙΑ ΟΡΙΩΝ',
            request_key=uuid.uuid4(), as_task=True, due_date=today(), assignee=assigned)
        note, _ = add_note(user, entity.pk, body='ΔΟΚΙΜΑΣΤΙΚΗ ΣΗΜΕΙΩΣΗ ΓΙΑ ΕΡΓΑΣΙΑ', request_key=uuid.uuid4())
        setattr(cls, 'task_' + suffix, task); setattr(cls, 'task_note_' + suffix, note)


class TaskSupport(Fixtures):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema(); super().setUpClass()

    def seed_tasks(self):
        self.seed()
        self.person = Entity.objects.create(office=self.office, name='ΔΟΚΙΜΑΣΤΙΚΗ ΚΑΡΤΕΛΑ ΕΡΓΑΣΙΩΝ', entity_type='CUSTOMER')
        self.peer = get_user_model().objects.create_user('cr006-peer', password=secrets.token_urlsafe(32))
        self.reader = get_user_model().objects.create_user('cr006-reader', password=secrets.token_urlsafe(32))
        self.foreign_owner = get_user_model().objects.create_user('cr006-foreign', password=secrets.token_urlsafe(32))
        for user, office, role in ((self.peer, self.office, 'accountant'), (self.reader, self.office, 'accountant'),
                                  (self.foreign_owner, self.foreign, 'owner')):
            create_accountant_profile(user_id=user.pk, office_id=office.pk, role=role)

    def create(self, *, user=None, person=None, **values):
        data = {'body': 'Δοκιμαστική εργασία', 'request_key': uuid.uuid4(), 'as_task': True, 'due_date': today()}
        data.update(values)
        return add_work_note(user or self.member, (person or self.person).pk, **data)

    def change(self, task, *, user=None, action='UPDATE', **values):
        task.refresh_from_db()
        data = {'version': task.version, 'request_key': uuid.uuid4(), 'action': action}
        if action == 'UPDATE':data.update(body=task.body, due_date=task.due_date, assignee=task.assignee_id)
        data.update(values)
        return change_task(user or self.member, task.pk, **data)

    def login(self, user=None, *, csrf=False):
        client = Client(enforce_csrf_checks=csrf)
        if csrf:
            client.get('/login/'); client.defaults['HTTP_X_CSRFTOKEN'] = client.cookies[settings.CSRF_COOKIE_NAME].value
        try:staff_client_login(client, user or self.member)
        finally:client.defaults.pop('HTTP_X_CSRFTOKEN', None)
        return client

    def money(self):
        return {m._meta.label:list(m.objects.order_by('pk').values()) for m in (Transaction, Charge, FinanceAuditEvent, OfficeAuditEvent)}

    def archive(self):
        self.person.refresh_from_db()
        result = archive_counterparty(self.member, self.person.pk, version=self.person.record_version, archive=True)
        self.person.refresh_from_db(); return result


class TaskCreationContracts(TaskSupport, TestCase):
    def setUp(self):self.seed_tasks()

    def test_new_task_creates_one_retained_note_and_one_attributed_activity(self):
        before = self.money(); start = timezone.now()
        note, task, replay = self.create()
        self.assertFalse(replay); self.assertEqual(task.source_note_id, note.pk)
        self.assertEqual(task.creator_id, self.member.pk); self.assertEqual(task.assignee_id, self.member.pk)
        self.assertEqual(task.status, 'OPEN'); self.assertGreaterEqual(task.created_at, start)
        self.assertEqual(task.activities.get().actor_label, self.member.username)
        self.assertEqual(self.money(), before)

    def test_plain_note_stays_a_note_with_bound_submission_intent(self):
        note, task, replay = self.create(as_task=False)
        self.assertIsNone(task); self.assertFalse(replay); self.assertEqual(CounterpartyNote.objects.count(), 1)
        self.assertEqual(ClientTaskActivity.objects.get().action, 'NOTE')

    def test_active_colleague_can_be_selected_as_assignee(self):
        _, task, _ = self.create(assignee=self.peer)
        self.assertEqual(task.assignee_id, self.peer.pk); self.assertEqual(task.creator_id, self.member.pk)

    def test_missing_deadline_does_not_leave_a_note_or_activity(self):
        with self.assertRaises(ValidationError):self.create(due_date=None)
        self.assertFalse(CounterpartyNote.objects.exists()); self.assertFalse(ClientTaskActivity.objects.exists())

    def test_past_deadline_is_allowed_for_recording_overdue_work(self):
        _, task, _ = self.create(due_date=today()-timedelta(days=5))
        self.assertLess(task.due_date, today())

    def test_invalid_deadline_types_and_range_are_denied(self):
        for value in ('2026-11-21', True, datetime.now(dt_timezone.utc), date(1800,1,1), date(2201,1,1)):
            with self.subTest(value=str(value)), self.assertRaises(ValidationError):self.create(due_date=value)
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_foreign_assignee_is_rejected_before_note_creation(self):
        with self.assertRaises(ValidationError):self.create(assignee=self.foreign_owner)
        self.assertFalse(CounterpartyNote.objects.exists()); self.assertFalse(ClientTask.objects.exists())

    def test_inactive_assignee_and_inactive_profile_are_rejected(self):
        self.peer.is_active=False; self.peer.save(update_fields=['is_active'])
        with self.assertRaises(ValidationError):self.create(assignee=self.peer)
        AccountantProfile.objects.filter(user=self.reader).update(is_active=False)
        with self.assertRaises(ValidationError):self.create(assignee=self.reader)
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_duplicate_creation_replays_one_note_task_and_activity(self):
        key=uuid.uuid4(); first=self.create(request_key=key); second=self.create(request_key=key)
        self.assertEqual(first[0].pk, second[0].pk); self.assertEqual(first[1].pk, second[1].pk)
        self.assertTrue(second[2]); self.assertEqual(ClientTaskActivity.objects.count(),1)

    def test_changed_note_only_submission_cannot_silently_become_a_task(self):
        key=uuid.uuid4(); self.create(request_key=key, as_task=False)
        with self.assertRaises(ValidationError):self.create(request_key=key)
        self.assertFalse(ClientTask.objects.exists()); self.assertEqual(CounterpartyNote.objects.count(),1)

    def test_changed_creation_payload_is_rejected_without_writes(self):
        key=uuid.uuid4(); self.create(request_key=key)
        before=list(ClientTask.objects.values())
        for values in ({'body':'Άλλη εργασία'}, {'assignee':self.peer}, {'due_date':today()+timedelta(days=1)}):
            with self.assertRaises(ValidationError):self.create(request_key=key, **values)
        self.assertEqual(list(ClientTask.objects.values()),before); self.assertEqual(ClientTaskActivity.objects.count(),1)

    def test_creation_replay_after_edit_and_completion_never_reopens_work(self):
        key=uuid.uuid4(); _, task, _=self.create(request_key=key)
        self.change(task, body='Διορθωμένη εργασία'); self.change(task, action='COMPLETE')
        _, again, replay=self.create(request_key=key)
        self.assertTrue(replay); self.assertEqual(again.pk,task.pk); self.assertEqual(again.status,'DONE')
        self.assertEqual(again.body,'Διορθωμένη εργασία'); self.assertEqual(again.activities.count(),3)

    def test_legacy_note_conversion_keeps_every_original_note_field(self):
        note,_=add_note(self.member,self.person.pk,body='Αρχικό κείμενο',request_key=uuid.uuid4())
        before=list(CounterpartyNote.objects.values())
        task,replay=convert_note(self.peer,self.person.pk,note.pk,body=note.body,due_date=today(),assignee=self.peer,request_key=uuid.uuid4())
        self.assertFalse(replay); self.assertEqual(task.creator_id,self.peer.pk)
        self.assertEqual(list(CounterpartyNote.objects.values()),before)

    def test_existing_note_can_have_only_one_task(self):
        note,task,_=self.create()
        with self.assertRaises(ValidationError):convert_note(self.peer,self.person.pk,note.pk,body=note.body,
            due_date=today(),assignee=self.peer,request_key=uuid.uuid4())
        self.assertEqual(ClientTask.objects.count(),1); self.assertEqual(task.activities.count(),1)

    def test_conversion_retry_is_bound_to_its_exact_payload(self):
        note,_=add_note(self.member,self.person.pk,body='Παλιά σημείωση',request_key=uuid.uuid4()); key=uuid.uuid4()
        values={'body':note.body,'due_date':today(),'assignee':self.member,'request_key':key}
        one,_=convert_note(self.member,self.person.pk,note.pk,**values)
        two,replay=convert_note(self.member,self.person.pk,note.pk,**values)
        self.assertTrue(replay); self.assertEqual(one.pk,two.pk)
        with self.assertRaises(ValidationError):convert_note(self.member,self.person.pk,note.pk,**(values|{'body':'Αλλαγή'}))

    def test_legacy_plain_note_retry_does_not_gain_new_task_effects(self):
        key=uuid.uuid4(); note,_=add_note(self.member,self.person.pk,body='Παλιά απλή σημείωση',request_key=key)
        with self.assertRaises(ValidationError):self.create(request_key=key,body=note.body)
        replayed,task,replay=self.create(request_key=key,body=note.body,as_task=False)
        self.assertTrue(replay); self.assertEqual(note.pk,replayed.pk); self.assertIsNone(task)

    def test_note_from_another_client_cannot_be_converted_under_this_client(self):
        note,_=add_note(self.member,self.customer.pk,body='Άλλη καρτέλα',request_key=uuid.uuid4())
        with self.assertRaises(Http404):convert_note(self.member,self.person.pk,note.pk,
            body=note.body,due_date=today(),assignee=self.member,request_key=uuid.uuid4())

    def test_archived_client_cannot_receive_a_new_note_task(self):
        self.archive()
        with self.assertRaises(ValidationError):self.create()
        self.assertFalse(CounterpartyNote.objects.exists())

    def test_database_overrides_forged_clock_labels_and_initial_status(self):
        note,_=add_note(self.member,self.person.pk,body='Πηγή ελέγχου',request_key=uuid.uuid4())
        with task_context(self.member,uuid.uuid4(),'sha256:'+'b'*64):
            task=ClientTask.objects.create(office=self.office,entity=self.person,source_note=note,
                creator=self.member,creator_label='Ψεύτικος δημιουργός',assignee=self.member,assignee_label='Ψεύτικος υπεύθυνος',
                body=note.body,due_date=today(),status='DONE',version=99,created_at=datetime(1900,1,1,tzinfo=dt_timezone.utc))
        task.refresh_from_db(); self.assertEqual(task.status,'OPEN'); self.assertEqual(task.version,0)
        self.assertEqual(task.creator_label,self.member.username); self.assertEqual(task.assignee_label,self.member.username)
        self.assertGreater(task.created_at.year,1900)

    def test_raw_task_creation_requires_an_explicit_actor_context(self):
        note,_=add_note(self.member,self.person.pk,body='Πηγή ελέγχου',request_key=uuid.uuid4())
        with self.assertRaises(IntegrityError),transaction.atomic():ClientTask.objects.create(office=self.office,
            entity=self.person,source_note=note,creator=self.member,creator_label='',assignee=self.member,
            assignee_label='',body=note.body,due_date=today())
        self.assertFalse(ClientTask.objects.exists())


class TaskAuthorityContracts(TaskSupport, TestCase):
    def setUp(self):self.seed_tasks(); self.note,self.task,_=self.create(assignee=self.peer)

    def test_creator_can_edit_work_assigned_to_someone_else(self):
        self.change(self.task,body='Αλλαγή από δημιουργό')
        self.task.refresh_from_db(); self.assertEqual(self.task.body,'Αλλαγή από δημιουργό')

    def test_assignee_can_edit_and_reassign_the_task(self):
        self.change(self.task,user=self.peer,body='Αλλαγή από υπεύθυνο',assignee=self.reader)
        self.task.refresh_from_db(); self.assertEqual(self.task.assignee_id,self.reader.pk)
        self.assertEqual(self.task.activities.last().actor_id,self.peer.pk)

    def test_owner_can_edit_any_task_in_the_office(self):
        self.change(self.task,user=self.owner,assignee=self.owner)
        self.task.refresh_from_db(); self.assertEqual(self.task.assignee_id,self.owner.pk)

    def test_unrelated_member_cannot_edit_even_with_platform_flags(self):
        self.reader.is_staff=True; self.reader.is_superuser=True; self.reader.save(update_fields=['is_staff','is_superuser'])
        with self.assertRaises(PermissionDenied):self.change(self.task,user=self.reader,body='Απαγορευμένη')
        self.assertEqual(self.task.activities.count(),1)

    def test_foreign_owner_cannot_modify_task(self):
        with self.assertRaises(Http404):self.change(self.task,user=self.foreign_owner)

    def test_revoked_creator_has_no_write_authority(self):
        AccountantProfile.objects.filter(user=self.member).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.change(self.task)

    def test_stale_version_cannot_overwrite_another_users_change(self):
        self.change(self.task,user=self.peer,body='Νεότερη αλλαγή')
        with self.assertRaises(ValidationError):self.change(self.task,version=0,body='Παλιά φόρμα')
        self.task.refresh_from_db(); self.assertEqual(self.task.body,'Νεότερη αλλαγή'); self.assertEqual(self.task.activities.count(),2)

    def test_completion_is_attributed_and_keeps_the_original_note_and_money(self):
        before_note=list(CounterpartyNote.objects.values()); before_money=self.money()
        self.change(self.task,user=self.peer,action='COMPLETE')
        self.task.refresh_from_db(); self.assertEqual(self.task.status,'DONE'); self.assertEqual(self.task.completed_by_id,self.peer.pk)
        self.assertIsNotNone(self.task.completed_at); self.assertEqual(self.task.activities.last().action,'COMPLETE')
        self.assertEqual(list(CounterpartyNote.objects.values()),before_note); self.assertEqual(self.money(),before_money)

    def test_reopen_clears_completion_and_keeps_both_activity_records(self):
        self.change(self.task,action='COMPLETE'); self.change(self.task,action='REOPEN')
        self.task.refresh_from_db(); self.assertEqual(self.task.status,'OPEN'); self.assertIsNone(self.task.completed_at)
        self.assertIsNone(self.task.completed_by_id); self.assertEqual(self.task.activities.count(),3)

    def test_replayed_completion_after_reopen_does_not_complete_again(self):
        key=uuid.uuid4(); self.change(self.task,action='COMPLETE',request_key=key)
        self.change(self.task,action='REOPEN')
        _,replay=self.change(self.task,action='COMPLETE',request_key=key,version=0)
        self.task.refresh_from_db(); self.assertTrue(replay); self.assertEqual(self.task.status,'OPEN')
        self.assertEqual(self.task.activities.count(),3)

    def test_completion_request_cannot_be_reused_for_reopen(self):
        key=uuid.uuid4(); self.change(self.task,action='COMPLETE',request_key=key)
        with self.assertRaises(ValidationError):self.change(self.task,action='REOPEN',request_key=key)

    def test_owner_can_recover_work_after_assignee_deactivation(self):
        self.peer.is_active=False; self.peer.save(update_fields=['is_active'])
        self.change(self.task,user=self.owner,assignee=self.reader)
        self.task.refresh_from_db(); self.assertEqual(self.task.assignee_id,self.reader.pk)

    def test_raw_sql_unrelated_actor_and_foreign_assignment_are_denied(self):
        payload='sha256:'+'a'*64
        with self.assertRaises(IntegrityError),transaction.atomic(),task_context(self.reader,uuid.uuid4(),payload):
            ClientTask.objects.filter(pk=self.task.pk).update(body='Παράκαμψη',version=1)
        with self.assertRaises(IntegrityError),transaction.atomic(),task_context(self.owner,uuid.uuid4(),payload):
            ClientTask.objects.filter(pk=self.task.pk).update(assignee=self.foreign_owner,version=1)
        self.assertEqual(self.task.activities.count(),1)

    def test_task_note_identity_and_activity_cannot_be_rewritten(self):
        note,_=add_note(self.member,self.person.pk,body='Άλλη σημείωση',request_key=uuid.uuid4())
        with self.assertRaises(IntegrityError),transaction.atomic(),task_context(self.owner,uuid.uuid4(),'sha256:'+'a'*64):
            ClientTask.objects.filter(pk=self.task.pk).update(source_note=note,version=1)
        with self.assertRaises(IntegrityError),transaction.atomic():ClientTaskActivity.objects.filter(task=self.task).update(actor_label='Άλλος')
        with self.assertRaises(IntegrityError),transaction.atomic():ClientTaskActivity.objects.filter(task=self.task).delete()

    def test_database_generated_audit_failure_rolls_back_the_state_change(self):
        with connection.cursor() as cursor:
            cursor.execute("CREATE FUNCTION pg_temp.cr006_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected'; END $$")
            cursor.execute('CREATE TRIGGER cr006_test_failure BEFORE INSERT ON accounting_clienttaskactivity FOR EACH ROW EXECUTE FUNCTION pg_temp.cr006_failure()')
        try:
            with self.assertRaises(DatabaseError),transaction.atomic():self.change(self.task,body='Δεν αποθηκεύεται')
            self.task.refresh_from_db(); self.assertEqual(self.task.body,'Δοκιμαστική εργασία'); self.assertEqual(self.task.version,0)
            self.assertEqual(self.task.activities.count(),1)
        finally:
            with connection.cursor() as cursor:cursor.execute('DROP TRIGGER cr006_test_failure ON accounting_clienttaskactivity')


class TaskWorkspaceContracts(TaskSupport, TestCase):
    def setUp(self):self.seed_tasks()

    def test_personal_home_contains_only_assigned_open_work(self):
        self.create(assignee=self.member); self.create(assignee=self.peer); _,done,_=self.create(); self.change(done,action='COMPLETE')
        context=dashboard_tasks(self.member)
        self.assertEqual(len(context['my_tasks']),1); self.assertEqual(context['my_task_totals']['total'],1)
        self.assertEqual(dashboard_tasks(self.owner)['my_task_totals']['total'],0)

    def test_deadlines_sort_overdue_then_today_then_future(self):
        for days in (8,0,-4,1):self.create(due_date=today()+timedelta(days=days))
        context=dashboard_tasks(self.member)
        self.assertEqual([t.days_left for t in context['my_tasks']],[-4,0,1,8])
        self.assertEqual(context['my_task_totals']['overdue'],1); self.assertEqual(context['my_task_totals']['due_today'],1)

    def test_day_counter_uses_athens_even_with_another_active_timezone(self):
        _,task,_=self.create(due_date=date(2026,11,22))
        with timezone.override('UTC'),patch('django.utils.timezone.now',return_value=datetime(2026,11,21,22,30,tzinfo=dt_timezone.utc)):
            self.assertEqual(dashboard_tasks(self.member)['my_tasks'][0].days_left,0)

    def test_personal_list_cannot_be_changed_to_office_scope_by_query_parameter(self):
        self.create(assignee=self.member); self.create(assignee=self.peer)
        response=self.login().get(reverse('task-list'),{'scope':'office','assignee':self.peer.pk})
        self.assertEqual(response.status_code,200); self.assertEqual(response.context['task_page'].paginator.count,1)
        self.assertEqual(response.context['task_page'][0].assignee_id,self.member.pk)

    def test_office_overview_is_owner_only_and_excludes_foreign_tasks(self):
        self.create(); self.create(assignee=self.peer)
        foreign=Entity.objects.create(office=self.foreign,name='ΞΕΝΗ ΕΡΓΑΣΙΑ',entity_type='CUSTOMER')
        self.create(user=self.foreign_owner,person=foreign)
        self.assertEqual(self.login().get(reverse('office-task-list')).status_code,403)
        response=self.login(self.owner).get(reverse('office-task-list'))
        self.assertEqual(response.context['task_page'].paginator.count,2); self.assertNotContains(response,'ΞΕΝΗ ΕΡΓΑΣΙΑ')

    def test_client_card_shows_agreements_notes_tasks_and_conversion_links(self):
        note,task,_=self.create(person=self.customer)
        plain,_=add_note(self.member,self.customer.pk,body='Απλή σημείωση',request_key=uuid.uuid4())
        response=self.login().get(reverse('entity-detail',args=[self.customer.pk]))
        self.assertContains(response,'Συμφωνίες'); self.assertContains(response,'Σημειώσεις καρτέλας')
        self.assertContains(response,'Εργασίες πελάτη'); self.assertContains(response,reverse('task-detail',args=[task.pk]))
        self.assertContains(response,reverse('note-to-task',args=[self.customer.pk,plain.pk]))

    def test_task_changes_appear_in_journal_with_distinct_colour(self):
        _,task,_=self.create(); self.change(task,action='COMPLETE')
        context=journal_page(self.member,self.person.pk,JournalForm({'kind':'task'}))
        self.assertEqual(context['journal_page'].paginator.count,2)
        self.assertTrue(all(row['tone']=='purple' for row in context['journal_page']))
        notes=journal_page(self.member,self.person.pk,JournalForm({'kind':'note'}))
        self.assertEqual(notes['journal_page'].paginator.count,1)

    def test_month_calendar_counts_task_events_without_recolouring_notes(self):
        self.create()
        context=journal_page(self.member,self.person.pk,JournalForm({'view':'month','month':today().strftime('%Y-%m')}))
        cells=[c for week in context['journal_calendar']['weeks'] for c in week if c]
        self.assertEqual(sum(c['counts'].get('purple',0) for c in cells),1)
        self.assertEqual(sum(c['counts'].get('blue',0) for c in cells),1)

    def test_all_page_totals_are_not_limited_to_the_displayed_page(self):
        for number in range(26):self.create(body='Εργασία '+str(number))
        response=self.login().get(reverse('task-list'))
        self.assertEqual(len(response.context['task_page'].object_list),25)
        self.assertEqual(response.context['task_page'].paginator.count,26); self.assertEqual(response.context['task_totals']['total'],26)

    def test_assignee_choices_are_active_same_office_and_default_to_actor(self):
        form=WorkNoteForm(user=self.member)
        self.assertEqual(form.fields['assignee'].initial,self.member.pk)
        self.assertNotIn(self.foreign_owner.pk,form.fields['assignee'].queryset.values_list('pk',flat=True))

    def test_recorded_clock_creator_and_status_cannot_be_forged_in_note_post(self):
        response=self.login().post(reverse('entity-note-add',args=[self.person.pk]),{'request_key':uuid.uuid4(),
            'body':'Ασφαλής υποβολή','as_task':'on','due_date':today().isoformat(),'actor':self.foreign_owner.pk,
            'office':self.foreign.pk,'recorded_on':'1900-01-01','status':'DONE'})
        self.assertEqual(response.status_code,302)
        task=ClientTask.objects.get(); self.assertEqual(task.creator_id,self.member.pk)
        self.assertEqual(task.assignee_id,self.member.pk); self.assertEqual(task.status,'OPEN')
        self.assertEqual(task.created_at.astimezone(timezone.get_default_timezone()).date(),today())

    def test_existing_note_conversion_get_is_read_only(self):
        note,_=add_note(self.member,self.person.pk,body='Για μετατροπή',request_key=uuid.uuid4())
        response=self.login().get(reverse('note-to-task',args=[self.person.pk,note.pk]))
        self.assertEqual(response.status_code,200); self.assertFalse(ClientTask.objects.exists())
        self.assertContains(response,'Για μετατροπή')

    def test_task_status_get_is_not_a_mutation(self):
        _,task,_=self.create(); client=self.login()
        for route in ('task-complete','task-reopen'):self.assertEqual(client.get(reverse(route,args=[task.pk])).status_code,405)
        task.refresh_from_db(); self.assertEqual(task.status,'OPEN')

    def test_missing_csrf_is_denied_after_real_owner_mfa_authentication(self):
        _,task,_=self.create(); client=self.login(self.owner,csrf=True)
        self.assertEqual(client.get(reverse('task-detail',args=[task.pk])).status_code,200)
        response=client.post(reverse('task-complete',args=[task.pk]),{'version':0,'request_key':uuid.uuid4()})
        self.assertEqual(response.status_code,403); task.refresh_from_db(); self.assertEqual(task.status,'OPEN')

    def test_valid_csrf_owner_can_complete_and_reopen_from_the_page(self):
        _,task,_=self.create(); client=self.login(self.owner,csrf=True)
        for route,version,status in (('task-complete',0,'DONE'),('task-reopen',1,'OPEN')):
            response=client.post(reverse(route,args=[task.pk]),{'version':version,'request_key':uuid.uuid4(),
                'csrfmiddlewaretoken':client.cookies[settings.CSRF_COOKIE_NAME].value})
            self.assertEqual(response.status_code,302); task.refresh_from_db(); self.assertEqual(task.status,status)

    def test_foreign_task_detail_and_mutation_are_not_found(self):
        _,task,_=self.create(); client=self.login(self.foreign_owner)
        self.assertEqual(client.get(reverse('task-detail',args=[task.pk])).status_code,404)
        self.assertEqual(client.post(reverse('task-complete',args=[task.pk]),{'version':0,'request_key':uuid.uuid4()}).status_code,404)

    def test_task_free_text_is_escaped_in_detail_card_and_journal(self):
        _,task,_=self.create(body='<script>synthetic()</script>')
        client=self.login()
        for url in (reverse('task-detail',args=[task.pk]),reverse('entity-detail',args=[self.person.pk]),reverse('entity-journal',args=[self.person.pk])):
            response=client.get(url); self.assertNotContains(response,'<script>synthetic()'); self.assertContains(response,'&lt;script&gt;')


class TaskArchiveContracts(TaskSupport, TestCase):
    def setUp(self):self.seed_tasks(); _,self.task,_=self.create()

    def test_open_work_blocks_archive_in_service_without_writes(self):
        with self.assertRaisesMessage(ValidationError,'ανοιχτές εργασίες'):self.archive()
        self.person.refresh_from_db(); self.assertFalse(self.person.is_archived)

    def test_raw_sql_archive_cannot_bypass_open_task_rule(self):
        with self.assertRaises(IntegrityError),transaction.atomic():Entity.objects.filter(pk=self.person.pk).update(is_archived=True)
        self.person.refresh_from_db(); self.assertFalse(self.person.is_archived)

    def test_archive_page_explains_tasks_and_hides_confirmation(self):
        response=self.login().get(reverse('archive-entity',args=[self.person.pk]))
        self.assertContains(response,'Ολοκληρώστε πρώτα'); self.assertContains(response,reverse('task-detail',args=[self.task.pk]))
        self.assertNotContains(response,'Επιβεβαίωση αρχειοθέτησης')

    def test_completed_tasks_allow_archive_but_cannot_be_reopened_until_restore(self):
        self.change(self.task,action='COMPLETE'); self.archive()
        with self.assertRaises(ValidationError):self.change(self.task,action='REOPEN')
        archive_counterparty(self.member,self.person.pk,version=self.person.record_version,archive=False)
        self.change(self.task,action='REOPEN'); self.task.refresh_from_db(); self.assertEqual(self.task.status,'OPEN')

    def test_owner_deletion_retains_closed_task_note_and_activity_rows(self):
        self.change(self.task,action='COMPLETE'); self.archive()
        notes=list(CounterpartyNote.objects.values()); activity=list(ClientTaskActivity.objects.values())
        delete_counterparty(self.owner,self.person.pk,version=self.person.record_version,confirmed=True)
        self.assertEqual(list(CounterpartyNote.objects.values()),notes); self.assertEqual(list(ClientTaskActivity.objects.values()),activity)
        self.assertFalse(task_rows(self.owner).exists()); self.assertEqual(ClientTask.objects.count(),1)
        self.assertEqual(self.login(self.owner).get(reverse('task-detail',args=[self.task.pk])).status_code,404)


class TaskMigrationContracts(TaskSupport, TransactionTestCase):
    def tearDown(self):restore_current_test_schema(); super().tearDown()

    def test_current_30_to_32_upgrade_preserves_original_people_and_notes(self):
        MigrationExecutor(connection).migrate([('accounting','0030_counterparty_retirement_guards')])
        self.seed_tasks(); add_note(self.member,self.person.pk,body='Πριν τις εργασίες',request_key=uuid.uuid4())
        models=(Entity,CounterpartyNote,AccountantProfile,get_user_model())
        before={m._meta.label:list(m.objects.order_by('pk').values()) for m in models}
        restore_current_test_schema()
        self.assertEqual({m._meta.label:list(m.objects.order_by('pk').values()) for m in models},before)
        self.assertTrue(tasks_installed()); self.assertFalse(ClientTask.objects.exists()); self.assertFalse(ClientTaskActivity.objects.exists())

    def test_partial_task_schema_does_not_fall_back_to_an_empty_dashboard(self):
        MigrationExecutor(connection).migrate([('accounting','0031_client_tasks')])
        with self.assertRaisesMessage(RuntimeError,'δεν έχει ολοκληρωθεί'):tasks_installed()

    def test_missing_tables_after_recorded_upgrade_do_not_hide_tasks(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP TABLE accounting_clienttaskactivity,accounting_clienttask CASCADE')
            with self.assertRaisesMessage(RuntimeError,'δεν έχει ολοκληρωθεί'):tasks_installed()
            transaction.set_rollback(True)
        self.assertTrue(tasks_installed())

    def test_downgrade_does_not_discard_task_or_submission_history(self):
        self.seed_tasks(); self.create()
        with self.assertRaisesMessage(DatabaseError,'Retain task'):MigrationExecutor(connection).migrate([('accounting','0030_counterparty_retirement_guards')])
        self.assertEqual(ClientTask.objects.count(),1)


class TaskConcurrencyContracts(TaskSupport, TransactionTestCase):
    def setUp(self):self.seed_tasks()

    def test_simultaneous_identical_submissions_create_one_task(self):
        key=uuid.uuid4(); gate=Barrier(2)
        def submit():
            close_old_connections()
            try:gate.wait(timeout=10); return self.create(request_key=key)[1].pk
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(submit) for _ in range(2)]; ids=[f.result(timeout=30) for f in futures]
        self.assertEqual(ids[0],ids[1]); self.assertEqual(ClientTask.objects.count(),1); self.assertEqual(ClientTaskActivity.objects.count(),1)

    def test_competing_edits_cannot_overwrite_the_same_version(self):
        _,task,_=self.create(); gate=Barrier(2)
        def submit(body):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                change_task(self.member,task.pk,version=0,request_key=uuid.uuid4(),action='UPDATE',body=body,due_date=today(),assignee=self.member)
                return 'saved'
            except ValidationError:return 'stale'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(submit,body) for body in ('Πρώτη αλλαγή','Δεύτερη αλλαγή')]
            results=[f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(results),['saved','stale']); task.refresh_from_db()
        self.assertEqual(task.version,1); self.assertEqual(task.activities.count(),2)

    def test_waiting_writer_rechecks_revoked_membership_after_office_lock(self):
        _,task,_=self.create()
        def submit():
            close_old_connections()
            try:return change_task(self.member,task.pk,version=0,request_key=uuid.uuid4(),action='COMPLETE')
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                Office.objects.select_for_update().get(pk=self.office.pk)
                future=pool.submit(submit); time.sleep(.15)
                AccountantProfile.objects.filter(user=self.member).update(is_active=False)
            with self.assertRaises(PermissionDenied):future.result(timeout=30)
        task.refresh_from_db(); self.assertEqual(task.status,'OPEN'); self.assertEqual(task.activities.count(),1)

    def test_new_task_and_client_archive_cannot_both_commit(self):
        gate=Barrier(2)
        def submit(kind):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                if kind=='task':self.create()
                else:archive_counterparty(self.member,self.person.pk,version=0,archive=True)
                return 'saved'
            except ValidationError:return 'blocked'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(submit,kind) for kind in ('task','archive')]
            results=[f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(results),['blocked','saved']); self.person.refresh_from_db()
        self.assertFalse(self.person.is_archived and ClientTask.objects.filter(entity=self.person,status='OPEN').exists())
