"""Atomic, replay-safe uploads and owner removals; sealed bytes join DB backups."""
from contextlib import contextmanager
import hashlib
import json
import uuid

from django.core.exceptions import ValidationError
from django.db import IntegrityError,connection,transaction
from django.http import Http404
from django.views.decorators.debug import sensitive_variables

from core.attachment_crypto import seal,unseal
from .attachment_models import AttachmentCategory,ClientAttachment,AttachmentEvent
from .attachment_selectors import attachments_installed
from .attachment_validation import label,upload_bytes,inspect_content,scan_content
from .capabilities import require_capability
from .counterparty_services import ARCHIVED,STALE
from .models import Entity
from .office_access import locked_office,record


@contextmanager
def attachment_context(user,action):
    names=('accounting.cr008_actor','accounting.cr008_action')
    with connection.cursor() as cursor:
        previous=[]
        for name in names:
            cursor.execute('SELECT current_setting(%s,true)',[name]);previous.append(cursor.fetchone()[0] or '')
        for name,value in zip(names,(str(user.pk),action)):cursor.execute('SELECT set_config(%s,%s,true)',[name,value])
    try:yield
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                for name,value in zip(names,previous):cursor.execute('SELECT set_config(%s,%s,true)',[name,value])


def ready():
    if not attachments_installed():raise ValidationError('Η ενότητα συνημμένων δεν είναι ακόμη διαθέσιμη.')


def key(value):
    try:return uuid.UUID(str(value))
    except (ValueError,TypeError,AttributeError):raise ValidationError('Ανοίξτε ξανά τη φόρμα και επαναλάβετε.') from None


def person_locked(user,entity_id,capability):
    office=locked_office(user,capability)
    from .counterparty_retirement_selectors import visible_counterparties
    try:return office,visible_counterparties(Entity.objects.select_for_update()).get(pk=entity_id,office=office)
    except (Entity.DoesNotExist,ValueError,TypeError):raise Http404('Η καρτέλα δεν βρέθηκε.') from None


def attachment_locked(office,entity,file_id):
    try:return ClientAttachment.objects.select_for_update().get(pk=file_id,office=office,entity=entity,purged=False)
    except (ClientAttachment.DoesNotExist,ValueError,TypeError,ValidationError):raise Http404('Το συνημμένο δεν βρέθηκε.') from None


def selected_category(office,category_id,*,previous=None):
    try:row=AttachmentCategory.objects.select_for_update().get(pk=category_id,office=office)
    except (AttachmentCategory.DoesNotExist,ValueError,TypeError,ValidationError):
        raise ValidationError({'category':'Επιλέξτε χαρακτηρισμό του γραφείου.'}) from None
    if not row.is_active and row.pk!=previous:raise ValidationError({'category':'Ο χαρακτηρισμός δεν είναι πλέον ενεργός.'})
    return row


@transaction.atomic
def save_category(user,*,name,is_active=True,category_id=None,version=0):
    ready();office=locked_office(user,'office.settings');name=label(name,'name',80)
    if type(version) is not int or type(is_active) is not bool:raise ValidationError(STALE)
    if category_id is None:row=AttachmentCategory(office=office,name=name,is_active=is_active)
    else:
        try:row=AttachmentCategory.objects.select_for_update().get(pk=category_id,office=office)
        except (AttachmentCategory.DoesNotExist,ValueError,TypeError):raise Http404('Ο χαρακτηρισμός δεν βρέθηκε.') from None
        if row.record_version!=version:raise ValidationError(STALE)
        row.name=name;row.is_active=is_active;row.record_version+=1
    try:
        with transaction.atomic(),attachment_context(user,'CATEGORY'):
            row.save();row.refresh_from_db()
    except IntegrityError as error:
        if getattr(getattr(error.__cause__,'diag',None),'constraint_name',None)=='cr008_category_name':
            raise ValidationError({'name':'Υπάρχει ήδη αυτός ο χαρακτηρισμός στο γραφείο.'}) from None
        raise
    return row


