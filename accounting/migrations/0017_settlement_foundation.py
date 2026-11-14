"""Add allocation commands/events without rewriting cash, charges or people."""
from decimal import Decimal
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('accounting', '0016_agreement_charge_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='SettlementCommand', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('operation', models.CharField(choices=[('ALLOCATE', 'Αντιστοίχιση'), ('RELEASE', 'Αποδέσμευση')], max_length=8)),
            ('effective_date', models.DateField()), ('reason', models.CharField(max_length=500)),
            ('key_digest', models.CharField(editable=False, max_length=71)), ('payload_digest', models.CharField(editable=False, max_length=71)),
            ('expected_count', models.PositiveSmallIntegerField(editable=False)),
            ('state', models.CharField(choices=[('pending', 'Σε καταχώριση'), ('completed', 'Καταχωρισμένη')], default='pending', max_length=10)),
            ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('completed_at', models.DateTimeField(editable=False, null=True)),
            ('actor', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ('source_cash', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.transaction')),
            ('office', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.office', verbose_name='Λογιστικό γραφείο')),
        ], options={'verbose_name': 'Ενέργεια αντιστοίχισης', 'verbose_name_plural': 'Ενέργειες αντιστοίχισης'}),
        migrations.CreateModel(name='CashAllocation', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('amount', models.DecimalField(decimal_places=2, max_digits=12)), ('effective_date', models.DateField()),
            ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('command', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='allocations', to='accounting.settlementcommand')),
            ('source_cash', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='cash_allocations', to='accounting.transaction')),
            ('charge', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='cash_allocations', to='accounting.charge')),
            ('office', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.office', verbose_name='Λογιστικό γραφείο')),
        ], options={'ordering': ['effective_date', 'recorded_at', 'id'], 'verbose_name': 'Αντιστοίχιση πληρωμής', 'verbose_name_plural': 'Αντιστοιχίσεις πληρωμών'}),
        migrations.CreateModel(name='AllocationRelease', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('effective_date', models.DateField()), ('recorded_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('command', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='releases', to='accounting.settlementcommand')),
            ('allocation', models.OneToOneField(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='release_record', to='accounting.cashallocation')),
            ('office', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, to='accounting.office', verbose_name='Λογιστικό γραφείο')),
        ], options={'verbose_name': 'Αποδέσμευση αντιστοίχισης', 'verbose_name_plural': 'Αποδεσμεύσεις αντιστοιχίσεων'}),
        migrations.AddConstraint(model_name='settlementcommand', constraint=models.UniqueConstraint(fields=('office', 'operation', 'key_digest'), name='s23_command_key')),
        migrations.AddConstraint(model_name='settlementcommand', constraint=models.UniqueConstraint(fields=('id', 'office'), name='s23_command_id_office')),
        migrations.AddConstraint(model_name='settlementcommand', constraint=models.UniqueConstraint(fields=('id', 'office', 'source_cash'), name='s23_command_id_source')),
        migrations.AddConstraint(model_name='settlementcommand', constraint=models.CheckConstraint(condition=models.Q(expected_count__gte=1, expected_count__lte=100), name='s23_command_count')),
        migrations.AddConstraint(model_name='settlementcommand', constraint=models.CheckConstraint(condition=models.Q(state__in=['pending', 'completed']), name='s23_command_state')),
        migrations.AddConstraint(model_name='cashallocation', constraint=models.UniqueConstraint(fields=('id', 'office'), name='s23_allocation_id_office')),
        migrations.AddConstraint(model_name='cashallocation', constraint=models.UniqueConstraint(fields=('command', 'charge'), name='s23_command_charge')),
        migrations.AddConstraint(model_name='cashallocation', constraint=models.CheckConstraint(condition=models.Q(amount__gt=0, amount__lte=Decimal('9999999999.99')), name='s23_allocation_positive')),
    ]
