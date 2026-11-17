"""S28 explicit automation consent and durable per-delivery reconciliation."""
from django.conf import settings
from django.db import models
from django.utils import timezone
from .charge_models import RetainedRecord
from .ownership import OfficeOwned

OUTCOMES = [('pending','Σε αναμονή'),('generated','Δημιουργήθηκε χρέωση'),
    ('existing','Η πηγή έχει ήδη καταχωριστεί'),('outside','Εκτός ενεργού προγράμματος'),
    ('blocked','Μη ενεργός πελάτης ή όροι'),('review','Απαιτείται έλεγχος'),
    ('closed','Κλεισμένη περίοδος'),('future','Δεν έφτασε η έναρξη'),
    ('superseded','Η εξουσιοδότηση άλλαξε'),('paused','Η αυτόματη εκτέλεση είναι ανενεργή')]


class FeeAutomationVersion(RetainedRecord):
    schedule = models.ForeignKey('accounting.FeeSchedule', on_delete=models.PROTECT, related_name='automations')
    revision = models.PositiveIntegerField()
    enabled = models.BooleanField(default=False)
    first_period = models.DateField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-revision']
        verbose_name = 'Έκδοση εξουσιοδότησης αυτόματης χρέωσης'
        constraints = [models.UniqueConstraint(fields=['schedule','revision'], name='s28_automation_revision')]


class FeeGenerationRun(OfficeOwned):
    job = models.OneToOneField('accounting.BackgroundJob', primary_key=True, on_delete=models.PROTECT, related_name='fee_run')
    schedule = models.ForeignKey('accounting.FeeSchedule', on_delete=models.PROTECT, related_name='generation_runs')
    period = models.DateField()
    automation = models.ForeignKey(FeeAutomationVersion, null=True, blank=True, on_delete=models.PROTECT, related_name='runs')
    source_key = models.CharField(max_length=120)
    outcome = models.CharField(max_length=12, choices=OUTCOMES, default='pending')
    charge = models.ForeignKey('accounting.Charge', null=True, blank=True, on_delete=models.PROTECT)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Αποτέλεσμα μηνιαίας δημιουργίας χρέωσης'
        constraints = [models.UniqueConstraint(fields=['automation','period'], name='s28_auto_period_once'),
            models.CheckConstraint(condition=models.Q(outcome__in=[v[0] for v in OUTCOMES]), name='s28_run_outcome'),
            models.CheckConstraint(condition=(models.Q(outcome__in=['generated','existing'],charge__isnull=False) |
                (~models.Q(outcome__in=['generated','existing']) & models.Q(charge__isnull=True))), name='s28_run_charge_shape')]
