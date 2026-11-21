"""Fiscal profile tables only; no backfill or financial posting."""
import uuid
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

class Migration(migrations.Migration):
    dependencies = [('accounting','0032_client_task_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='EntityProfile', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('entity', models.OneToOneField('accounting.entity', on_delete=models.PROTECT, related_name='fiscal_profile', editable=False)),
            ('contact_status', models.CharField(max_length=8, choices=[('ACTIVE', 'Ενεργός'), ('INACTIVE', 'Ανενεργός')], default='ACTIVE')),
            ('person_kind', models.CharField(max_length=20, choices=[('UNREVIEWED', 'Χρειάζεται εξειδίκευση'), ('INDIVIDUAL', 'Φυσικό Πρόσωπο'), ('FISHER', 'ΦΠ Αλιείς'), ('SOLE_TRADER', 'Ατομική Επιχείρηση ή Επαγγελματίας'), ('FARMER_NORMAL', 'ΦΠ Αγρότης Κανονικού Καθεστώτος'), ('FARMER_SPECIAL', 'ΦΠ Αγρότης Ειδικού Καθεστώτος'), ('LEGAL_ENTITY', 'Νομικό Πρόσωπο')], default='UNREVIEWED')),
            ('main_amka', models.CharField(max_length=11, blank=True, default='')),
            ('spouse_enabled', models.BooleanField(default=False)),
            ('spouse_first_name', models.CharField(max_length=100, blank=True, default='')),
            ('spouse_last_name', models.CharField(max_length=100, blank=True, default='')),
            ('spouse_vat_number', models.CharField(max_length=9, blank=True, default='')),
            ('spouse_tax_office', models.CharField(max_length=100, blank=True, default='')),
            ('spouse_amka', models.CharField(max_length=11, blank=True, default='')),
            ('spouse_person_kind', models.CharField(max_length=20, choices=[('UNREVIEWED', 'Χρειάζεται εξειδίκευση'), ('INDIVIDUAL', 'Φυσικό Πρόσωπο'), ('FISHER', 'ΦΠ Αλιείς'), ('SOLE_TRADER', 'Ατομική Επιχείρηση ή Επαγγελματίας'), ('FARMER_NORMAL', 'ΦΠ Αγρότης Κανονικού Καθεστώτος'), ('FARMER_SPECIAL', 'ΦΠ Αγρότης Ειδικού Καθεστώτος'), ('LEGAL_ENTITY', 'Νομικό Πρόσωπο')], default='UNREVIEWED')),
            ('spouse_inherit_contacts', models.BooleanField(default=True)),
            ('spouse_address', models.CharField(max_length=255, blank=True, default='')),
            ('spouse_city', models.CharField(max_length=100, blank=True, default='')),
            ('spouse_postal_code', models.CharField(max_length=10, blank=True, default='')),
            ('spouse_phone_number', models.CharField(max_length=20, blank=True, default='')),
            ('spouse_email', models.EmailField(blank=True, default='')),
            ('liable_a21', models.BooleanField(default=False)),
            ('prefilled_return', models.BooleanField(default=False)),
            ('disability', models.BooleanField(default=False)),
            ('rent_subsidy', models.BooleanField(default=False)),
            ('rented_home', models.BooleanField(default=False)),
            ('student_allowance', models.BooleanField(default=False)),
            ('tags', models.JSONField(default=list, blank=True)),
            ('internal_notes', models.TextField(max_length=10000, blank=True, default='')),
            ('record_version', models.PositiveBigIntegerField(default=0, editable=False)),
            ('updated_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('office', models.ForeignKey('accounting.office',on_delete=models.PROTECT,editable=False,verbose_name='Λογιστικό γραφείο')),
        ], options={
            'verbose_name': 'Φορολογικό προφίλ συναλλασσομένου',
            'indexes': [models.Index(fields=['office', 'contact_status', 'person_kind'], name='cr007_profile_filter')],
            'constraints': [models.CheckConstraint(condition=models.Q(contact_status__in=['ACTIVE', 'INACTIVE']), name='cr007_contact_status'), models.CheckConstraint(condition=models.Q(person_kind__in=['UNREVIEWED', 'INDIVIDUAL', 'FISHER', 'SOLE_TRADER', 'FARMER_NORMAL', 'FARMER_SPECIAL', 'LEGAL_ENTITY']), name='cr007_person_kind'), models.CheckConstraint(condition=models.Q(spouse_person_kind__in=['UNREVIEWED', 'INDIVIDUAL', 'FISHER', 'SOLE_TRADER', 'FARMER_NORMAL', 'FARMER_SPECIAL', 'LEGAL_ENTITY']), name='cr007_spouse_kind')],
        }),
        migrations.CreateModel(name='TaxisCredential', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('entity', models.ForeignKey('accounting.entity', on_delete=models.PROTECT, related_name='sealed_credentials', editable=False)),
            ('subject', models.CharField(max_length=6, choices=[('MAIN', 'Υπόχρεος'), ('SPOUSE', 'Σύζυγος')], editable=False)),
            ('salt', models.BinaryField(editable=False)),
            ('sealed_username', models.BinaryField(editable=False)),
            ('sealed_password', models.BinaryField(editable=False)),
            ('updated_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('office', models.ForeignKey('accounting.office',on_delete=models.PROTECT,editable=False,verbose_name='Λογιστικό γραφείο')),
        ], options={
            'constraints': [models.UniqueConstraint(fields=['office', 'entity', 'subject'], name='cr007_credential_subject'), models.CheckConstraint(condition=models.Q(subject__in=['MAIN', 'SPOUSE']), name='cr007_credential_kind')],
        }),
        migrations.CreateModel(name='EntityProfileEvent', fields=[
            ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ('entity', models.ForeignKey('accounting.entity', on_delete=models.PROTECT, related_name='fiscal_events', editable=False)),
            ('actor', models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)),
            ('actor_label', models.CharField(max_length=150, editable=False)),
            ('action', models.CharField(max_length=12, choices=[('UPDATE', 'Ενημέρωση προφίλ'), ('VAULT_SET', 'Αποθήκευση κωδικών'), ('VAULT_CLEAR', 'Αφαίρεση κωδικών'), ('REVEAL', 'Προβολή κωδικών'), ('PURGE', 'Αφαίρεση προσωπικών στοιχείων')], editable=False)),
            ('subject', models.CharField(max_length=6, blank=True, default='', editable=False)),
            ('changed_fields', models.JSONField(default=list, editable=False)),
            ('record_version', models.PositiveBigIntegerField(editable=False)),
            ('occurred_at', models.DateTimeField(default=timezone.now, editable=False)),
            ('office', models.ForeignKey('accounting.office',on_delete=models.PROTECT,editable=False,verbose_name='Λογιστικό γραφείο')),
        ], options={
            'ordering': ['-occurred_at', '-id'],
            'indexes': [models.Index(fields=['office', 'entity', '-occurred_at'], name='cr007_profile_history')],
        }),
    ]
