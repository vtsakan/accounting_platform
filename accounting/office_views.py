from django.contrib import messages
from django.contrib.auth import logout
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST, require_GET

from .auth_forms import PasswordProofForm
from .auth_policy import recent_mfa, reserve_attempt
from .auth_views import limited
from .capabilities import office_view, require_capability
from .models import AccountantProfile, Office
from .office_forms import HandoverForm, InviteForm, OfficeSettingsForm
from .office_models import OfficeAuditEvent, OwnershipHandover, StaffInvitation
from .office_services import AUDIT_LABELS, decide_handover, decide_invitation, invite_staff, propose_handover, set_member_active, update_settings


def budget(request):
    return reserve_attempt("office-manage", str(request.user.pk), request.META.get("REMOTE_ADDR"))


def proof_form(request, *, auto_id="id_%s", return_to=None):
    request.session["s13_next"] = return_to or request.path
    return PasswordProofForm(request.POST if request.method == "POST" else None, auto_id=auto_id)


def validation(form, operation):
    if form.is_valid():
        try:
            operation(form.cleaned_data)
            return True
        except ValidationError as error:
            form.add_error(None, error)
        except DatabaseError as error:
            if getattr(error.__cause__, "sqlstate", None) not in {"23505", "23514", "40P01", "40001"}:
                raise
            form.add_error(None, "Η ενέργεια δεν ολοκληρώθηκε επειδή άλλαξαν τα στοιχεία ή τα δικαιώματα. Ανανεώστε τη σελίδα και δοκιμάστε ξανά.")
    return False


@office_view("office.settings")
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def settings_view(request):
    office = Office.objects.get(pk=require_capability(request.user, "office.settings").office_id)
    request.session["s13_next"] = request.path
    form = OfficeSettingsForm(request.POST if request.method == "POST" else None, instance=office)
    if request.method == "POST":
        if not budget(request):
            return limited(request)
        if validation(form, lambda data: update_settings(request, data, data["password"])):
            messages.success(request, "Τα στοιχεία του γραφείου αποθηκεύτηκαν.")
            return redirect("office-settings")
    return render(request, "accounting/office/settings.html", {"form": form, "office": office, "recent": recent_mfa(request)})


@office_view("staff.manage")
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def members_view(request):
    office = require_capability(request.user, "staff.manage").office
    request.session["s13_next"] = request.path
    form = InviteForm(request.POST if request.method == "POST" else None, auto_id="id_new_invite_%s")
    if request.method == "POST":
        if not budget(request):
            return limited(request)
        if validation(form, lambda data: invite_staff(request, data["email"], data["password"])):
            messages.success(request, "Η πρόσκληση δημιουργήθηκε. Ελέγξτε την ένδειξη υποβολής μηνύματος στη λίστα.")
            return redirect("office-members")
    members = list(AccountantProfile.objects.filter(office=office).select_related("user").order_by("user__username"))
    invites = list(StaffInvitation.objects.filter(office=office).select_related("accepted_by").order_by("-created_at")[:100])
    statuses = {"pending": "Αναμονή επεξεργασίας", "disabled": "Η αποστολή δεν έχει ενεργοποιηθεί", "captured": "Τοπική αποθήκευση μηνύματος",
                "test": "Δοκιμαστικό μήνυμα", "submitted": "Υποβλήθηκε στον διακομιστή αλληλογραφίας", "failed": "Η υποβολή δεν ολοκληρώθηκε"}
    for member in members:
        member.proof_form = PasswordProofForm(auto_id="id_member_" + str(member.pk) + "_%s")
    for invite in invites:
        invite.proof_form = PasswordProofForm(auto_id="id_invite_" + str(invite.pk) + "_%s")
        invite.mail_label = statuses.get(invite.mail_status, "Η υποβολή δεν επιβεβαιώθηκε")
        invite.expired = invite.status == "pending" and invite.expires_at <= timezone.now()
    return render(request, "accounting/office/members.html", {"office": office, "members": members, "invites": invites, "form": form,
        "recent": recent_mfa(request)})


