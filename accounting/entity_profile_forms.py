"""Four Greek form sections, explicit contact state and write-only credential inputs."""
from django import forms
from django.core.exceptions import ValidationError
from django.views.decorators.debug import sensitive_variables

from .forms import EntityForm
from .entity_profile_models import CONTACT_FIELDS, FLAG_LABELS, PERSON_KINDS
from .entity_profile_selectors import profile_for, tags_in_office
from .entity_profile_services import PROFILE_FIELDS, save_profile, validate_credentials
from .entity_profile_validation import profile_values


class EntityProfileForm(EntityForm):
    contact_status = forms.ChoiceField(label='Κατάσταση', choices=[('ACTIVE','Ενεργός'),('INACTIVE','Ανενεργός')])
    person_kind = forms.ChoiceField(label='Κατηγορία προσώπου', choices=[('','Επιλέξτε κατηγορία'),*PERSON_KINDS])
    main_amka = forms.CharField(label='ΑΜΚΑ υπόχρεου', max_length=11, required=False)
    spouse_enabled = forms.BooleanField(label='Καταχώριση στοιχείων συζύγου',required=False)
    spouse_first_name = forms.CharField(label='Όνομα συζύγου',max_length=100,required=False)
    spouse_last_name = forms.CharField(label='Επώνυμο συζύγου',max_length=100,required=False)
    spouse_vat_number = forms.CharField(label='ΑΦΜ συζύγου',max_length=64,required=False)
    spouse_tax_office = forms.CharField(label='ΔΟΥ συζύγου',max_length=100,required=False)
    spouse_amka = forms.CharField(label='ΑΜΚΑ συζύγου',max_length=11,required=False)
    spouse_person_kind = forms.ChoiceField(label='Κατηγορία προσώπου συζύγου',choices=[('','Επιλέξτε κατηγορία'),*PERSON_KINDS],required=False)
    spouse_inherit_contacts = forms.BooleanField(label='Κοινά στοιχεία επικοινωνίας με τον υπόχρεο',required=False,initial=True)
    spouse_address = forms.CharField(label='Διεύθυνση συζύγου',max_length=255,required=False)
    spouse_city = forms.CharField(label='Πόλη συζύγου',max_length=100,required=False)
    spouse_postal_code = forms.CharField(label='Ταχυδρομικός κώδικας συζύγου',max_length=10,required=False)
    spouse_phone_number = forms.CharField(label='Τηλέφωνο συζύγου',max_length=20,required=False)
    spouse_email = forms.CharField(label='Email συζύγου',max_length=254,required=False)
    liable_a21 = forms.BooleanField(label=FLAG_LABELS['liable_a21'],required=False)
    prefilled_return = forms.BooleanField(label=FLAG_LABELS['prefilled_return'],required=False)
    disability = forms.BooleanField(label=FLAG_LABELS['disability'],required=False)
    rent_subsidy = forms.BooleanField(label=FLAG_LABELS['rent_subsidy'],required=False)
    rented_home = forms.BooleanField(label=FLAG_LABELS['rented_home'],required=False)
    student_allowance = forms.BooleanField(label=FLAG_LABELS['student_allowance'],required=False)
    tags = forms.CharField(label='Ετικέτες',required=False,max_length=1100,
        help_text='Έως 25 ετικέτες χωρισμένες με κόμμα, π.χ. επιδοτούμενος, ανήλικα τέκνα.')
    internal_notes = forms.CharField(label='Γενικές σημειώσεις και παρατηρήσεις γραφείου',required=False,max_length=10000,
        widget=forms.Textarea(attrs={'rows':7}))
    main_taxis_username = forms.CharField(label='TaxisNet υπόχρεου — username',max_length=200,required=False,strip=False,widget=forms.PasswordInput)
    main_taxis_password = forms.CharField(label='TaxisNet υπόχρεου — password',max_length=512,required=False,strip=False,widget=forms.PasswordInput)
    main_taxis_clear = forms.BooleanField(label='Αφαίρεση αποθηκευμένων κωδικών υπόχρεου',required=False)
    spouse_taxis_username = forms.CharField(label='TaxisNet συζύγου — username',max_length=200,required=False,strip=False,widget=forms.PasswordInput)
    spouse_taxis_password = forms.CharField(label='TaxisNet συζύγου — password',max_length=512,required=False,strip=False,widget=forms.PasswordInput)
    spouse_taxis_clear = forms.BooleanField(label='Αφαίρεση αποθηκευμένων κωδικών συζύγου',required=False)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['legal_kind'].widget=forms.HiddenInput()
        self.initial['legal_kind']=self.instance.legal_kind if self.instance.legal_kind in {'BUSINESS','INDIVIDUAL'} else 'INDIVIDUAL'
        self.initial.update(contact_status='ACTIVE',spouse_inherit_contacts=True)
        self.profile=profile_for(self.instance) if self.instance.pk else None
        if self.profile:
            self.initial.update({name:getattr(self.profile,name) for name in PROFILE_FIELDS})
            self.initial['tags']=', '.join(self.profile.tags)
        elif self.instance.pk and self.instance.legal_kind=='INDIVIDUAL':
            self.initial['person_kind']='INDIVIDUAL'
        if self.profile and self.profile.person_kind=='UNREVIEWED':self.initial['person_kind']=''
        if self.profile and self.profile.spouse_person_kind=='UNREVIEWED':self.initial['spouse_person_kind']=''
        for name,field in self.fields.items():
            if field.widget.is_hidden:continue
            field.widget.attrs['class']='form-check-input' if isinstance(field,forms.BooleanField) else 'form-select' if isinstance(field,forms.ChoiceField) else 'form-control'
            if '_taxis_' in name and not name.endswith('_clear'):
                field.widget.attrs.update(autocomplete='new-password', spellcheck='false')
        self.sections=[
            ('basic','Βασικά στοιχεία', ['name','is_customer','is_supplier','contact_status','person_kind','vat_number','tax_office','main_amka',*CONTACT_FIELDS,'main_taxis_username','main_taxis_password','main_taxis_clear']),
            ('spouse','Σύζυγος',['spouse_enabled','spouse_first_name','spouse_last_name','spouse_vat_number','spouse_tax_office','spouse_amka','spouse_person_kind','spouse_inherit_contacts',*['spouse_'+name for name in CONTACT_FIELDS],'spouse_taxis_username','spouse_taxis_password','spouse_taxis_clear']),
            ('tax','Φορολογικά χαρακτηριστικά',[*FLAG_LABELS,'tags']),
            ('notes','Σημειώσεις',['internal_notes']),
        ]
        self.profile_sections=[{'id':key,'title':title,'fields':[self[name] for name in names]} for key,title,names in self.sections]
        self.spouse_contact_names=['spouse_'+name for name in CONTACT_FIELDS]

    @sensitive_variables('__ALL__')
    def clean(self):
        values=super().clean()
        if all(name in values for name in ('contact_status','person_kind')):
            try:values.update(profile_values({name:values.get(name,'') for name in PROFILE_FIELDS}))
            except ValidationError as error:
                for name,errors in error.error_dict.items():self.add_error(name,errors)
        try:validate_credentials(values)
        except ValidationError as error:
            if hasattr(error,'error_dict'):
                for name,errors in error.error_dict.items():self.add_error(name,errors)
            else:self.add_error(None,error)
        return values

    @sensitive_variables('__ALL__')
    def save(self,commit=True):
        if not commit:raise ValueError('Το προφίλ και οι κωδικοί αποθηκεύονται μαζί.')
        from .counterparty_services import FIELDS
        self.instance=save_profile(self.actor,{name:self.cleaned_data[name] for name in FIELDS},
            {name:self.cleaned_data[name] for name in PROFILE_FIELDS},self.cleaned_data,
            key=self.instance.pk,version=self.cleaned_data['version'])
        return self.instance


