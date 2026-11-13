"""Typed, office-scoped movement filters shared by the list and report."""
from django import forms
from .capabilities import require_capability
from .models import CashAccount, Category, Entity


class CashMovementFilterForm(forms.Form):
    start_date = forms.DateField(required=False, label='Από ημερομηνία', input_formats=['%Y-%m-%d', '%d/%m/%Y'], widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    end_date = forms.DateField(required=False, label='Έως ημερομηνία', input_formats=['%Y-%m-%d', '%d/%m/%Y'], widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    transaction_type = forms.ChoiceField(required=False, label='Κατεύθυνση', choices=[('', 'Όλες οι κατευθύνσεις'), ('INCOME', 'Εισερχόμενα'), ('EXPENSE', 'Εξερχόμενα')])
    cash_account = forms.ModelChoiceField(required=False, label='Ταμείο', queryset=CashAccount.objects.none(), empty_label='Όλα τα ταμεία')
    category = forms.ModelChoiceField(required=False, label='Κατηγορία', queryset=Category.objects.none(), empty_label='Όλες οι κατηγορίες')
    entity = forms.ModelChoiceField(required=False, label='Συναλλασσόμενος', queryset=Entity.objects.none(), empty_label='Όλοι οι συναλλασσόμενοι')
    query = forms.CharField(required=False, max_length=255, label='Περιγραφή')
    page_size = forms.TypedChoiceField(required=False, coerce=int, empty_value=25, label='Κινήσεις ανά σελίδα', choices=[(25, '25'), (50, '50'), (100, '100')])
    page = forms.IntegerField(required=False, min_value=1, max_value=2147483647, widget=forms.HiddenInput, label='Σελίδα')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = user
        self.office_id = require_capability(user, 'finance.read').office_id
        # Historical filters deliberately include inactive/archived references.
        for field, model in [('cash_account', CashAccount), ('category', Category), ('entity', Entity)]:
            self.fields[field].queryset = model.objects.filter(office_id=self.office_id).order_by('name', 'pk')
        self.fields['category'].queryset = self.fields['category'].queryset.select_related('parent')
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'form-select' if isinstance(field, forms.ChoiceField) else 'form-control')

    def clean(self):
        values = super().clean()
        if require_capability(self.actor, 'finance.read').office_id != self.office_id:
            raise forms.ValidationError('Η πρόσβαση στο γραφείο άλλαξε. Συνδεθείτε ξανά.')
        if hasattr(self.data, 'getlist'):
            for name in self.fields:
                if len(self.data.getlist(name)) > 1:
                    self.add_error(name, 'Υποβάλετε μία μόνο τιμή για αυτό το φίλτρο.')
        if values.get('start_date') and values.get('end_date') and values['start_date'] > values['end_date']:
            self.add_error('end_date', 'Η τελική ημερομηνία δεν μπορεί να προηγείται της αρχικής.')
        values['page'] = values.get('page') or 1
        values['page_size'] = values.get('page_size') or 25
        return values
