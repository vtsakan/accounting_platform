"""Explicit secret reveal and scoped directory exports; contacts never alter money."""
from collections import defaultdict

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404,HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters,sensitive_variables
from django.views.decorators.http import require_GET,require_POST

from .capabilities import office_view,require_capability
from .counterparty_views import SearchForm
from .counterparty_validation import afm_text
from .entity_profile_models import FLAG_LABELS
from .entity_profile_selectors import (bulk_balances,decorate_profiles,filter_profiles,financial_summary,
    profile_for,profile_installed,spouse_contacts)
from .entity_profile_services import reveal_credentials
from .export_renderers import render_csv,render_pdf
from .export_schema import Column,Document,ExportError,Provenance,Section
from .models import Entity,Office,TaxisCredential
from .office_access import record,records
from .report_selectors import read_snapshot


def profile_context_data(user,entity):
    profile=profile_for(entity)
    saved=set(TaxisCredential.objects.filter(office_id=entity.office_id,entity=entity).values_list('subject',flat=True)) if profile_installed() else set()
    return {'fiscal_profile':profile,'effective_spouse_contacts':spouse_contacts(entity,profile) if profile and profile.spouse_enabled else {},
        'profile_flags':[(label,getattr(profile,name)) for name,label in FLAG_LABELS.items()] if profile else [],
        'main_credentials_stored':'MAIN' in saved,'spouse_credentials_stored':'SPOUSE' in saved,
        'profile_events':entity.fiscal_events.filter(office_id=entity.office_id)[:10] if profile_installed() else []}


def editor_context(request,entity,form):
    context={'entity':entity,'form':form}
    if entity:context.update(profile_context_data(request.user,entity),financial_summary=financial_summary(request.user,entity))
    return context


@office_view('clients.credentials')
@never_cache
@sensitive_post_parameters('__ALL__')
@sensitive_variables('__ALL__')
@require_POST
def reveal(request,pk,subject):
    entity=record(Entity,request.user,pk)
    try:
        username,password=reveal_credentials(request.user,pk,subject)
    except ValidationError as error:
        response=render(request,'accounting/entity_profile/reveal.html',{'entity':entity,'credential_error':' '.join(error.messages)},status=409)
    else:
        response=render(request,'accounting/entity_profile/reveal.html',{'entity':entity,'taxis_username':username,
            'taxis_password':password,'subject_label':'Σύζυγος' if subject=='SPOUSE' else 'Υπόχρεος'})
    response['Cache-Control']='no-store, private';response['Pragma']='no-cache';response['Referrer-Policy']='no-referrer'
    return response


def directory_rows(user,form):
    from django.db.models import Q
    rows=records(Entity,user)
    values=form.cleaned_data
    if values.get('status')!='all':rows=rows.filter(is_archived=values.get('status')=='archived')
    if values.get('role') in {'customer','both'}:rows=rows.filter(is_customer=True)
    if values.get('role') in {'supplier','both'}:rows=rows.filter(is_supplier=True)
    if values.get('kind'):rows=rows.filter(legal_kind=values['kind'])
    if values.get('q'):
        import re
        q=values['q'];key=afm_text(q);condition=Q(name__icontains=q)
        if re.fullmatch(r'[0-9]{1,9}',key):condition|=Q(vat_key__contains=key)
        rows=rows.filter(condition)
    return filter_profiles(rows,values).order_by('name','pk')


