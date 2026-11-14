"""Scoped settlement workspace and explicit confirmations; GET never writes."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from .capabilities import office_view, require_capability
from .models import CashAllocation, Entity, Transaction
from .office_access import record
from .settlement_forms import AllocationFormSet, AllocationHeaderForm, ReleaseForm, SettlementDateForm
from .settlement_selectors import allocation_history, cash_sources, charge_balances, settlement_totals
from .settlement_services import allocate_cash, eligible_source, release_allocation


def expected_error(form, error):
    if isinstance(error, ValidationError):
        form.add_error(None, error.messages)
    elif getattr(error.__cause__, 'sqlstate', None) in {'23505', '23514', '40001', '40P01'}:
        form.add_error(None, 'Η ενέργεια δεν ολοκληρώθηκε. Ανανεώστε τη σελίδα ή επαναλάβετε την ίδια επιβεβαίωση.')
    else:
        raise error


@office_view('finance.read')
@never_cache
@require_http_methods(['GET'])
def workspace(request, pk):
    entity = record(Entity, request.user, pk)
    form = SettlementDateForm(request.GET)
    valid = form.is_valid()
    day = form.cleaned_data['as_of'] if valid else timezone.localdate()
    charges = charge_balances(request.user, entity=entity, as_of=day)
    sources = cash_sources(request.user, entity=entity, as_of=day)
    history = allocation_history(request.user, entity=entity, as_of=day)
    if not valid:
        charges, sources, history = charges.none(), sources.none(), history.none()
    totals = settlement_totals(request.user, entity=entity, as_of=day) if valid else None
    history_page = Paginator(history, 20).get_page(request.GET.get('history_page'))
    owner = require_capability(request.user, 'finance.read').role == 'owner'
    for row in history_page:
        row.release_form = ReleaseForm(auto_id='id_release_' + row.pk.hex + '_%s') if owner and day == timezone.localdate() and not row.released_by_day else None
    from .correction_selectors import refund_history
    refunds=refund_history(request.user,entity=entity,as_of=day) if valid else None
    params = request.GET.copy()
    for field in ('history_page', 'charge_page', 'source_page'):
        params.pop(field, None)
    return render(request, 'accounting/settlements/workspace.html', {'entity': entity, 'date_form': form, 'as_of': day,
        'totals': totals, 'charge_page': Paginator(charges, 20).get_page(request.GET.get('charge_page')),
        'source_page': Paginator(sources, 20).get_page(request.GET.get('source_page')), 'history_page': history_page,
        'page_query': params.urlencode(), 'refund_page': Paginator(refunds,20).get_page(request.GET.get('refund_page')) if refunds is not None else None,
        'can_refund': owner and valid and day==timezone.localdate(), 'can_allocate': valid and not entity.is_archived and day == timezone.localdate()})


@office_view('finance.write')
@never_cache
@sensitive_post_parameters('reason', 'posting_key')
@require_http_methods(['GET', 'POST'])
def allocate(request, pk):
    source = record(Transaction, request.user, pk)
    form = AllocationHeaderForm(request.POST if request.method == 'POST' else None)
    header_valid = form.is_valid() if form.is_bound else False
    day = form.cleaned_data.get('effective_date', timezone.localdate()) if header_valid else timezone.localdate()
    eligible, warning = True, ''
    try:
        eligible_source(source)
    except ValidationError as error:
        eligible, warning = False, ' '.join(error.messages)
    if source.entity_id and source.entity.is_archived:
        eligible, warning = False, 'Επαναφέρετε τον συναλλασσόμενο πριν από νέα αντιστοίχιση.'
    choices = charge_balances(request.user, entity=source.entity_id or -1, as_of=day).filter(
        direction='RECEIVABLE' if source.transaction_type == 'INCOME' else 'PAYABLE')
    if not eligible:
        choices = choices.none()
    lines = AllocationFormSet(request.POST if request.method == 'POST' else None, prefix='lines', form_kwargs={'choices': choices})
    balance = cash_sources(request.user, as_of=day).filter(pk=source.pk).first()
    if request.method == 'POST' and header_valid and lines.is_valid():
        try:
            data = form.cleaned_data
            command = allocate_cash(request.user, source_cash=source.pk,
                lines=[{'charge': row.cleaned_data['charge'], 'amount': row.cleaned_data['amount']} for row in lines.forms if row.cleaned_data],
                effective_date=data['effective_date'], reason=data['reason'], idempotency_key=str(data['posting_key']))
        except (ValidationError, DatabaseError) as error:
            expected_error(form, error)
        else:
            messages.success(request, 'Οι αντιστοιχίσεις καταχωρίστηκαν. Το ταμείο δεν μεταβλήθηκε. Αναφορά: ' + str(command.pk))
            return redirect('entity-settlements', pk=source.entity_id)
    return render(request, 'accounting/settlements/allocate.html', {'source': source, 'balance': balance, 'form': form,
        'lines': lines, 'eligible': eligible, 'warning': warning})


@office_view('finance.release', mfa=True)
@never_cache
@sensitive_post_parameters('password', 'reason', 'posting_key')
@require_POST
def release(request, key):
    office_id = require_capability(request.user, 'finance.release').office_id
    allocated = get_object_or_404(CashAllocation.objects.filter(office_id=office_id).select_related('charge'), pk=key)
    form = ReleaseForm(request.POST)
    if form.is_valid():
        try:
            release_allocation(request, allocation=allocated.pk, password=form.cleaned_data['password'],
                effective_date=form.cleaned_data['effective_date'], reason=form.cleaned_data['reason'],
                idempotency_key=str(form.cleaned_data['posting_key']))
        except (ValidationError, DatabaseError) as error:
            expected_error(form, error)
        else:
            messages.success(request, 'Η αντιστοίχιση αποδεσμεύτηκε. Το αρχικό ιστορικό και οι κινήσεις ταμείου διατηρήθηκαν.')
            return redirect('entity-settlements', pk=allocated.charge.entity_id)
    return render(request, 'accounting/settlements/release.html', {'allocation': allocated, 'form': form}, status=400)
