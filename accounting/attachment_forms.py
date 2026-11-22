"""One private attachment per submission; catalogue belongs to the office."""
import uuid
from django import forms
from django.db.models import Q

from .attachment_models import AttachmentCategory,FILE_TYPES,MAX_FILE_BYTES
from .attachment_selectors import categories


class AttachmentForm(forms.Form):
    category=forms.ModelChoiceField(label='Χαρακτηρισμός',queryset=AttachmentCategory.objects.none(),empty_label='Επιλέξτε χαρακτηρισμό')
    description=forms.CharField(label='Περιγραφή',max_length=1000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    file=forms.FileField(label='Αρχείο',help_text='Έως 25 μεγαμπάιτ. Έγγραφα και εικόνες, χωρίς κωδικό προστασίας ή μακροεντολές.')
    request_key=forms.UUIDField(widget=forms.HiddenInput)
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput,required=False)

    def __init__(self,*args,user,row=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['category'].queryset=categories(user).filter(Q(is_active=True)|Q(pk=row.category_id if row else None))
        self.fields['request_key'].initial=uuid.uuid4()
        self.fields['file'].widget.attrs['accept']=','.join('.'+x for x in FILE_TYPES)
        if row:
            self.fields.pop('file');self.fields.pop('request_key');self.fields['version'].required=True
            self.initial.update(category=row.category_id,description=row.description,version=row.record_version)
        else:self.fields.pop('version')
        for field in self.fields.values():field.widget.attrs['class']='form-control'

    def clean_file(self):
        value=self.cleaned_data['file']
        if value.size>MAX_FILE_BYTES:raise forms.ValidationError('Το αρχείο υπερβαίνει τα 25 μεγαμπάιτ.')
        return value


class AttachmentCategoryForm(forms.Form):
    name=forms.CharField(label='Χαρακτηρισμός',max_length=80)
    is_active=forms.BooleanField(label='Ενεργός χαρακτηρισμός',required=False,initial=True)
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput,initial=0)


class AttachmentRemoveForm(forms.Form):
    version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='Επιβεβαιώνω την οριστική αφαίρεση του αρχείου')


class AttachmentFilterForm(forms.Form):
    attachment_category=forms.ModelChoiceField(label='Χαρακτηρισμός',queryset=AttachmentCategory.objects.none(),required=False,empty_label='Όλοι οι χαρακτηρισμοί')
    attachment_q=forms.CharField(label='Όνομα αρχείου ή περιγραφή',max_length=100,required=False)

    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs);self.fields['attachment_category'].queryset=categories(user)
        for field in self.fields.values():field.widget.attrs['class']='form-control'
