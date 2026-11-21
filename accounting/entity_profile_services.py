"""Atomic versioned profile writes; no plaintext credentials in models or audit."""
from contextlib import contextmanager

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, connection, transaction
from django.http import Http404
from django.views.decorators.debug import sensitive_variables

from core.taxis_crypto import open_sealed, seal
from .capabilities import require_capability
from .counterparty_services import FIELDS, ARCHIVED, actor_scope, locked_record, save_counterparty
from .entity_profile_models import CONTACT_FIELDS, FLAG_LABELS
from .entity_profile_selectors import profile_installed
from .entity_profile_validation import profile_values
from .finance_services import audit_context
from .models import EntityProfile, EntityProfileEvent, TaxisCredential
from .office_access import locked_office, record
from .models import Entity

PROFILE_FIELDS = ('contact_status','person_kind','main_amka','spouse_enabled','spouse_first_name','spouse_last_name',
    'spouse_vat_number','spouse_tax_office','spouse_amka','spouse_person_kind','spouse_inherit_contacts',
    *['spouse_'+name for name in CONTACT_FIELDS], *FLAG_LABELS, 'tags','internal_notes')


@contextmanager
def profile_context(user, action):
    with audit_context(user, 'Ενημέρωση στοιχείων καρτέλας'):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_setting('accounting.cr007_action',true)")
            previous = cursor.fetchone()[0]
            cursor.execute("SELECT set_config('accounting.cr007_action',%s,true)", [action])
        try: yield
        except DatabaseError:
            if connection.in_atomic_block: connection.set_rollback(True)
            raise
        finally:
            if not connection.needs_rollback:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('accounting.cr007_action',%s,true)", [previous or ''])


def audit(entity, user, action, fields):
    return EntityProfileEvent.objects.create(office_id=entity.office_id, entity=entity, actor=user,
        actor_label='', action=action, changed_fields=sorted(set(fields)), record_version=entity.record_version)


@sensitive_variables('__ALL__')
def validate_credentials(values):
    result = {}
    for subject in ('main','spouse'):
        username, password = values.get(subject+'_taxis_username',''), values.get(subject+'_taxis_password','')
        clear = values.get(subject+'_taxis_clear',False)
        if not isinstance(username,str) or not isinstance(password,str) or type(clear) is not bool:
            raise ValidationError('Ελέγξτε την ενέργεια ενημέρωσης κωδικών.')
        if (bool(username) != bool(password)) or (clear and (username or password)):
            raise ValidationError({subject+'_taxis_password':'Συμπληρώστε και τους δύο κωδικούς ή επιλέξτε μόνο αφαίρεση.'})
        if len(username)>200 or len(password)>512 or any(ord(c)<32 for c in username+password):
            raise ValidationError({subject+'_taxis_password':'Ελέγξτε το μήκος και τους χαρακτήρες των κωδικών.'})
        result[subject.upper()] = (username,password,clear)
    return result


@sensitive_variables('__ALL__')
def write_credentials(entity, user, values, profile):
    changes = validate_credentials(values)
    for subject, (username,password,clear) in changes.items():
        if not (username or clear): continue
        require_capability(user, 'clients.credentials')
        existing = TaxisCredential.objects.select_for_update().filter(office_id=entity.office_id, entity=entity, subject=subject).first()
        if username and subject=='SPOUSE' and not profile.spouse_enabled:
            raise ValidationError({'spouse_enabled':'Ενεργοποιήστε πρώτα την ενότητα συζύγου.'})
        if clear:
            if existing:
                TaxisCredential.objects.filter(pk=existing.pk,office_id=entity.office_id).delete()
        elif username:
            salt, sealed_username, sealed_password = seal(entity.office_id,entity.pk,subject,username,password)
            row = existing or TaxisCredential(office_id=entity.office_id,entity=entity,subject=subject)
            row.salt,row.sealed_username,row.sealed_password = salt,sealed_username,sealed_password
            row.save()


@transaction.atomic
@sensitive_variables('__ALL__')
def save_profile(user, core_values, values, credential_values, *, key=None, version=0):
    office = actor_scope(user)
    if not profile_installed(): raise ValidationError('Η αναβάθμιση του προφίλ δεν είναι ακόμη διαθέσιμη.')
    existing = locked_record(office,key,version) if key is not None else None
    if existing and existing.is_archived: raise ValidationError(ARCHIVED)
    cleaned = profile_values(values)
    commands = validate_credentials(credential_values)
    if any(username or clear for username,_,clear in commands.values()):
        require_capability(user,'clients.credentials')
    old_profile = EntityProfile.objects.select_for_update().filter(office=office,entity=existing).first() if existing else None
    if existing:
        identity_changed = existing.vat_number != core_values['vat_number']
        spouse_changed = old_profile and (old_profile.spouse_vat_number != cleaned['spouse_vat_number'] or old_profile.spouse_enabled != cleaned['spouse_enabled'])
        for subject, changed in (('MAIN',identity_changed),('SPOUSE',spouse_changed)):
            if changed and TaxisCredential.objects.filter(office=office,entity=existing,subject=subject).exists():
                username,_,clear = commands[subject]
                if not (username or clear):
                    raise ValidationError('Με την αλλαγή φορολογικής ταυτότητας απαιτείται αντικατάσταση ή αφαίρεση των συνδεδεμένων κωδικών TaxisNet.')
    core_values = dict(core_values)
    core_values['legal_kind'] = 'BUSINESS' if cleaned['person_kind'] in {'SOLE_TRADER','LEGAL_ENTITY'} else 'INDIVIDUAL'
    with profile_context(user,'EDIT'):
        entity = save_counterparty(user,{name:core_values[name] for name in FIELDS},key=key,version=version)
        profile = old_profile or EntityProfile(office=office,entity=entity)
        changed = [name for name in PROFILE_FIELDS if getattr(profile,name)!=cleaned[name]]
        for name in PROFILE_FIELDS: setattr(profile,name,cleaned[name])
        profile.record_version=entity.record_version
        profile.save()
        write_credentials(entity,user,credential_values,profile)
    return entity


@transaction.atomic
@sensitive_variables('__ALL__')
def reveal_credentials(user, key, subject):
    office = locked_office(user,'clients.credentials')
    if subject not in {'MAIN','SPOUSE'}: raise Http404('Η επιλογή κωδικών δεν βρέθηκε.')
    entity = record(Entity,user,key)
    entity = Entity.objects.select_for_update().get(pk=entity.pk,office=office)
    if entity.is_archived: raise ValidationError(ARCHIVED)
    row = TaxisCredential.objects.filter(office=office,entity=entity,subject=subject).first()
    if row is None: raise ValidationError('Δεν έχουν αποθηκευτεί κωδικοί για αυτή την επιλογή.')
    with profile_context(user,'REVEAL'):
        result = open_sealed(row)
        audit(entity,user,'REVEAL',[subject])
    return result


def purge_profile(entity,user):
    """Called only inside the retained owner deletion transaction before its marker."""
    if not profile_installed(): return
    require_capability(user,'clients.delete')
    with profile_context(user,'PURGE'):
        TaxisCredential.objects.filter(office_id=entity.office_id,entity=entity).delete()
        profile = EntityProfile.objects.filter(office_id=entity.office_id,entity=entity).first()
        if profile:
            defaults = EntityProfile(office_id=entity.office_id,entity=entity)
            for name in PROFILE_FIELDS: setattr(profile,name,getattr(defaults,name))
            profile.contact_status='INACTIVE'; profile.record_version=entity.record_version
            profile.save()
