"""Greek ordinary cash entry and immutable, paginated movement history."""
import uuid
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, Paginator
from django.db import DatabaseError
from django.db.models import F, Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from .capabilities import office_view, require_capability
from .forms import ExpenseForm, IncomeForm
from .finance_services import fingerprint, legacy_settlement, post_cash, submission_key
from .models import Agreement, FinanceCommand, Transaction
from .movement_forms import CashMovementFilterForm
from .movement_selectors import filtered_movements, movement_totals
from .office_access import records, validate_filter_ids


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
    kind = 'RECEIVABLE' if direction == 'INCOME' else 'PAYABLE'
    agreements = records(Agreement, request.user).filter(agreement_type=kind, status='ACTIVE', entity__is_archived=False).annotate(
        total_payments=legacy_settlement('transactions__')).annotate(remaining_balance=F('total_amount') - F('total_payments'))
    form = form_class(request.POST if request.method == 'POST' else None, user=request.user, agreements_queryset=agreements,
                      initial={'transaction_date': timezone.localdate()})
    if request.method == 'POST':
        existing_submission(form, request.user, direction)
        if form.is_valid():
            data = form.cleaned_data
            try:
                post_cash(request.user, idempotency_key=submission_key(request, data), transaction_type=direction,
                          **{name: data[name] for name in ('transaction_date', 'amount', 'cash_account', 'description', 'remarks', 'category', 'entity', 'agreement')})
            except ValidationError as error:
                form.add_error(None, error)
            except DatabaseError as error:
                if getattr(error.__cause__, 'sqlstate', None) not in {'23505', '23514', '40001', '40P01'}:
                    raise
                form.add_error(None, 'Η καταχώρηση δεν ολοκληρώθηκε. Ελέγξτε τα στοιχεία και επαναλάβετε με την ίδια ταυτότητα καταχώρισης.')
            else:
                messages.success(request, 'Η κίνηση καταχωρίστηκε. Η επανάληψη της ίδιας υποβολής δεν δημιουργεί δεύτερη κίνηση.')
                return redirect('transaction-list')
    elif request.GET.get('entity_id'):
        # Reuse the scoped, role-appropriate field instead of trusting a URL ID.
        try:
            form.initial['entity'] = form.fields['entity'].clean(request.GET['entity_id'])
        except ValidationError as error:
            form.cleaned_data = {}
            form.add_error('entity', error)
    return render(request, 'accounting/add_income.html' if direction == 'INCOME' else 'accounting/add_expense.html', {'form': form})


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
