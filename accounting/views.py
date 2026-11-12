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
    # This is an advanced but very efficient way to calculate balances for all accounts in one go.
    # It gets the sum of all 'INCOME' transactions and subtracts the sum of all 'EXPENSE' transactions.

    accounts_with_balances = records(CashAccount, request.user).filter(is_active=True).annotate(
        # Calculate the total income for each account
        total_income=Sum(
            'transaction__amount',
            filter=Q(transaction__transaction_type='INCOME'),
            output_field=DecimalField()
        ),
        # Calculate the total expense for each account
        total_expense=Sum(
            'transaction__amount',
            filter=Q(transaction__transaction_type='EXPENSE'),
            output_field=DecimalField()
        )
    ).annotate(
        # Calculate the final balance
        current_balance=F('opening_balance') + F('total_income') - F('total_expense')
    )

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
    validate_filter_ids(request)
    # --- Get Filter Data from the URL ---
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    transaction_type = request.GET.get('transaction_type')
    cash_account_id = request.GET.get('cash_account')
    category_id = request.GET.get('category')
    entity_id = request.GET.get('entity')
    query = request.GET.get('query')

    # --- Start with a base queryset ---
    transactions = records(Transaction, request.user).select_related('cash_account', 'category', 'entity').all()

    # --- Apply Filters if they exist (WITH CORRECTION) ---
    if start_date_str:
        # Convert the string to a date object before filtering
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        transactions = transactions.filter(transaction_date__gte=start_date)

    if end_date_str:
        # Convert the string to a date object before filtering
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        transactions = transactions.filter(transaction_date__lte=end_date)

    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)

    if cash_account_id:
        transactions = transactions.filter(cash_account_id=cash_account_id)

    if category_id:
        transactions = transactions.filter(category_id=category_id)

    if entity_id:
        transactions = transactions.filter(entity_id=entity_id)

    if query:
        transactions = transactions.filter(description__icontains=query)

    context = {
        'transactions': transactions,
        # Data for populating the filter dropdowns
        'all_cash_accounts': records(CashAccount, request.user).all(),
        'all_categories': records(Category, request.user).all(),
        'all_entities': records(Entity, request.user).all(),
        # Pass selected filter values back to the template
        'selected_start_date': start_date_str,
        'selected_end_date': end_date_str,
        'selected_type': transaction_type,
        'selected_cash_account_id': cash_account_id,
        'selected_category_id': category_id,
        'selected_entity_id': entity_id,
        'query': query,
    }

    return render(request, 'accounting/transaction_list.html', context)

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
    validate_filter_ids(request)
    # Pre-calculate balances with the explicit output_field
    payable_agreements = records(Agreement, request.user).filter(agreement_type='PAYABLE', status='ACTIVE').annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).annotate(
        remaining_balance=F('total_amount') - F('total_payments')
    )

    if request.method == 'POST':
        form = ExpenseForm(request.POST, user=request.user, agreements_queryset=payable_agreements)
        if form.is_valid():
            new_transaction = Transaction(
                transaction_date=form.cleaned_data['transaction_date'],
                description=form.cleaned_data['description'],
                amount=form.cleaned_data['amount'],
                cash_account=form.cleaned_data['cash_account'],
                category=form.cleaned_data['category'],
                entity=form.cleaned_data['entity'],
                agreement=form.cleaned_data['agreement'],
                transaction_type='EXPENSE'
            )
            try:
                save_for_user(new_transaction, request.user)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('transaction-list')
    else:
        initial_data = {}
        entity_id = request.GET.get('entity_id')
        if entity_id:
            initial_data['entity'] = entity_id

        form = ExpenseForm(user=request.user, initial=initial_data, agreements_queryset=payable_agreements)

    return render(request, 'accounting/add_expense.html', {'form': form})


