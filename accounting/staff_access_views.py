"""Owner provisioning and password-only forced change before normal MFA."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404,HttpResponseRedirect
from django.shortcuts import redirect,render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
import django_otp

from .auth_models import AuthenticatorDevice
from .auth_policy import bind_session,recent_mfa,require_eligible,requires_mfa,reserve_attempt
from .auth_views import limited,safe_next
from .capabilities import office_view,require_capability
from .models import AccountantProfile
from .office_views import budget,validation
from .staff_access_forms import DirectStaffForm,RequiredPasswordForm,ResetStaffForm
from .staff_access_models import StaffCredentialRequirement
from .staff_access_services import create_direct_staff,finish_required_password_change,require_installation,reset_staff_password


@office_view('staff.manage',mfa=True)
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def direct_create(request):
    require_installation();request.session['s13_next']=request.path
    form=DirectStaffForm(request.POST if request.method=='POST' else None)
    if request.method=='POST':
        if not budget(request):return limited(request)
        if validation(form,lambda data:create_direct_staff(request,username=data['username'],role=data['role'],
                temporary_password=data['temporary_password'],owner_password=data['owner_password'])):
            messages.success(request,'Ο λογαριασμός δημιουργήθηκε. Ο χρήστης θα αλλάξει τον προσωρινό κωδικό στην πρώτη σύνδεση.')
            return redirect('office-members')
    return render(request,'accounting/office/direct_staff.html',{'form':form,'title':'Νέος χρήστης γραφείου','recent':recent_mfa(request)})


@office_view('staff.manage',mfa=True)
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def direct_reset(request,user_id):
    require_installation();office=require_capability(request.user,'staff.manage').office
    target=AccountantProfile.objects.select_related('user').filter(office=office,user_id=user_id,
        user__is_staff=False,user__is_superuser=False).exclude(user_id=request.user.pk).first()
    if target is None:raise Http404('Ο χρήστης δεν βρέθηκε.')
    row=StaffCredentialRequirement.objects.filter(user_id=user_id,office=office).first()
    form=ResetStaffForm(request.POST if request.method=='POST' else None,initial={'version':row.version if row else -1})
    request.session['s13_next']=request.path
    if request.method=='POST':
        if not budget(request):return limited(request)
        if validation(form,lambda data:reset_staff_password(request,user_id,temporary_password=data['temporary_password'],
                owner_password=data['owner_password'],version=data['version'])):
            messages.success(request,'Ο προσωρινός κωδικός αντικαταστάθηκε. Οι παλιές συνεδρίες έληξαν και απαιτείται αλλαγή στην επόμενη σύνδεση.')
            return redirect('office-members')
    return render(request,'accounting/office/direct_staff.html',{'form':form,'title':'Επαναφορά κωδικού χρήστη',
        'target_username':target.user.username,'recent':recent_mfa(request)})


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def required_change(request):
    require_installation();require_eligible(request.user)
    row=StaffCredentialRequirement.objects.filter(user_id=request.user.pk,required=True).first()
    if row is None:return HttpResponseRedirect(safe_next(request))
    form=RequiredPasswordForm(request.POST if request.method=='POST' else None,initial={'version':row.version})
    if request.method=='POST':
        if not reserve_attempt('manage',str(request.user.pk),request.META.get('REMOTE_ADDR')):return limited(request)
        if form.is_valid():
            try:
                user,state=finish_required_password_change(request,current_password=form.cleaned_data['current_password'],
                    new_password=form.cleaned_data['new_password'],version=form.cleaned_data['version'])
            except ValidationError as error:form.add_error(None,error)
            else:
                update_session_auth_hash(request,user)
                request.session.pop(django_otp.DEVICE_ID_SESSION_KEY,None);request.user.otp_device=None
                for key in ('s13_pending_device','s13_recovery_until','s13_mfa_at'):request.session.pop(key,None)
                bind_session(request,state,new_login=True)
                if requires_mfa(user,state):
                    first=not state.enrolled_at and not AuthenticatorDevice.objects.filter(user=user,confirmed=True).exists()
                    return redirect('mfa-setup' if first else 'mfa-verify')
                return HttpResponseRedirect(safe_next(request))
    return render(request,'accounting/auth/required_password.html',{'form':form})
