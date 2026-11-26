"""Add subjects and an unfinished state; preserve every historical value."""
import uuid
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):
    dependencies = [('accounting', '0036_attachment_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='counterpartynote', name='subject', field=models.CharField(max_length=200, blank=True, default='', verbose_name='Θέμα')),
        migrations.AddField(model_name='clienttask', name='subject', field=models.CharField(max_length=200, blank=True, default='', verbose_name='Θέμα')),
        migrations.RemoveConstraint(model_name='clienttask', name='cr006_task_status'),
        migrations.RemoveConstraint(model_name='clienttask', name='cr006_task_completion'),
        migrations.AlterField(model_name='clienttask', name='status', field=models.CharField(max_length=4, choices=[('OPEN', 'Ανοιχτή'), ('DONE', 'Ολοκληρωμένη'), ('WAIT', 'Σε εκκρεμότητα')], default='OPEN', editable=False)),
        migrations.AddConstraint(model_name='clienttask', constraint=models.CheckConstraint(condition=models.Q(status__in=['OPEN', 'WAIT', 'DONE']), name='cr006_task_status')),
        migrations.AddConstraint(model_name='clienttask', constraint=models.CheckConstraint(condition=(models.Q(status__in=['OPEN', 'WAIT'], completed_at__isnull=True, completed_by__isnull=True) | models.Q(status='DONE', completed_at__isnull=False, completed_by__isnull=False)), name='cr006_task_completion')),
        migrations.AlterField(model_name='clienttaskactivity', name='action', field=models.CharField(max_length=8, choices=[('NOTE', 'Σημείωση'), ('CREATE', 'Δημιουργία εργασίας'), ('UPDATE', 'Αλλαγή εργασίας'), ('COMPLETE', 'Ολοκλήρωση εργασίας'), ('REOPEN', 'Εκ νέου άνοιγμα'), ('PENDING', 'Σε εκκρεμότητα'), ('RESUME', 'Συνέχιση εργασίας')], editable=False)),
        migrations.CreateModel(name='AgreementCreationReceipt', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('request_key', models.UUIDField(editable=False)),
            ('agreement', models.OneToOneField('accounting.agreement', on_delete=models.PROTECT, editable=False)),
            ('actor', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)),
            ('payload_sha256', models.CharField(max_length=71, editable=False)),
            ('created_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('office', models.ForeignKey('accounting.office', on_delete=models.PROTECT, editable=False, verbose_name='Λογιστικό γραφείο')),
        ], options={'constraints': [models.UniqueConstraint(fields=['office', 'request_key'], name='cr010_agreement_request')]}),
        migrations.CreateModel(name='CounterpartyImport', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('actor', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)),
            ('source_sha256', models.CharField(max_length=71, editable=False)),
            ('salt', models.BinaryField(editable=False)), ('payload', models.BinaryField(editable=False)),
            ('state', models.CharField(max_length=9, default='PREVIEW', editable=False)),
            ('created_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('expires_at', models.DateTimeField(editable=False)),
            ('completed_at', models.DateTimeField(null=True, editable=False)),
            ('decisions_sha256', models.CharField(max_length=71, blank=True, default='', editable=False)),
            ('outcome', models.JSONField(default=dict, editable=False)),
            ('office', models.ForeignKey('accounting.office', on_delete=models.PROTECT, editable=False, verbose_name='Λογιστικό γραφείο')),
        ], options={'constraints': [models.CheckConstraint(condition=models.Q(state__in=['PREVIEW', 'DONE', 'CANCELLED']), name='cr010_import_state')],
            'indexes': [models.Index(fields=['office', 'actor', 'state', 'expires_at'], name='cr010_import_expiry')]}),
    ]