@login_required
def add_income_view(request):
    validate_filter_ids(request)
    # Pre-calculate balances with the explicit output_field
    receivable_agreements = records(Agreement, request.user).filter(agreement_type='RECEIVABLE', status='ACTIVE').annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).annotate(
        remaining_balance=F('total_amount') - F('total_payments')
    )

    if request.method == 'POST':
        form = IncomeForm(request.POST, user=request.user, agreements_queryset=receivable_agreements)
        if form.is_valid():
            new_transaction = Transaction(
                transaction_date=form.cleaned_data['transaction_date'],
                description=form.cleaned_data['description'],
                amount=form.cleaned_data['amount'],
                cash_account=form.cleaned_data['cash_account'],
                category=form.cleaned_data['category'],
                entity=form.cleaned_data['entity'],
                agreement=form.cleaned_data['agreement'],
                transaction_type='INCOME'
            )
            try:
                save_for_user(new_transaction, request.user)
            except ValidationError as error:
                form.add_error(None, error)
            else:
                return redirect('transaction-list')
    else:
        initial_data = {}
        entity_id = request.GET.get('entity_id')
        if entity_id:
            initial_data['entity'] = entity_id

        form = IncomeForm(user=request.user, initial=initial_data, agreements_queryset=receivable_agreements)

    return render(request, 'accounting/add_income.html', {'form': form})

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
    # --- Transaction Filtering (unchanged) ---
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    transaction_type = request.GET.get('transaction_type')
    cash_account_id = request.GET.get('cash_account')
    category_id = request.GET.get('category')

    transactions = records(Transaction, request.user).all()
    if start_date_str:
        transactions = transactions.filter(transaction_date__gte=start_date_str)
    if end_date_str:
        transactions = transactions.filter(transaction_date__lte=end_date_str)
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
    if cash_account_id:
        transactions = transactions.filter(cash_account_id=cash_account_id)
    if category_id:
        transactions = transactions.filter(category_id=category_id)

    # --- Transaction Calculations (unchanged) ---
    totals = transactions.aggregate(
        total_income=Sum('amount', filter=Q(transaction_type='INCOME'), default=0),
        total_expense=Sum('amount', filter=Q(transaction_type='EXPENSE'), default=0)
    )
    net_for_period = totals['total_income'] - totals['total_expense']

    income_by_category = transactions.filter(transaction_type='INCOME').values('category__name').annotate(total_amount=Sum('amount')).order_by('-total_amount')
    expense_by_category = transactions.filter(transaction_type='EXPENSE').values('category__name').annotate(total_amount=Sum('amount')).order_by('-total_amount')


    # --- FINAL CORRECTED AGREEMENT ANALYTICS ---
    receivable_agreements = records(Agreement, request.user).filter(agreement_type='RECEIVABLE', status='ACTIVE')
    total_receivable = receivable_agreements.annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).aggregate(
        total=Coalesce(Sum(F('total_amount') - F('total_payments'), output_field=DecimalField()), Value(0), output_field=DecimalField()) # <-- Final fix is here
    )['total']

    payable_agreements = records(Agreement, request.user).filter(agreement_type='PAYABLE', status='ACTIVE')
    total_payable = payable_agreements.annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).aggregate(
        total=Coalesce(Sum(F('total_amount') - F('total_payments'), output_field=DecimalField()), Value(0), output_field=DecimalField()) # <-- Final fix is here
    )['total']
    # --- END OF CORRECTION ---

    context = {
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

    return render(request, 'accounting/summary_report.html', context)

@login_required
def edit_entity_view(request, pk):
    # Fetch the existing entity object we want to edit
    return counterparty_views.edit(request, key=pk)

@login_required
def agreement_list_view(request):
    # This query now calculates the remaining balance for every agreement
    agreements = records(Agreement, request.user).annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).annotate(
        remaining_balance=F('total_amount') - F('total_payments')
    )

    context = {
        'agreements': agreements
    }
    return render(request, 'accounting/agreement_list.html', context)

@login_required
def agreement_detail_view(request, pk):
    # Get the specific Agreement object from the database
    agreement = record(Agreement, request.user, pk)

    # Get all transactions that are linked to this specific agreement
    transactions = agreement.transactions.filter(office_id=agreement.office_id).order_by('-transaction_date')

    # Calculate the sum of all payments made against this agreement
    total_payments = transactions.aggregate(total=Sum('amount'))['total'] or 0

    # Calculate the remaining balance
    remaining_balance = agreement.total_amount - total_payments

    context = {
        'agreement': agreement,
        'transactions': transactions,
        'total_payments': total_payments,
        'remaining_balance': remaining_balance
    }
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

            # We must specify the output_field in this calculation
            total_payments = updated_agreement.transactions.aggregate(
                total=Coalesce(Sum('amount'), Value(0), output_field=DecimalField())
            )['total']
            # --- END OF FIX ---

            remaining_balance = updated_agreement.total_amount - total_payments

            if updated_agreement.status != 'CANCELLED':
                if remaining_balance <= 0:
                    updated_agreement.status = Agreement.AgreementStatus.COMPLETED
                else:
                    updated_agreement.status = Agreement.AgreementStatus.ACTIVE

            try:
                save_for_user(updated_agreement, request.user)
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
@transaction.atomic # This is a decorator that ensures the two transactions are created together or not at all
def add_transfer_view(request):
    if request.method == 'POST':
        form = TransferForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            transfer_uuid = uuid.uuid4() # A unique ID for this transfer

            # Create the EXPENSE transaction from the source account
            Transaction.objects.create(office_id=require_office_profile(request.user).office_id,
                transaction_date=data['transfer_date'],
                description=f"Transfer to {data['to_account'].name}: {data['description']}",
                amount=data['amount'],
                cash_account=data['from_account'],
                transaction_type=Transaction.TransactionType.EXPENSE,
                transfer_id=transfer_uuid
            )

            # Create the INCOME transaction to the destination account
            Transaction.objects.create(office_id=require_office_profile(request.user).office_id,
                transaction_date=data['transfer_date'],
                description=f"Transfer from {data['from_account'].name}: {data['description']}",
                amount=data['amount'],
                cash_account=data['to_account'],
                transaction_type=Transaction.TransactionType.INCOME,
                transfer_id=transfer_uuid
            )

            return redirect('transaction-list')
    else:
        form = TransferForm(user=request.user, )

    return render(request, 'accounting/add_transfer.html', {'form': form})
