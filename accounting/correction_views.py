"""Owner-confirmed Greek correction screens. Every request is office-scoped."""
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
from .models import Agreement, Charge, Transaction
from .office_access import record
from .correction_forms import (AgreementChangeForm, CashCorrectionForm, CashReplacementForm, ChargeCorrectionForm,
                               PeriodCloseForm, RefundForm, TransferReplacementForm)
from .correction_selectors import closed_through, correction_history, terms_on
from .correction_services import (amend_agreement, close_period, correct_cash, correct_charge, correct_transfer,
                                  refund_credit, reverse_refund, unreversed_refunds)
from .settlement_selectors import cash_sources
from .settlement_views import expected_error


def proof_values(data):
    return dict(password=data['password'], reason=data['reason'], effective_date=data['effective_date'], idempotency_key=str(data['posting_key']))


@office_view('finance.reverse', mfa=True)
@never_cache
@sensitive_post_parameters('password', 'reason', 'posting_key', 'new-remarks')
@require_http_methods(['GET', 'POST'])
def cash_correction(request, pk):
    source = record(Transaction, request.user, pk)
    form = CashCorrectionForm(request.POST if request.method == 'POST' else None, user=request.user, source=source)
    transfer = source.posting_kind == 'TRANSFER'
    replacement_class = TransferReplacementForm if transfer else CashReplacementForm
    valid = form.is_valid() if form.is_bound else False
    wants_replacement = valid and form.cleaned_data.get('replace') and source.posting_kind not in {'REFUND', 'REVERSAL'}
    initial = {'amount': source.amount, 'description': source.description}
    if not transfer:
        initial.update(transaction_type=source.transaction_type, cash_account=source.cash_account_id,
                       entity=source.entity_id, agreement=source.agreement_id, category=source.category_id, remarks=source.remarks)
    replacement = replacement_class(request.POST if wants_replacement else None, user=request.user, prefix='new', initial=initial)
    if valid and (not wants_replacement or replacement.is_valid()):
        values = proof_values(form.cleaned_data)
        try:
            if source.posting_kind == 'REFUND':
                action = reverse_refund(request, entry_id=source.pk, **values)
            elif transfer:
                action = correct_transfer(request, entry_id=source.pk, replacement=replacement.cleaned_data if wants_replacement else None, **values)
            else:
                new = replacement.cleaned_data | {'transaction_date': form.cleaned_data['effective_date']} if wants_replacement else None
                action = correct_cash(request, entry_id=source.pk, replacement=new,
                                      dependent_refunds=[row.pk for row in form.cleaned_data['dependent_refunds']], **values)
        except (ValidationError, DatabaseError) as error:
            expected_error(form, error)
        else:
            messages.success(request, 'Η διόρθωση καταχωρίστηκε με διατηρημένο ιστορικό. Αναφορά: ' + str(action.pk))
            return redirect('finance-correction-history')
    return render(request, 'accounting/corrections/cash.html', {'source': source, 'form': form, 'replacement': replacement,
        'transfer': transfer, 'refund': source.posting_kind == 'REFUND', 'dependencies': unreversed_refunds(source),
        'history': correction_history(request.user, source_cash=source)[:10]})


@office_view('finance.refund', mfa=True)
@never_cache
@sensitive_post_parameters('password', 'reason', 'posting_key')
@require_http_methods(['GET', 'POST'])
def refund(request, pk):
    source = record(Transaction, request.user, pk)
    form = RefundForm(request.POST if request.method == 'POST' else None, user=request.user, initial={'cash_account': source.cash_account_id})
    balance = cash_sources(request.user).filter(pk=source.pk).first()
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            action = refund_credit(request, source_cash=source.pk, cash_account=data['cash_account'], amount=data['amount'], **proof_values(data))
        except (ValidationError, DatabaseError) as error:
            expected_error(form, error)
        else:
            messages.success(request, 'Η επιστροφή καταχωρίστηκε και συνδέθηκε με την αρχική κίνηση. Αναφορά: ' + str(action.pk))
            return redirect('entity-settlements', pk=source.entity_id)
    return render(request, 'accounting/corrections/refund.html', {'source': source, 'balance': balance, 'form': form})


@office_view('finance.reverse', mfa=True)
@never_cache
@sensitive_post_parameters('password', 'reason', 'posting_key')
@require_POST
def charge_correction(request, key):
    office = require_capability(request.user, 'finance.reverse').office_id
    charge = get_object_or_404(Charge.objects.filter(office_id=office), pk=key)
    form = ChargeCorrectionForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        try:
            action = correct_charge(request, charge_id=charge.pk,
                replacement_amount=data.get('replacement_amount') if data.get('replace') else None,
                replacement_due_date=data.get('replacement_due_date') if data.get('replace') else None, **proof_values(data))
        except (ValidationError, DatabaseError) as error:
            expected_error(form, error)
        else:
            messages.success(request, 'Η χρέωση διορθώθηκε και οι σχετικές αντιστοιχίσεις αποδεσμεύτηκαν. Αναφορά: ' + str(action.pk))
            return redirect('agreement-detail', pk=charge.agreement_id)
    return render(request, 'accounting/corrections/charge.html', {'charge': charge, 'form': form}, status=400)


@office_view('finance.amend', mfa=True)
@never_cache
@sensitive_post_parameters('password', 'reason', 'posting_key')
@require_http_methods(['GET', 'POST'])
def agreement_change(request, pk):
    agreement = record(Agreement, request.user, pk)
    latest = agreement.terms_versions.first()
    form = AgreementChangeForm(request.POST if request.method == 'POST' else None, initial={
        'expected_revision': latest.revision if latest else 0, 'description': latest.description if latest else agreement.description,
        'amount': latest.agreed_amount if latest else agreement.total_amount, 'lifecycle': 'ACTIVE'})
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            action = amend_agreement(request, agreement_id=agreement.pk,
                **{name: data[name] for name in ('expected_revision', 'description', 'amount', 'lifecycle')}, **proof_values(data))
        except (ValidationError, DatabaseError) as error:
            expected_error(form, error)
        else:
            messages.success(request, 'Η νέα έκδοση όρων καταχωρίστηκε. Οι προηγούμενες χρεώσεις διατηρήθηκαν. Αναφορά: ' + str(action.pk))
            return redirect('agreement-detail', pk=agreement.pk)
    return render(request, 'accounting/corrections/agreement.html', {'agreement': agreement, 'terms': terms_on(agreement),
        'latest': latest, 'form': form, 'history': correction_history(request.user, agreement=agreement)[:20]})


@office_view('finance.close', mfa=True)
@never_cache
@sensitive_post_parameters('password', 'reason', 'posting_key')
@require_http_methods(['GET', 'POST'])
def period_close(request):
    form = PeriodCloseForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            close_period(request, closed_through=data['effective_date'], password=data['password'], reason=data['reason'], idempotency_key=str(data['posting_key']))
        except (ValidationError, DatabaseError) as error:
            expected_error(form, error)
        else:
            messages.success(request, 'Η οικονομική περίοδος έκλεισε έως και την επιλεγμένη ημερομηνία.')
            return redirect('finance-period-close')
    return render(request, 'accounting/corrections/period.html', {'form': form, 'cutoff': closed_through(request.user)})


@office_view('finance.read')
@never_cache
@require_http_methods(['GET'])
def history(request):
    page = Paginator(correction_history(request.user), 25).get_page(request.GET.get('page'))
    return render(request, 'accounting/corrections/history.html', {'page_obj': page, 'cutoff': closed_through(request.user),
        'can_correct': require_capability(request.user, 'finance.read').role == 'owner'})
