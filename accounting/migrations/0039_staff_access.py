"""Add an empty credential requirement table; no existing user or hash changes."""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('accounting','0038_subject_import_guards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='StaffCredentialRequirement', fields=[
        ('user',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,primary_key=True,serialize=False,
            related_name='credential_requirement',editable=False,to=settings.AUTH_USER_MODEL)),
        ('required',models.BooleanField(default=True,editable=False)),
        ('version',models.PositiveBigIntegerField(default=0,editable=False)),
        ('security_revision',models.PositiveBigIntegerField(editable=False)),
        ('password_marker',models.CharField(max_length=71,editable=False)),
        ('issued_at',models.DateTimeField(default=django.utils.timezone.now,editable=False)),
        ('changed_at',models.DateTimeField(null=True,editable=False)),
        ('issued_by',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
            related_name='temporary_credentials_issued',editable=False,to=settings.AUTH_USER_MODEL)),
        ('office',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,editable=False,to='accounting.office')),
    ], options={'verbose_name':'Υποχρεωτική αλλαγή κωδικού','verbose_name_plural':'Υποχρεωτικές αλλαγές κωδικού'})]
