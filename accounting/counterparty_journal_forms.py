"""Greek note and journal filters; neither accepts an authority or timestamp."""
import re
import uuid

from django import forms
from django.utils import timezone

from .counterparty_note_services import note_text

KINDS = [('', 'Όλες οι εγγραφές'), ('agreement', 'Συμφωνίες και αλλαγές όρων'),
    ('charge', 'Χρεώσεις'), ('cash', 'Εισπράξεις και πληρωμές'),
    ('allocation', 'Αντιστοιχίσεις'), ('release', 'Αποδεσμεύσεις'),
    ('correction', 'Αντιλογισμοί χρεώσεων'), ('note', 'Σημειώσεις'), ('task', 'Εργασίες')]


class NoteForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput, label='Αναγνωριστικό υποβολής')
    subject = forms.CharField(label='Θέμα', max_length=200, required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Σύντομο θέμα'}))
    body = forms.CharField(label='Νέα σημείωση', max_length=5000,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 4,
            'placeholder': 'Τι θέλετε να καταγράψετε για αυτή την καρτέλα;'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['request_key'].initial = uuid.uuid4

    def clean_body(self):
        try:
            return note_text(self.cleaned_data['body'])
        except forms.ValidationError as error:
            raise forms.ValidationError(error.error_dict['body']) from None


class JournalForm(forms.Form):
    view = forms.ChoiceField(required=False, label='Προβολή', choices=[('list', 'Αναλυτική λίστα'), ('month', 'Μηνιαίο ημερολόγιο')])
    month = forms.CharField(required=False, label='Μήνας', max_length=7,
        widget=forms.TextInput(attrs={'type': 'month', 'min': '1900-01', 'max': '2200-12'}))
    start_date = forms.DateField(required=False, label='Από ημερομηνία', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, label='Έως ημερομηνία', input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    kind = forms.ChoiceField(required=False, label='Είδος εγγραφής', choices=KINDS)
    direction = forms.ChoiceField(required=False, label='Κατεύθυνση', choices=[('', 'Όλες οι κατευθύνσεις'),
        ('RECEIVABLE', 'Εισπρακτέα / έσοδα'), ('PAYABLE', 'Πληρωτέα / έξοδα'), ('NOTE', 'Σημειώσεις'), ('TASK', 'Εργασίες')])
    q = forms.CharField(required=False, label='Αναζήτηση στο ιστορικό', max_length=100)

    def __init__(self, data=None, **kwargs):
        data = data.copy() if data is not None else {}
        if not data.get('view'):
            data['view'] = 'list'
        if not data.get('month'):
            data['month'] = timezone.localdate().strftime('%Y-%m')
        super().__init__(data, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-select' if isinstance(field, forms.ChoiceField) else 'form-control'

    def clean_month(self):
        value = self.cleaned_data['month']
        if not re.fullmatch(r'(19[0-9]{2}|20[0-9]{2}|21[0-9]{2}|2200)-(0[1-9]|1[0-2])', value):
            raise forms.ValidationError('Επιλέξτε έγκυρο μήνα από το 1900 έως το 2200.')
        return value

    def clean(self):
        values = super().clean()
        if values.get('start_date') and values.get('end_date') and values['start_date'] > values['end_date']:
            self.add_error('end_date', 'Η τελική ημερομηνία πρέπει να είναι ίδια ή μεταγενέστερη της αρχικής.')
        if hasattr(self.data, 'getlist'):
            for field in self.fields:
                if len(self.data.getlist(field)) > 1:
                    self.add_error(field, 'Επιλέξτε μία μόνο τιμή για αυτό το φίλτρο.')
        return values
