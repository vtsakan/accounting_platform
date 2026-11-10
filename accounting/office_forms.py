from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from .auth_forms import PasswordProofForm
from .models import Office, AccountantProfile
from .office_services import OFFICE_FIELDS


class OfficeSettingsForm(forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput)
    password = forms.CharField(label="Κωδικός πρόσβασης", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))
    class Meta:
        model = Office
        fields = OFFICE_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["version"].initial = self.instance.settings_version
        for name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["vat_number"].help_text = "Εννέα ψηφία, χωρίς κενά."

    def clean_vat_number(self):
        import re
        value = self.cleaned_data["vat_number"]
        if value and not re.fullmatch(r"[0-9]{9}", value):
            raise forms.ValidationError("Ο Α.Φ.Μ. πρέπει να αποτελείται από εννέα ψηφία.")
        return value


class InviteForm(PasswordProofForm):
    email = forms.EmailField(label="Ηλεκτρονική διεύθυνση συναδέλφου", max_length=254,
                            widget=forms.EmailInput(attrs={"autocomplete": "email", "class": "form-control"}))


class JoinForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class HandoverForm(PasswordProofForm):
    recipient = forms.ModelChoiceField(queryset=AccountantProfile.objects.none(), label="Νέος υπεύθυνος",
                                      to_field_name="user_id", widget=forms.Select(attrs={"class": "form-select"}))

    def __init__(self, *args, office, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recipient"].queryset = AccountantProfile.objects.filter(office=office, role="accountant",
            is_active=True, user__is_active=True, user__is_staff=False, user__is_superuser=False).select_related("user")
        self.fields["recipient"].label_from_instance = lambda profile: profile.user.get_username()
