import time

from django.contrib.auth import logout
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from core.referrer import referrer_policy

from .auth_policy import bind_session, eligible, recovery_authorized, requires_mfa, session_valid, state_for
from .auth_models import AuthenticatorDevice


class StaffSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(("/login/", "/auth/", "/admin/", "/office/", "/join/")):
            response["Cache-Control"] = "no-store, private"
            response["Referrer-Policy"] = referrer_policy(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        match = request.resolver_match
        admin = match and match.namespace == "admin"
        if admin and match.url_name == "login":
            return HttpResponseRedirect(reverse("login") + "?next=/admin/")
        # Django's reset-token flow is available independently of stale sessions.
        if match and (match.url_name or "").startswith("password-reset"):
            return None
        protected = bool(hasattr(request, "accountant_profile") or admin or request.path.startswith("/auth/"))
        if not protected or not request.user.is_authenticated:
            return None
        state = state_for(request.user)
        must_verify = requires_mfa(request.user, state) or bool(getattr(view_func, "staff_mfa_required", False))
        if not session_valid(request, state):
            logout(request)
            return HttpResponseRedirect(reverse("login") + "?expired=1")
        bind_session(request, state)
        if not eligible(request.user):
            return render(request, "403.html", status=403)
        if not request.user.is_verified() and not recovery_authorized(request):
            if time.time() >= request.session.get("s13_mfa_deadline", 0) and must_verify:
                logout(request)
                return HttpResponseRedirect(reverse("login") + "?expired=1")
        if request.path.startswith("/auth/"):
            return None  # Individual auth views still require eligibility/proof.
        global_auth = admin and ((match.url_name or "").startswith("auth_") or
            (match.url_name == "app_list" and view_kwargs.get("app_label") == "auth") or
            (match.url_name == "autocomplete" and request.GET.get("app_label") == "auth"))
        if admin and (not request.user.is_staff or (global_auth and not request.user.is_superuser)):
            return render(request, "403.html", status=403)
        if not must_verify:
            return None
        if request.user.is_verified():
            return None
        request.session["s13_next"] = request.get_full_path()
        first = recovery_authorized(request) or (not state.enrolled_at and not AuthenticatorDevice.objects.filter(user=request.user, confirmed=True).exists())
        return HttpResponseRedirect(reverse("mfa-setup" if first else "mfa-verify"))
