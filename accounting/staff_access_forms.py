from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UsernameField


def password_field(label, *, current=False):
    return forms.CharField(label=label,strip=False,max_length=256,
        widget=forms.PasswordInput(attrs={'autocomplete':'current-password' if current else 'new-password','class':'form-control'}))


class TemporaryPasswordForm(forms.Form):
    temporary_password=password_field('Προσωρινός κωδικός')
    temporary_password_confirm=password_field('Επιβεβαίωση προσωρινού κωδικού')
    owner_password=password_field('Δικός σας κωδικός πρόσβασης',current=True)

    def clean(self):
        data=super().clean()
        if data.get('temporary_password')!=data.get('temporary_password_confirm'):
            self.add_error('temporary_password_confirm','Οι προσωρινοί κωδικοί δεν συμφωνούν.')
        return data


class DirectStaffForm(TemporaryPasswordForm):
    username=UsernameField(label='Όνομα χρήστη',max_length=150,
        validators=get_user_model()._meta.get_field('username').validators,
        widget=forms.TextInput(attrs={'autocomplete':'off','class':'form-control'}))
    role=forms.ChoiceField(label='Ρόλος',choices=(('accountant','Λογιστής'),('owner','Υπεύθυνος γραφείου')),initial='accountant')
    field_order=['username','role','temporary_password','temporary_password_confirm','owner_password']


class ResetStaffForm(TemporaryPasswordForm):
    version=forms.IntegerField(min_value=-1,widget=forms.HiddenInput)


class RequiredPasswordForm(forms.Form):
    current_password=password_field('Τρέχων προσωρινός κωδικός',current=True)
    new_password=password_field('Νέος προσωπικός κωδικός')
    new_password_confirm=password_field('Επιβεβαίωση νέου κωδικού')
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)

    def clean(self):
        data=super().clean()
        if data.get('new_password')!=data.get('new_password_confirm'):
            self.add_error('new_password_confirm','Οι νέοι κωδικοί δεν συμφωνούν.')
        return data
