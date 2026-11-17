"""Owner-confirmed opt-in and scoped, read-only reconciliation in Greek."""
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from .capabilities import office_view
from .fee_forms import GreekFeeForm
from .fee_services import schedules, month
from .fee_generation_services import configure_automation, reconciliation
from .fee_views import failed


class AutomationForm(GreekFeeForm):
    enabled=forms.BooleanField(required=False,label='Ενεργοποίηση αυτόματης δημιουργίας για τον τρέχοντα και τους επόμενους μήνες')
    expected_revision=forms.IntegerField(min_value=0,widget=forms.HiddenInput,label='Έκδοση εξουσιοδότησης')
    password=forms.CharField(label='Κωδικός πρόσβασης',widget=forms.PasswordInput)


class ReconciliationForm(forms.Form):
    start_period=forms.CharField(label='Μήνας ελέγχου',required=False,max_length=7,
        widget=forms.TextInput(attrs={'type':'month','class':'form-control'}))

    def clean_start_period(self):
        return month(self.cleaned_data['start_period']) if self.cleaned_data['start_period'] else None


@office_view('finance.amend',mfa=True)
@never_cache
@sensitive_post_parameters('password','reason')
@require_http_methods(['GET','POST'])
def automation(request,key):
    schedule=get_object_or_404(schedules(request.user),pk=key);latest=schedule.automations.first()
    form=AutomationForm(request.POST if request.method=='POST' else None,
        initial={'enabled':latest.enabled if latest else False,'expected_revision':latest.revision if latest else 0})
    if request.method=='POST' and form.is_valid():
        try:configure_automation(request,schedule_id=key,**form.cleaned_data)
        except (ValidationError,DatabaseError) as error:failed(form,error)
        else:return redirect('fee-automation',key=key)
    return render(request,'accounting/fees/automation.html',{'schedule':schedule,'form':form,'versions':schedule.automations.all(),
        'automation_available':settings.FEE_AUTOMATION_ENABLED and settings.BACKGROUND_JOBS_ENABLED})


@office_view('finance.read')
@never_cache
@require_http_methods(['GET'])
def reconciliation_view(request):
    form=ReconciliationForm(request.GET if request.GET else None)
    result=None
    if not request.GET or form.is_valid():
        # The office/month view deliberately uses one period, not a write action.
        from django.utils import timezone
        period=(form.cleaned_data.get('start_period') if request.GET else None) or timezone.localdate().replace(day=1)
        result=reconciliation(request.user,period=period)
    return render(request,'accounting/fees/reconciliation.html',{'form':form,'result':result})
