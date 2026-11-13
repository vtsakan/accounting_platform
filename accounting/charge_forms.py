"""Greek explicit obligation posting, with no cash/account field."""
import uuid
from django import forms
from django.utils import timezone
from core.locale import GreekMoneyField
from .charge_services import period_start


class ChargeForm(forms.Form):
    amount = GreekMoneyField(label='Μικτό ποσό χρέωσης (€)', max_digits=12, decimal_places=2)
    effective_date = forms.DateField(label='Ημερομηνία χρέωσης', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
                                    widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    due_date = forms.DateField(label='Προθεσμία πληρωμής', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
                              widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    period = forms.CharField(label='Μήνας χρέωσης', required=False, max_length=7, widget=forms.TextInput(attrs={'type': 'month'}),
                             help_text='Μόνο για μηνιαία συμφωνία. Για εφάπαξ χρέωση αφήστε το κενό.')
    reason = forms.CharField(label='Αιτιολογία και επιβεβαίωση ποσού', max_length=500, min_length=4,
                             help_text='Για πρώτο μερικό μήνα επιβεβαιώστε το ποσό με τον λογιστή. Δεν υπολογίζεται αυτόματη αναλογία ή ΦΠΑ.')
    terms_revision = forms.IntegerField(min_value=0, widget=forms.HiddenInput, label='Έκδοση όρων')
    posting_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput, label='Ταυτότητα καταχώρισης')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if not field.widget.is_hidden:
                field.widget.attrs['class'] = 'form-control'

    def clean_amount(self):
        from .finance_money import money
        return money(self.cleaned_data['amount'])

    def clean_period(self):
        try:
            return period_start(self.cleaned_data['period'])
        except forms.ValidationError as error:
            # A field cleaner must return field messages, not an error dict.
            raise forms.ValidationError(error.messages) from None

    def clean(self):
        values = super().clean()
        if values.get('effective_date') and values['effective_date'] > timezone.localdate():
            self.add_error('effective_date', 'Η ημερομηνία χρέωσης δεν μπορεί να είναι μελλοντική.')
        if values.get('effective_date') and values.get('due_date') and values['due_date'] < values['effective_date']:
            self.add_error('due_date', 'Η προθεσμία δεν μπορεί να προηγείται της χρέωσης.')
        if hasattr(self.data, 'getlist'):
            for name in self.fields:
                if len(self.data.getlist(name)) > 1:
                    self.add_error(name, 'Υποβάλετε μία μόνο τιμή για αυτό το πεδίο.')
        return values
