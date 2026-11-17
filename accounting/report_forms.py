"""Typed report bases; cash-period filters and dated debt have separate labels."""
from django import forms
from django.utils import timezone
from .movement_forms import CashMovementFilterForm


class PeriodReportForm(CashMovementFilterForm):
    as_of=forms.DateField(required=False,label='Υπόλοιπα χρεώσεων έως',input_formats=['%Y-%m-%d','%d/%m/%Y'],
        widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    charge_page=forms.IntegerField(required=False,min_value=1,max_value=2147483647,widget=forms.HiddenInput,label='Σελίδα χρεώσεων')
    credit_page=forms.IntegerField(required=False,min_value=1,max_value=2147483647,widget=forms.HiddenInput,label='Σελίδα αδιάθετων ποσών')
    event_page=forms.IntegerField(required=False,min_value=1,max_value=2147483647,widget=forms.HiddenInput,label='Σελίδα αντιστοιχίσεων')

    def clean(self):
        values=super().clean();today=timezone.localdate()
        as_of=values.get('as_of') or values.get('end_date') or today
        values['as_of']=as_of
        for name in ('as_of','start_date','end_date'):
            if values.get(name) and values[name]>today:self.add_error(name,'Η ημερομηνία δεν μπορεί να είναι μελλοντική.')
        if values.get('end_date') and values['end_date']>as_of:
            self.add_error('as_of','Η ημερομηνία αναφοράς δεν προηγείται του τέλους της περιόδου.')
        if values.get('start_date') and values['start_date']>as_of:
            self.add_error('start_date','Η αρχική ημερομηνία δεν έπεται της ημερομηνίας αναφοράς.')
        return values


class StatementForm(PeriodReportForm):
    def __init__(self,data=None,*,user,entity,**kwargs):
        data=data.copy() if data is not None else {}
        if 'entity' not in data:data['entity']=str(entity.pk)
        super().__init__(data,user=user,**kwargs)
        self.fixed_entity=entity
        for name in ('cash_account','category','transaction_type','query'):self.fields.pop(name)
        self.fields['entity'].widget=forms.HiddenInput()

    def clean(self):
        values=super().clean()
        if values.get('entity') is None or values['entity'].pk!=self.fixed_entity.pk:
            self.add_error('entity','Τα φίλτρα πρέπει να αφορούν την επιλεγμένη καρτέλα.')
        return values


class AnnualReportForm(PeriodReportForm):
    year=forms.IntegerField(min_value=1,max_value=9999,required=False,label='Έτος',widget=forms.NumberInput)
    month=forms.IntegerField(min_value=1,max_value=12,required=False,label='Ανάλυση μήνα',widget=forms.NumberInput)

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for name in ('start_date','end_date','cash_account','category','transaction_type','query','event_page'):self.fields.pop(name)

    def clean(self):
        values=super().clean();as_of=values.get('as_of') or timezone.localdate()
        values['year']=values.get('year') or as_of.year
        values['month']=values.get('month') or min(timezone.localdate().month,12)
        if values['year']>as_of.year:self.add_error('year','Το έτος δεν μπορεί να έπεται της ημερομηνίας αναφοράς.')
        return values
