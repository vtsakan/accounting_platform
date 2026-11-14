"""Greek Django auth forms; reset never removes an existing second factor."""
from urllib.parse import urlsplit

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.core.exceptions import ValidationError
from django.db import transaction
from django.template.loader import render_to_string

from core.auth_mail import deliver, public_origin
from .auth_policy import AUTH_ERROR, eligible
from .auth_services import lock_state


class StaffAuthenticationForm(AuthenticationForm):
    error_messages = {"invalid_login": AUTH_ERROR, "inactive": AUTH_ERROR}

    def confirm_login_allowed(self, user):
        if not eligible(user):
            raise ValidationError(AUTH_ERROR, code="invalid_login")


class StaffPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(label="Ηλεκτρονική διεύθυνση", max_length=254,
        widget=forms.EmailInput(attrs={"autocomplete": "email", "class": "form-control"}))

    def get_users(self, email):
        # A shared/ambiguous email must not reset a different staff identity.
        users = list(get_user_model().objects.filter(email__iexact=email)[:2])
        return users if len(users) == 1 and users[0].has_usable_password() and eligible(users[0]) else []

    def save(self, **kwargs):
        origin = public_origin(settings.AUTH_PUBLIC_ORIGIN, settings.ALLOWED_HOSTS,
                               production=settings.SETTINGS_MODULE == "core.settings.production")
        parsed = urlsplit(origin)
        kwargs.update(domain_override=parsed.netloc, use_https=parsed.scheme == "https",
                      extra_email_context={"domain": parsed.netloc, "protocol": parsed.scheme})
        super().save(**kwargs)

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email,
                  html_email_template_name=None):
        subject = "".join(render_to_string(subject_template_name, context).splitlines())
        deliver(subject, render_to_string(email_template_name, context), to_email)


class StaffSetPasswordForm(SetPasswordForm):
    def save(self, commit=True):
        with transaction.atomic():
            state = lock_state(self.user)
            user = super().save(commit=commit)
            if commit:
                state.revision += 1
                state.save(update_fields=["revision"])
            return user


class PasswordProofForm(forms.Form):
    password = forms.CharField(label="Κωδικός πρόσβασης", strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "class": "form-control"}))


class TokenForm(forms.Form):
    otp_token = forms.RegexField(r"^[0-9]{6}$", label="Εξαψήφιος κωδικός", max_length=6, min_length=6,
        error_messages={"invalid": "Πληκτρολογήστε έξι ψηφία."},
        widget=forms.TextInput(attrs={"inputmode": "numeric", "autocomplete": "one-time-code", "class": "form-control"}))


class RecoveryCodeForm(forms.Form):
    recovery_code = forms.CharField(label="Κωδικός ανάκτησης", max_length=64,
        widget=forms.PasswordInput(attrs={"autocomplete": "off", "class": "form-control"}))
