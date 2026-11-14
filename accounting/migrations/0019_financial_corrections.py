"""Add retained correction links; no inferred correction or existing field rewrite."""
from decimal import Decimal
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


def uid():
    return ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False))


def office():
    return ('office', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.office', verbose_name='Λογιστικό γραφείο'))


def fk(to, *, related_name=None, one=False, null=False):
    options = dict(editable=False, on_delete=django.db.models.deletion.PROTECT, to=to)
    if related_name is not None: options['related_name'] = related_name
    if null: options['null'] = True
    return (models.OneToOneField if one else models.ForeignKey)(**options)


def recorded():
    return ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False))


class Migration(migrations.Migration):
    dependencies = [('accounting', '0018_settlement_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='FinanceCorrection', fields=[uid(), office(),
            ('actor', fk(settings.AUTH_USER_MODEL)),
            ('operation', models.CharField(max_length=14, choices=[('CASH', 'Διόρθωση κίνησης'), ('TRANSFER', 'Διόρθωση μεταφοράς'), ('CHARGE', 'Διόρθωση χρέωσης'), ('REFUND', 'Επιστροφή χρημάτων'), ('REFUND_REVERSE', 'Αντιλογισμός επιστροφής'), ('TERMS', 'Αλλαγή συμφωνίας'), ('CLOSE', 'Κλείσιμο περιόδου')])),
            ('source_cash', fk('accounting.transaction', null=True)), ('source_charge', fk('accounting.charge', null=True)),
            ('agreement', fk('accounting.agreement', null=True)), ('cash_command', fk('accounting.financecommand', one=True, null=True, related_name='correction_group')),
            ('effective_date', models.DateField()), ('reason', models.CharField(max_length=500)),
            ('key_digest', models.CharField(max_length=71, editable=False)), ('payload_digest', models.CharField(max_length=71, editable=False)),
            ('expected_cash_count', models.PositiveSmallIntegerField(default=0, editable=False)),
            ('expected_release_count', models.PositiveSmallIntegerField(default=0, editable=False)),
            ('refund_reversal_count', models.PositiveSmallIntegerField(default=0, editable=False)),
            ('has_replacement', models.BooleanField(default=False, editable=False)),
            ('state', models.CharField(max_length=10, default='pending', choices=[('pending', 'Σε καταχώριση'), ('completed', 'Καταχωρισμένη')])),
            recorded(), ('completed_at', models.DateTimeField(null=True, editable=False))],
            options={'verbose_name': 'Ομάδα οικονομικής διόρθωσης', 'verbose_name_plural': 'Ομάδες οικονομικών διορθώσεων'}),
        migrations.CreateModel(name='CorrectionRelease', fields=[uid(), office(),
            ('correction', fk('accounting.financecorrection', related_name='allocation_releases')),
            ('release', fk('accounting.allocationrelease', one=True))],
            options={'verbose_name': 'Αποδέσμευση ομάδας διόρθωσης', 'verbose_name_plural': 'Αποδεσμεύσεις ομάδων διόρθωσης'}),
        migrations.CreateModel(name='CashRefund', fields=[uid(), office(), recorded(),
            ('correction', fk('accounting.financecorrection', one=True, related_name='refund_record')),
            ('source_cash', fk('accounting.transaction', related_name='refunds_as_source')),
            ('entry', fk('accounting.transaction', one=True, related_name='refund_record')),
            ('amount', models.DecimalField(max_digits=12, decimal_places=2)), ('effective_date', models.DateField())],
            options={'verbose_name': 'Επιστροφή πίστωσης ή προκαταβολής', 'verbose_name_plural': 'Επιστροφές πίστωσης ή προκαταβολής'}),
        migrations.CreateModel(name='ChargeReversal', fields=[uid(), office(), recorded(),
            ('correction', fk('accounting.financecorrection', one=True, related_name='charge_reversal')),
            ('charge', fk('accounting.charge', one=True, related_name='reversal_record')), ('effective_date', models.DateField())],
            options={'verbose_name': 'Αντιλογισμός χρέωσης', 'verbose_name_plural': 'Αντιλογισμοί χρεώσεων'}),
        migrations.CreateModel(name='ChargeReplacement', fields=[uid(), office(),
            ('correction', fk('accounting.financecorrection', one=True, related_name='charge_replacement')),
            ('original', fk('accounting.charge', one=True, related_name='replacement_record')),
            ('replacement', fk('accounting.charge', one=True, related_name='replacement_of'))],
            options={'verbose_name': 'Αντικατάσταση χρέωσης', 'verbose_name_plural': 'Αντικαταστάσεις χρεώσεων'}),
        migrations.CreateModel(name='AgreementChange', fields=[uid(), office(),
            ('correction', fk('accounting.financecorrection', one=True, related_name='terms_change')),
            ('agreement', fk('accounting.agreement', related_name='amendments')),
            ('previous_revision', models.PositiveIntegerField(editable=False)),
            ('version', fk('accounting.agreementtermsversion', one=True, related_name='amendment')),
            ('description', models.CharField(max_length=255)), ('amount', models.DecimalField(max_digits=12, decimal_places=2)),
            ('billing_mode', models.CharField(max_length=12, choices=[('ONE_OFF', 'Εφάπαξ'), ('MONTHLY', 'Ανά ημερολογιακό μήνα')])),
            ('lifecycle', models.CharField(max_length=12, choices=[('ACTIVE', 'Ενεργή'), ('ENDED', 'Έληξε'), ('CANCELLED', 'Ακυρωμένη')]))],
            options={'verbose_name': 'Μελλοντική αλλαγή συμφωνίας', 'verbose_name_plural': 'Μελλοντικές αλλαγές συμφωνιών'}),
        migrations.CreateModel(name='FinancePeriodClose', fields=[uid(), office(), recorded(),
            ('correction', fk('accounting.financecorrection', one=True, related_name='period_close')), ('closed_through', models.DateField())],
            options={'verbose_name': 'Κλείσιμο οικονομικής περιόδου', 'verbose_name_plural': 'Κλεισίματα οικονομικών περιόδων'}),
        migrations.AddConstraint(model_name='financecorrection', constraint=models.UniqueConstraint(fields=['office', 'operation', 'key_digest'], name='s24_correction_key')),
        migrations.AddConstraint(model_name='financecorrection', constraint=models.UniqueConstraint(fields=['id', 'office'], name='s24_correction_office')),
        migrations.AddConstraint(model_name='financecorrection', constraint=models.CheckConstraint(condition=models.Q(state__in=['pending', 'completed']), name='s24_correction_state')),
        migrations.AddConstraint(model_name='financecorrection', constraint=models.CheckConstraint(condition=models.Q(expected_cash_count__lte=102, expected_release_count__lte=1000, refund_reversal_count__lte=100), name='s24_correction_counts')),
        migrations.AddConstraint(model_name='cashrefund', constraint=models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=Decimal('9999999999.99')), name='s24_refund_positive')),
        migrations.AddConstraint(model_name='financeperiodclose', constraint=models.UniqueConstraint(fields=['office', 'closed_through'], name='s24_period_office_day')),
        migrations.AlterField(model_name='financecommand', name='operation', field=models.CharField(max_length=30, choices=[('cash.post', 'Καταχώρηση'), ('cash.transfer', 'Μεταφορά'), ('cash.reverse', 'Αντιλογισμός'), ('cash.correct', 'Αντιλογισμός και αντικατάσταση'), ('transfer.reverse', 'Αντιλογισμός μεταφοράς'), ('transfer.correct', 'Αντικατάσταση μεταφοράς'), ('cash.refund', 'Επιστροφή χρημάτων'), ('refund.reverse', 'Αντιλογισμός επιστροφής')])),
        migrations.AlterField(model_name='transaction', name='posting_kind', field=models.CharField(max_length=12, default='LEGACY', editable=False, verbose_name='Είδος καταχώρισης', choices=[('LEGACY', 'Αρχική/διαχειριστική εγγραφή'), ('ORDINARY', 'Κανονική κίνηση'), ('TRANSFER', 'Εσωτερική μεταφορά'), ('REVERSAL', 'Αντιλογισμός'), ('REFUND', 'Επιστροφή χρημάτων')])),
        migrations.RemoveConstraint(model_name='transaction', name='s18_reversal_reference'),
        migrations.AddConstraint(model_name='transaction', constraint=models.CheckConstraint(condition=models.Q(posting_kind='REVERSAL', reversal_of__isnull=False) | models.Q(posting_kind__in=['LEGACY', 'ORDINARY', 'TRANSFER', 'REFUND'], reversal_of__isnull=True), name='s18_reversal_reference')),
    ]
