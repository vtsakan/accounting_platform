"""S26 adds job/outbox tables only; no existing rows are rewritten."""
import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion as deletion
import django.utils.timezone as tz

STATES = [('queued', 'Σε αναμονή'), ('running', 'Εκτελείται'), ('retry', 'Αναμονή επανάληψης'),
    ('succeeded', 'Ολοκληρώθηκε'), ('failed', 'Απέτυχε'), ('cancelled', 'Ακυρώθηκε'),
    ('blocked', 'Απαιτείται ενεργή εξουσιοδότηση')]


def fk(to, **kwargs):
    return models.ForeignKey(to=to, on_delete=deletion.PROTECT, **kwargs)


def bigid():
    return models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')


class Migration(migrations.Migration):
    dependencies = [('accounting', '0020_financial_correction_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='BackgroundJob', fields=[
            ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ('office', fk('accounting.office')), ('actor', fk(settings.AUTH_USER_MODEL)), ('entity', fk('accounting.entity')),
            ('kind', models.CharField(max_length=40)), ('key', models.UUIDField(editable=False)),
            ('correlation_id', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
            ('payload', models.JSONField(default=dict, editable=False)), ('payload_digest', models.CharField(max_length=71, editable=False)),
            ('state', models.CharField(choices=STATES, default='queued', max_length=12, verbose_name='Κατάσταση')),
            ('attempts', models.PositiveSmallIntegerField(default=0)), ('max_attempts', models.PositiveSmallIntegerField(default=3)),
            ('dispatch_tries', models.PositiveIntegerField(default=0)),
            ('available_at', models.DateTimeField(default=tz.now)), ('dispatch_after', models.DateTimeField(default=tz.now)),
            ('lease_token', models.UUIDField(null=True, editable=False)), ('lease_until', models.DateTimeField(null=True, editable=False)),
            ('last_code', models.CharField(max_length=40, default='', blank=True)),
            ('created_at', models.DateTimeField(default=tz.now, editable=False)), ('updated_at', models.DateTimeField(default=tz.now)),
            ('finished_at', models.DateTimeField(null=True, editable=False)),
        ], options={'verbose_name': 'Εργασία παρασκηνίου', 'verbose_name_plural': 'Εργασίες παρασκηνίου',
            'indexes': [models.Index(fields=['state', 'dispatch_after'], name='s26_dispatch_due')],
            'constraints': [
                models.UniqueConstraint(fields=['office', 'kind', 'key'], name='s26_job_source_once'),
                models.UniqueConstraint(fields=['id', 'office'], name='s26_job_office'),
                models.UniqueConstraint(fields=['id', 'office', 'entity', 'actor'], name='s26_job_effect_scope'),
                models.CheckConstraint(condition=models.Q(state__in=[x[0] for x in STATES]), name='s26_job_state'),
                models.CheckConstraint(condition=models.Q(attempts__lte=models.F('max_attempts'), max_attempts=3), name='s26_attempt_bounds'),
                models.CheckConstraint(condition=(models.Q(state='running', lease_token__isnull=False, lease_until__isnull=False) |
                    (~models.Q(state='running') & models.Q(lease_token__isnull=True, lease_until__isnull=True))), name='s26_lease_shape'),
                models.CheckConstraint(condition=(models.Q(state__in=['succeeded', 'failed', 'cancelled', 'blocked'], finished_at__isnull=False) |
                    models.Q(state__in=['queued', 'running', 'retry'], finished_at__isnull=True)), name='s26_finish_shape'),
            ]}),
        migrations.CreateModel(name='JobEvent', fields=[
            ('id', bigid()), ('job', fk('accounting.backgroundjob', related_name='events')), ('office', fk('accounting.office')),
            ('state', models.CharField(choices=STATES, max_length=12)), ('code', models.CharField(max_length=40)),
            ('attempt', models.PositiveSmallIntegerField()), ('occurred_at', models.DateTimeField(default=tz.now)),
        ], options={'verbose_name': 'Συμβάν εργασίας', 'verbose_name_plural': 'Συμβάντα εργασιών'}),
        migrations.CreateModel(name='JobProbeEffect', fields=[
            ('job', models.OneToOneField(to='accounting.backgroundjob', primary_key=True, serialize=False, on_delete=deletion.PROTECT)),
            ('office', fk('accounting.office')), ('actor', fk(settings.AUTH_USER_MODEL)), ('entity', fk('accounting.entity')),
            ('value', models.PositiveSmallIntegerField(default=1)), ('occurred_at', models.DateTimeField(default=tz.now)),
        ], options={'verbose_name': 'Αποτέλεσμα δοκιμαστικής εργασίας',
            'constraints': [models.CheckConstraint(condition=models.Q(value=1), name='s26_probe_one')]}),
        migrations.CreateModel(name='BackgroundPulse', fields=[
            ('service', models.CharField(max_length=12, primary_key=True, serialize=False)), ('owner', models.UUIDField()),
            ('last_seen_at', models.DateTimeField(default=tz.now)),
        ], options={'constraints': [models.CheckConstraint(condition=models.Q(service__in=['worker', 'scheduler']), name='s26_pulse_kind')]}),
    ]
