"""New active agreement terms; charges are a later explicit action."""
import uuid

from django import forms
from django.utils import timezone

from core.locale import GreekMoneyField
from .manual_agreement_creation import create_manual
from .forms import AgreementForm


class AgreementCreationForm(AgreementForm):
    creation_key = forms.UUIDField(initial=uuid.uuid4, widget=forms.HiddenInput, label='Ταυτότητα νέας συμφωνίας')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['billing_mode'].choices = [('ONE_OFF', 'Εφάπαξ'), ('MONTHLY', 'Ανά ημερολογιακό μήνα')]
        self.fields['billing_mode'].required = True
        self.fields['billing_mode'].help_text = 'Η συμφωνία αποθηκεύει τους όρους. Προσθέστε χρέωση χωριστά όταν απαιτείται.'
        self.fields['lifecycle'].choices = [('ACTIVE', 'Ενεργή')]
        self.fields['lifecycle'].required = True
        self.fields['lifecycle'].widget = forms.HiddenInput()
        self.fields['status'].choices = [('ACTIVE', 'Ενεργή')]
        self.fields['reason'].required = True
        self.fields['reason'].min_length = 4
        self.fields['reason'].label = 'Αιτιολογία συμφωνίας'
        self.initial.setdefault('billing_mode', 'ONE_OFF')
        self.initial.setdefault('lifecycle', 'ACTIVE')
        self.initial.setdefault('status', 'ACTIVE')
        if not self.initial.get('start_date'):
            self.initial['start_date'] = timezone.localdate()
        self.initial.setdefault('reason', 'Δημιουργία συμφωνίας')

    def clean(self):
        values = super().clean()
        day = values.get('start_date')
        if day and day > timezone.localdate():
            self.add_error('start_date', 'Η ημερομηνία έναρξης πρέπει να είναι έως σήμερα.')
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
        self.instance, self.replayed = create_manual(self.actor, instance,
            billing_mode=self.cleaned_data['billing_mode'], reason=self.cleaned_data['reason'],
            creation_key=self.cleaned_data['creation_key'])
        self.created_charge = None
        return self.instance
