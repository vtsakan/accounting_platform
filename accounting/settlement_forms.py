"""Greek confirmation forms. No office, counterparty or direction authority fields."""
import uuid
from django import forms
from django.forms import formset_factory
from django.utils import timezone
from core.locale import GreekMoneyField
from .finance_money import money
from .settlement_services import clean_reason


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.widget.is_hidden:
                field.widget.attrs['class'] = 'form-check-input' if isinstance(field.widget, forms.CheckboxInput) else 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'

    def clean(self):
        values = super().clean()
        if hasattr(self.data, 'getlist'):
            for name in self.fields:
                if not isinstance(self.fields[name], forms.MultipleChoiceField) and len(self.data.getlist(self.add_prefix(name))) > 1:
                    self.add_error(name, 'Υποβάλετε μία μόνο τιμή για αυτό το πεδίο.')
        return values


class SettlementDateForm(StyledForm):
    as_of = forms.DateField(label='Υπόλοιπα κατά την ημερομηνία', required=False,
        input_formats=['%Y-%m-%d', '%d/%m/%Y'], widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))

    def clean_as_of(self):
        day = self.cleaned_data['as_of'] or timezone.localdate()
        if day > timezone.localdate():
            raise forms.ValidationError('Η ημερομηνία αναφοράς δεν μπορεί να είναι μελλοντική.')
        return day


class AllocationHeaderForm(StyledForm):
    effective_date = forms.DateField(label='Ημερομηνία αντιστοίχισης', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}), initial=timezone.localdate)
    reason = forms.CharField(label='Αιτιολογία επιβεβαίωσης', min_length=4, max_length=500)
    posting_key = forms.UUIDField(label='Ταυτότητα επιβεβαίωσης', initial=uuid.uuid4, widget=forms.HiddenInput)

    def clean_reason(self):
        return clean_reason(self.cleaned_data['reason'])

    def clean_effective_date(self):
        value = self.cleaned_data['effective_date']
        if value > timezone.localdate():
            raise forms.ValidationError('Η ημερομηνία δεν μπορεί να είναι μελλοντική.')
        return value


class ChargeChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # The UUID distinguishes equal-price/monthly obligations without trusting
        # a posted label. Exact amounts remain server-validated.
        amount = f'{obj.outstanding:.2f}'.replace('.', ',')
        return f'{obj.description} · {obj.due_date:%d/%m/%Y} · Υπόλοιπο {amount} € · {obj.pk}'


class AllocationLineForm(StyledForm):
    charge = ChargeChoice(label='Χρέωση προς εξόφληση', queryset=None, empty_label='Επιλέξτε χρέωση')
    amount = GreekMoneyField(label='Ποσό αντιστοίχισης (€)', max_digits=12, decimal_places=2)

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['charge'].queryset = choices

    def clean_amount(self):
        return money(self.cleaned_data['amount'])


class AllocationLines(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        keys = [row.cleaned_data['charge'].pk for row in self.forms if row.cleaned_data]
        if len(keys) != len(set(keys)):
            raise forms.ValidationError('Επιλέξτε κάθε χρέωση μία φορά ανά επιβεβαίωση.')


AllocationFormSet = formset_factory(AllocationLineForm, formset=AllocationLines, extra=5,
    min_num=1, validate_min=True, max_num=20, validate_max=True, absolute_max=40)


class ReleaseForm(AllocationHeaderForm):
    effective_date = forms.DateField(label='Ημερομηνία αποδέσμευσης', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}), initial=timezone.localdate)
    password = forms.CharField(label='Ο κωδικός πρόσβασής σας', widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
