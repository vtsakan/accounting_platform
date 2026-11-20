"""One confirmation for a new active agreement and its first charge."""
import uuid

from django import forms
from django.utils import timezone

from core.locale import GreekMoneyField
from .agreement_creation import create_with_charge
from .forms import AgreementForm


class AgreementCreationForm(AgreementForm):
    creation_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput, label='Ταυτότητα νέας συμφωνίας')
    due_date = forms.DateField(required=False, label='Προθεσμία πληρωμής',
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text='Αν μείνει κενή, χρησιμοποιείται η ημερομηνία έναρξης.')
    first_charge_amount = GreekMoneyField(required=False, max_digits=12, decimal_places=2,
        label='Ποσό πρώτου μη πλήρους μήνα (€)',
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        help_text='Προαιρετικό: μόνο για μηνιαία συμφωνία που αρχίζει εντός μήνα. Διαφορετικά χρεώνεται ολόκληρο το συμφωνημένο ποσό, χωρίς αυτόματη αναλογία.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['billing_mode'].choices = [('ONE_OFF', 'Εφάπαξ'), ('MONTHLY', 'Ανά ημερολογιακό μήνα')]
        self.fields['billing_mode'].required = True
        self.fields['billing_mode'].help_text = 'Με την αποθήκευση καταχωρίζεται η εφάπαξ ή η πρώτη μηνιαία χρέωση.'
        self.fields['lifecycle'].choices = [('ACTIVE', 'Ενεργή')]
        self.fields['lifecycle'].required = True
        self.fields['lifecycle'].widget = forms.HiddenInput()
        self.fields['status'].choices = [('ACTIVE', 'Ενεργή')]
        self.fields['reason'].required = True
        self.fields['reason'].min_length = 4
        self.fields['reason'].label = 'Αιτιολογία συμφωνίας και χρέωσης'
        self.initial.setdefault('billing_mode', 'ONE_OFF')
        self.initial.setdefault('lifecycle', 'ACTIVE')
        self.initial.setdefault('status', 'ACTIVE')
        if not self.initial.get('start_date'):
            self.initial['start_date'] = timezone.localdate()
        self.initial.setdefault('reason', 'Δημιουργία συμφωνίας και αρχικής χρέωσης')

    def clean(self):
        values = super().clean()
        day, due = values.get('start_date'), values.get('due_date')
        if day and day > timezone.localdate():
            self.add_error('start_date', 'Η άμεση χρέωση απαιτεί ημερομηνία έναρξης έως σήμερα.')
        if day and due and due < day:
            self.add_error('due_date', 'Η προθεσμία πληρωμής δεν μπορεί να προηγείται της έναρξης.')
        if values.get('first_charge_amount') is not None and day and (
                values.get('billing_mode') != 'MONTHLY' or day.day == 1):
            self.add_error('first_charge_amount', 'Το ειδικό πρώτο ποσό αφορά μόνο μηνιαία συμφωνία που αρχίζει εντός μήνα.')
        if values.get('terms_revision') not in (None, 0):
            self.add_error('terms_revision', 'Η ενέργεια αφορά νέα συμφωνία.')
        if hasattr(self.data, 'getlist'):
            for name in self.fields:
                if len(self.data.getlist(name)) > 1:
                    self.add_error(name, 'Υποβάλετε μία μόνο τιμή για αυτό το πεδίο.')
        return values

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not commit:
            return instance
        self.instance, self.created_charge, self.replayed = create_with_charge(self.actor, instance,
            billing_mode=self.cleaned_data['billing_mode'], reason=self.cleaned_data['reason'],
            creation_key=self.cleaned_data['creation_key'], due_date=self.cleaned_data.get('due_date'),
            first_charge_amount=self.cleaned_data.get('first_charge_amount'))
        return self.instance
