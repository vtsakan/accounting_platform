"""Greek account/category workspace forms; office context is never a submitted field."""
import uuid
from django import forms
from django.db.models import Q
from django.utils import timezone
from core.locale import GreekMoneyField
from .models import Category
from .capabilities import require_capability

class StyledForm(forms.Form):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in self.fields.values():
            if not isinstance(field.widget,(forms.HiddenInput,forms.CheckboxInput)):
                field.widget.attrs.setdefault('class','form-control')
        for name,field in self.fields.items():
            if isinstance(field,forms.DateField):
                field.input_formats=['%Y-%m-%d','%d/%m/%Y'];field.widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date','class':'form-control'})

class AccountForm(StyledForm):
    name=forms.CharField(max_length=100,label='Όνομα ταμείου')
    is_active=forms.BooleanField(required=False,initial=True,label='Ενεργό ταμείο')
    version=forms.IntegerField(min_value=0,initial=0,widget=forms.HiddenInput,label='Έκδοση')

class CategoryForm(StyledForm):
    name=forms.CharField(max_length=100,label='Όνομα κατηγορίας')
    parent=forms.ModelChoiceField(queryset=Category.objects.none(),required=False,label='Γονική κατηγορία',empty_label='Χωρίς γονική κατηγορία')
    is_active=forms.BooleanField(required=False,initial=True,label='Ενεργή κατηγορία')
    version=forms.IntegerField(min_value=0,initial=0,widget=forms.HiddenInput,label='Έκδοση')

    def __init__(self,*args,user,instance=None,**kwargs):
        super().__init__(*args,**kwargs)
        office=require_capability(user,'finance.write').office_id
        qs=Category.objects.filter(office_id=office)
        excluded={instance.pk} if instance else set()
        if instance:
            links=list(qs.values_list('id','parent_id'));changed=True
            while changed:
                next_ids={key for key,parent in links if parent in excluded};changed=bool(next_ids-excluded);excluded|=next_ids
        available=qs.filter(is_active=True)
        if instance and instance.parent_id:available=qs.filter(Q(is_active=True)|Q(pk=instance.parent_id))
        self.fields['parent'].queryset=available.exclude(pk__in=excluded).select_related('parent').order_by('name','pk')

class StateForm(StyledForm):
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput,label='Έκδοση')
    active=forms.BooleanField(required=False,widget=forms.HiddenInput,label='Νέα κατάσταση')

class OpeningForm(StyledForm):
    amount=GreekMoneyField(max_digits=12,decimal_places=2,label='Αρχικό υπόλοιπο')
    effective_date=forms.DateField(label='Ημερομηνία έναρξης αρχικού υπολοίπου')
    reason=forms.CharField(max_length=250,label='Αιτιολογία')
    review_reference=forms.CharField(max_length=200,label='Αναφορά ελέγχου',help_text='Σύντομη αναφορά στο στοιχείο που ελέγξατε, χωρίς κωδικούς ή διαπιστευτήρια.')
    password=forms.CharField(required=False,widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}),label='Κωδικός πρόσβασης')
    review_token=forms.CharField(required=False,widget=forms.HiddenInput,label='Προεπισκόπηση')
    idempotency_key=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput,label='Ταυτότητα αιτήματος')
    acknowledged=forms.BooleanField(required=False,label='Επιβεβαιώνω την ημερομηνία και ότι το αρχικό ποσό περιλαμβάνει τις προγενέστερες κινήσεις που εξαιρούνται από τον υπολογισμό.')

class AdjustmentForm(StyledForm):
    amount=GreekMoneyField(required=False,max_digits=12,decimal_places=2,label='Προσαρμογή με πρόσημο',help_text='Θετικό ποσό αυξάνει το ταμείο, αρνητικό το μειώνει. Δεν δημιουργείται έσοδο ή έξοδο.')
    effective_date=forms.DateField(initial=timezone.localdate,label='Ημερομηνία προσαρμογής',help_text='Επιτρέπεται μόνο η σημερινή ημερομηνία.')
    reason=forms.CharField(max_length=250,label='Αιτιολογία')
    review_reference=forms.CharField(max_length=200,label='Αναφορά ελέγχου αρχικού υπολοίπου')
    password=forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete':'current-password'}),label='Κωδικός πρόσβασης')
    idempotency_key=forms.UUIDField(initial=uuid.uuid4,widget=forms.HiddenInput,label='Ταυτότητα αιτήματος')
    reversal_of_id=forms.IntegerField(required=False,min_value=1,widget=forms.HiddenInput,label='Αρχική προσαρμογή')

class BalanceDateForm(StyledForm):
    as_of=forms.DateField(required=False,initial=timezone.localdate,label='Υπόλοιπο στις')
    def clean_as_of(self):
        value=self.cleaned_data['as_of'] or timezone.localdate()
        if value>timezone.localdate():raise forms.ValidationError('Η ημερομηνία υπολοίπου δεν μπορεί να είναι μελλοντική.')
        return value
