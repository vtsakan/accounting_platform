# accounting/forms.py

from django import forms
from django.db import models
from django.utils import timezone
from .models import CashAccount, Category, Entity, Agreement
from django.utils.translation import gettext, gettext_lazy as _
from core.locale import GreekMoneyField, format_euro
from django.core.exceptions import PermissionDenied
from .membership import require_office_profile, DENIED
from .office_access import records, save_for_user


class GreekFormMixin:
    def __init__(self, *args, **kwargs):
        self.actor = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        if self.__class__.__name__ in {'IncomeForm','ExpenseForm','TransferForm'}:
            import uuid
            self.fields['posting_key']=forms.UUIDField(required=False,initial=uuid.uuid4,widget=forms.HiddenInput,label='Ταυτότητα καταχώρισης')
        self.office_id = require_office_profile(self.actor).office_id if self.actor is not None else None
        if isinstance(self, forms.ModelForm) and self.office_id:
            if self.instance.office_id and self.instance.office_id != self.office_id:
                raise PermissionDenied(DENIED)
            self.instance.office_id = self.office_id
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                model = field.queryset.model
                field.queryset = (field.queryset.filter(office_id=self.office_id)
                                  if self.office_id else model.objects.none())
            if field.label:
                field.label = gettext(str(field.label))
            if isinstance(field, forms.ChoiceField) and not isinstance(field, forms.ModelChoiceField):
                field.choices = [(key, gettext(str(label))) for key, label in field.choices]
            if isinstance(field, forms.DateField):
                # Native HTML date controls exchange ISO values, independent of display locale.
                field.widget.format = "%Y-%m-%d"
                field.input_formats = ["%Y-%m-%d", "%d/%m/%Y"]

    def clean(self):
        cleaned = super().clean()
        if self.actor is None:
            raise forms.ValidationError(DENIED)
        profile = require_office_profile(self.actor)
        if profile.office_id != self.office_id:
            raise forms.ValidationError(DENIED)
        from .finance_money import money
        for name in ('amount','total_amount'):
            if name in cleaned:
                try:cleaned[name]=money(cleaned[name])
                except forms.ValidationError as error:self.add_error(name,error)
        if self.__class__.__name__ in {'IncomeForm', 'ExpenseForm'} and not getattr(self, 'replay_entry', None):
            day, account = cleaned.get('transaction_date'), cleaned.get('cash_account')
            if day and day > timezone.localdate():
                self.add_error('transaction_date', 'Η ημερομηνία κίνησης δεν μπορεί να είναι μελλοντική.')
            elif day and account and account.opening_date and day < account.opening_date:
                self.add_error('transaction_date', 'Η κίνηση δεν μπορεί να προηγείται του αρχικού υπολοίπου του ταμείου.')
        selected,agreement=cleaned.get('entity'),cleaned.get('agreement')
        if agreement and selected and selected.pk!=agreement.entity_id:
            self.add_error('agreement','Η συμφωνία πρέπει να ανήκει στον ίδιο συναλλασσόμενο.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        profile = require_office_profile(self.actor)
        if profile.office_id != self.office_id:
            raise PermissionDenied(DENIED)
        instance.office_id = self.office_id
        if commit:
            save_for_user(instance, self.actor)
            self.save_m2m()
        return instance

# A dictionary of common Bootstrap attributes to avoid repetition
bootstrap_form_attrs = {'class': 'form-control'}
bootstrap_select_attrs = {'class': 'form-select'}


# This custom widget will add a data-type attribute to each option
class EntityTypeSelectWidget(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value:
            # Get the Entity instance for this option
            entity_instance = value.instance
            # Add the data-type attribute to the HTML option tag
            option['attrs']['data-type'] = entity_instance.entity_type
            option['attrs']['data-customer'] = '1' if entity_instance.is_customer else '0'
            option['attrs']['data-supplier'] = '1' if entity_instance.is_supplier else '0'
        return option

# This is the proper way to customize the dropdown labels.
class AgreementChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        # This method is called for each object to create its display text.
        # It can access annotated fields like 'remaining_balance'.
        if hasattr(obj, 'remaining_balance'):
            return f"{obj.description} (Ανεξόφλητο: {format_euro(obj.remaining_balance)})"
        # Fallback for when the balance isn't calculated
        return f"{obj.description} (Σύνολο: {format_euro(obj.total_amount)})"

class ExpenseForm(GreekFormMixin, forms.Form):
    transaction_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}), label="Ημερομηνία")
    description = forms.CharField(widget=forms.TextInput(attrs=bootstrap_form_attrs), label="Περιγραφή", max_length=255)
    amount = GreekMoneyField(label="Ποσό", max_digits=12, decimal_places=2)
    remarks = forms.CharField(required=False, max_length=10000, label="Παρατηρήσεις", widget=forms.Textarea(attrs={'rows': 3, **bootstrap_form_attrs}))
    cash_account = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=CashAccount.objects.filter(is_active=True,opening_date__isnull=False), label="Ταμείο")
    category = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Category.objects.filter(is_active=True), required=False, label="Κατηγορία")
    entity = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Entity.objects.filter(is_supplier=True, is_archived=False), required=False, label="Προμηθευτής")

    agreement = AgreementChoiceField( # Use our new custom field
        queryset=Agreement.objects.none(),
        required=False,
        label=_("Agreement (Payable)"),
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )
    def __init__(self, *args, **kwargs):
        agreements_queryset = kwargs.pop('agreements_queryset', None)
        super().__init__(*args, **kwargs)
        if agreements_queryset is not None:
            self.fields['agreement'].queryset = (agreements_queryset.filter(office_id=self.office_id, entity__is_archived=False)
                                                 if self.office_id else Agreement.objects.none())

