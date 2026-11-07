# accounting/forms.py

from django import forms
from .models import CashAccount, Category, Entity, Agreement

# A dictionary of common Bootstrap attributes to avoid repetition
bootstrap_form_attrs = {'class': 'form-control'}
bootstrap_select_attrs = {'class': 'form-select'}


# This custom widget will add a data-type attribute to each option
class EntityTypeSelectWidget(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            # Get the Entity instance for this option
            entity_instance = self.choices.queryset.get(pk=value.value)
            # Add the data-type attribute to the HTML option tag
            option['attrs']['data-type'] = entity_instance.entity_type
        return option
    
# This is the proper way to customize the dropdown labels.
class AgreementChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # This method is called for each object to create its display text.
        # It can access annotated fields like 'remaining_balance'.
        if hasattr(obj, 'remaining_balance'):
            return f"{obj.description} (Remaining: {obj.remaining_balance}€)"
        # Fallback for when the balance isn't calculated
        return f"{obj.description} (Total: {obj.total_amount}€)"

class ExpenseForm(forms.Form):
    transaction_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}), label="Ημερομηνία")
    description = forms.CharField(widget=forms.TextInput(attrs=bootstrap_form_attrs), label="Περιγραφή", max_length=255)
    amount = forms.DecimalField(widget=forms.NumberInput(attrs=bootstrap_form_attrs), label="Ποσό", max_digits=12, decimal_places=2)
    cash_account = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=CashAccount.objects.filter(is_active=True), label="Ταμείο")
    category = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Category.objects.all(), label="Κατηγορία")
    entity = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Entity.objects.filter(entity_type='SUPPLIER'), required=False, label="Προμηθευτής (Supplier)")
    
    agreement = AgreementChoiceField( # Use our new custom field
        queryset=Agreement.objects.none(),
        required=False,
        label="Agreement (Payable)",
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )
    def __init__(self, *args, **kwargs):
        agreements_queryset = kwargs.pop('agreements_queryset', None)
        super().__init__(*args, **kwargs)
        if agreements_queryset is not None:
            self.fields['agreement'].queryset = agreements_queryset

class IncomeForm(forms.Form):
    transaction_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}), label="Ημερομηνία")
    description = forms.CharField(widget=forms.TextInput(attrs=bootstrap_form_attrs), label="Περιγραφή", max_length=255)
    amount = forms.DecimalField(widget=forms.NumberInput(attrs=bootstrap_form_attrs), label="Ποσό", max_digits=12, decimal_places=2)
    cash_account = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=CashAccount.objects.filter(is_active=True), label="Ταμείο")
    category = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Category.objects.all(), label="Κατηγορία")
    entity = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Entity.objects.filter(entity_type='CUSTOMER'), required=False, label="Πελάτης (Customer)")
    agreement = AgreementChoiceField( # Use our new custom field
        queryset=Agreement.objects.none(),
        required=False,
        label="Agreement (Receivable)",
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )

    def __init__(self, *args, **kwargs):
        agreements_queryset = kwargs.pop('agreements_queryset', None)
        super().__init__(*args, **kwargs)
        if agreements_queryset is not None:
            self.fields['agreement'].queryset = agreements_queryset

class EntityForm(forms.ModelForm):
    class Meta:
        model = Entity
        fields = ['name', 'entity_type', 'vat_number', 'tax_office', 'address', 'city', 'postal_code', 'phone_number', 'email']
        widgets = {
            'name': forms.TextInput(attrs=bootstrap_form_attrs),
            'entity_type': forms.Select(attrs=bootstrap_select_attrs),
            'vat_number': forms.TextInput(attrs=bootstrap_form_attrs),
            'tax_office': forms.TextInput(attrs=bootstrap_form_attrs),
            'address': forms.TextInput(attrs=bootstrap_form_attrs),
            'city': forms.TextInput(attrs=bootstrap_form_attrs),
            'postal_code': forms.TextInput(attrs=bootstrap_form_attrs),
            'phone_number': forms.TextInput(attrs=bootstrap_form_attrs),
            'email': forms.EmailInput(attrs=bootstrap_form_attrs),
        }

class AgreementForm(forms.ModelForm):
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}),
        label="Start Date"
    )
    
    class Meta:
        model = Agreement
        fields = [
            'entity',
            'agreement_type',
            'description',
            'total_amount',
            'start_date',
            'status',
        ]
        widgets = {
            # Use our new custom widget for the 'entity' field
            'entity': EntityTypeSelectWidget(attrs=bootstrap_select_attrs),
            'agreement_type': forms.Select(attrs=bootstrap_select_attrs),
            'description': forms.TextInput(attrs=bootstrap_form_attrs),
            'total_amount': forms.NumberInput(attrs=bootstrap_form_attrs),
            'status': forms.Select(attrs=bootstrap_select_attrs),
        }

# accounting/forms.py

from django import forms
from .models import CashAccount, Category, Entity, Agreement

# ... (your existing form classes) ...


class TransferForm(forms.Form):
    transfer_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}),
        label="Transfer Date"
    )
    amount = forms.DecimalField(
        label="Amount", 
        max_digits=12, 
        decimal_places=2,
        widget=forms.NumberInput(attrs=bootstrap_form_attrs)
    )
    from_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.filter(is_active=True),
        label="From Account",
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )
    to_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.filter(is_active=True),
        label="To Account",
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )
    description = forms.CharField(label="Description", max_length=255, widget=forms.TextInput(attrs=bootstrap_form_attrs))

    # This is a custom validation method
    def clean(self):
        cleaned_data = super().clean()
        from_account = cleaned_data.get("from_account")
        to_account = cleaned_data.get("to_account")

        if from_account and to_account and from_account == to_account:
            raise forms.ValidationError("The 'From' and 'To' accounts cannot be the same.")

        return cleaned_data