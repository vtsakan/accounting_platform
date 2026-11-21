"""Manual client tasks and append-only command/activity records; no backfill."""
import uuid
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

class Migration(migrations.Migration):
    dependencies = [('accounting','0030_counterparty_retirement_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='ClientTask', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('entity', models.ForeignKey('accounting.entity', on_delete=models.PROTECT, related_name='work_tasks', editable=False)),
            ('source_note', models.OneToOneField('accounting.counterpartynote', on_delete=models.PROTECT, related_name='work_task', editable=False)),
            ('creator', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_client_tasks', editable=False)),
            ('creator_label', models.CharField(max_length=150, editable=False)),
            ('assignee', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_client_tasks', verbose_name='Ανάθεση σε')),
            ('assignee_label', models.CharField(max_length=150, editable=False)),
            ('body', models.TextField(max_length=5000, verbose_name='Περιγραφή εργασίας')),
            ('due_date', models.DateField(verbose_name='Ημερομηνία λήξης')),
            ('status', models.CharField(max_length=4, choices=[('OPEN', 'Ανοιχτή'), ('DONE', 'Ολοκληρωμένη')], default='OPEN', editable=False)),
            ('version', models.PositiveBigIntegerField(default=0, editable=False)),
            ('created_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('updated_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('completed_at', models.DateTimeField(null=True, editable=False)),
            ('completed_by', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='completed_client_tasks', editable=False)),
            ('office', models.ForeignKey('accounting.office', on_delete=models.PROTECT, editable=False, verbose_name='Λογιστικό γραφείο')),
        ], options={
            'ordering': ['due_date', 'created_at', 'id'],
            'verbose_name': 'Εργασία πελάτη',
            'verbose_name_plural': 'Εργασίες πελατών',
            'constraints': [models.CheckConstraint(condition=models.Q(status__in=['OPEN', 'DONE']), name='cr006_task_status'), models.CheckConstraint(condition=~models.Q(body__regex='^\\s*$'), name='cr006_task_nonempty'), models.CheckConstraint(condition=models.Q(status='OPEN', completed_at__isnull=True, completed_by__isnull=True) | models.Q(status='DONE', completed_at__isnull=False, completed_by__isnull=False), name='cr006_task_completion')],
            'indexes': [models.Index(fields=['office', 'assignee', 'status', 'due_date'], name='cr006_task_assigned_due'), models.Index(fields=['office', 'entity', 'status', 'due_date'], name='cr006_task_client_due')],
        }),
        migrations.CreateModel(name='ClientTaskActivity', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('task', models.ForeignKey('accounting.clienttask', on_delete=models.PROTECT, null=True, related_name='activities', editable=False)),
            ('note', models.ForeignKey('accounting.counterpartynote', on_delete=models.PROTECT, related_name='task_activities', editable=False)),
            ('request_key', models.UUIDField(editable=False)),
            ('payload_sha256', models.CharField(max_length=71, editable=False)),
            ('actor', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)),
            ('actor_label', models.CharField(max_length=150, editable=False)),
            ('action', models.CharField(max_length=8, choices=[('NOTE', 'Σημείωση'), ('CREATE', 'Δημιουργία εργασίας'), ('UPDATE', 'Αλλαγή εργασίας'), ('COMPLETE', 'Ολοκλήρωση εργασίας'), ('REOPEN', 'Εκ νέου άνοιγμα')], editable=False)),
            ('task_version', models.PositiveBigIntegerField(null=True, editable=False)),
            ('before', models.JSONField(default=dict, editable=False)),
            ('after', models.JSONField(default=dict, editable=False)),
            ('created_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('office', models.ForeignKey('accounting.office', on_delete=models.PROTECT, editable=False, verbose_name='Λογιστικό γραφείο')),
        ], options={
            'ordering': ['created_at', 'id'],
            'verbose_name': 'Ενέργεια εργασίας',
            'verbose_name_plural': 'Ιστορικό εργασιών',
            'constraints': [models.UniqueConstraint(fields=['office', 'request_key'], name='cr006_activity_request'), models.UniqueConstraint(fields=['task', 'task_version'], condition=models.Q(task__isnull=False), name='cr006_activity_version')],
            'indexes': [models.Index(fields=['office', 'task', 'created_at'], name='cr006_activity_task_time')],
        }),
    ]
