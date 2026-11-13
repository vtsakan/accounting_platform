from .finance_services import legacy_settlement, submission_key, post_transfer
from . import counterparty_views
from django.core.exceptions import ValidationError
from .office_access import records, record, save_for_user, validate_filter_ids
from .membership import require_office_profile
# accounting/views.py

from django.shortcuts import render
from django.db.models import Sum, Q, F, DecimalField
from .models import CashAccount, Transaction
from .forms import ExpenseForm, IncomeForm, EntityForm, AgreementForm
from django.shortcuts import render, redirect, get_object_or_404 # Add get_object_or_404
from datetime import datetime
from .models import Transaction, CashAccount, Category, Agreement
from django.contrib.auth.decorators import login_required
from django.db.models.functions import Coalesce
import uuid

@login_required
def dashboard_view(request):
    from .cash_selectors import cash_accounts
    accounts_with_balances=cash_accounts(request.user)

    # Prepare the data to be sent to the template
    context = {
        'cash_accounts': accounts_with_balances
    }

    # Render the HTML page and pass the data to it
    return render(request, 'accounting/dashboard.html', context)


# accounting/views.py

from django.shortcuts import render
from django.db.models import Sum, Q, F, DecimalField, Value
from .models import CashAccount, Transaction

@login_required
def transaction_list_view(request):
    from .movement_views import movement_list
    return movement_list(request)


# accounting/views.py

from django.shortcuts import render
from .models import CashAccount, Transaction, Entity # Make sure Entity is imported

@login_required
def customer_list_view(request):
    # Fetch only the entities where the entity_type is 'CUSTOMER'
    return counterparty_views.workspace(request, fixed_role='customer')


@login_required
def supplier_list_view(request):
    # Fetch only the entities where the entity_type is 'SUPPLIER'
    return counterparty_views.workspace(request, fixed_role='supplier')


from django.shortcuts import render, redirect # Add redirect
from .models import CashAccount, Transaction, Entity
from .forms import ExpenseForm # Import our new form


@login_required
def add_expense_view(request):
    from .movement_views import expense
    return expense(request)


@login_required
def add_income_view(request):
    from .movement_views import income
    return income(request)


@login_required
def add_entity_view(request):
    return counterparty_views.edit(request)

@login_required
def entity_detail_view(request, pk):
    # Get the specific Entity object
    return counterparty_views.detail(request, key=pk)

@login_required
def summary_report_view(request):
    validate_filter_ids(request)
    from .movement_forms import CashMovementFilterForm
    from .movement_selectors import filtered_movements, operating_movements, movement_totals
    filter_form = CashMovementFilterForm(request.GET, user=request.user)
    transactions = operating_movements(filtered_movements(request.user, filter_form))
    start_date_str = request.GET.get('start_date', '')
    end_date_str = request.GET.get('end_date', '')
    transaction_type = request.GET.get('transaction_type', '')
    cash_account_id = request.GET.get('cash_account', '')
    category_id = request.GET.get('category', '')

    # Operating cash totals exclude explicit transfers before every aggregate.
    # Cash balances/history continue to include both legs on their own dates.
    totals = movement_totals(transactions)
    net_for_period = totals['net_for_period']

    income_by_category = transactions.filter(transaction_type='INCOME').values('category__name').annotate(total_amount=Sum('amount')).order_by('-total_amount')
    expense_by_category = transactions.filter(transaction_type='EXPENSE').values('category__name').annotate(total_amount=Sum('amount')).order_by('-total_amount')


    # --- FINAL CORRECTED AGREEMENT ANALYTICS ---
    receivable_agreements = records(Agreement, request.user).filter(agreement_type='RECEIVABLE', status='ACTIVE')
    total_receivable = receivable_agreements.annotate(
        total_payments=legacy_settlement('transactions__')
    ).aggregate(
        total=Coalesce(Sum(F('total_amount') - F('total_payments'), output_field=DecimalField()), Value(0), output_field=DecimalField()) # <-- Final fix is here
    )['total']

    payable_agreements = records(Agreement, request.user).filter(agreement_type='PAYABLE', status='ACTIVE')
    total_payable = payable_agreements.annotate(
        total_payments=legacy_settlement('transactions__')
    ).aggregate(
        total=Coalesce(Sum(F('total_amount') - F('total_payments'), output_field=DecimalField()), Value(0), output_field=DecimalField()) # <-- Final fix is here
    )['total']
    # --- END OF CORRECTION ---

    context = {
        'filter_form': filter_form,
        'total_income': totals['total_income'],
        'total_expense': totals['total_expense'],
        'net_for_period': net_for_period,
        'income_by_category': income_by_category,
        'expense_by_category': expense_by_category,
        'accounts_receivable': total_receivable,
        'accounts_payable': total_payable,
        'all_cash_accounts': records(CashAccount, request.user).all(),
        'all_categories': records(Category, request.user).all(),
        'start_date_str': start_date_str,
        'end_date_str': end_date_str,
        'selected_type': transaction_type,
        'selected_cash_account_id': cash_account_id,
        'selected_category_id': category_id,
    }

    from .agreement_selectors import obligation_totals
    context.update(obligation_totals(request.user))
    return render(request, 'accounting/summary_report.html', context)

