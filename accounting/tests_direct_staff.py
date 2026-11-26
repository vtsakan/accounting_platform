"""Operator PG17 contracts: direct credentials, first-login gate, MFA and races."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import hashlib,json,secrets,uuid
from types import SimpleNamespace
from unittest.mock import patch

from django.core import mail
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import connection,transaction,IntegrityError,DatabaseError,close_old_connections
from django.db.migrations.executor import MigrationExecutor
from django.http import Http404
from django.test import Client,TestCase,TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .auth_models import AuthSecurityState,AuthenticatorDevice,MFARecoveryCode
from .auth_policy import bind_session,state_for
from .auth_forms import StaffSetPasswordForm
from .models import AccountantProfile,OfficeAuditEvent,Transaction,Charge,FinanceAuditEvent
from .membership import change_membership
from .schema_test_support import restore_current_test_schema
from .staff_access_models import StaffCredentialRequirement
from .staff_access_selectors import credentials_installed,password_change_required
from .staff_access_services import create_direct_staff,reset_staff_password,finish_required_password_change,credential_context,password_marker
from .tests_auth_support import staff_client_login
from .tests_finance_posting import Fixtures


class DirectStaffSupport(Fixtures):
    @classmethod
    def setUpClass(cls):
        restore_current_test_schema();super().setUpClass()

    def prepare(self):
        self.seed();self.temporary=secrets.token_urlsafe(30);self.permanent=secrets.token_urlsafe(30)
        self.owner_client=Client();staff_client_login(self.owner_client,self.owner)
        self.request=self.owner_client.get(reverse('office-members')).wsgi_request

    def create(self,**changes):
        values={'username':'cr011-'+uuid.uuid4().hex[:16],'temporary_password':self.temporary,
            'role':'accountant','owner_password':self.password};values.update(changes)
        return create_direct_staff(self.request,**values)

    def reset(self,user,**changes):
        row=StaffCredentialRequirement.objects.filter(user=user).first()
        values={'temporary_password':self.temporary,'owner_password':self.password,'version':row.version if row else -1}
        values.update(changes);return reset_staff_password(self.request,user.pk,**values)

    def login_temporary(self,user):
        client=Client();response=client.post(reverse('login'),{'username':user.username,'password':self.temporary})
        self.assertRedirects(response,reverse('password-change-required'),fetch_redirect_response=False)
        return client

    def change(self,client,user,**changes):
        row=StaffCredentialRequirement.objects.get(user=user)
        values={'current_password':self.temporary,'new_password':self.permanent,
            'new_password_confirm':self.permanent,'version':row.version};values.update(changes)
        return client.post(reverse('password-change-required'),values)

    def snapshot(self,user):
        user.refresh_from_db();state=state_for(user)
        row=StaffCredentialRequirement.objects.filter(user=user).values().first()
        audit_rows=list(OfficeAuditEvent.objects.filter(target_user=user).order_by('pk').values())
        return user.password,state.revision,row,audit_rows


class DirectStaffContracts(DirectStaffSupport,TestCase):
    def setUp(self):self.prepare()

    def test_owner_creates_accountant_without_email_or_invitation(self):
        from .office_models import StaffInvitation
        before=StaffInvitation.objects.count();user=self.create();profile=AccountantProfile.objects.get(user=user)
        self.assertEqual((profile.office_id,profile.role,profile.is_active,user.email),(self.office.pk,'accountant',True,''))
        self.assertTrue(user.check_password(self.temporary));self.assertTrue(password_change_required(user))
        self.assertEqual(StaffInvitation.objects.count(),before);self.assertEqual(len(mail.outbox),0)

    def test_owner_creates_additional_owner_without_demoting_original(self):
        user=self.create(role='owner');self.assertEqual(AccountantProfile.objects.get(user=user).role,'owner')
        self.assertEqual(AccountantProfile.objects.get(user=self.owner).role,'owner')
        self.assertEqual(AccountantProfile.objects.filter(office=self.office,role='owner',is_active=True).count(),2)

    def test_roles_are_bounded_and_platform_flags_are_never_granted(self):
        for role in ('superuser','staff','',None):
            with self.assertRaises(ValidationError):self.create(role=role)
        user=self.create(role='owner');self.assertFalse(user.is_staff);self.assertFalse(user.is_superuser)

    def test_existing_other_office_username_is_not_adopted(self):
        other=get_user_model().objects.create_user('foreign-direct',password=secrets.token_urlsafe(30))
        from .membership import create_accountant_profile
        create_accountant_profile(user_id=other.pk,office_id=self.foreign.pk,role='owner')
        with self.assertRaises(ValidationError):self.create(username=other.username)
        self.assertEqual(AccountantProfile.objects.get(user=other).office_id,self.foreign.pk)

    def test_casefold_duplicate_is_rejected(self):
        self.create(username='BoundedName')
        with self.assertRaises(ValidationError):self.create(username='boundedname')
        with self.assertRaises(ValidationError):self.create(username='ｂｏｕｎｄｅｄｎａｍｅ')

    def test_invalid_usernames_leave_no_new_identity(self):
        before=get_user_model().objects.count()
        for username in ('',' spaced ','not valid','x'*151):
            with self.subTest(username=username),self.assertRaises(ValidationError):self.create(username=username)
        self.assertEqual(get_user_model().objects.count(),before)

    def test_weak_temporary_password_leaves_no_user_profile_or_requirement(self):
        before=(get_user_model().objects.count(),AccountantProfile.objects.count(),StaffCredentialRequirement.objects.count())
        with self.assertRaises(ValidationError):self.create(temporary_password='123')
        self.assertEqual((get_user_model().objects.count(),AccountantProfile.objects.count(),StaffCredentialRequirement.objects.count()),before)

    def test_plaintext_is_absent_from_saved_requirement_and_audit(self):
        user=self.create();data=json.dumps(list(StaffCredentialRequirement.objects.filter(user=user).values()),default=str)
        data+=json.dumps(list(OfficeAuditEvent.objects.filter(target_user=user).values()),default=str)
        self.assertNotIn(self.temporary,data);self.assertNotIn(self.password,data)

    def test_creation_is_attributed_and_has_no_financial_effect(self):
        before=tuple(m.objects.count() for m in (Transaction,Charge,FinanceAuditEvent));start=timezone.now();user=self.create()
        audit=OfficeAuditEvent.objects.get(action='staff.create',target_user=user)
        self.assertEqual((audit.actor_id,audit.office_id,audit.role_after),(self.owner.pk,self.office.pk,'accountant'))
        self.assertGreaterEqual(StaffCredentialRequirement.objects.get(user=user).issued_at,start)
        self.assertEqual(tuple(m.objects.count() for m in (Transaction,Charge,FinanceAuditEvent)),before)

    def test_wrong_owner_password_denies_creation(self):
        with self.assertRaises(ValidationError):self.create(owner_password=secrets.token_urlsafe(30))

    def test_stale_mfa_denies_creation(self):
        self.request.session['s13_mfa_at']=0
        with self.assertRaises(ValidationError):self.create()

    def test_revoked_owner_cannot_create_account(self):
        self.create(role='owner')
        change_membership(user_id=self.owner.pk,office_id=self.office.pk,role='accountant',is_active=True)
        with self.assertRaises(PermissionDenied):self.create()

    def test_creation_failure_rolls_back_identity_and_membership(self):
        before=(get_user_model().objects.count(),AccountantProfile.objects.count(),StaffCredentialRequirement.objects.count())
        with patch('accounting.staff_access_services.audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.create()
        self.assertEqual((get_user_model().objects.count(),AccountantProfile.objects.count(),StaffCredentialRequirement.objects.count()),before)

    def test_create_page_get_is_read_only_and_greek(self):
        before=get_user_model().objects.count();response=self.owner_client.get(reverse('staff-direct-create'))
        self.assertContains(response,'Προσωρινός κωδικός');self.assertContains(response,'Υπεύθυνος γραφείου')
        self.assertEqual(get_user_model().objects.count(),before)

    def test_create_post_ignores_submitted_office_and_platform_flags(self):
        response=self.owner_client.post(reverse('staff-direct-create'),{'username':'http-direct','role':'owner',
            'temporary_password':self.temporary,'temporary_password_confirm':self.temporary,
            'owner_password':self.password,'office_id':self.foreign.pk,'is_superuser':'1','is_staff':'1'})
        self.assertEqual(response.status_code,302);user=get_user_model().objects.get(username='http-direct')
        self.assertEqual(AccountantProfile.objects.get(user=user).office_id,self.office.pk)
        self.assertFalse(user.is_staff);self.assertFalse(user.is_superuser)

    def test_invalid_form_does_not_echo_passwords(self):
        response=self.owner_client.post(reverse('staff-direct-create'),{'username':'http-direct','role':'accountant',
            'temporary_password':self.temporary,'temporary_password_confirm':secrets.token_urlsafe(30),'owner_password':self.password})
        self.assertEqual(response.status_code,200);self.assertNotContains(response,self.temporary);self.assertNotContains(response,self.password)

    def test_create_and_reset_require_csrf(self):
        guarded=Client(enforce_csrf_checks=True);guarded.cookies.update(self.owner_client.cookies)
        for url in (reverse('staff-direct-create'),reverse('staff-direct-reset',args=[self.member.pk])):
            self.assertEqual(guarded.post(url,{}).status_code,403)

    def test_accountant_cannot_open_create_or_reset(self):
        state=state_for(self.member);state.enrolled_at=timezone.now();state.save(update_fields=['enrolled_at'])
        client=Client();staff_client_login(client,self.member)
        for url in (reverse('staff-direct-create'),reverse('staff-direct-reset',args=[self.owner.pk])):
            self.assertEqual(client.get(url).status_code,403)

    def test_foreign_reset_target_is_not_disclosed(self):
        other=self.create();AccountantProfile.objects.filter(user=other).update(is_active=False)
        foreign=get_user_model().objects.create_user('outside-reset')
        response=self.owner_client.get(reverse('staff-direct-reset',args=[foreign.pk]))
        self.assertEqual(response.status_code,404);self.assertNotContains(response,foreign.username,status_code=404)

    def test_members_page_exposes_direct_create_reset_and_pending_badge(self):
        self.create();response=self.owner_client.get(reverse('office-members'))
        self.assertContains(response,'Νέος χρήστης χωρίς πρόσκληση');self.assertContains(response,'Επαναφορά κωδικού')
        self.assertContains(response,'Αναμονή αλλαγής κωδικού')

    def test_accountant_login_stops_at_required_change(self):
        user=self.create();client=self.login_temporary(user)
        self.assertRedirects(client.get('/'),reverse('password-change-required'),fetch_redirect_response=False)

    def test_owner_login_requires_password_change_before_mfa(self):
        user=self.create(role='owner');self.login_temporary(user)
        self.assertFalse(AuthenticatorDevice.objects.filter(user=user).exists())

    def test_pending_password_cannot_post_business_actions(self):
        user=self.create();client=self.login_temporary(user);before=Transaction.objects.count()
        response=client.post(reverse('add-income'),{'amount':'100'})
        self.assertRedirects(response,reverse('password-change-required'),fetch_redirect_response=False)
        self.assertEqual(Transaction.objects.count(),before)

    def test_pending_password_cannot_enrol_or_verify_a_factor(self):
        user=self.create(role='owner');client=self.login_temporary(user)
        for route in ('mfa-setup','mfa-verify','mfa-qr','security-settings'):
            response=client.get(reverse(route));self.assertRedirects(response,reverse('password-change-required'),fetch_redirect_response=False)
        self.assertFalse(AuthenticatorDevice.objects.filter(user=user).exists())

    def test_required_change_get_is_read_only(self):
        user=self.create();client=self.login_temporary(user);before=self.snapshot(user)
        self.assertContains(client.get(reverse('password-change-required')),'Νέος προσωπικός κωδικός')
        self.assertEqual(self.snapshot(user),before)

    def test_successful_change_sets_personal_hash_clears_requirement_and_keeps_login(self):
        user=self.create();client=self.login_temporary(user);response=self.change(client,user)
        self.assertEqual(response.status_code,302);user.refresh_from_db()
        self.assertTrue(user.check_password(self.permanent));self.assertFalse(user.check_password(self.temporary))
        self.assertFalse(password_change_required(user));self.assertEqual(int(client.session['_auth_user_id']),user.pk)
        self.assertEqual(OfficeAuditEvent.objects.get(action='staff.password_change',target_user=user).actor_id,user.pk)

    def test_wrong_current_password_leaves_everything_unchanged(self):
        user=self.create();client=self.login_temporary(user);before=self.snapshot(user)
        self.assertEqual(self.change(client,user,current_password=secrets.token_urlsafe(30)).status_code,200)
        self.assertEqual(self.snapshot(user),before)

    def test_reused_temporary_or_weak_personal_password_is_rejected(self):
        user=self.create();client=self.login_temporary(user);before=self.snapshot(user)
        for value in (self.temporary,'123'):
            self.assertEqual(self.change(client,user,new_password=value,new_password_confirm=value).status_code,200)
            self.assertEqual(self.snapshot(user),before)

    def test_mismatched_personal_confirmation_is_rejected(self):
        user=self.create();client=self.login_temporary(user);before=self.snapshot(user)
        self.assertEqual(self.change(client,user,new_password_confirm=secrets.token_urlsafe(30)).status_code,200);self.assertEqual(self.snapshot(user),before)

    def test_required_change_cannot_target_another_identity(self):
        user=self.create();other=self.create();before=self.snapshot(other);client=self.login_temporary(user)
        self.assertEqual(self.change(client,user,user_id=other.pk).status_code,302);self.assertEqual(self.snapshot(other),before)

    def test_stale_change_version_is_rejected(self):
        user=self.create();client=self.login_temporary(user);before=self.snapshot(user)
        self.assertEqual(self.change(client,user,version=999).status_code,200);self.assertEqual(self.snapshot(user),before)

    def test_completed_change_does_not_accept_old_temporary_password_again(self):
        user=self.create();client=self.login_temporary(user);self.change(client,user)
        response=Client().post(reverse('login'),{'username':user.username,'password':self.temporary})
        self.assertEqual(response.status_code,200);self.assertNotIn('_auth_user_id',response.wsgi_request.session)

    def test_owner_continues_to_mfa_setup_after_personal_password(self):
        user=self.create(role='owner');client=self.login_temporary(user)
        self.assertRedirects(self.change(client,user),reverse('mfa-setup'),fetch_redirect_response=False)
        self.assertFalse(client.session.get('otp_device_id'))

    def test_membership_revocation_between_login_and_change_denies_access(self):
        user=self.create();client=self.login_temporary(user);AccountantProfile.objects.filter(user=user).update(is_active=False)
        response=self.change(client,user);self.assertEqual(response.status_code,403);self.assertTrue(password_change_required(user))

    def test_temporary_credentials_never_appear_in_redirect_url(self):
        user=self.create();response=Client().post(reverse('login'),{'username':user.username,'password':self.temporary})
        self.assertNotIn(self.temporary,response['Location']);self.assertNotIn(user.username,response['Location'])

    def test_owner_reset_replaces_hash_and_sets_required_change(self):
        old=self.member.password;self.reset(self.member);self.member.refresh_from_db()
        self.assertNotEqual(self.member.password,old);self.assertTrue(self.member.check_password(self.temporary))
        self.assertTrue(password_change_required(self.member));self.login_temporary(self.member)

    def test_reset_of_another_owner_keeps_both_ownerships(self):
        other=self.create(role='owner');self.reset(other)
        self.assertEqual(AccountantProfile.objects.get(user=other).role,'owner')
        self.assertEqual(AccountantProfile.objects.get(user=self.owner).role,'owner')

    def test_owner_cannot_use_admin_reset_on_self(self):
        with self.assertRaises(ValidationError):self.reset(self.owner)

    def test_reset_does_not_reactivate_inactive_membership(self):
        AccountantProfile.objects.filter(user=self.member).update(is_active=False);self.reset(self.member)
        self.assertFalse(AccountantProfile.objects.get(user=self.member).is_active)

    def test_reset_invalidates_existing_authenticated_sessions(self):
        self.member.set_password(self.permanent);self.member.save(update_fields=['password'])
        clients=[Client(),Client()]
        for client in clients:self.assertEqual(client.post(reverse('login'),{'username':self.member.username,'password':self.permanent}).status_code,302)
        self.reset(self.member)
        for client in clients:
            response=client.get('/');self.assertEqual(response.status_code,302);self.assertNotIn('_auth_user_id',client.session)

    def test_reset_retains_enrolled_mfa_and_recovery_codes(self):
        state=state_for(self.member);state.enrolled_at=timezone.now();state.save(update_fields=['enrolled_at'])
        member_client=Client();staff_client_login(member_client,self.member)
        before=list(AuthenticatorDevice.objects.filter(user=self.member).values());codes=list(MFARecoveryCode.objects.filter(user=self.member).values())
        self.reset(self.member);self.assertEqual(list(AuthenticatorDevice.objects.filter(user=self.member).values()),before)
        self.assertEqual(list(MFARecoveryCode.objects.filter(user=self.member).values()),codes)
        client=self.login_temporary(self.member);self.assertRedirects(self.change(client,self.member),reverse('mfa-verify'),fetch_redirect_response=False)

    def test_stale_reset_is_not_a_second_password_write(self):
        self.reset(self.member);before=self.snapshot(self.member)
        with self.assertRaises(ValidationError):self.reset(self.member,version=-1)
        self.assertEqual(self.snapshot(self.member),before)

    def test_reset_failure_rolls_back_hash_revision_and_requirement(self):
        before=self.snapshot(self.member)
        with patch('accounting.staff_access_services.audit',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):self.reset(self.member)
        self.assertEqual(self.snapshot(self.member),before)

    def test_reset_get_does_not_modify_password(self):
        before=self.snapshot(self.member);self.assertEqual(self.owner_client.get(reverse('staff-direct-reset',args=[self.member.pk])).status_code,200)
        self.assertEqual(self.snapshot(self.member),before)

    def test_email_recovery_can_complete_pending_change_without_erasing_mfa(self):
        self.reset(self.member);form=StaffSetPasswordForm(self.member,{'new_password1':self.permanent,'new_password2':self.permanent})
        self.assertTrue(form.is_valid());form.save();self.assertFalse(password_change_required(self.member))

    def test_raw_clear_without_credential_command_is_denied(self):
        user=self.create()
        with self.assertRaises(IntegrityError),transaction.atomic():StaffCredentialRequirement.objects.filter(user=user).update(required=False)
        self.assertTrue(password_change_required(user))

    def test_owner_context_cannot_finish_another_users_required_change(self):
        user=self.create();row=StaffCredentialRequirement.objects.get(user=user)
        with self.assertRaises(IntegrityError),transaction.atomic(),credential_context(self.request.user,'CHANGE'):
            row.required=False;row.version+=1;row.save()

    def test_missing_guard_after_recorded_installation_fails_closed(self):
        with transaction.atomic():
            with connection.cursor() as cursor:cursor.execute('ALTER TABLE accounting_staffcredentialrequirement DISABLE TRIGGER cr011_credential_guard')
            with self.assertRaises(RuntimeError):credentials_installed()
            transaction.set_rollback(True)
        self.assertTrue(credentials_installed())


class DirectStaffMigrationContracts(DirectStaffSupport,TransactionTestCase):
    def tearDown(self):restore_current_test_schema();super().tearDown()

    def test_upgrade_retains_every_old_table_row_and_hash_without_creating_accounts(self):
        MigrationExecutor(connection).migrate([('accounting','0038_subject_import_guards')]);self.seed()
        with connection.cursor() as cursor:
            tables=[n for n in connection.introspection.table_names(cursor) if n!='django_migrations'];before={}
            for name in tables:
                cursor.execute('SELECT * FROM '+connection.ops.quote_name(name));before[name]=hashlib.sha256(repr(sorted(cursor.fetchall(),key=repr)).encode()).hexdigest()
        restore_current_test_schema()
        with connection.cursor() as cursor:
            for name in tables:
                cursor.execute('SELECT * FROM '+connection.ops.quote_name(name));self.assertEqual(hashlib.sha256(repr(sorted(cursor.fetchall(),key=repr)).encode()).hexdigest(),before[name],name)
        self.assertFalse(StaffCredentialRequirement.objects.exists());self.assertTrue(credentials_installed())

    def test_partial_foundation_schema_cannot_issue_credentials(self):
        MigrationExecutor(connection).migrate([('accounting','0039_staff_access')])
        with self.assertRaises(RuntimeError):credentials_installed()

    def test_downgrade_does_not_erase_issued_credential_attribution(self):
        self.prepare();self.create()
        with self.assertRaisesMessage(DatabaseError,'Retain staff credential attribution'):
            MigrationExecutor(connection).migrate([('accounting','0038_subject_import_guards')])
        self.assertEqual(StaffCredentialRequirement.objects.count(),1)


class DirectStaffConcurrencyContracts(DirectStaffSupport,TransactionTestCase):
    def setUp(self):self.prepare()

    def threaded_request(self):
        return SimpleNamespace(user=self.request.user,session=dict(self.request.session))

    def test_parallel_duplicate_username_creates_exactly_one_identity(self):
        gate=Barrier(2)
        def submit(_):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                try:create_direct_staff(self.threaded_request(),username='concurrent-direct',temporary_password=self.temporary,role='owner',owner_password=self.password)
                except ValidationError:return 'denied'
                return 'saved'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(submit,range(2)))
        self.assertEqual(sorted(outcomes),['denied','saved']);self.assertEqual(get_user_model().objects.filter(username='concurrent-direct').count(),1)

    def test_parallel_resets_with_same_version_cannot_both_succeed(self):
        gate=Barrier(2)
        def submit(_):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                try:reset_staff_password(self.threaded_request(),self.member.pk,temporary_password=secrets.token_urlsafe(30),owner_password=self.password,version=-1)
                except ValidationError:return 'denied'
                return 'saved'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:outcomes=list(pool.map(submit,range(2)))
        self.assertEqual(sorted(outcomes),['denied','saved']);self.assertEqual(StaffCredentialRequirement.objects.get(user=self.member).version,0)
