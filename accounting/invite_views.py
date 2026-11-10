"""Invitation possession plus recipient credentials; no implicit login/grants."""
from django.contrib.auth import get_user_model, logout
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from .auth_forms import PasswordProofForm
from .auth_policy import reserve_attempt
from .auth_views import limited
from .office_forms import JoinForm
from .office_services import accept_invitation, exchange_invitation, session_invitation


def guarded_response(response):
    response["Cache-Control"] = "no-store, private"
    response["Referrer-Policy"] = "no-referrer"
    return response


@never_cache
@require_GET
def token_entry(request, key, token):
    if not reserve_attempt("join", str(key), request.META.get("REMOTE_ADDR")):
        return guarded_response(limited(request))
    invite = exchange_invitation(key, token)
    request.session.cycle_key()
    request.session["s14_invitation_proof"] = {"id": str(key), "digest": invite.token_digest}
    return guarded_response(redirect("staff-join", key=key))


@never_cache
@sensitive_post_parameters("password", "password1", "password2")
@require_http_methods(["GET", "POST"])
def join(request, key):
    invite = session_invitation(request, key)
    existing = list(get_user_model().objects.filter(email__iexact=invite.recipient_email)[:2])
    form_class = PasswordProofForm if existing else JoinForm
    form = form_class(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if not reserve_attempt("join", str(key), request.META.get("REMOTE_ADDR")):
            return guarded_response(limited(request))
        if form.is_valid():
            try:
                accept_invitation(request, key, username=form.cleaned_data.get("username", ""),
                    password=form.cleaned_data["password"] if existing else form.cleaned_data["password1"])
                logout(request)  # Approval precedes any application login.
                return guarded_response(render(request, "accounting/office/join_done.html"))
            except ValidationError as error:
                form.add_error(None, error)
            except DatabaseError as error:
                if getattr(error.__cause__, "sqlstate", None) not in {"23505", "23514", "40P01", "40001"}:
                    raise
                form.add_error(None, "Ο λογαριασμός ή η πρόσκληση άλλαξε. Ανανεώστε τη σελίδα και ελέγξτε τα στοιχεία.")
    return guarded_response(render(request, "accounting/office/join.html", {"form": form, "invite": invite, "existing": bool(existing)}))
