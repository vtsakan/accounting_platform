"""Dependent agreement choices for the existing Greek receipt/payment forms."""
from django.core.exceptions import ValidationError
from django import forms
from django.utils import timezone
from core.locale import format_euro

from .cash_entry_selectors import receipt_agreements,receipt_charges,legacy_unbilled_agreement
from .models import Agreement,Charge
from .settlement_services import cash_key


class CashChargeChoice(forms.ModelChoiceField):
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('queryset',Charge.objects.none());kwargs.setdefault('required',False)
        kwargs.setdefault('label','Χρέωση προς εξόφληση');kwargs.setdefault('empty_label','Επιλέξτε πρώτα συμφωνία')
        kwargs.setdefault('widget',forms.Select(attrs={'class':'form-select'}))
        super().__init__(*args,**kwargs)

    def label_from_instance(self,obj):
        return obj.description+' · '+obj.effective_date.strftime('%d/%m/%Y')+' · Διαθέσιμο '+format_euro(getattr(obj,'receipt_capacity',obj.outstanding))+' · '+obj.pk.hex[:8]


class AgreementCashFormMixin:
    def __init__(self, *args, **kwargs):
        supplied = kwargs.pop('agreements_queryset', None)
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        self.fields['description'].help_text = 'Με συμφωνία συμπληρώνεται αυτόματα αν μείνει κενή. Χωρίς συμφωνία γράψτε σύντομη περιγραφή.'
        self.fields['settle_agreement'].label='Αφορά συγκεκριμένη χρέωση συμφωνίας'
        self.fields['agreement'].help_text = 'Επιλέξτε συμφωνία και έπειτα τη συγκεκριμένη χρέωση προς εξόφληση.'
        self.fields['charge'].help_text='Το ποσό αντιστοιχίζεται μόνο σε αυτή τη χρέωση. Τυχόν επιπλέον ποσό παραμένει αδιάθετη πίστωση.'
        if self.actor is not None and self.office_id and supplied is not None:
            base = receipt_agreements(self.actor, self.cash_direction)
            base = base.filter(pk__in=supplied.filter(office_id=self.office_id).values('pk'))
            self._agreement_choices = base
        else:
            self._agreement_choices = Agreement.objects.none()
        selected = self.data.get('entity') if self.is_bound else self.initial.get('entity')
        self.scope_agreements(selected)
        self.scope_charges(selected,self.data.get('agreement') if self.is_bound else self.initial.get('agreement'))
        self.order_fields(['transaction_date','amount','cash_account','category','entity','settle_agreement','agreement','charge','description','remarks','posting_key'])

    def scope_charges(self,party,agreement):
        day=timezone.localdate()
        raw=self.data.get('transaction_date') if self.is_bound else self.initial.get('transaction_date')
        if raw:
            try:day=self.fields['transaction_date'].clean(raw)
            except ValidationError:pass
        if day>timezone.localdate():day=timezone.localdate()
        try:party_key,agreement_key=cash_key(party),cash_key(agreement)
        except ValidationError:self.fields['charge'].queryset=Charge.objects.none()
        else:
            self.fields['charge'].queryset=receipt_charges(self.actor,self.cash_direction,as_of=day).filter(entity_id=party_key,agreement_id=agreement_key) if self.actor else Charge.objects.none()
            # Retain the one submitted same-party choice on an error/retry,
            # even if it has since been settled. The service either proves an
            # exact replay or rejects unavailable capacity before any writes.
            if self.actor and self.is_bound and self.data.get('charge'):
                from .settlement_services import event_key
                try:key=event_key(self.data['charge'])
                except ValidationError:pass
                else:
                    self.fields['charge'].queryset=receipt_charges(self.actor,self.cash_direction,as_of=day,include_key=key).filter(entity_id=party_key,agreement_id=agreement_key)
        self.fields['charge'].empty_label='Επιλέξτε χρέωση' if party and agreement else 'Επιλέξτε πρώτα συμφωνία'

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
        if hasattr(self.data,'getlist'):
            for name in self.fields:
                if len(self.data.getlist(name))>1:self.add_error(name,'Υποβάλετε μία μόνο τιμή για αυτό το πεδίο.')
        agreement = values.get('agreement')
        chosen=values.get('charge')
        # Older clients predate both controls. This compatibility case never
        # creates an allocation: only unreviewed agreements with no charges
        # qualify, and the posting service repeats the check under the lock.
        self.legacy_unbilled_cash=bool(agreement and self.is_bound and self.actor
            and 'charge' not in self.data and 'settle_agreement' not in self.data
            and legacy_unbilled_agreement(agreement))
        wants_agreement = bool(values.get('settle_agreement') or agreement or chosen)
        if wants_agreement and agreement is None and 'agreement' not in self.errors:
            self.add_error('agreement', 'Επιλέξτε τη συμφωνία που αφορά η είσπραξη ή πληρωμή.')
        if wants_agreement and chosen is None and 'charge' not in self.errors and not (
                getattr(self,'legacy_cash_replay',False) or self.legacy_unbilled_cash):
            self.add_error('charge','Επιλέξτε τη συγκεκριμένη χρέωση προς εξόφληση.')
        if chosen and (not agreement or chosen.agreement_id!=agreement.pk or not values.get('entity') or chosen.entity_id!=values['entity'].pk):
            self.add_error('charge','Η χρέωση πρέπει να ανήκει στον ίδιο συναλλασσόμενο και στην επιλεγμένη συμφωνία.')
        if not values.get('description') and not wants_agreement:
            self.add_error('description', 'Συμπληρώστε περιγραφή ή επιλέξτε συμφωνία για αυτόματη συμπλήρωση.')
        return values
