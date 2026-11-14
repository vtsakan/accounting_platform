"""S22 agreement snapshots and obligations, separate from the cash ledger."""
from decimal import Decimal
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from .ownership import OfficeOwned

IMMUTABLE = 'Η καταχωρισμένη χρέωση και οι εγκεκριμένοι όροι διατηρούνται. Η διόρθωση απαιτεί συνδεδεμένο ιστορικό.'
BILLING = [('UNREVIEWED', 'Σε αναμονή επιλογής'), ('ONE_OFF', 'Εφάπαξ'), ('MONTHLY', 'Ανά ημερολογιακό μήνα')]
LIFECYCLE = [('UNREVIEWED', 'Σε αναμονή ελέγχου'), ('DRAFT', 'Πρόχειρη'), ('ACTIVE', 'Ενεργή'), ('ENDED', 'Έληξε'), ('CANCELLED', 'Ακυρωμένη')]
DIRECTION = [('RECEIVABLE', 'Εισπρακτέα'), ('PAYABLE', 'Πληρωτέα')]


class RetainedRecord(OfficeOwned):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError(IMMUTABLE)
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(IMMUTABLE)


class AgreementTermsVersion(RetainedRecord):
    agreement = models.ForeignKey('accounting.Agreement', on_delete=models.PROTECT, related_name='terms_versions', editable=False)
    entity = models.ForeignKey('accounting.Entity', on_delete=models.PROTECT, editable=False)
    revision = models.PositiveIntegerField(editable=False)
    billing_mode = models.CharField(max_length=12, choices=BILLING, default='UNREVIEWED')
    lifecycle = models.CharField(max_length=12, choices=LIFECYCLE, default='UNREVIEWED')
    direction = models.CharField(max_length=10, choices=DIRECTION)
    description = models.CharField(max_length=255)
    agreed_amount = models.DecimalField(max_digits=12, decimal_places=2)
    start_date = models.DateField()
    effective_date = models.DateField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, editable=False)
    origin = models.CharField(max_length=12, choices=[('legacy', 'Απογραφή'), ('user', 'Λογιστής'), ('database', 'Διαχειριστική εγγραφή')])
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-revision']
        verbose_name = 'Έκδοση όρων συμφωνίας'
        verbose_name_plural = 'Εκδόσεις όρων συμφωνιών'
        constraints = [models.UniqueConstraint(fields=['agreement', 'revision'], name='s22_terms_revision'),
                       models.UniqueConstraint(fields=['id', 'office', 'agreement'], name='s22_terms_id_office_agreement')]


class Charge(RetainedRecord):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agreement = models.ForeignKey('accounting.Agreement', on_delete=models.PROTECT, related_name='charges', editable=False)
    terms = models.ForeignKey(AgreementTermsVersion, on_delete=models.PROTECT, editable=False)
    entity = models.ForeignKey('accounting.Entity', on_delete=models.PROTECT, editable=False)
    direction = models.CharField(max_length=10, choices=DIRECTION)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='EUR', editable=False)
    effective_date = models.DateField()
    due_date = models.DateField()
    period = models.DateField(null=True, editable=False)
    source_key = models.CharField(max_length=120, editable=False)
    key_digest = models.CharField(max_length=71, editable=False)
    payload_digest = models.CharField(max_length=71, editable=False)
    description = models.CharField(max_length=255)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-effective_date', '-recorded_at']
        verbose_name = 'Χρέωση'
        verbose_name_plural = 'Χρεώσεις'
        constraints = [models.UniqueConstraint(fields=['office', 'source_key'], name='s22_charge_source'),
                       models.UniqueConstraint(fields=['office', 'key_digest'], name='s22_charge_request'),
                       models.UniqueConstraint(fields=['id', 'office'], name='s22_charge_id_office'),
                       models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=Decimal('9999999999.99')), name='s22_charge_positive'),
                       models.CheckConstraint(condition=models.Q(currency='EUR'), name='s22_charge_eur')]