def directory_document(user,form,filetype,group):
    if not form.is_valid():raise ExportError('Διορθώστε τα φίλτρα πριν από την εξαγωγή.')
    limit=400 if filetype=='pdf' else 2000
    with read_snapshot(user) as office:
        rows=list(directory_rows(user,form)[:limit+1])
        if len(rows)>limit:raise ExportError(f'Περιορίστε τα φίλτρα σε έως {limit} εγγραφές.',status=422)
        rows=decorate_profiles(rows);day=timezone.localdate()
        amounts=bulk_balances(user,rows,as_of=day)
        columns=(Column('entity','Συναλλασσόμενος',weight=2),Column('vat','ΑΦΜ','identifier'),
            Column('contact_status','Κατάσταση'),Column('person_kind','Κατηγορία',weight=2),Column('tags','Ετικέτες',weight=2),
            Column('customer_balance','Υπόλοιπο πελάτη','money'),Column('supplier_balance','Υπόλοιπο προμηθευτή','money'))
        groups=defaultdict(list)
        for entity in rows:
            profile=getattr(entity,'profile_summary',None);tags=profile.tags if profile else []
            if group=='tag':labels=tags or ['Χωρίς ετικέτα']
            elif group=='kind':labels=[entity.person_kind_label]
            elif group=='status':labels=[entity.contact_status_label]
            else:labels=['Εγγραφές']
            row=(entity.name,entity.vat_number or '',entity.contact_status_label,entity.person_kind_label,', '.join(tags),
                amounts[entity.pk]['customer_balance'] if entity.is_customer else None,
                amounts[entity.pk]['supplier_balance'] if entity.is_supplier else None)
            for label in labels:groups[label].append(row)
        if not groups:groups['Εγγραφές']=[]
        sections=[Section(label,columns,tuple(values)) for label,values in sorted(groups.items())]
        totals=(Column('label','Μέγεθος',weight=2),Column('value','Στοιχείο',weight=4))
        sections.append(Section('Σύνοψη επιλογής',totals,(
            ('Μοναδικές εγγραφές',str(len(rows))),
            ('Φίλτρα','Κατάσταση: '+{'ACTIVE':'Ενεργοί','INACTIVE':'Ανενεργοί','ALL':'Όλοι'}[form.cleaned_data.get('contact_status') or 'ACTIVE']+' · Ετικέτες: '+', '.join(form.cleaned_data.get('tags') or [])),
            ('Ομαδοποίηση','Ανά ετικέτα: μια εγγραφή μπορεί να εμφανίζεται σε περισσότερες ομάδες.' if group=='tag' else 'Κάθε εγγραφή εμφανίζεται μία φορά.'),
            ('Υπόλοιπα','Καταχωρισμένες χρεώσεις μείον εξοφλήσεις και αδιάθετα ποσά έως σήμερα. Αρνητικό ποσό = πιστωτικό υπόλοιπο.'),
        )))
        office_record=Office.objects.get(pk=office)
        return Document('Κατάλογος συναλλασσομένων',str(office),office_record.name,day,timezone.now(),tuple(sections),Provenance())


@office_view('clients.read')
@never_cache
@require_GET
def export_directory(request,filetype):
    if filetype not in {'csv','pdf'}:raise Http404('Η μορφή εξαγωγής δεν είναι διαθέσιμη.')
    group=request.GET.get('group','none')
    if group not in {'none','tag','kind','status'}:raise Http404('Η ομαδοποίηση δεν είναι διαθέσιμη.')
    data=request.GET.copy()
    if not data.get('status'):data['status']='active'
    form=SearchForm(data,user=request.user)
    office_id=require_capability(request.user,'clients.read').office_id
    try:
        document=directory_document(request.user,form,filetype,group)
        payload=render_pdf(document) if filetype=='pdf' else render_csv(document)
        current=require_capability(request.user,'clients.read')
        if current.office_id!=office_id or str(current.office_id)!=document.office_id:raise PermissionDenied('Η πρόσβαση στο γραφείο άλλαξε.')
    except ExportError as error:
        return render(request,'accounting/reports/export_error.html',{'filter_form':form,'back_url':'/counterparties/','export_error':str(error)},status=error.status)
    response=HttpResponse(payload,content_type='application/pdf' if filetype=='pdf' else 'text/csv; charset=utf-8')
    response['Content-Disposition']=content_disposition_header(True,'Συναλλασσόμενοι-'+document.as_of.isoformat()+'.'+filetype)
    response['Content-Length']=str(len(payload));response['X-Content-Type-Options']='nosniff';response['Pragma']='no-cache'
    return response
