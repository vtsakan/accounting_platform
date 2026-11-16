"""S26 durable job/outbox state; Redis is never the business ledger."""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


class JobState(models.TextChoices):
    QUEUED = 'queued', 'Σε αναμονή'
    RUNNING = 'running', 'Εκτελείται'
    RETRY = 'retry', 'Αναμονή επανάληψης'
    SUCCEEDED = 'succeeded', 'Ολοκληρώθηκε'
    FAILED = 'failed', 'Απέτυχε'
    CANCELLED = 'cancelled', 'Ακυρώθηκε'
    BLOCKED = 'blocked', 'Απαιτείται ενεργή εξουσιοδότηση'


class BackgroundJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    office = models.ForeignKey('accounting.Office', on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    entity = models.ForeignKey('accounting.Entity', on_delete=models.PROTECT)
    kind = models.CharField(max_length=40)
    key = models.UUIDField(editable=False)
    correlation_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payload = models.JSONField(default=dict, editable=False)
    payload_digest = models.CharField(max_length=71, editable=False)
    state = models.CharField(max_length=12, choices=JobState.choices, default=JobState.QUEUED, verbose_name='Κατάσταση')
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    dispatch_tries = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    dispatch_after = models.DateTimeField(default=timezone.now)
    lease_token = models.UUIDField(null=True, editable=False)
    lease_until = models.DateTimeField(null=True, editable=False)
    last_code = models.CharField(max_length=40, default='', blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        verbose_name = 'Εργασία παρασκηνίου'
        verbose_name_plural = 'Εργασίες παρασκηνίου'
        constraints = [
            models.UniqueConstraint(fields=['office', 'kind', 'key'], name='s26_job_source_once'),
            models.UniqueConstraint(fields=['id', 'office'], name='s26_job_office'),
            models.UniqueConstraint(fields=['id', 'office', 'entity', 'actor'], name='s26_job_effect_scope'),
            models.CheckConstraint(condition=models.Q(state__in=JobState.values), name='s26_job_state'),
            models.CheckConstraint(condition=models.Q(attempts__lte=models.F('max_attempts'), max_attempts=3), name='s26_attempt_bounds'),
            models.CheckConstraint(condition=(models.Q(state='running', lease_token__isnull=False, lease_until__isnull=False) |
                (~models.Q(state='running') & models.Q(lease_token__isnull=True, lease_until__isnull=True))), name='s26_lease_shape'),
            models.CheckConstraint(condition=(models.Q(state__in=['succeeded', 'failed', 'cancelled', 'blocked'], finished_at__isnull=False) |
                models.Q(state__in=['queued', 'running', 'retry'], finished_at__isnull=True)), name='s26_finish_shape'),
        ]
        indexes = [models.Index(fields=['state', 'dispatch_after'], name='s26_dispatch_due')]
class JobEvent(models.Model):
    job = models.ForeignKey(BackgroundJob, on_delete=models.PROTECT, related_name='events')
    office = models.ForeignKey('accounting.Office', on_delete=models.PROTECT)
    state = models.CharField(max_length=12, choices=JobState.choices)
    code = models.CharField(max_length=40)
    attempt = models.PositiveSmallIntegerField()
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Συμβάν εργασίας'
        verbose_name_plural = 'Συμβάντα εργασιών'


class JobProbeEffect(models.Model):
    """One inert DB effect, never a charge, cash entry or client edit."""
    job = models.OneToOneField(BackgroundJob, primary_key=True, on_delete=models.PROTECT)
    office = models.ForeignKey('accounting.Office', on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    entity = models.ForeignKey('accounting.Entity', on_delete=models.PROTECT)
    value = models.PositiveSmallIntegerField(default=1)
    occurred_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Αποτέλεσμα δοκιμαστικής εργασίας'
        constraints = [models.CheckConstraint(condition=models.Q(value=1), name='s26_probe_one')]


class BackgroundPulse(models.Model):
    service = models.CharField(max_length=12, primary_key=True)
    owner = models.UUIDField()
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(service__in=['worker', 'scheduler']), name='s26_pulse_kind')]
