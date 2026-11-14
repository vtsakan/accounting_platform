"""S24 retained correction groups, refunds, term versions and period cutoffs."""
from decimal import Decimal
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone
from .ownership import OfficeOwned
from .charge_models import RetainedRecord

OPERATIONS = [('CASH', 'Διόρθωση κίνησης'), ('TRANSFER', 'Διόρθωση μεταφοράς'), ('CHARGE', 'Διόρθωση χρέωσης'),
              ('REFUND', 'Επιστροφή χρημάτων'), ('REFUND_REVERSE', 'Αντιλογισμός επιστροφής'),
              ('TERMS', 'Αλλαγή συμφωνίας'), ('CLOSE', 'Κλείσιμο περιόδου')]


class FinanceCorrection(OfficeOwned):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    operation = models.CharField(max_length=14, choices=OPERATIONS)
    source_cash = models.ForeignKey('accounting.Transaction', on_delete=models.PROTECT, null=True, editable=False)
    source_charge = models.ForeignKey('accounting.Charge', on_delete=models.PROTECT, null=True, editable=False)
    agreement = models.ForeignKey('accounting.Agreement', on_delete=models.PROTECT, null=True, editable=False)
    cash_command = models.OneToOneField('accounting.FinanceCommand', on_delete=models.PROTECT, null=True, editable=False, related_name='correction_group')
    effective_date = models.DateField()
    reason = models.CharField(max_length=500)
    key_digest = models.CharField(max_length=71, editable=False)
    payload_digest = models.CharField(max_length=71, editable=False)
    expected_cash_count = models.PositiveSmallIntegerField(default=0, editable=False)
    expected_release_count = models.PositiveSmallIntegerField(default=0, editable=False)
    refund_reversal_count = models.PositiveSmallIntegerField(default=0, editable=False)
    has_replacement = models.BooleanField(default=False, editable=False)
    state = models.CharField(max_length=10, default='pending', choices=[('pending', 'Σε καταχώριση'), ('completed', 'Καταχωρισμένη')])
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        verbose_name = 'Ομάδα οικονομικής διόρθωσης'
        verbose_name_plural = 'Ομάδες οικονομικών διορθώσεων'
        constraints = [models.UniqueConstraint(fields=['office', 'operation', 'key_digest'], name='s24_correction_key'),
                       models.UniqueConstraint(fields=['id', 'office'], name='s24_correction_office'),
                       models.CheckConstraint(condition=models.Q(state__in=['pending', 'completed']), name='s24_correction_state'),
                       models.CheckConstraint(condition=models.Q(expected_cash_count__lte=102, expected_release_count__lte=1000, refund_reversal_count__lte=100), name='s24_correction_counts')]


class CorrectionRelease(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correction = models.ForeignKey(FinanceCorrection, on_delete=models.PROTECT, related_name='allocation_releases', editable=False)
    release = models.OneToOneField('accounting.AllocationRelease', on_delete=models.PROTECT, editable=False)

    class Meta:
        verbose_name = 'Αποδέσμευση ομάδας διόρθωσης'
        verbose_name_plural = 'Αποδεσμεύσεις ομάδων διόρθωσης'


class CashRefund(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correction = models.OneToOneField(FinanceCorrection, on_delete=models.PROTECT, related_name='refund_record', editable=False)
    source_cash = models.ForeignKey('accounting.Transaction', on_delete=models.PROTECT, related_name='refunds_as_source', editable=False)
    entry = models.OneToOneField('accounting.Transaction', on_delete=models.PROTECT, related_name='refund_record', editable=False)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Επιστροφή πίστωσης ή προκαταβολής'
        verbose_name_plural = 'Επιστροφές πίστωσης ή προκαταβολής'
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=Decimal('9999999999.99')), name='s24_refund_positive')]


class ChargeReversal(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correction = models.OneToOneField(FinanceCorrection, on_delete=models.PROTECT, related_name='charge_reversal', editable=False)
    charge = models.OneToOneField('accounting.Charge', on_delete=models.PROTECT, related_name='reversal_record', editable=False)
    effective_date = models.DateField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Αντιλογισμός χρέωσης'
        verbose_name_plural = 'Αντιλογισμοί χρεώσεων'


class ChargeReplacement(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correction = models.OneToOneField(FinanceCorrection, on_delete=models.PROTECT, related_name='charge_replacement', editable=False)
    original = models.OneToOneField('accounting.Charge', on_delete=models.PROTECT, related_name='replacement_record', editable=False)
    replacement = models.OneToOneField('accounting.Charge', on_delete=models.PROTECT, related_name='replacement_of', editable=False)

    class Meta:
        verbose_name = 'Αντικατάσταση χρέωσης'
        verbose_name_plural = 'Αντικαταστάσεις χρεώσεων'


class AgreementChange(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correction = models.OneToOneField(FinanceCorrection, on_delete=models.PROTECT, related_name='terms_change', editable=False)
    agreement = models.ForeignKey('accounting.Agreement', on_delete=models.PROTECT, related_name='amendments', editable=False)
    previous_revision = models.PositiveIntegerField(editable=False)
    version = models.OneToOneField('accounting.AgreementTermsVersion', on_delete=models.PROTECT, related_name='amendment', editable=False)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    billing_mode = models.CharField(max_length=12, choices=[('ONE_OFF', 'Εφάπαξ'), ('MONTHLY', 'Ανά ημερολογιακό μήνα')])
    lifecycle = models.CharField(max_length=12, choices=[('ACTIVE', 'Ενεργή'), ('ENDED', 'Έληξε'), ('CANCELLED', 'Ακυρωμένη')])

    class Meta:
        verbose_name = 'Μελλοντική αλλαγή συμφωνίας'
        verbose_name_plural = 'Μελλοντικές αλλαγές συμφωνιών'


class FinancePeriodClose(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correction = models.OneToOneField(FinanceCorrection, on_delete=models.PROTECT, related_name='period_close', editable=False)
    closed_through = models.DateField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = 'Κλείσιμο οικονομικής περιόδου'
        verbose_name_plural = 'Κλεισίματα οικονομικών περιόδων'
        constraints = [models.UniqueConstraint(fields=['office', 'closed_through'], name='s24_period_office_day')]
