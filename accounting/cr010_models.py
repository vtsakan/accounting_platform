"""Manual agreement creation receipts and sealed, short-lived Excel previews."""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from .ownership import OfficeOwned


class AgreementCreationReceipt(OfficeOwned):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request_key = models.UUIDField(editable=False)
    agreement = models.OneToOneField('accounting.Agreement', on_delete=models.PROTECT, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    payload_sha256 = models.CharField(max_length=71, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['office', 'request_key'], name='cr010_agreement_request')]


class CounterpartyImport(OfficeOwned):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, editable=False)
    source_sha256 = models.CharField(max_length=71, editable=False)
    salt = models.BinaryField(editable=False)
    payload = models.BinaryField(editable=False)
    state = models.CharField(max_length=9, default='PREVIEW', editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField(editable=False)
    completed_at = models.DateTimeField(null=True, editable=False)
    decisions_sha256 = models.CharField(max_length=71, blank=True, default='', editable=False)
    outcome = models.JSONField(default=dict, editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(state__in=['PREVIEW', 'DONE', 'CANCELLED']), name='cr010_import_state')]
        indexes = [models.Index(fields=['office', 'actor', 'state', 'expires_at'], name='cr010_import_expiry')]
