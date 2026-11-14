"""Captured staff mail; SMTP needs the separate staff-purpose opt-in."""
import logging
from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from core.auth_mail import deliver, public_origin
from .office_models import StaffInvitation, OwnershipHandover

logger = logging.getLogger(__name__)


def url(name, **kwargs):
    origin = public_origin(settings.AUTH_PUBLIC_ORIGIN, settings.ALLOWED_HOSTS, production=bool(settings.SECURE_SSL_REDIRECT))
    return origin + reverse(name, kwargs=kwargs)


def schedule_invitation(invite, token):
    key, digest = invite.pk, invite.token_digest
    def send():
        try:
            from .office_services import invitation_available
            current = StaffInvitation.objects.select_related("office", "invited_by").filter(pk=key, token_digest=digest).first()
            if not invitation_available(current):
                return
            body = render_to_string("accounting/office/invitation_email.txt", {"office": current.office,
                "link": url("staff-join-token", key=key, token=token)})
            status = deliver("Πρόσκληση σε λογιστικό γραφείο", body, current.recipient_email, purpose="staff")
            StaffInvitation.objects.filter(pk=key, token_digest=digest).update(mail_status=status)
        except Exception as error:
            StaffInvitation.objects.filter(pk=key, token_digest=digest).update(mail_status="failed")
            logger.warning("Staff invitation mail unavailable (%s); payload omitted.", type(error).__name__)
    transaction.on_commit(send)


def schedule_approval(invite):
    key = invite.pk
    def send():
        try:
            current = StaffInvitation.objects.select_related("office", "accepted_by").filter(pk=key, status="approved").first()
            if current is None:
                return
            body = render_to_string("accounting/office/approval_email.txt", {"office": current.office,
                "username": current.accepted_by.username, "link": url("login")})
            deliver("Εγκρίθηκε η πρόσβασή σας στο γραφείο", body, current.recipient_email, purpose="staff")
        except Exception as error:
            logger.warning("Staff approval mail unavailable (%s); payload omitted.", type(error).__name__)
    transaction.on_commit(send)


def schedule_handover(handover):
    key = handover.pk
    def send():
        try:
            current = OwnershipHandover.objects.select_related("office", "recipient").filter(pk=key, status="pending").first()
            if current is None:
                return
            body = render_to_string("accounting/office/handover_email.txt", {"office": current.office,
                "link": url("office-handover-detail", key=key)})
            deliver("Πρόταση παράδοσης ευθύνης γραφείου", body, current.recipient.email, purpose="staff")
        except Exception as error:
            logger.warning("Ownership mail unavailable (%s); payload omitted.", type(error).__name__)
    transaction.on_commit(send)
