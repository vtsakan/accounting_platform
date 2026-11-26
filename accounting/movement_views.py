"""Greek ordinary cash entry and immutable, paginated movement history."""
import uuid
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, Paginator
from django.db import DatabaseError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from .capabilities import office_view, require_capability
from .forms import ExpenseForm, IncomeForm
from .finance_services import fingerprint, submission_key
from .cash_entry_selectors import receipt_agreements,receipt_charges
from .cash_entry_services import post_agreement_cash
from .cash_charge_services import post_charge_cash
from .finance_validation import add_financial_error
from .models import Entity, FinanceCommand, Transaction,CashChargeSelection,Agreement
from .movement_forms import CashMovementFilterForm
from .movement_selectors import filtered_movements, movement_totals
from .office_access import record, records, validate_filter_ids
from core.locale import format_euro


def existing_submission(form, user, direction):
    """Restore only a completed operation's stored choices for an exact retry.

    Replaying after a reference is retired or a linked agreement is settled
    remains possible. The service still compares the entire payload and locks
    fresh authority before returning the original; a changed payload fails.
    """
    if not form.is_bound or not form.data.get('posting_key'):
        return
    try:
        key = str(uuid.UUID(form.data['posting_key']))
    except (ValueError, TypeError, AttributeError):
        return
    office = require_capability(user, 'finance.write').office_id
    command = FinanceCommand.objects.filter(office_id=office, operation='cash.post', key_digest=fingerprint(key), state='completed').first()
    if command is None:
        return
    entry = Transaction.objects.filter(office_id=office, command=command, transaction_type=direction).first()
    if entry is None:
        return
    form.replay_entry = entry
    selection=CashChargeSelection.objects.filter(office_id=office,source_cash=entry).first()
    form.legacy_cash_replay=selection is None
    if selection is not None:
        from .settlement_selectors import charge_balances
        field=form.fields['charge']
        originals=charge_balances(user,as_of=entry.transaction_date)
        field.queryset=originals.filter(Q(pk__in=field.queryset.values('pk'))|Q(pk=selection.charge_id))
    for name in ('cash_account', 'category', 'entity', 'agreement'):
        field = form.fields[name]
        key = getattr(entry, name + '_id')
        if key is not None:
            scoped = records(field.queryset.model, user)
            field.queryset = scoped.filter(Q(pk__in=field.queryset.values('pk')) | Q(pk=key))


@office_view('finance.read')
@never_cache
@require_GET
def movement_list(request):
    validate_filter_ids(request)  # Numeric foreign-office keys remain 404.
    form = CashMovementFilterForm(request.GET, user=request.user)
    rows = filtered_movements(request.user, form)
    valid = form.is_valid()
    paginator = Paginator(rows, form.cleaned_data['page_size'] if valid else 25)
    try:
        page = paginator.page(form.cleaned_data['page'] if valid else 1)
    except EmptyPage:
        form.add_error('page', 'Η ζητούμενη σελίδα δεν υπάρχει. Επιλέξτε ξανά τα φίλτρα.')
        rows = rows.none()
        page = Paginator(rows, 25).page(1)
    parameters = request.GET.copy()
    for name in list(parameters):
        if name == 'page' or name not in form.fields:
            del parameters[name]
    return render(request, 'accounting/transaction_list.html', {
        'filter_form': form, 'page_obj': page, 'transactions': page.object_list,
        'result_count': page.paginator.count, 'filter_query': parameters.urlencode(),
        'filters_valid': not form.errors, **movement_totals(rows)})


def posting(request, direction):
    validate_filter_ids(request)
    form_class = IncomeForm if direction == 'INCOME' else ExpenseForm
    agreements = receipt_agreements(request.user, direction)
    form = form_class(request.POST if request.method == 'POST' else None, user=request.user, agreements_queryset=agreements,
                      initial={'transaction_date': timezone.localdate()})
    if request.method == 'POST':
        existing_submission(form, request.user, direction)
        if form.is_valid():
            data = form.cleaned_data
            try:
                # Preserve the exact tokenless S20 payload: the new presentation
                # checkbox must not change a legacy receipt's retry identity.
                original_fields = ('transaction_date', 'amount', 'cash_account', 'description', 'remarks', 'category', 'entity', 'agreement', 'posting_key')
                identity_inputs={name:data[name] for name in original_fields}
                if data.get('charge'):identity_inputs['charge']=data['charge']
                identity=submission_key(request,identity_inputs)
                inputs={name:data[name] for name in ('transaction_date','amount','cash_account','description','remarks','category','entity','agreement')}
                if data.get('charge'):
                    entry,allocated,replayed=post_charge_cash(request.user,charge=data['charge'],idempotency_key=identity,transaction_type=direction,**inputs)
                else:
                    entry,allocated,replayed=post_agreement_cash(request.user,idempotency_key=identity,transaction_type=direction,**inputs)
            except (ValidationError,DatabaseError) as error:
                add_financial_error(form,error)
            else:
                if replayed:
                    messages.success(request, 'Η ίδια κίνηση είναι ήδη καταχωρισμένη. Δεν προστέθηκε δεύτερη κίνηση ή αντιστοίχιση.')
                elif data.get('agreement'):
                    messages.success(request, 'Η κίνηση καταχωρίστηκε. Αντιστοιχίστηκαν ' + format_euro(allocated) +
                        ' στην επιλεγμένη χρέωση. Αδιάθετη πίστωση ή προκαταβολή: ' + format_euro(entry.amount - allocated) + '.')
                else:
                    messages.success(request, 'Η κίνηση καταχωρίστηκε. Η επανάληψη της ίδιας υποβολής δεν δημιουργεί δεύτερη κίνηση.')
                return redirect('transaction-list')
    elif request.GET.get('entity_id'):
        # Reuse the scoped, role-appropriate field instead of trusting a URL ID.
        try:
            form.initial['entity'] = form.fields['entity'].clean(request.GET['entity_id'])
            form.scope_agreements(form.initial['entity'])
            if request.GET.get('agreement_id'):
                form.initial['agreement']=form.fields['agreement'].clean(request.GET['agreement_id'])
                form.scope_charges(form.initial['entity'],form.initial['agreement'])
                if request.GET.get('charge_id'):
                    form.initial['charge']=form.fields['charge'].clean(request.GET['charge_id'])
                    form.initial['amount']=form.initial['charge'].receipt_capacity
                    form.initial['settle_agreement']=True
        except ValidationError as error:
            form.cleaned_data = {}
            form.add_error('entity', error)
    return render(request, 'accounting/add_income.html' if direction == 'INCOME' else 'accounting/add_expense.html',
                  {'form': form, 'cash_direction': direction})


