"""Greek owner confirmations; source and office authority always come from URLs/session."""
import uuid
from django import forms
from django.utils import timezone
from django.db.models import Exists, OuterRef
from core.locale import GreekMoneyField
from .finance_money import money
from .finance_services import clean_reason
from .settlement_forms import StyledForm
from .models import Agreement, CashAccount, CashRefund, Category, Entity, Transaction
from .office_access import records


def date_field(label):
    return forms.DateField(label=label, initial=timezone.localdate, input_formats=['%Y-%m-%d', '%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))


class CorrectionProofForm(StyledForm):
    effective_date = date_field('Ημερομηνία διόρθωσης')
    reason = forms.CharField(label='Αιτιολογία', min_length=4, max_length=500)
    password = forms.CharField(label='Ο κωδικός πρόσβασής σας', widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    posting_key = forms.UUIDField(label='Ταυτότητα επιβεβαίωσης', initial=uuid.uuid4, widget=forms.HiddenInput)

    def clean_reason(self):
        return clean_reason(self.cleaned_data['reason'])

    def clean_effective_date(self):
        value = self.cleaned_data['effective_date']
        if value > timezone.localdate():
            raise forms.ValidationError('Η χρηματική διόρθωση δεν καταχωρίζεται σε μελλοντική ημερομηνία.')
        return value


class RefundChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        amount = f'{obj.amount:.2f}'.replace('.', ',')
        status = 'Αντιλογισμένη' if obj.voided else 'Ενεργή'
        return f'{status} επιστροφή {amount} € · Κίνηση #{obj.entry_id} · {obj.effective_date:%d/%m/%Y}'


class CashCorrectionForm(CorrectionProofForm):
    replace = forms.BooleanField(label='Αντιλογισμός και νέα καταχώριση αντικατάστασης', required=False)
    dependent_refunds = RefundChoice(label='Επιστροφές που επιβεβαιώνω να αντιλογιστούν μαζί', required=False,
                                    queryset=CashRefund.objects.none(), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, user, source, **kwargs):
        super().__init__(*args, **kwargs)
        # Include historical choices for a completed identical POST retry. The
        # service requires exactly the currently active dependencies for new work.
        self.fields['dependent_refunds'].queryset = CashRefund.objects.filter(office_id=source.office_id, source_cash=source).annotate(voided=Exists(Transaction.objects.filter(reversal_of_id=OuterRef('entry_id')))).order_by('pk')
        self.fields['dependent_refunds'].widget.attrs.pop('class', None)
        if source.posting_kind in {'REFUND', 'REVERSAL'}:
            self.fields['replace'].disabled = True


class CashReplacementForm(StyledForm):
    transaction_type = forms.ChoiceField(label='Κατεύθυνση νέας κίνησης', choices=[('INCOME', 'Είσπραξη / έσοδο'), ('EXPENSE', 'Πληρωμή / έξοδο')])
    cash_account = forms.ModelChoiceField(label='Ταμείο αντικατάστασης', queryset=CashAccount.objects.none())
    entity = forms.ModelChoiceField(label='Συναλλασσόμενος νέας κίνησης', queryset=Entity.objects.none(), required=False)
    agreement = forms.ModelChoiceField(label='Συνδεδεμένη συμφωνία', queryset=Agreement.objects.none(), required=False)
    category = forms.ModelChoiceField(label='Κατηγορία', queryset=Category.objects.none(), required=False)
    amount = GreekMoneyField(label='Ποσό νέας κίνησης (€)', max_digits=12, decimal_places=2)
    description = forms.CharField(label='Περιγραφή νέας κίνησης', max_length=255)
    remarks = forms.CharField(label='Παρατηρήσεις', required=False, max_length=10000, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cash_account'].queryset = records(CashAccount, user).filter(is_active=True, opening_date__isnull=False)
        self.fields['category'].queryset = records(Category, user).filter(is_active=True)
        self.fields['entity'].queryset = records(Entity, user).filter(is_archived=False)
        self.fields['agreement'].queryset = records(Agreement, user).filter(entity__is_archived=False).exclude(status='CANCELLED')

    def clean_amount(self):
        return money(self.cleaned_data['amount'])


class TransferReplacementForm(StyledForm):
    from_account = forms.ModelChoiceField(label='Νέο ταμείο προέλευσης', queryset=CashAccount.objects.none())
    to_account = forms.ModelChoiceField(label='Νέο ταμείο προορισμού', queryset=CashAccount.objects.none())
    amount = GreekMoneyField(label='Ποσό νέας μεταφοράς (€)', max_digits=12, decimal_places=2)
    description = forms.CharField(label='Περιγραφή νέας μεταφοράς', max_length=200)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        for key in ('from_account', 'to_account'):
            self.fields[key].queryset = records(CashAccount, user).filter(is_active=True, opening_date__isnull=False)

    def clean_amount(self):
        return money(self.cleaned_data['amount'])


class RefundForm(CorrectionProofForm):
    cash_account = forms.ModelChoiceField(label='Ταμείο επιστροφής', queryset=CashAccount.objects.none())
    amount = GreekMoneyField(label='Ποσό επιστροφής (€)', max_digits=12, decimal_places=2)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cash_account'].queryset = records(CashAccount, user).filter(is_active=True, opening_date__isnull=False)

    def clean_amount(self):
        return money(self.cleaned_data['amount'])


class ChargeCorrectionForm(CorrectionProofForm):
    replace = forms.BooleanField(label='Νέα χρέωση αντικατάστασης μετά τον αντιλογισμό', required=False)
    replacement_amount = GreekMoneyField(label='Ποσό νέας χρέωσης (€)', required=False, max_digits=12, decimal_places=2)
    replacement_due_date = date_field('Προθεσμία νέας χρέωσης')
    replacement_due_date.required = False

    def clean(self):
        values = super().clean()
        if values.get('replace'):
            if values.get('replacement_amount') is None:
                self.add_error('replacement_amount', 'Συμπληρώστε το ποσό αντικατάστασης.')
            else:
                try: values['replacement_amount'] = money(values['replacement_amount'])
                except forms.ValidationError as error: self.add_error('replacement_amount', error)
            if not values.get('replacement_due_date'):
                self.add_error('replacement_due_date', 'Συμπληρώστε τη νέα προθεσμία.')
            elif values.get('effective_date') and values['replacement_due_date'] < values['effective_date']:
                self.add_error('replacement_due_date', 'Η προθεσμία δεν προηγείται της διόρθωσης.')
        return values


class AgreementChangeForm(CorrectionProofForm):
    expected_revision = forms.IntegerField(label='Έκδοση όρων', min_value=0, widget=forms.HiddenInput)
    description = forms.CharField(label='Περιγραφή νέων όρων', max_length=255)
    amount = GreekMoneyField(label='Συμφωνημένο ποσό νέων όρων (€)', max_digits=12, decimal_places=2)
    lifecycle = forms.ChoiceField(label='Ενέργεια συμφωνίας', choices=[('ACTIVE', 'Μελλοντική αλλαγή όρων'), ('CANCELLED', 'Ακύρωση από την ημερομηνία'), ('ENDED', 'Λήξη από την ημερομηνία')])

    def clean_effective_date(self):
        value = self.cleaned_data['effective_date']
        if value < timezone.localdate():
            raise forms.ValidationError('Η αλλαγή ή ακύρωση εφαρμόζεται από σήμερα ή από μελλοντική ημερομηνία.')
        return value

    def clean_amount(self):
        return money(self.cleaned_data['amount'])


class PeriodCloseForm(CorrectionProofForm):
    acknowledged = forms.BooleanField(label='Επιβεβαιώνω ότι κλείνω τις οικονομικές εγγραφές έως και αυτή την ημερομηνία.')
