"""Authenticated immediate attachments; no persisted artifact or bearer URL."""
from django.core.exceptions import PermissionDenied
from django.http import Http404,HttpResponse
from django.shortcuts import get_object_or_404,render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from .capabilities import office_view,require_capability
from .export_schema import ExportError
from .export_selectors import build_document
from .export_renderers import render_csv,render_pdf
from .models import Entity
from .office_access import record,validate_filter_ids
from .report_forms import PeriodReportForm,StatementForm,AnnualReportForm


def attachment(request,kind,filetype,pk=None):
    if filetype not in {'pdf','csv'}:raise Http404('Η μορφή εξαγωγής δεν είναι διαθέσιμη.')
    profile=require_capability(request.user,'finance.read');office_id=profile.office_id
    validate_filter_ids(request)
    if kind=='statement':
        entity=record(Entity,request.user,pk)
        form=StatementForm(request.GET,user=request.user,entity=entity)
        back=reverse('client-statement',args=[pk]);filename='Καρτέλα συναλλασσομένου'
    elif kind=='annual':
        form=AnnualReportForm(request.GET,user=request.user);back=reverse('fees-overview');filename='Δωδεκάμηνη εικόνα αμοιβών'
    else:
        form=PeriodReportForm(request.GET,user=request.user);back=reverse('summary-report');filename='Οικονομική αναφορά'
    try:
        document=build_document(request.user,form,kind,filetype)
        payload=render_pdf(document) if filetype=='pdf' else render_csv(document)
        # Rendering happens after the money snapshot. Re-read live membership
        # before headers/bytes, including office reassignment during rendering.
        current=require_capability(request.user,'finance.read')
        if current.office_id!=office_id or str(current.office_id)!=document.office_id:
            raise PermissionDenied('Η πρόσβαση στο γραφείο άλλαξε. Ζητήστε ξανά την αναφορά.')
    except ExportError as error:
        response=render(request,'accounting/reports/export_error.html',{'filter_form':form,'back_url':back,'export_error':str(error)},status=error.status)
        if error.status==503:response['Retry-After']='5'
        return response
    response=HttpResponse(payload,content_type='application/pdf' if filetype=='pdf' else 'text/csv; charset=utf-8')
    response['Content-Disposition']=content_disposition_header(True,filename+'-'+document.as_of.isoformat()+'.'+filetype)
    response['Content-Length']=str(len(payload));response['X-Content-Type-Options']='nosniff';response['Pragma']='no-cache'
    return response


@office_view('finance.read')
@never_cache
@require_GET
def period(request,filetype):return attachment(request,'period',filetype)


@office_view('finance.read')
@never_cache
@require_GET
def statement(request,pk,filetype):return attachment(request,'statement',filetype,pk)


@office_view('finance.read')
@never_cache
@require_GET
def annual(request,filetype):return attachment(request,'annual',filetype)
