"""Manual office tasks linked to retained notes, with append-only activity."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .ownership import OfficeOwned


class ClientTask(OfficeOwned):
    class Status(models.TextChoices):
        OPEN = 'OPEN', 'Ανοιχτή'
        DONE = 'DONE', 'Ολοκληρωμένη'
        PENDING = 'WAIT', 'Σε εκκρεμότητα'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity = models.ForeignKey('accounting.Entity', on_delete=models.PROTECT, related_name='work_tasks', editable=False)
    source_note = models.OneToOneField('accounting.CounterpartyNote', on_delete=models.PROTECT, related_name='work_task', editable=False)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_client_tasks', editable=False)
    creator_label = models.CharField(max_length=150, editable=False)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='assigned_client_tasks', verbose_name='Ανάθεση σε')
    assignee_label = models.CharField(max_length=150, editable=False)
    subject = models.CharField(max_length=200, blank=True, default='', verbose_name='Θέμα')
    body = models.TextField(max_length=5000, verbose_name='Περιγραφή εργασίας')
    due_date = models.DateField(verbose_name='Ημερομηνία λήξης')
    status = models.CharField(max_length=4, choices=Status.choices, default=Status.OPEN, editable=False)
    version = models.PositiveBigIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_at = models.DateTimeField(null=True, editable=False)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name='completed_client_tasks', editable=False)

    def delete(self, *args, **kwargs):
        raise ValidationError('Η εργασία διατηρείται στο ιστορικό. Επιλέξτε ολοκλήρωση.')

    class Meta:
        ordering = ['due_date', 'created_at', 'id']
        verbose_name = 'Εργασία πελάτη'
        verbose_name_plural = 'Εργασίες πελατών'
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=['OPEN', 'WAIT', 'DONE']), name='cr006_task_status'),
            models.CheckConstraint(condition=~models.Q(body__regex=r'^\s*$'), name='cr006_task_nonempty'),
            models.CheckConstraint(condition=(models.Q(status__in=['OPEN', 'WAIT'], completed_at__isnull=True, completed_by__isnull=True) |
                models.Q(status='DONE', completed_at__isnull=False, completed_by__isnull=False)), name='cr006_task_completion'),
        ]
        indexes = [models.Index(fields=['office', 'assignee', 'status', 'due_date'], name='cr006_task_assigned_due'),
            models.Index(fields=['office', 'entity', 'status', 'due_date'], name='cr006_task_client_due')]


class ClientTaskActivity(OfficeOwned):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(ClientTask, on_delete=models.PROTECT, null=True, related_name='activities', editable=False)
    note = models.ForeignKey('accounting.CounterpartyNote', on_delete=models.PROTECT, related_name='task_activities', editable=False)
    request_key = models.UUIDField(editable=False)
    payload_sha256 = models.CharField(max_length=71, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    actor_label = models.CharField(max_length=150, editable=False)
    action = models.CharField(max_length=8, choices=[('NOTE', 'Σημείωση'), ('CREATE', 'Δημιουργία εργασίας'),
        ('UPDATE', 'Αλλαγή εργασίας'), ('COMPLETE', 'Ολοκλήρωση εργασίας'), ('REOPEN', 'Εκ νέου άνοιγμα'), ('PENDING', 'Σε εκκρεμότητα'), ('RESUME', 'Συνέχιση εργασίας')], editable=False)
    task_version = models.PositiveBigIntegerField(null=True, editable=False)
    before = models.JSONField(default=dict, editable=False)
    after = models.JSONField(default=dict, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Το ιστορικό εργασίας διατηρείται χωρίς αλλαγές.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Το ιστορικό εργασίας διατηρείται χωρίς διαγραφή.')

    class Meta:
        ordering = ['created_at', 'id']
        verbose_name = 'Ενέργεια εργασίας'
        verbose_name_plural = 'Ιστορικό εργασιών'
        constraints = [models.UniqueConstraint(fields=['office', 'request_key'], name='cr006_activity_request'),
            models.UniqueConstraint(fields=['task', 'task_version'], condition=models.Q(task__isnull=False), name='cr006_activity_version')]
        indexes = [models.Index(fields=['office', 'task', 'created_at'], name='cr006_activity_task_time')]
