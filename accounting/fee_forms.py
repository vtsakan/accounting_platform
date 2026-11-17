"""Greek scoped configuration forms; no office identifiers or posting action."""
from django import forms
from django.utils import timezone
from core.locale import GreekMoneyField
from .capabilities import require_capability
from .fee_services import month
from .models import Agreement


class GreekFeeForm(forms.Form):
    reason = forms.CharField(label='Αιτιολογία', min_length=4, max_length=500)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.widget.is_hidden:
                field.widget.attrs['class'] = 'form-check-input' if isinstance(field.widget, forms.CheckboxInput) else 'form-control'

    def clean(self):
        values = super().clean()
        if hasattr(self.data, 'getlist'):
            for name in self.fields:
                if len(self.data.getlist(name)) > 1:
                    self.add_error(name, 'Υποβάλετε μία μόνο τιμή για αυτό το πεδίο.')
        return values


class PriceForm(GreekFeeForm):
    code = forms.RegexField(r'^[A-Z0-9][A-Z0-9._-]{0,39}$', label='Κωδικός υπηρεσίας', max_length=40)
    description = forms.CharField(label='Περιγραφή υπηρεσίας', max_length=255)
    amount = GreekMoneyField(label='Μικτή τιμή (€)', max_digits=12, decimal_places=2)
    effective_date = forms.DateField(label='Ισχύει από', initial=timezone.localdate,
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type':'date'}))
    is_active = forms.BooleanField(label='Διαθέσιμη για νέες συμφωνίες', initial=True, required=False)
    expected_revision = forms.IntegerField(label='Έκδοση τιμοκαταλόγου', initial=0, min_value=0, widget=forms.HiddenInput)

    def __init__(self, *args, service=None, **kwargs):
        super().__init__(*args, **kwargs)
        if service:
            del self.fields['code']


class ScheduleForm(GreekFeeForm):
    agreement = forms.ModelChoiceField(label='Ελεγμένη μηνιαία εισπρακτέα συμφωνία', queryset=Agreement.objects.none())
    start_period = forms.CharField(label='Πρώτος μήνας', max_length=7, widget=forms.TextInput(attrs={'type':'month'}))
    end_period = forms.CharField(label='Τελευταίος μήνας (προαιρετικά)', required=False, max_length=7,
        widget=forms.TextInput(attrs={'type':'month'}))
    due_day = forms.IntegerField(label='Ημέρα προθεσμίας (1–28)', min_value=1, max_value=28, initial=15)
    due_next_month = forms.BooleanField(label='Η προθεσμία είναι στον επόμενο μήνα', required=False)
    first_amount = GreekMoneyField(label='Επιβεβαιωμένο ποσό πρώτου μη πλήρους μήνα (€)', required=False,
        max_digits=12, decimal_places=2, help_text='Μόνο αν η συμφωνία αρχίζει εντός του πρώτου μήνα. Δεν γίνεται αυτόματη αναλογία.')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        office = require_capability(user, 'finance.write').office_id
        self.fields['agreement'].queryset = Agreement.objects.filter(office_id=office, agreement_type='RECEIVABLE',
            entity__is_archived=False, entity__is_customer=True, terms_versions__billing_mode='MONTHLY').distinct().order_by('id')

    def clean_start_period(self):
        return month(self.cleaned_data['start_period'])

    def clean_end_period(self):
        return month(self.cleaned_data['end_period']) if self.cleaned_data['end_period'] else None


class ScheduleChangeForm(GreekFeeForm):
    effective_period = forms.CharField(label='Αλλαγή από τον μήνα', max_length=7, widget=forms.TextInput(attrs={'type':'month'}))
    end_period = forms.CharField(label='Τελευταίος μήνας (προαιρετικά)', required=False, max_length=7,
        widget=forms.TextInput(attrs={'type':'month'}))
    due_day = forms.IntegerField(label='Ημέρα προθεσμίας (1–28)', min_value=1, max_value=28, initial=15)
    due_next_month = forms.BooleanField(label='Η προθεσμία είναι στον επόμενο μήνα', required=False)
    cancelled = forms.BooleanField(label='Οριστική διακοπή προγράμματος από αυτόν τον μήνα', required=False)
    password = forms.CharField(label='Κωδικός πρόσβασης', widget=forms.PasswordInput)
    expected_revision = forms.IntegerField(label='Έκδοση προγράμματος', min_value=1, widget=forms.HiddenInput)

    def clean_effective_period(self):
        return month(self.cleaned_data['effective_period'])

    def clean_end_period(self):
        return month(self.cleaned_data['end_period']) if self.cleaned_data['end_period'] else None


class PreviewForm(forms.Form):
    start_period = forms.CharField(label='Προεπισκόπηση από τον μήνα', required=False, max_length=7,
        widget=forms.TextInput(attrs={'type':'month', 'class':'form-control'}))
    months = forms.IntegerField(label='Πλήθος μηνών (έως 24)', min_value=1, max_value=24, initial=12,
        widget=forms.NumberInput(attrs={'class':'form-control'}))

    def clean_start_period(self):
        return month(self.cleaned_data['start_period']) if self.cleaned_data['start_period'] else None
