"""Dependent agreement choices for the existing Greek receipt/payment forms."""
from django.core.exceptions import ValidationError

from .cash_entry_selectors import receipt_agreements
from .models import Agreement
from .settlement_services import cash_key


class AgreementCashFormMixin:
    def __init__(self, *args, **kwargs):
        supplied = kwargs.pop('agreements_queryset', None)
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['description'].help_text = 'Με συμφωνία συμπληρώνεται αυτόματα αν μείνει κενή. Χωρίς συμφωνία γράψτε σύντομη περιγραφή.'
        self.fields['agreement'].help_text = 'Η αποθήκευση εξοφλεί αυτόματα τις χρεώσεις της επιλεγμένης συμφωνίας, πρώτα την παλαιότερη προθεσμία. Τυχόν επιπλέον ποσό παραμένει αδιάθετο.'
        if self.actor is not None and self.office_id and supplied is not None:
            base = receipt_agreements(self.actor, self.cash_direction)
            base = base.filter(pk__in=supplied.filter(office_id=self.office_id).values('pk'))
            self._agreement_choices = base
        else:
            self._agreement_choices = Agreement.objects.none()
        selected = self.data.get('entity') if self.is_bound else self.initial.get('entity')
        self.scope_agreements(selected)

    def scope_agreements(self, selected):
        try:
            key = cash_key(selected)
        except ValidationError:
            self.fields['agreement'].queryset = self._agreement_choices.none()
            self.fields['agreement'].empty_label = 'Επιλέξτε πρώτα συναλλασσόμενο'
        else:
            self.fields['agreement'].queryset = self._agreement_choices.filter(entity_id=key)
            self.fields['agreement'].empty_label = 'Επιλέξτε συμφωνία'

    def clean(self):
        values = super().clean()
        agreement = values.get('agreement')
        wants_agreement = bool(values.get('settle_agreement') or agreement)
        if wants_agreement and agreement is None and 'agreement' not in self.errors:
            self.add_error('agreement', 'Επιλέξτε τη συμφωνία που αφορά η είσπραξη ή πληρωμή.')
        if not values.get('description') and not wants_agreement:
            self.add_error('description', 'Συμπληρώστε περιγραφή ή επιλέξτε συμφωνία για αυτόματη συμπλήρωση.')
        return values