@login_required
def edit_entity_view(request, pk):
    # Fetch the existing entity object we want to edit
    return counterparty_views.edit(request, key=pk)

@login_required
def agreement_list_view(request):
    from django.core.paginator import Paginator
    from .agreement_selectors import agreement_rows
    page = Paginator(agreement_rows(records(Agreement, request.user)), 25).get_page(request.GET.get('page'))
    context = {'agreements': page.object_list, 'page_obj': page}
    return render(request, 'accounting/agreement_list.html', context)

@login_required
def agreement_detail_view(request, pk):
    agreement = record(Agreement, request.user, pk)
    from .agreement_selectors import agreement_projection
    from django.core.paginator import Paginator
    context = {'agreement': agreement, **agreement_projection(agreement)}
    context['charge_page'] = Paginator(context['charges'], 25).get_page(request.GET.get('page'))
    context['terms_history'] = agreement.terms_versions.filter(office_id=agreement.office_id)[:20]
    return render(request, 'accounting/agreement_detail.html', context)

@login_required
def add_agreement_view(request):
    validate_filter_ids(request)
    if request.method == 'POST':
        form = AgreementForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                form.save()
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('agreement-list')
    else:
        # --- THIS IS THE 'GET' REQUEST PART - START OF CHANGES ---
        initial_data = {}
        # Check for entity_id and type in the URL
        entity_id = request.GET.get('entity_id')
        agreement_type = request.GET.get('type')

        if entity_id:
            initial_data['entity'] = entity_id
        if agreement_type:
            initial_data['agreement_type'] = agreement_type

        # Pass the initial_data to the form
        form = AgreementForm(user=request.user, initial=initial_data)
        # --- END OF CHANGES ---

    return render(request, 'accounting/add_agreement.html', {'form': form})

@login_required
def edit_agreement_view(request, pk):
    agreement_to_edit = record(Agreement, request.user, pk)

    if request.method == 'POST':
        form = AgreementForm(request.POST, user=request.user, instance=agreement_to_edit)
        if form.is_valid():
            updated_agreement = form.save(commit=False)

            try:
                updated_agreement = form.save()
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('agreement-detail', pk=updated_agreement.pk)
    else:
        form = AgreementForm(user=request.user, instance=agreement_to_edit)

    context = {
        'form': form,
        'agreement': agreement_to_edit
    }
    return render(request, 'accounting/edit_agreement.html', context)

# accounting/views.py

from django.db import transaction # <-- Add this import at the top of the file
# ... (your other imports) ...
from .forms import TransferForm # <-- Add TransferForm to your form imports

# ... (your existing views) ...

# ADD THIS NEW VIEW
@login_required
def add_transfer_view(request):
    from .transfer_views import transfer
    return transfer(request)
