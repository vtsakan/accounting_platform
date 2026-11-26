"""Last temporary-credential issue; passwords remain only in auth.User hashes."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class StaffCredentialRequirement(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, primary_key=True,
        related_name='credential_requirement', editable=False)
    office = models.ForeignKey('accounting.Office', on_delete=models.PROTECT, editable=False)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='temporary_credentials_issued', editable=False)
    required = models.BooleanField(default=True, editable=False)
    version = models.PositiveBigIntegerField(default=0, editable=False)
    security_revision = models.PositiveBigIntegerField(editable=False)
    password_marker = models.CharField(max_length=71, editable=False)
    issued_at = models.DateTimeField(default=timezone.now, editable=False)
    changed_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        verbose_name = 'Υποχρεωτική αλλαγή κωδικού'
        verbose_name_plural = 'Υποχρεωτικές αλλαγές κωδικού'