class IncomeForm(GreekFormMixin, forms.Form):
    transaction_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}), label="Ημερομηνία")
    description = forms.CharField(widget=forms.TextInput(attrs=bootstrap_form_attrs), label="Περιγραφή", max_length=255)
    amount = GreekMoneyField(label="Ποσό", max_digits=12, decimal_places=2)
    remarks = forms.CharField(required=False, max_length=10000, label="Παρατηρήσεις", widget=forms.Textarea(attrs={'rows': 3, **bootstrap_form_attrs}))
    cash_account = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=CashAccount.objects.filter(is_active=True,opening_date__isnull=False), label="Ταμείο")
    category = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Category.objects.filter(is_active=True), required=False, label="Κατηγορία")
    entity = forms.ModelChoiceField(widget=forms.Select(attrs=bootstrap_select_attrs), queryset=Entity.objects.filter(is_customer=True, is_archived=False), required=False, label="Πελάτης")
    agreement = AgreementChoiceField( # Use our new custom field
        queryset=Agreement.objects.none(),
        required=False,
        label=_("Agreement (Receivable)"),
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )

    def __init__(self, *args, **kwargs):
        agreements_queryset = kwargs.pop('agreements_queryset', None)
        super().__init__(*args, **kwargs)
        if agreements_queryset is not None:
            self.fields['agreement'].queryset = (agreements_queryset.filter(office_id=self.office_id, entity__is_archived=False)
                                                 if self.office_id else Agreement.objects.none())

