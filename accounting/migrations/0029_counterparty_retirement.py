"""Retained nonfinancial deletion markers; existing client/finance rows stay exact."""
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('accounting', '0028_counterparty_note_guards'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='CounterpartyDeletion', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('actor_label', models.CharField(max_length=150, editable=False)),
            ('confirmed_version', models.PositiveBigIntegerField(editable=False)),
            ('contact_digest', models.CharField(max_length=71, editable=False)),
            ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
            ('actor', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT, editable=False)),
            ('entity', models.OneToOneField(to='accounting.entity', on_delete=django.db.models.deletion.PROTECT,
                related_name='deletion_record', editable=False)),
            ('office', models.ForeignKey(to='accounting.office', on_delete=django.db.models.deletion.PROTECT,
                editable=False, verbose_name='Λογιστικό γραφείο')),
        ], options={'verbose_name': 'Ίχνος διαγραφής συναλλασσομένου',
            'verbose_name_plural': 'Ίχνη διαγραφής συναλλασσομένων'}),
        migrations.AlterField(model_name='counterpartyevent', name='action',
            field=models.CharField(max_length=10, verbose_name='Ενέργεια', choices=[
                ('create','Δημιουργία'),('update','Ενημέρωση'),('archive','Αρχειοθέτηση'),
                ('restore','Επαναφορά'),('delete','Διαγραφή')])),
        migrations.RemoveConstraint(model_name='counterpartyevent', name='counterparty_valid_event'),
        migrations.AddConstraint(model_name='counterpartyevent', constraint=models.CheckConstraint(
            condition=models.Q(action__in=['create','update','archive','restore','delete']), name='counterparty_valid_event')),
    ]
