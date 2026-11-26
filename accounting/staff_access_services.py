"""Fresh same-office owner authority, hashed temporary credentials and forced change."""
from contextlib import contextmanager
import hashlib

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, IntegrityError, transaction
from django.http import Http404

from core.redaction import register_secret
from .auth_services import lock_request_state, lock_state
from .membership import create_accountant_profile, require_office_profile
from .models import AccountantProfile, Office
from .office_services import audit, lock_identifiers, lock_office, lock_users, prove_actor
from .staff_access_models import StaffCredentialRequirement
from .staff_access_selectors import credentials_installed


def password_marker(user):
    return 'sha256:'+hashlib.sha256(user.password.encode()).hexdigest()


def require_installation():
    if not credentials_installed():
        raise RuntimeError('Απαιτείται η ολοκληρωμένη αναβάθμιση διαχείρισης κωδικών.')


def owner_not_pending(user):
    if StaffCredentialRequirement.objects.filter(user=user,required=True).exists():
        raise PermissionDenied('Αλλάξτε πρώτα τον προσωρινό κωδικό σας.')


def lock_password_reset_office(user):
    profile=AccountantProfile.objects.filter(user_id=user.pk).only('office_id').first()
    if profile:
        Office.objects.select_for_update().get(pk=profile.office_id)


def complete_email_password_change(user,state):
    if not credentials_installed():return
    row=StaffCredentialRequirement.objects.select_for_update().filter(user=user,required=True).first()
    if row is None:return
    profile=require_office_profile(user)
    row.required=False;row.version+=1;row.security_revision=state.revision;row.password_marker=password_marker(user)
    with credential_context(user,'CHANGE'):row.save()
    audit(profile.office,user,'staff.password_change',target=user,
        before=(profile.role,profile.is_active),after=(profile.role,profile.is_active))


def checked_password(value, user):
    if not isinstance(value, str) or not value or len(value)>256 or '\x00' in value:
        raise ValidationError('Ο κωδικός πρόσβασης δεν είναι έγκυρος.')
    register_secret(value)
    password_validation.validate_password(value, user=user)
    return value


@contextmanager
def credential_context(actor, action):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('accounting.cr011_actor',true),current_setting('accounting.cr011_action',true)")
        before = cursor.fetchone()
        cursor.execute("SELECT set_config('accounting.cr011_actor',%s,true),set_config('accounting.cr011_action',%s,true)", [str(actor.pk), action])
    try:
        yield
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('accounting.cr011_actor',%s,true),set_config('accounting.cr011_action',%s,true)", [before[0] or '', before[1] or ''])


def issue_requirement(office, actor, user, state):
    row = StaffCredentialRequirement.objects.select_for_update().filter(user=user).first()
    if row is not None and row.office_id != office.pk:
        raise PermissionDenied('Ο χρήστης δεν ανήκει στο γραφείο.')
    if row is None:
        row = StaffCredentialRequirement(user=user, office=office, issued_by=actor)
    else:
        row.version += 1
    row.required = True; row.issued_by = actor; row.changed_at = None
    row.security_revision = state.revision; row.password_marker = password_marker(user)
    with credential_context(actor, 'ISSUE'):
        row.save()
    row.refresh_from_db()
    return row


@transaction.atomic
def create_direct_staff(request, *, username, temporary_password, role, owner_password):
    require_installation()
    office = lock_office(request.user, 'staff.manage')
    lock_users(request.user.pk); prove_actor(request, office, owner_password, 'staff.manage')
    owner_not_pending(request.user)
    if role not in ('owner','accountant'):
        raise ValidationError('Επιλέξτε υπεύθυνο ή λογιστή.')
    if not isinstance(username,str) or username != username.strip() or not username or len(username)>150:
        raise ValidationError('Το όνομα χρήστη δεν είναι έγκυρο.')
    username = get_user_model().normalize_username(username)
    lock_identifiers('username:'+username.casefold())
    if get_user_model().objects.filter(username__iexact=username).exists():
        raise ValidationError('Το όνομα χρήστη δεν είναι διαθέσιμο.')
    user = get_user_model()(username=username, email='', is_active=True, is_staff=False, is_superuser=False)
    user.set_password(checked_password(temporary_password,user)); user.full_clean()
    try:
        with transaction.atomic():
            user.save(force_insert=True)
    except IntegrityError:
        raise ValidationError('Το όνομα χρήστη δεν είναι διαθέσιμο.') from None
    create_accountant_profile(user_id=user.pk, office_id=office.pk, role=role)
    state = lock_state(user); state.revision += 1; state.save(update_fields=['revision'])
    issue_requirement(office,request.user,user,state)
    audit(office,request.user,'staff.create',target=user,after=(role,True))
    return user


@transaction.atomic
def reset_staff_password(request, user_id, *, temporary_password, owner_password, version):
    require_installation()
    office = lock_office(request.user,'staff.manage')
    users = lock_users(request.user.pk,user_id)
    prove_actor(request,office,owner_password,'staff.manage')
    owner_not_pending(request.user)
    target = AccountantProfile.objects.select_for_update().filter(user_id=user_id,office=office).first()
    user = users.get(user_id)
    if target is None or user is None or user.is_staff or user.is_superuser:
        raise Http404('Ο χρήστης δεν βρέθηκε.')
    if user.pk == request.user.pk:
        raise ValidationError('Η επαναφορά αφορά άλλον χρήστη του γραφείου.')
    row = StaffCredentialRequirement.objects.select_for_update().filter(user=user).first()
    current = row.version if row else -1
    if type(version) is not int or version != current:
        raise ValidationError('Ο κωδικός άλλαξε στο μεταξύ. Ανοίξτε ξανά τη φόρμα επαναφοράς.')
    user.set_password(checked_password(temporary_password,user)); user.save(update_fields=['password'])
    state = lock_state(user); state.revision += 1; state.save(update_fields=['revision'])
    issue_requirement(office,request.user,user,state)
    audit(office,request.user,'staff.password_reset',target=user,
        before=(target.role,target.is_active),after=(target.role,target.is_active))
    return user


@transaction.atomic
def finish_required_password_change(request, *, current_password, new_password, version):
    require_installation()
    profile = require_office_profile(request.user)
    office = lock_office(request.user,'clients.write')
    user = lock_users(request.user.pk)[request.user.pk]
    state = lock_request_state(request)
    row = StaffCredentialRequirement.objects.select_for_update().filter(user=user,office=office).first()
    if row is None or not row.required or type(version) is not int or version != row.version:
        raise ValidationError('Η αίτηση αλλαγής κωδικού δεν είναι πλέον διαθέσιμη. Συνδεθείτε ξανά.')
    register_secret(current_password)
    if not user.check_password(current_password) or row.password_marker != password_marker(user):
        raise ValidationError('Ο τρέχων προσωρινός κωδικός δεν είναι σωστός.')
    checked_password(new_password,user)
    if user.check_password(new_password):
        raise ValidationError('Ο νέος κωδικός πρέπει να διαφέρει από τον προσωρινό.')
    user.set_password(new_password); user.save(update_fields=['password'])
    state.revision += 1; state.save(update_fields=['revision'])
    row.required=False; row.version += 1; row.security_revision=state.revision; row.password_marker=password_marker(user)
    with credential_context(user,'CHANGE'):
        row.save()
    audit(office,user,'staff.password_change',target=user,
        before=(profile.role,profile.is_active),after=(profile.role,profile.is_active))
    return user,state