class EntityForm(GreekFormMixin, forms.ModelForm):
    vat_number = forms.CharField(label="Α.Φ.Μ.", max_length=64, required=False, widget=forms.TextInput(attrs=bootstrap_form_attrs))
    version = forms.IntegerField(label="Έκδοση εγγραφής", min_value=0, widget=forms.HiddenInput)
    legal_kind = forms.ChoiceField(label="Κατηγορία προσώπου", choices=[('', 'Επιλέξτε κατηγορία'),
        (Entity.LegalKind.INDIVIDUAL, 'Φυσικό πρόσωπο'), (Entity.LegalKind.BUSINESS, 'Επιχείρηση')],
        widget=forms.Select(attrs=bootstrap_select_attrs))

    class Meta:
        model = Entity
        fields = ['name', 'is_customer', 'is_supplier', 'legal_kind', 'vat_number', 'tax_office', 'address', 'city', 'postal_code', 'phone_number', 'email']
        widgets = {
            'name': forms.TextInput(attrs=bootstrap_form_attrs),
            'vat_number': forms.TextInput(attrs=bootstrap_form_attrs),
            'tax_office': forms.TextInput(attrs=bootstrap_form_attrs),
            'address': forms.TextInput(attrs=bootstrap_form_attrs),
            'city': forms.TextInput(attrs=bootstrap_form_attrs),
            'postal_code': forms.TextInput(attrs=bootstrap_form_attrs),
            'phone_number': forms.TextInput(attrs=bootstrap_form_attrs),
            'email': forms.EmailInput(attrs=bootstrap_form_attrs),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['version'].initial = self.instance.record_version
        self.fields['name'].label = "Ονοματεπώνυμο ή επωνυμία"
        self.fields['vat_number'].max_length = 64
        self.fields['vat_number'].help_text = "Εννέα ψηφία ή κενό. Γίνονται δεκτά κενά, παύλες και το πρόθεμα EL."
        self.fields['vat_number'].widget.attrs.update(inputmode='text', autocomplete='off')
        for name in ('is_customer', 'is_supplier'):
            self.fields[name].widget.attrs['class'] = 'form-check-input'

    def clean(self):
        cleaned = super().clean()
        from .counterparty_validation import contact_values
        if 'name' in cleaned:
            cleaned.update(contact_values(cleaned))
        if not (cleaned.get('is_customer') or cleaned.get('is_supplier')):
            raise forms.ValidationError("Επιλέξτε τουλάχιστον έναν ρόλο: πελάτης ή προμηθευτής.")
        return cleaned

    def save(self, commit=True):
        if not commit:
            return super().save(commit=False)
        from .counterparty_services import FIELDS, save_counterparty
        self.instance = save_counterparty(self.actor, {name:self.cleaned_data[name] for name in FIELDS},
            key=self.instance.pk, version=self.cleaned_data['version'])
        return self.instance

class AgreementForm(GreekFormMixin, forms.ModelForm):
    total_amount = GreekMoneyField(label=_("Total Agreed Amount"), max_digits=12, decimal_places=2)
    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}),
        label=_("Start Date")
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
            'status': forms.Select(attrs=bootstrap_select_attrs),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep an unchanged historical link visible on edit; new choices are active.
        self.fields['entity'].queryset = self.fields['entity'].queryset.filter(
            models.Q(is_archived=False) | (models.Q(pk=self.instance.entity_id) if self.instance.pk else models.Q(pk__in=[])))

# accounting/forms.py

from django import forms
from .models import CashAccount, Category, Entity, Agreement

# ... (your existing form classes) ...


class TransferForm(GreekFormMixin, forms.Form):
    transfer_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', **bootstrap_form_attrs}),
        label=_("Transfer Date")
    )
    amount = GreekMoneyField(
        label=_("Amount"),
        max_digits=12,
        decimal_places=2,
    )
    from_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.filter(is_active=True,opening_date__isnull=False),
        label=_("From Account"),
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )
    to_account = forms.ModelChoiceField(
        queryset=CashAccount.objects.filter(is_active=True,opening_date__isnull=False),
        label=_("To Account"),
        widget=forms.Select(attrs=bootstrap_select_attrs)
    )
    description = forms.CharField(label=_("Description"), max_length=255, widget=forms.TextInput(attrs=bootstrap_form_attrs))

    # This is a custom validation method
    def clean(self):
        cleaned_data = super().clean()
        from_account = cleaned_data.get("from_account")
        to_account = cleaned_data.get("to_account")

        if from_account and to_account and from_account == to_account:
            raise forms.ValidationError(_("The source and destination cash accounts must differ."))

        return cleaned_data
