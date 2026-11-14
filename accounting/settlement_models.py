"""S23 immutable allocation/release events; cash and charges remain originals."""
from decimal import Decimal
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from .ownership import OfficeOwned
from .charge_models import RetainedRecord


class SettlementCommand(OfficeOwned):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_cash = models.ForeignKey('accounting.Transaction', on_delete=models.PROTECT, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    operation = models.CharField(max_length=8, choices=[('ALLOCATE', 'Αντιστοίχιση'), ('RELEASE', 'Αποδέσμευση')])
    effective_date = models.DateField()
    reason = models.CharField(max_length=500)
    key_digest = models.CharField(max_length=71, editable=False)
    payload_digest = models.CharField(max_length=71, editable=False)
    expected_count = models.PositiveSmallIntegerField(editable=False)
    state = models.CharField(max_length=10, default='pending', choices=[('pending', 'Σε καταχώριση'), ('completed', 'Καταχωρισμένη')])
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        verbose_name = 'Ενέργεια αντιστοίχισης'
        verbose_name_plural = 'Ενέργειες αντιστοίχισης'
        constraints = [models.UniqueConstraint(fields=['office', 'operation', 'key_digest'], name='s23_command_key'),
                       models.UniqueConstraint(fields=['id', 'office'], name='s23_command_id_office'),
                       models.UniqueConstraint(fields=['id', 'office', 'source_cash'], name='s23_command_id_source'),
                       models.CheckConstraint(condition=models.Q(expected_count__gte=1, expected_count__lte=100), name='s23_command_count'),
                       models.CheckConstraint(condition=models.Q(state__in=['pending', 'completed']), name='s23_command_state')]


class CashAllocation(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    command = models.ForeignKey(SettlementCommand, on_delete=models.PROTECT, related_name='allocations', editable=False)
    source_cash = models.ForeignKey('accounting.Transaction', on_delete=models.PROTECT, related_name='cash_allocations', editable=False)
    charge = models.ForeignKey('accounting.Charge', on_delete=models.PROTECT, related_name='cash_allocations', editable=False)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['effective_date', 'recorded_at', 'id']
        verbose_name = 'Αντιστοίχιση πληρωμής'
        verbose_name_plural = 'Αντιστοιχίσεις πληρωμών'
        constraints = [models.UniqueConstraint(fields=['id', 'office'], name='s23_allocation_id_office'),
                       models.UniqueConstraint(fields=['command', 'charge'], name='s23_command_charge'),
                       models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=Decimal('9999999999.99')), name='s23_allocation_positive')]


class AllocationRelease(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    command = models.ForeignKey(SettlementCommand, on_delete=models.PROTECT, related_name='releases', editable=False)
    allocation = models.OneToOneField(CashAllocation, on_delete=models.PROTECT, related_name='release_record', editable=False)
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Αποδέσμευση αντιστοίχισης'
        verbose_name_plural = 'Αποδεσμεύσεις αντιστοιχίσεων'
