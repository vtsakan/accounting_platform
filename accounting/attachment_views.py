"""Greek private file actions; no public object names or browser inline content."""
import io

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse,Http404
from django.shortcuts import render,redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET,require_POST,require_http_methods

from .attachment_forms import AttachmentForm,AttachmentCategoryForm,AttachmentRemoveForm
from .attachment_models import ClientAttachment,AttachmentCategory
from .attachment_selectors import categories,attachments_installed
from .attachment_services import upload_attachment,edit_attachment,remove_attachment,download_attachment,save_category
from .capabilities import office_view,require_capability
from .counterparty_views import form_error
from .office_access import record
from .models import Entity


def metadata(user,entity,key):
    from .attachment_selectors import attachment_rows
    try:return attachment_rows(user,entity).get(pk=key)
    except ClientAttachment.DoesNotExist:raise Http404('Το συνημμένο δεν βρέθηκε.') from None


@office_view('clients.write')
@never_cache
@sensitive_post_parameters('__ALL__')
@require_http_methods(['GET','POST'])
def upload(request,pk):
    entity=record(Entity,request.user,pk)
    if not attachments_installed():return render(request,'accounting/attachments/unavailable.html',{'entity':entity},status=503)
    if entity.is_archived:return render(request,'accounting/entity_archived.html',{'entity':entity},status=409)
    form=AttachmentForm(request.POST if request.method=='POST' else None,request.FILES if request.method=='POST' else None,user=request.user)
    if request.method=='POST' and form.is_valid():
        values=form.cleaned_data
        try:row,replay=upload_attachment(request.user,pk,category_id=values['category'].pk,
            description=values['description'],upload=values['file'],request_key=values['request_key'])
        except ValidationError as error:form_error(form,error)
        else:
            messages.success(request,'Το συνημμένο είχε ήδη καταχωριστεί.' if replay else 'Το συνημμένο ελέγχθηκε και αποθηκεύτηκε ιδιωτικά.')
            return redirect(reverse('entity-detail',args=[pk])+'#attachments')
    return render(request,'accounting/attachments/form.html',{'entity':entity,'form':form,'has_categories':categories(request.user,active=True).exists()})


@office_view('clients.write')
@never_cache
@sensitive_post_parameters('__ALL__')
@require_http_methods(['GET','POST'])
def edit(request,pk,key):
    entity=record(Entity,request.user,pk);row=metadata(request.user,entity,key)
    if entity.is_archived:return render(request,'accounting/entity_archived.html',{'entity':entity},status=409)
    form=AttachmentForm(request.POST if request.method=='POST' else None,user=request.user,row=row)
    if request.method=='POST' and form.is_valid():
        try:edit_attachment(request.user,pk,key,category_id=form.cleaned_data['category'].pk,
            description=form.cleaned_data['description'],version=form.cleaned_data['version'])
        except ValidationError as error:form_error(form,error)
        else:
            messages.success(request,'Ο χαρακτηρισμός και η περιγραφή ενημερώθηκαν.')
            return redirect(reverse('entity-detail',args=[pk])+'#attachments')
    return render(request,'accounting/attachments/form.html',{'entity':entity,'form':form,'attachment':row,'has_categories':True})


@office_view('clients.delete',mfa=True)
@never_cache
@require_http_methods(['GET','POST'])
def remove(request,pk,key):
    entity=record(Entity,request.user,pk);row=metadata(request.user,entity,key)
    form=AttachmentRemoveForm(request.POST if request.method=='POST' else None,initial={'version':row.record_version})
    if request.method=='POST' and form.is_valid():
        try:remove_attachment(request.user,pk,key,**form.cleaned_data)
        except ValidationError as error:form_error(form,error)
        else:
            messages.success(request,'Το αρχείο αφαιρέθηκε. Η ενέργεια διατηρήθηκε στο ιστορικό.')
            return redirect(reverse('entity-detail',args=[pk])+'#attachments')
    return render(request,'accounting/attachments/remove.html',{'entity':entity,'attachment':row,'form':form})


@office_view('clients.read')
@never_cache
@require_POST
def download(request,pk,key):
    try:row,payload=download_attachment(request.user,pk,key)
    except ValidationError:
        return render(request,'accounting/attachments/unavailable.html',status=409)
    response=FileResponse(io.BytesIO(payload),as_attachment=True,filename=row.original_name,content_type='application/octet-stream')
    response['X-Content-Type-Options']='nosniff';response['Content-Security-Policy']="sandbox; default-src 'none'"
    response['Referrer-Policy']='no-referrer';response['Cache-Control']='private, no-store'
    return response


@office_view('clients.read')
@never_cache
@require_GET
def catalogue(request):
    return render(request,'accounting/attachments/categories.html',{'categories':categories(request.user),
        'can_manage_attachment_categories':require_capability(request.user,'clients.read').role=='owner'})


@office_view('office.settings',mfa=True)
@never_cache
@require_http_methods(['GET','POST'])
def category_edit(request,key=None):
    row=None
    if key is not None:
        try:row=categories(request.user).get(pk=key)
        except AttachmentCategory.DoesNotExist:raise Http404('Ο χαρακτηρισμός δεν βρέθηκε.') from None
    initial={'name':row.name,'is_active':row.is_active,'version':row.record_version} if row else None
    form=AttachmentCategoryForm(request.POST if request.method=='POST' else None,initial=initial)
    if request.method=='POST' and form.is_valid():
        try:save_category(request.user,category_id=key,**form.cleaned_data)
        except ValidationError as error:form_error(form,error)
        else:
            messages.success(request,'Ο χαρακτηρισμός αποθηκεύτηκε.');return redirect('attachment-categories')
    return render(request,'accounting/attachments/category_form.html',{'form':form,'category':row})
