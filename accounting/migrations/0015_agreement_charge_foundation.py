"""Additive S22 schema. No legacy obligation or settlement is inferred."""
from decimal import Decimal
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('accounting', '0014_cash_workspace_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='AgreementTermsVersion', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('revision', models.PositiveIntegerField(editable=False)),
            ('billing_mode', models.CharField(choices=[('UNREVIEWED', 'Σε αναμονή επιλογής'), ('ONE_OFF', 'Εφάπαξ'), ('MONTHLY', 'Ανά ημερολογιακό μήνα')], default='UNREVIEWED', max_length=12)),
            ('lifecycle', models.CharField(choices=[('UNREVIEWED', 'Σε αναμονή ελέγχου'), ('DRAFT', 'Πρόχειρη'), ('ACTIVE', 'Ενεργή'), ('ENDED', 'Έληξε'), ('CANCELLED', 'Ακυρωμένη')], default='UNREVIEWED', max_length=12)),
            ('direction', models.CharField(choices=[('RECEIVABLE', 'Εισπρακτέα'), ('PAYABLE', 'Πληρωτέα')], max_length=10)),
            ('description', models.CharField(max_length=255)),
            ('agreed_amount', models.DecimalField(decimal_places=2, max_digits=12)),
            ('start_date', models.DateField()), ('effective_date', models.DateField()),
            ('origin', models.CharField(choices=[('legacy', 'Απογραφή'), ('user', 'Λογιστής'), ('database', 'Διαχειριστική εγγραφή')], max_length=12)),
            ('reason', models.CharField(max_length=500)),
            ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('actor', models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('agreement', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='terms_versions', to='accounting.agreement')),
            ('entity', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.entity')),
            ('office', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.office', verbose_name='Λογιστικό γραφείο')),
        ], options={'ordering': ['-revision'], 'verbose_name': 'Έκδοση όρων συμφωνίας', 'verbose_name_plural': 'Εκδόσεις όρων συμφωνιών'}),
        migrations.CreateModel(name='Charge', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('direction', models.CharField(choices=[('RECEIVABLE', 'Εισπρακτέα'), ('PAYABLE', 'Πληρωτέα')], max_length=10)),
            ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
            ('currency', models.CharField(default='EUR', editable=False, max_length=3)),
            ('effective_date', models.DateField()), ('due_date', models.DateField()), ('period', models.DateField(editable=False, null=True)),
            ('source_key', models.CharField(editable=False, max_length=120)),
            ('key_digest', models.CharField(editable=False, max_length=71)), ('payload_digest', models.CharField(editable=False, max_length=71)),
            ('description', models.CharField(max_length=255)), ('reason', models.CharField(max_length=500)),
            ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('actor', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('agreement', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='charges', to='accounting.agreement')),
            ('entity', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.entity')),
            ('terms', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.agreementtermsversion')),
            ('office', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.office', verbose_name='Λογιστικό γραφείο')),
        ], options={'ordering': ['-effective_date', '-recorded_at'], 'verbose_name': 'Χρέωση', 'verbose_name_plural': 'Χρεώσεις'}),
        migrations.AddConstraint(model_name='agreementtermsversion', constraint=models.UniqueConstraint(fields=('agreement', 'revision'), name='s22_terms_revision')),
        migrations.AddConstraint(model_name='agreementtermsversion', constraint=models.UniqueConstraint(fields=('id', 'office', 'agreement'), name='s22_terms_id_office_agreement')),
        migrations.AddConstraint(model_name='charge', constraint=models.UniqueConstraint(fields=('office', 'source_key'), name='s22_charge_source')),
        migrations.AddConstraint(model_name='charge', constraint=models.UniqueConstraint(fields=('office', 'key_digest'), name='s22_charge_request')),
        migrations.AddConstraint(model_name='charge', constraint=models.UniqueConstraint(fields=('id', 'office'), name='s22_charge_id_office')),
        migrations.AddConstraint(model_name='charge', constraint=models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=Decimal('9999999999.99')), name='s22_charge_positive')),
        migrations.AddConstraint(model_name='charge', constraint=models.CheckConstraint(condition=models.Q(currency='EUR'), name='s22_charge_eur')),
    ]