@office_view("staff.manage")
@sensitive_post_parameters("password")
@require_POST
def invitation_action(request, key, action):
    office = require_capability(request.user, "staff.manage").office
    invite = StaffInvitation.objects.filter(pk=key, office=office).first()
    if invite is None:
        raise Http404("Η πρόσκληση δεν βρέθηκε.")
    if not budget(request):
        return limited(request)
    form = proof_form(request, return_to=reverse("office-members"))
    def perform(data):
        if action == "resend":
            invite_staff(request, invite.recipient_email, data["password"], resend=key)
        else:
            decide_invitation(request, key, action, data["password"])
    if validation(form, perform):
        messages.success(request, "Η ενέργεια για την πρόσκληση ολοκληρώθηκε.")
        return redirect("office-members")
    return render(request, "accounting/office/action.html", {"form": form, "title": "Ενέργεια πρόσκλησης", "recent": recent_mfa(request)})


@office_view("staff.manage")
@sensitive_post_parameters("password")
@require_POST
def member_action(request, user_id, action):
    office = require_capability(request.user, "staff.manage").office
    if not AccountantProfile.objects.filter(office=office, user_id=user_id).exists() or action not in {"deactivate", "reactivate"}:
        raise Http404("Ο λογιστής ή η ενέργεια δεν βρέθηκε.")
    if not budget(request):
        return limited(request)
    form = proof_form(request, return_to=reverse("office-members"))
    if validation(form, lambda data: set_member_active(request, user_id, action == "reactivate", data["password"])):
        if user_id == request.user.pk:
            logout(request); return redirect("login")
        messages.success(request, "Η κατάσταση του λογιστή ενημερώθηκε.")
        return redirect("office-members")
    return render(request, "accounting/office/action.html", {"form": form, "title": "Αλλαγή κατάστασης λογιστή", "recent": recent_mfa(request)})


@office_view("ownership.accept")
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def ownership_view(request):
    profile = require_capability(request.user, "ownership.accept")
    request.session["s13_next"] = request.path
    form = HandoverForm(request.POST if request.method == "POST" else None, office=profile.office)
    if request.method == "POST":
        require_capability(request.user, "ownership.propose")
        if not budget(request):
            return limited(request)
        if validation(form, lambda data: propose_handover(request, data["recipient"].user_id, data["password"])):
            messages.success(request, "Η πρόταση δημιουργήθηκε. Ο συνάδελφος πρέπει να την αποδεχτεί με επαλήθευση ταυτότητας.")
            return redirect("office-ownership")
    from django.db.models import Q
    offers = OwnershipHandover.objects.filter(office=profile.office).filter(Q(requested_by=request.user) | Q(recipient=request.user)).select_related("requested_by", "recipient").order_by("-created_at")[:100]
    return render(request, "accounting/office/ownership.html", {"form": form, "profile": profile, "offers": offers, "recent": recent_mfa(request)})


@office_view("ownership.accept", mfa=True)
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def handover_detail(request, key):
    profile = require_capability(request.user, "ownership.accept")
    offer = OwnershipHandover.objects.select_related("requested_by", "recipient").filter(pk=key, office=profile.office).first()
    if offer is None or request.user.pk not in {offer.requested_by_id, offer.recipient_id}:
        raise Http404("Η πρόταση δεν βρέθηκε.")
    form = proof_form(request)
    if request.method == "POST":
        if not budget(request):
            return limited(request)
        decision = request.POST.get("action")
        if validation(form, lambda data: decide_handover(request, key, decision, data["password"])):
            if decision == "accept":
                logout(request)
                return redirect("login")
            messages.success(request, "Η πρόταση ακυρώθηκε.")
            return redirect("office-ownership")
    return render(request, "accounting/office/handover.html", {"offer": offer, "form": form,
        "recipient": request.user.pk == offer.recipient_id, "recent": recent_mfa(request)})


@office_view("office.audit")
@require_GET
def audit_view(request):
    office = require_capability(request.user, "office.audit").office
    events = list(OfficeAuditEvent.objects.filter(office=office).select_related("actor", "target_user")[:200])
    for event in events:
        event.label = AUDIT_LABELS.get(event.action, "Ενέργεια γραφείου")
    return render(request, "accounting/office/audit.html", {"events": events, "office": office})