@office_view('finance.write')
@never_cache
@sensitive_post_parameters('description', 'remarks', 'posting_key')
@require_http_methods(['GET', 'POST'])
def income(request):
    return posting(request, 'INCOME')


@office_view('finance.write')
@never_cache
@sensitive_post_parameters('description', 'remarks', 'posting_key')
@require_http_methods(['GET', 'POST'])
def expense(request):
    return posting(request, 'EXPENSE')


@office_view('finance.write')
@never_cache
@require_GET
def agreement_options(request):
    """Read-only dependent choices; office context is exclusively the actor's."""
    direction = request.GET.get('direction', 'INCOME')
    if direction not in {'INCOME', 'EXPENSE'} or any(len(request.GET.getlist(name)) > 1 for name in ('direction', 'entity_id')):
        return JsonResponse({'error': 'Ελέγξτε τον συναλλασσόμενο και την κατεύθυνση.'}, status=400)
    value = request.GET.get('entity_id')
    if not value:
        return JsonResponse({'options': []})
    party = record(Entity, request.user, value)
    if party.is_archived or not (party.is_customer if direction == 'INCOME' else party.is_supplier):
        return JsonResponse({'error': 'Ο συναλλασσόμενος δεν είναι διαθέσιμος για αυτή την κίνηση.'}, status=400)
    rows = receipt_agreements(request.user, direction).filter(entity=party)
    options = [{'value': str(row.pk), 'label': row.description + ' — Ανεξόφλητο σήμερα: ' + format_euro(row.remaining_balance)} for row in rows]
    return JsonResponse({'entity_id': str(party.pk), 'options': options}, json_dumps_params={'ensure_ascii': False})


@office_view('finance.write')
@never_cache
@require_GET
def charge_options(request):
    from .settlement_services import cash_key
    from .settlement_selectors import business_day
    from django import forms
    direction=request.GET.get('direction','INCOME')
    names={'direction','entity_id','agreement_id','transaction_date'}
    if direction not in {'INCOME','EXPENSE'} or any(len(request.GET.getlist(name))>1 for name in names):
        return JsonResponse({'error':'Ελέγξτε τα φίλτρα χρεώσεων.'},status=400)
    if not request.GET.get('entity_id') or not request.GET.get('agreement_id'):return JsonResponse({'options':[]})
    try:
        party=record(Entity,request.user,cash_key(request.GET['entity_id']))
        agreement=record(Agreement,request.user,cash_key(request.GET['agreement_id']))
        raw=request.GET.get('transaction_date')
        day=business_day(forms.DateField(input_formats=['%Y-%m-%d','%d/%m/%Y']).clean(raw)) if raw else business_day()
    except ValidationError:return JsonResponse({'error':'Ελέγξτε τις επιλογές και την ημερομηνία κίνησης.'},status=400)
    if party.is_archived or agreement.entity_id!=party.pk or agreement.agreement_type!=('RECEIVABLE' if direction=='INCOME' else 'PAYABLE') or not(party.is_customer if direction=='INCOME' else party.is_supplier):
        return JsonResponse({'error':'Η συμφωνία δεν είναι διαθέσιμη για τον επιλεγμένο συναλλασσόμενο.'},status=400)
    from .cash_entry_forms import CashChargeChoice
    field=CashChargeChoice()
    options=[]
    for row in receipt_charges(request.user,direction,as_of=day).filter(entity=party,agreement=agreement):
        options.append({'value':str(row.pk),'label':field.label_from_instance(row),'outstanding':str(row.outstanding),'available':str(row.receipt_capacity)})
    return JsonResponse({'entity_id':str(party.pk),'agreement_id':str(agreement.pk),'options':options},json_dumps_params={'ensure_ascii':False})
