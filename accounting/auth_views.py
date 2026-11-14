"""Password authentication plus a separately enforced staff MFA lifecycle."""
import base64
from functools import wraps
import io
import time
from urllib.parse import urlencode

from cryptography.fernet import InvalidToken
from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth import views as django_auth
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_GET
import django_otp
import qrcode
import qrcode.image.svg

from .auth_forms import PasswordProofForm, RecoveryCodeForm, StaffAuthenticationForm, StaffPasswordResetForm, StaffSetPasswordForm, TokenForm
from .auth_models import AuthenticatorDevice, MFARecoveryCode
from .auth_policy import bind_session, eligible, recent_mfa, recovery_authorized, require_eligible, requires_mfa, reserve_attempt, state_for
from .auth_services import begin_enrollment, complete_enrollment, consume_recovery, lock_state, may_manage, regenerate_codes, verify_authenticator

WRONG_FACTOR = "Ο κωδικός δεν είναι έγκυρος ή έχει λήξει. Δοκιμάστε ξανά."


def safe_next(request, candidate=None):
    candidate = candidate or request.session.get("s13_next", "")
    if candidate and url_has_allowed_host_and_scheme(candidate, {request.get_host()}, require_https=request.is_secure()):
        # Auth pages are never the destination of a completed login.
        if candidate.startswith("/") and not candidate.startswith(("/auth/", "/login/", "/logout/")):
            return candidate
    return "/admin/" if request.user.is_staff and request.user.is_superuser else "/"


def attempt(request, action, identifier):
    return reserve_attempt(action, identifier, request.META.get("REMOTE_ADDR"))


def limited(request):
    response = render(request, "accounting/auth/message.html", {"title": "Προσωρινός περιορισμός",
        "message": "Έγιναν πολλές προσπάθειες. Δοκιμάστε ξανά σε δεκαπέντε λεπτά."}, status=429)
    response["Retry-After"] = str(settings.AUTH_RATE_WINDOW_SECONDS)
    return response


@method_decorator(sensitive_post_parameters(), name="dispatch")
class StaffLoginView(django_auth.LoginView):
    template_name = "accounting/login.html"
    authentication_form = StaffAuthenticationForm

    def post(self, request, *args, **kwargs):
        if not attempt(request, "login", request.POST.get("username", "")[:254]):
            return limited(request)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)  # Django rotates the password session/CSRF.
        self.request.session.pop(django_otp.DEVICE_ID_SESSION_KEY, None)
        self.request.user.otp_device = None
        for key in ("s13_pending_device", "s13_recovery_until", "s13_mfa_at"):
            self.request.session.pop(key, None)
        bind_session(self.request, new_login=True)
        self.request.session.pop("s13_next", None)
        self.request.session["s13_next"] = safe_next(self.request, self.get_redirect_url())
        if requires_mfa(self.request.user):
            state = state_for(self.request.user)
            first = not state.enrolled_at and not AuthenticatorDevice.objects.filter(user=self.request.user, confirmed=True).exists()
            return redirect("mfa-setup" if first else "mfa-verify")
        return HttpResponseRedirect(self.request.session["s13_next"])


class StaffPasswordResetView(django_auth.PasswordResetView):
    form_class = StaffPasswordResetForm
    template_name = "accounting/auth/reset_request.html"
    email_template_name = "accounting/auth/reset_email.txt"
    subject_template_name = "accounting/auth/reset_subject.txt"
    success_url = reverse_lazy("password-reset-done")

    def post(self, request, *args, **kwargs):
        if not attempt(request, "reset", request.POST.get("email", "")[:254]):
            return limited(request)
        return super().post(request, *args, **kwargs)


class StaffPasswordResetConfirmView(django_auth.PasswordResetConfirmView):
    form_class = StaffSetPasswordForm
    template_name = "accounting/auth/reset_confirm.html"
    success_url = reverse_lazy("password-reset-complete")

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        return user if user and eligible(user) else None

    def post(self, request, *args, **kwargs):
        if not attempt(request, "reset", "confirm:" + str(self.user.pk)):
            return limited(request)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        # Recheck the token while holding the user lock: two concurrent resets
        # cannot both consume the same link with different new passwords.
        with transaction.atomic():
            lock_state(self.user)
            self.user.refresh_from_db()
            token = self.request.session.get(django_auth.INTERNAL_RESET_SESSION_TOKEN)
            if not eligible(self.user) or not default_token_generator.check_token(self.user, token):
                self.validlink = False
                return self.render_to_response(self.get_context_data())
            form.user = self.user
            return super().form_valid(form)


def staff_auth_view(view):
    @login_required
    @sensitive_post_parameters("password", "otp_token", "recovery_code")
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        require_eligible(request.user)
        return view(request, *args, **kwargs)
    return wrapped


def verified_session(request, device, state=None):
    django_otp.login(request, device)
    request.session.cycle_key()
    bind_session(request, state)
    request.session["s13_mfa_at"] = time.time()
    for key in ("s13_pending_device", "s13_recovery_until"):
        request.session.pop(key, None)


