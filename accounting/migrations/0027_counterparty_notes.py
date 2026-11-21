"""New note records only; existing tables and financial history are retained."""
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('accounting', '0026_fee_generation_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='CounterpartyNote', fields=[
        ('id', models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False, serialize=False)),
        ('actor_label', models.CharField(max_length=150, editable=False, verbose_name='Όνομα λογιστή κατά την καταχώριση')),
        ('request_key', models.UUIDField(editable=False)),
        ('body', models.TextField(max_length=5000, verbose_name='Σημείωση')),
        ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False, verbose_name='Καταχωρίστηκε')),
        ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, editable=False,
            to=settings.AUTH_USER_MODEL, verbose_name='Λογιστής')),
        ('entity', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, editable=False,
            related_name='journal_notes', to='accounting.entity', verbose_name='Συναλλασσόμενος')),
        ('office', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, editable=False,
            to='accounting.office', verbose_name='Λογιστικό γραφείο')),
    ], options={
        'ordering': ['-created_at', '-id'], 'verbose_name': 'Σημείωση συναλλασσομένου',
        'verbose_name_plural': 'Σημειώσεις συναλλασσομένων',
        'constraints': [models.UniqueConstraint(fields=['office', 'request_key'], name='cr004_note_request'),
            models.CheckConstraint(condition=~models.Q(body__regex=r'^\s*$'), name='cr004_note_nonempty')],
        'indexes': [models.Index(fields=['office', 'entity', '-created_at', '-id'], name='cr004_note_entity_time')],
    })]
