"""Private classified attachments; no backfill or financial changes."""
import uuid
from django.conf import settings
from django.db import migrations,models
from django.db.models.functions import Lower,Replace
from django.utils import timezone

class Migration(migrations.Migration):
    dependencies=[('accounting','0034_entity_profile_guards'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.CreateModel(name='AttachmentCategory',fields=[
            ('id',models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('name',models.CharField(max_length=80, verbose_name='Χαρακτηρισμός')),
            ('is_active',models.BooleanField(default=True, verbose_name='Ενεργός χαρακτηρισμός')),
            ('record_version',models.PositiveIntegerField(default=0, editable=False)),
            ('updated_at',models.DateTimeField(default=timezone.now, editable=False)),
            ('office',models.ForeignKey('accounting.office',on_delete=models.PROTECT,editable=False,verbose_name='Λογιστικό γραφείο')),
        ],options={
            'ordering':['name', 'id'],
            'verbose_name':'Χαρακτηρισμός συνημμένων',
            'verbose_name_plural':'Χαρακτηρισμοί συνημμένων',
            'constraints':[models.UniqueConstraint(Replace(Lower('name'),models.Value('ς'),models.Value('σ')), models.F('office'), name='cr008_category_name'), models.UniqueConstraint(fields=['id', 'office'], name='cr008_category_pair')],
        }),
        migrations.CreateModel(name='ClientAttachment',fields=[
            ('id',models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('entity',models.ForeignKey('accounting.entity', on_delete=models.PROTECT, related_name='client_attachments', editable=False)),
            ('category',models.ForeignKey('accounting.attachmentcategory', on_delete=models.PROTECT, null=True, related_name='attachments', verbose_name='Χαρακτηρισμός')),
            ('description',models.TextField(max_length=1000, blank=True, verbose_name='Περιγραφή')),
            ('original_name',models.CharField(max_length=180, editable=False)),
            ('content_type',models.CharField(max_length=100, editable=False)),
            ('content_sha256',models.CharField(max_length=64, editable=False)),
            ('byte_size',models.PositiveIntegerField(editable=False)),
            ('salt',models.BinaryField(editable=False)),
            ('nonce',models.BinaryField(editable=False)),
            ('payload',models.BinaryField(editable=False)),
            ('uploaded_by',models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)),
            ('uploader_label',models.CharField(max_length=150, editable=False)),
            ('scan_engine',models.CharField(max_length=120, editable=False)),
            ('scanned_at',models.DateTimeField(default=timezone.now, editable=False)),
            ('request_key',models.UUIDField(editable=False)),
            ('request_digest',models.CharField(max_length=64, editable=False)),
            ('record_version',models.PositiveIntegerField(default=0, editable=False)),
            ('purged',models.BooleanField(default=False, editable=False)),
            ('created_at',models.DateTimeField(default=timezone.now, editable=False)),
            ('updated_at',models.DateTimeField(default=timezone.now, editable=False)),
            ('office',models.ForeignKey('accounting.office',on_delete=models.PROTECT,editable=False,verbose_name='Λογιστικό γραφείο')),
        ],options={
            'ordering':['-created_at', '-id'],
            'verbose_name':'Συνημμένο καρτέλας',
            'verbose_name_plural':'Συνημμένα καρτελών',
            'constraints':[models.UniqueConstraint(fields=['office', 'request_key'], name='cr008_upload_request'), models.UniqueConstraint(fields=['id', 'office'], name='cr008_attachment_pair')],
            'indexes':[models.Index(fields=['office', 'entity', '-created_at', '-id'], name='cr008_attachment_card')],
        }),
        migrations.CreateModel(name='AttachmentEvent',fields=[
            ('id',models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('entity',models.ForeignKey('accounting.entity', on_delete=models.PROTECT, null=True, editable=False)),
            ('attachment',models.ForeignKey('accounting.clientattachment', on_delete=models.PROTECT, null=True, editable=False, related_name='events')),
            ('category',models.ForeignKey('accounting.attachmentcategory', on_delete=models.PROTECT, null=True, editable=False)),
            ('actor',models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)),
            ('actor_label',models.CharField(max_length=150, editable=False)),
            ('action',models.CharField(max_length=20, editable=False)),
            ('occurred_at',models.DateTimeField(default=timezone.now, editable=False)),
            ('office',models.ForeignKey('accounting.office',on_delete=models.PROTECT,editable=False,verbose_name='Λογιστικό γραφείο')),
        ],options={
            'ordering':['-occurred_at', '-id'],
            'verbose_name':'Ενέργεια συνημμένου',
            'verbose_name_plural':'Ενέργειες συνημμένων',
        }),
    ]
