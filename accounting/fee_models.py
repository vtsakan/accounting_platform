"""S27 retained catalogue quotes and monthly plan history; no posting scheduler."""
import uuid
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils import timezone
from .charge_models import RetainedRecord


class ServiceItem(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Υπηρεσία τιμοκαταλόγου'
        verbose_name_plural = 'Υπηρεσίες τιμοκαταλόγου'
        constraints = [models.UniqueConstraint(fields=['office', 'code'], name='s27_service_code')]


class ServicePrice(RetainedRecord):
    service = models.ForeignKey(ServiceItem, on_delete=models.PROTECT, related_name='prices')
    revision = models.PositiveIntegerField()
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_date = models.DateField()
    is_active = models.BooleanField(default=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-revision']
        verbose_name = 'Έκδοση τιμής υπηρεσίας'
        verbose_name_plural = 'Εκδόσεις τιμών υπηρεσιών'
        constraints = [models.UniqueConstraint(fields=['service', 'revision'], name='s27_price_revision'),
            models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=Decimal('9999999999.99')), name='s27_price_positive')]


class FeeSchedule(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agreement = models.OneToOneField('accounting.Agreement', on_delete=models.PROTECT, related_name='fee_schedule')
    start_period = models.DateField()
    first_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Μηνιαίο πρόγραμμα αμοιβής'
        verbose_name_plural = 'Μηνιαία προγράμματα αμοιβών'
        constraints = [models.CheckConstraint(condition=models.Q(first_amount__isnull=True) |
            models.Q(first_amount__gt=0, first_amount__lte=Decimal('9999999999.99')), name='s27_first_amount_positive')]


class FeeScheduleVersion(RetainedRecord):
    schedule = models.ForeignKey(FeeSchedule, on_delete=models.PROTECT, related_name='versions')
    revision = models.PositiveIntegerField()
    effective_period = models.DateField()
    end_period = models.DateField(null=True, blank=True)
    due_day = models.PositiveSmallIntegerField()
    due_next_month = models.BooleanField(default=False)
    cancelled = models.BooleanField(default=False)
    terms_snapshot = models.ForeignKey('accounting.AgreementTermsVersion', on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-revision']
        verbose_name = 'Έκδοση μηνιαίου προγράμματος'
        verbose_name_plural = 'Εκδόσεις μηνιαίου προγράμματος'
        constraints = [models.UniqueConstraint(fields=['schedule', 'revision'], name='s27_schedule_revision'),
            models.UniqueConstraint(fields=['schedule', 'effective_period'], name='s27_schedule_effective'),
            models.CheckConstraint(condition=models.Q(due_day__gte=1, due_day__lte=28), name='s27_due_day'),
            models.CheckConstraint(condition=models.Q(end_period__isnull=True) | models.Q(end_period__gte=models.F('effective_period')), name='s27_end_period')]
