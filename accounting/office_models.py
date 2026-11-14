"""S14 office workflows. Bearer invitation tokens are never stored here."""
import uuid
from django.conf import settings
from django.db import models


class StaffInvitation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Αναμονή αποδοχής"
        ACCEPTED = "accepted", "Αναμονή έγκρισης"
        APPROVED = "approved", "Εγκρίθηκε"
        CANCELLED = "cancelled", "Ακυρώθηκε"
        REJECTED = "rejected", "Απορρίφθηκε"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    office = models.ForeignKey("accounting.Office", on_delete=models.PROTECT)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="staff_invitations_created")
    inviter_revision = models.PositiveBigIntegerField()
    recipient_email = models.EmailField()
    token_digest = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="staff_invitations_accepted")
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    mail_status = models.CharField(max_length=16, default="pending")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["office", "recipient_email"],
            condition=models.Q(status__in=["pending", "accepted"]), name="one_open_staff_invitation")]


class OwnershipHandover(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Αναμονή αποδοχής"
        ACCEPTED = "accepted", "Ολοκληρώθηκε"
        CANCELLED = "cancelled", "Ακυρώθηκε"
        EXPIRED = "expired", "Έληξε"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    office = models.ForeignKey("accounting.Office", on_delete=models.PROTECT)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ownership_offers_created")
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ownership_offers_received")
    requester_revision = models.PositiveBigIntegerField()
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=~models.Q(requested_by=models.F("recipient")), name="handover_distinct_users"),
            models.UniqueConstraint(fields=["office", "requested_by"], condition=models.Q(status="pending"), name="one_pending_owner_handover")]


class OfficeAuditEvent(models.Model):
    office = models.ForeignKey("accounting.Office", on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="office_audit_actions")
    operator_ref = models.CharField(max_length=100, blank=True)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="office_audit_changes")
    action = models.CharField(max_length=40)
    subject = models.CharField(max_length=64, blank=True)
    role_before = models.CharField(max_length=10, blank=True)
    role_after = models.CharField(max_length=10, blank=True)
    active_before = models.BooleanField(null=True)
    active_after = models.BooleanField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
