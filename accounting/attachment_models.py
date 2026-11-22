"""Classified, sealed client files and immutable actor-attributed actions."""
import uuid

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower,Replace
from django.utils import timezone

from .ownership import OfficeOwned

MAX_FILE_BYTES=25_000_000
FILE_TYPES={'pdf':'application/pdf','doc':'application/msword',
    'docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','gif':'image/gif',
    'webp':'image/webp','tif':'image/tiff','tiff':'image/tiff','bmp':'image/bmp'}


class AttachmentCategory(OfficeOwned):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)
    name=models.CharField(max_length=80,verbose_name='Χαρακτηρισμός')
    is_active=models.BooleanField(default=True,verbose_name='Ενεργός χαρακτηρισμός')
    record_version=models.PositiveIntegerField(default=0,editable=False)
    updated_at=models.DateTimeField(default=timezone.now,editable=False)

    def __str__(self):return self.name

    class Meta:
        ordering=['name','id']
        verbose_name='Χαρακτηρισμός συνημμένων'
        verbose_name_plural='Χαρακτηρισμοί συνημμένων'
        constraints=[models.UniqueConstraint(Replace(Lower('name'),models.Value('ς'),models.Value('σ')),models.F('office'),name='cr008_category_name'),
            models.UniqueConstraint(fields=['id','office'],name='cr008_category_pair')]


class ClientAttachment(OfficeOwned):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)
    entity=models.ForeignKey('accounting.Entity',on_delete=models.PROTECT,related_name='client_attachments',editable=False)
    category=models.ForeignKey(AttachmentCategory,on_delete=models.PROTECT,null=True,related_name='attachments',verbose_name='Χαρακτηρισμός')
    description=models.TextField(max_length=1000,blank=True,verbose_name='Περιγραφή')
    original_name=models.CharField(max_length=180,editable=False)
    content_type=models.CharField(max_length=100,editable=False)
    content_sha256=models.CharField(max_length=64,editable=False)
    byte_size=models.PositiveIntegerField(editable=False)
    salt=models.BinaryField(editable=False)
    nonce=models.BinaryField(editable=False)
    payload=models.BinaryField(editable=False)
    uploaded_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,editable=False)
    uploader_label=models.CharField(max_length=150,editable=False)
    scan_engine=models.CharField(max_length=120,editable=False)
    scanned_at=models.DateTimeField(default=timezone.now,editable=False)
    request_key=models.UUIDField(editable=False)
    request_digest=models.CharField(max_length=64,editable=False)
    record_version=models.PositiveIntegerField(default=0,editable=False)
    purged=models.BooleanField(default=False,editable=False)
    created_at=models.DateTimeField(default=timezone.now,editable=False)
    updated_at=models.DateTimeField(default=timezone.now,editable=False)

    class Meta:
        ordering=['-created_at','-id']
        verbose_name='Συνημμένο καρτέλας'
        verbose_name_plural='Συνημμένα καρτελών'
        constraints=[models.UniqueConstraint(fields=['office','request_key'],name='cr008_upload_request'),
            models.UniqueConstraint(fields=['id','office'],name='cr008_attachment_pair')]
        indexes=[models.Index(fields=['office','entity','-created_at','-id'],name='cr008_attachment_card')]


class AttachmentEvent(OfficeOwned):
    id=models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)
    entity=models.ForeignKey('accounting.Entity',on_delete=models.PROTECT,null=True,editable=False)
    attachment=models.ForeignKey(ClientAttachment,on_delete=models.PROTECT,null=True,editable=False,related_name='events')
    category=models.ForeignKey(AttachmentCategory,on_delete=models.PROTECT,null=True,editable=False)
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,editable=False)
    actor_label=models.CharField(max_length=150,editable=False)
    action=models.CharField(max_length=20,editable=False)
    occurred_at=models.DateTimeField(default=timezone.now,editable=False)

    class Meta:
        ordering=['-occurred_at','-id']
        verbose_name='Ενέργεια συνημμένου'
        verbose_name_plural='Ενέργειες συνημμένων'