class ProfileSearchMixin:
    def add_profile_filters(self,user):
        self.fields['kind'].widget=forms.HiddenInput()
        self.fields['contact_status']=forms.ChoiceField(label='Κατάσταση επαφής',required=False,
            choices=[('ACTIVE','Ενεργοί'),('INACTIVE','Ανενεργοί'),('ALL','Όλοι')])
        self.fields['person_kind']=forms.ChoiceField(label='Φορολογική κατηγορία',required=False,
            choices=[('','Όλες οι κατηγορίες'),*PERSON_KINDS])
        self.fields['tags']=forms.MultipleChoiceField(label='Ετικέτες',required=False,choices=[(t,t) for t in tags_in_office(user)])
        self.fields['tag_mode']=forms.ChoiceField(label='Συνδυασμός ετικετών',required=False,choices=[('ALL','Όλες οι επιλεγμένες'),('ANY','Οποιαδήποτε επιλεγμένη')])
        self.fields['group_by']=forms.ChoiceField(label='Ομαδοποίηση εκτύπωσης / εξαγωγής',required=False,
            choices=[('','Χωρίς ομαδοποίηση'),('person_kind','Κατηγορία προσώπου'),('contact_status','Κατάσταση'),('tags','Ετικέτες')])
        for name,label in FLAG_LABELS.items():self.fields[name]=forms.BooleanField(label=label,required=False)
        for field in self.fields.values():
            field.widget.attrs['class']='form-check-input' if isinstance(field,forms.BooleanField) else 'form-select' if isinstance(field,forms.ChoiceField) else 'form-control'
