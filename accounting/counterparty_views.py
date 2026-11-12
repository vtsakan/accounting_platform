"""Greek counterparty workspace; no submitted office identity is authoritative."""
import re
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponseNotAllowed
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .capabilities import office_view
from .counterparty_services import ARCHIVED, archive_counterparty
from .counterparty_validation import afm_text
from .forms import EntityForm
from .models import Agreement, Entity, Transaction
from .office_access import record, records


class SearchForm(forms.Form):
    q = forms.CharField(label="Αναζήτηση με ονοματεπώνυμο, επωνυμία ή Α.Φ.Μ.", max_length=100, required=False)
    role = forms.ChoiceField(label="Ρόλος", required=False, choices=[('', 'Όλοι οι ρόλοι'),
        ('customer', 'Πελάτες'), ('supplier', 'Προμηθευτές'), ('both', 'Πελάτες και προμηθευτές')])
    kind = forms.ChoiceField(label="Κατηγορία προσώπου", required=False, choices=[('', 'Όλες οι κατηγορίες'),
        ('INDIVIDUAL', 'Φυσικά πρόσωπα'), ('BUSINESS', 'Επιχειρήσεις'), ('UNREVIEWED', 'Χρειάζονται επιβεβαίωση')])
    status = forms.ChoiceField(label="Κατάσταση", required=False, choices=[('active', 'Ενεργές εγγραφές'),
        ('archived', 'Αρχειοθετημένες εγγραφές'), ('all', 'Όλες οι εγγραφές')])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs['class'] = 'form-control' if name == 'q' else 'form-select'


class ArchiveForm(forms.Form):
    version = forms.IntegerField(label="Έκδοση εγγραφής", min_value=0, widget=forms.HiddenInput)


def form_error(form, error):
    if hasattr(error, 'error_dict'):
        for name, errors in error.error_dict.items():
            form.add_error(name if name in form.fields else None, errors)
    else:
        form.add_error(None, error)


@office_view('clients.read')
@require_http_methods(['GET'])
def workspace(request, *, fixed_role=None):
    data = request.GET.copy()
    if fixed_role:
        data['role'] = fixed_role
    if not data.get('status'):
        data['status'] = 'active'
    form = SearchForm(data)
    queryset = records(Entity, request.user)
    # A pending historical ownership backfill must never expose unassigned rows.
    if not queryset.exists():
        queryset = Entity.objects.none()
    if form.is_valid():
        values = form.cleaned_data
        if values['status'] != 'all':
            queryset = queryset.filter(is_archived=values['status'] == 'archived')
        if values['role'] in {'customer', 'both'}:
            queryset = queryset.filter(is_customer=True)
        if values['role'] in {'supplier', 'both'}:
            queryset = queryset.filter(is_supplier=True)
        if values['kind']:
            queryset = queryset.filter(legal_kind=values['kind'])
        if values['q']:
            key = afm_text(values['q'])
            condition = Q(name__icontains=values['q'])
            if re.fullmatch(r'[0-9]{1,9}', key):
                condition |= Q(vat_key__contains=key)
            queryset = queryset.filter(condition)
    else:
        queryset = queryset.none()
    page = Paginator(queryset.order_by('name', 'pk'), 25).get_page(request.GET.get('page'))
    params = request.GET.copy(); params.pop('page', None)
    return render(request, 'accounting/counterparty_list.html', {'form': form, 'page_obj': page,
        'counterparties': page.object_list, 'customers': page.object_list, 'suppliers': page.object_list,
        'fixed_role': fixed_role, 'page_query': params.urlencode(),
        'workspace_title': {'customer':'Πελάτες', 'supplier':'Προμηθευτές'}.get(fixed_role, 'Συναλλασσόμενοι')})


@office_view('clients.write')
@require_http_methods(['GET', 'POST'])
def edit(request, key=None):
    entity = record(Entity, request.user, key) if key is not None else None
    if entity and entity.is_archived:
        return render(request, 'accounting/entity_archived.html', {'entity': entity}, status=409)
    initial = {'is_customer': request.GET.get('role') != 'supplier', 'is_supplier': request.GET.get('role') == 'supplier'}
    form = EntityForm(request.POST if request.method == 'POST' else None, user=request.user, instance=entity, initial=initial if entity is None else None)
    if request.method == 'POST' and form.is_valid():
        try:
            saved = form.save()
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, 'Τα στοιχεία του συναλλασσομένου αποθηκεύτηκαν.')
            return redirect('entity-detail', pk=saved.pk)
    return render(request, 'accounting/edit_entity.html' if entity else 'accounting/add_entity.html', {'form': form, 'entity': entity})


@office_view('clients.read')
def detail(request, key):
    entity = record(Entity, request.user, key)
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    agreements = records(Agreement, request.user).filter(entity=entity).annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).annotate(remaining_balance=F('total_amount') - F('total_payments')).order_by('-start_date', '-pk')
    movements = records(Transaction, request.user).filter(entity=entity).select_related('agreement', 'cash_account').order_by('-transaction_date', '-pk')
    agreement_page = Paginator(agreements, 10).get_page(request.GET.get('agreement_page'))
    movement_page = Paginator(movements, 10).get_page(request.GET.get('movement_page'))
    events = entity.workspace_events.filter(office_id=entity.office_id).select_related('actor').order_by('-occurred_at', '-pk')[:10]
    return render(request, 'accounting/entity_detail.html', {'entity': entity, 'agreements': agreement_page,
        'transactions': movement_page, 'standalone_transactions': movement_page,
        'agreement_page': agreement_page, 'movement_page': movement_page,
        'workspace_events': events})


@office_view('clients.write')
@require_http_methods(['GET', 'POST'])
def archive(request, key, *, restore=False):
    entity = record(Entity, request.user, key)
    form = ArchiveForm(request.POST if request.method == 'POST' else None, initial={'version': entity.record_version})
    if request.method == 'POST' and form.is_valid():
        try:
            saved = archive_counterparty(request.user, key, version=form.cleaned_data['version'], archive=not restore)
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, 'Η εγγραφή επανήλθε στις ενεργές.' if restore else 'Η εγγραφή αρχειοθετήθηκε. Το ιστορικό διατηρήθηκε.')
            return redirect('entity-detail', pk=saved.pk)
    return render(request, 'accounting/entity_archive.html', {'entity': entity, 'form': form, 'restore': restore})


@office_view('clients.write')
def restore(request, pk):
    return archive(request, pk, restore=True)


@office_view('clients.write')
def archive_view(request, pk):
    return archive(request, pk)