def pending_device(request):
    device = AuthenticatorDevice.objects.filter(pk=request.session.get("s13_pending_device"), user=request.user,
        confirmed=False, setup_expires_at__gt=timezone.now()).first()
    return device if device and may_manage(request, state_for(request.user)) else None


@staff_auth_view
@require_http_methods(["GET", "POST"])
def mfa_setup(request):
    proof = PasswordProofForm()
    token = TokenForm()
    if request.method == "POST":
        if not attempt(request, "manage", str(request.user.pk)):
            return limited(request)
        if request.POST.get("action") == "start":
            proof = PasswordProofForm(request.POST)
            if proof.is_valid():
                try:
                    device = begin_enrollment(request, proof.cleaned_data["password"])
                    request.session["s13_pending_device"] = device.pk
                    return redirect("mfa-setup")
                except PermissionDenied:
                    proof.add_error(None, "Απαιτείται κωδικός πρόσβασης και πρόσφατη επαλήθευση ή κωδικός ανάκτησης.")
        else:
            token = TokenForm(request.POST)
            if token.is_valid():
                result = complete_enrollment(request, request.session.get("s13_pending_device"), token.cleaned_data["otp_token"])
                if result:
                    device, state, codes = result
                    verified_session(request, device, state)
                    return render(request, "accounting/auth/recovery_codes.html", {"codes": codes, "continue_url": safe_next(request)})
                token.add_error(None, WRONG_FACTOR)
    return render(request, "accounting/auth/mfa_setup.html", {"proof_form": proof, "token_form": token,
        "pending": pending_device(request) is not None, "can_manage": may_manage(request, state_for(request.user))})


@staff_auth_view
@require_GET
def mfa_qr(request):
    device = pending_device(request)
    if device is None:
        raise PermissionDenied("Η ρύθμιση δεν είναι διαθέσιμη. Ξεκινήστε ξανά.")
    try:
        secret = base64.b32encode(device.bin_key).decode("ascii")
    except (InvalidToken, ValueError):
        raise PermissionDenied("Η ρύθμιση δεν είναι διαθέσιμη. Ξεκινήστε ξανά.") from None
    # No username/email or third-party QR service. Seed stays in this private SVG.
    uri = "otpauth://totp/" + str(request.user.pk) + "?" + urlencode({"secret": secret, "issuer": "TotalAccounting", "digits": 6, "period": 30})
    stream = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=6, border=4).save(stream)
    return HttpResponse(stream.getvalue(), content_type="image/svg+xml")


@staff_auth_view
@require_http_methods(["GET", "POST"])
def mfa_verify(request):
    form = TokenForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if not attempt(request, "mfa", str(request.user.pk)):
            return limited(request)
        if form.is_valid():
            device = verify_authenticator(request, form.cleaned_data["otp_token"])
            if device:
                verified_session(request, device)
                return HttpResponseRedirect(safe_next(request))
            form.add_error(None, WRONG_FACTOR)
    return render(request, "accounting/auth/mfa_verify.html", {"form": form})


@staff_auth_view
@require_http_methods(["GET", "POST"])
def mfa_recover(request):
    form = RecoveryCodeForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if not attempt(request, "mfa", str(request.user.pk)):
            return limited(request)
        if form.is_valid():
            state = consume_recovery(request, form.cleaned_data["recovery_code"])
            if state:
                request.session.pop(django_otp.DEVICE_ID_SESSION_KEY, None)
                request.user.otp_device = None
                request.session.cycle_key()
                bind_session(request, state)
                request.session["s13_recovery_until"] = time.time() + settings.AUTH_MFA_PENDING_SECONDS
                return redirect("mfa-setup")
            form.add_error(None, WRONG_FACTOR)
    return render(request, "accounting/auth/mfa_recover.html", {"form": form})


@staff_auth_view
@require_http_methods(["GET", "POST"])
def security_settings(request):
    if requires_mfa(request.user) and not request.user.is_verified():
        return redirect("mfa-verify")
    form = PasswordProofForm(request.POST if request.method == "POST" else None)
    if request.method == "POST":
        if not attempt(request, "manage", str(request.user.pk)):
            return limited(request)
        if form.is_valid():
            try:
                state, codes = regenerate_codes(request, form.cleaned_data["password"])
                request.session.cycle_key(); bind_session(request, state)
                return render(request, "accounting/auth/recovery_codes.html", {"codes": codes, "continue_url": reverse("security-settings")})
            except PermissionDenied:
                form.add_error(None, "Απαιτείται κωδικός πρόσβασης και πρόσφατη επαλήθευση.")
    return render(request, "accounting/auth/security.html", {"form": form,
        "enrolled": bool(state_for(request.user).enrolled_at), "recent": recent_mfa(request),
        "codes_remaining": MFARecoveryCode.objects.filter(user=request.user).count()})