def request_hash(user,entity,category,description,name,digest):
    return hashlib.sha256(json.dumps([str(user.pk),str(entity),str(category),description,name,digest],
        ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def replay(office,request_key,digest):
    existing=ClientAttachment.objects.filter(office=office,request_key=request_key).defer('payload','salt','nonce').first()
    if existing is not None and existing.request_digest!=digest:
        raise ValidationError('Η υποβολή έχει χρησιμοποιηθεί για διαφορετικό αρχείο. Ανοίξτε νέα φόρμα.')
    return existing


@sensitive_variables('__ALL__')
def upload_attachment(user,entity_id,*,category_id,description,upload,request_key):
    ready();require_capability(user,'clients.write');record(Entity,user,entity_id)
    category_id=key(category_id);request_key=key(request_key)
    description=label(description,'description',1000,required=False)
    name,extension,payload,digest=upload_bytes(upload)
    identity=request_hash(user,entity_id,category_id,description,name,digest)
    with transaction.atomic():
        office,entity=person_locked(user,entity_id,'clients.write')
        previous=replay(office,request_key,identity)
        if previous:return previous,True
        if entity.is_archived:raise ValidationError(ARCHIVED)
        selected_category(office,category_id)
    # Potentially slow validation/antivirus never holds the office writer lock.
    scanner=scan_content(payload);mime=inspect_content(extension,payload)
    file_id=uuid.uuid4();salt,nonce,ciphertext=seal(office.pk,entity.pk,file_id,digest,mime,payload)
    with transaction.atomic():
        office,entity=person_locked(user,entity_id,'clients.write')
        previous=replay(office,request_key,identity)
        if previous:return previous,True
        if entity.is_archived:raise ValidationError(ARCHIVED)
        category=selected_category(office,category_id)
        with attachment_context(user,'UPLOAD'):
            row=ClientAttachment.objects.create(id=file_id,office=office,entity=entity,category=category,
                description=description,original_name=name,content_type=mime,content_sha256=digest,byte_size=len(payload),
                salt=salt,nonce=nonce,payload=ciphertext,uploaded_by=user,uploader_label='',scan_engine=scanner,
                request_key=request_key,request_digest=identity)
            row.refresh_from_db()
    return row,False


@transaction.atomic
def edit_attachment(user,entity_id,file_id,*,category_id,description,version):
    ready();office,entity=person_locked(user,entity_id,'clients.write')
    if entity.is_archived:raise ValidationError(ARCHIVED)
    row=attachment_locked(office,entity,file_id)
    if type(version) is not int or row.record_version!=version:raise ValidationError(STALE)
    row.category=selected_category(office,category_id,previous=row.category_id)
    row.description=label(description,'description',1000,required=False);row.record_version+=1
    with attachment_context(user,'EDIT'):row.save(update_fields=['category','description','record_version','updated_at'])
    return row


def purge_row(user,row):
    row.category=None;row.description='';row.original_name='';row.content_type='';row.content_sha256='';row.byte_size=0
    row.salt=b'';row.nonce=b'';row.payload=b'';row.scan_engine='';row.purged=True;row.record_version+=1
    row.save()


@transaction.atomic
def remove_attachment(user,entity_id,file_id,*,version,confirmed):
    ready();office,entity=person_locked(user,entity_id,'clients.delete')
    row=attachment_locked(office,entity,file_id)
    if confirmed is not True or type(version) is not int or row.record_version!=version:raise ValidationError(STALE)
    with attachment_context(user,'REMOVE'):purge_row(user,row)
    return row


def purge_client_attachments(entity,user):
    if not attachments_installed():return
    require_capability(user,'clients.delete')
    with attachment_context(user,'PURGE'):
        for row in ClientAttachment.objects.select_for_update().filter(office_id=entity.office_id,entity=entity,purged=False):
            purge_row(user,row)


@transaction.atomic
@sensitive_variables('__ALL__')
def download_attachment(user,entity_id,file_id):
    ready();office,entity=person_locked(user,entity_id,'clients.read')
    row=attachment_locked(office,entity,file_id)
    payload=unseal(row)
    if len(payload)!=row.byte_size or hashlib.sha256(payload).hexdigest()!=row.content_sha256:
        raise ValidationError('Δεν επιβεβαιώθηκε η ακεραιότητα του συνημμένου.')
    with attachment_context(user,'DOWNLOAD'):
        AttachmentEvent.objects.create(office=office,entity=entity,attachment=row,actor=user,
            actor_label='',action='DOWNLOAD')
    return row,payload
