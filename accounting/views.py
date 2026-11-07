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
    
    accounts_with_balances = CashAccount.objects.filter(is_active=True).annotate(
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
    # --- Get Filter Data from the URL ---
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    transaction_type = request.GET.get('transaction_type')
    cash_account_id = request.GET.get('cash_account')
    category_id = request.GET.get('category')
    entity_id = request.GET.get('entity')
    query = request.GET.get('query')

    # --- Start with a base queryset ---
    transactions = Transaction.objects.select_related('cash_account', 'category', 'entity').all()

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
        'all_cash_accounts': CashAccount.objects.all(),
        'all_categories': Category.objects.all(),
        'all_entities': Entity.objects.all(),
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
    customers = Entity.objects.filter(entity_type='CUSTOMER')
    
    context = {
        'customers': customers
    }
    
    return render(request, 'accounting/customer_list.html', context)


@login_required
def supplier_list_view(request):
    # Fetch only the entities where the entity_type is 'SUPPLIER'
    suppliers = Entity.objects.filter(entity_type='SUPPLIER')
    
    context = {
        'suppliers': suppliers
    }
    
    return render(request, 'accounting/supplier_list.html', context)


from django.shortcuts import render, redirect # Add redirect
from .models import CashAccount, Transaction, Entity
from .forms import ExpenseForm # Import our new form


@login_required
def add_expense_view(request):
    # Pre-calculate balances with the explicit output_field
    payable_agreements = Agreement.objects.filter(agreement_type='PAYABLE', status='ACTIVE').annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).annotate(
        remaining_balance=F('total_amount') - F('total_payments')
    )

    if request.method == 'POST':
        form = ExpenseForm(request.POST, agreements_queryset=payable_agreements)
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
            new_transaction.save()
            return redirect('transaction-list')
    else:
        initial_data = {}
        entity_id = request.GET.get('entity_id')
        if entity_id:
            initial_data['entity'] = entity_id
        
        form = ExpenseForm(initial=initial_data, agreements_queryset=payable_agreements)

    return render(request, 'accounting/add_expense.html', {'form': form})


@login_required
def add_income_view(request):
    # Pre-calculate balances with the explicit output_field
    receivable_agreements = Agreement.objects.filter(agreement_type='RECEIVABLE', status='ACTIVE').annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).annotate(
        remaining_balance=F('total_amount') - F('total_payments')
    )
    
    if request.method == 'POST':
        form = IncomeForm(request.POST, agreements_queryset=receivable_agreements)
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
            new_transaction.save()
            return redirect('transaction-list')
    else:
        initial_data = {}
        entity_id = request.GET.get('entity_id')
        if entity_id:
            initial_data['entity'] = entity_id
        
        form = IncomeForm(initial=initial_data, agreements_queryset=receivable_agreements)

    return render(request, 'accounting/add_income.html', {'form': form})

@login_required
def add_entity_view(request):
    if request.method == 'POST':
        form = EntityForm(request.POST)
        if form.is_valid():
            # Save the form and get the new entity object
            entity = form.save()
            
            # Check the type of the entity that was just created
            if entity.entity_type == 'CUSTOMER':
                # Redirect to the customer list
                return redirect('customer-list')
            else:
                # Redirect to the supplier list
                return redirect('supplier-list')
    else:
        form = EntityForm()

    return render(request, 'accounting/add_entity.html', {'form': form})

@login_required
def entity_detail_view(request, pk):
    # Get the specific Entity object
    entity = get_object_or_404(Entity, pk=pk)

    # 1. Get all agreements for this entity and calculate their balances
    agreements = entity.agreements.all().annotate(
        # For each agreement, calculate the sum of its associated transactions
        total_payments=Coalesce(
            Sum('transactions__amount'),
            Value(0),
            output_field=DecimalField()
        )
    ).annotate(
        # For each agreement, calculate the remaining balance
        remaining_balance=F('total_amount') - F('total_payments')
    )

    # 2. Get all transactions for this entity that are NOT linked to any agreement
    standalone_transactions = entity.entity_transactions.filter(agreement__isnull=True).order_by('-transaction_date')

    # 3. (Optional) Calculate a simple cash balance just for the standalone transactions
    standalone_balance_data = standalone_transactions.aggregate(
        total_income=Sum('amount', filter=Q(transaction_type='INCOME'), default=0),
        total_expense=Sum('amount', filter=Q(transaction_type='EXPENSE'), default=0)
    )
    if entity.entity_type == 'CUSTOMER':
        standalone_balance = standalone_balance_data['total_income'] - standalone_balance_data['total_expense']
    else:
        standalone_balance = standalone_balance_data['total_expense'] - standalone_balance_data['total_income']


    context = {
        'entity': entity,
        'agreements': agreements,
        'standalone_transactions': standalone_transactions,
        'standalone_balance': standalone_balance
    }

    return render(request, 'accounting/entity_detail.html', context)

@login_required
def summary_report_view(request):
    # --- Transaction Filtering (unchanged) ---
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    transaction_type = request.GET.get('transaction_type')
    cash_account_id = request.GET.get('cash_account')
    category_id = request.GET.get('category')

    transactions = Transaction.objects.all()
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
    receivable_agreements = Agreement.objects.filter(agreement_type='RECEIVABLE', status='ACTIVE')
    total_receivable = receivable_agreements.annotate(
        total_payments=Coalesce(Sum('transactions__amount'), Value(0), output_field=DecimalField())
    ).aggregate(
        total=Coalesce(Sum(F('total_amount') - F('total_payments'), output_field=DecimalField()), Value(0), output_field=DecimalField()) # <-- Final fix is here
    )['total']

    payable_agreements = Agreement.objects.filter(agreement_type='PAYABLE', status='ACTIVE')
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
        'all_cash_accounts': CashAccount.objects.all(),
        'all_categories': Category.objects.all(),
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
    entity_to_edit = get_object_or_404(Entity, pk=pk)

    if request.method == 'POST':
        # If the form is submitted, pass the submitted data AND the instance to the form
        form = EntityForm(request.POST, instance=entity_to_edit)
        if form.is_valid():
            form.save() # Save the changes to the existing entity
            # Redirect back to the detail page for that entity
            return redirect('entity-detail', pk=entity_to_edit.pk)
    else:
        # If it's a GET request, create the form and pre-populate it with the existing entity's data
        form = EntityForm(instance=entity_to_edit)
    
    context = {
        'form': form,
        'entity': entity_to_edit
    }
    return render(request, 'accounting/edit_entity.html', context)

@login_required
def agreement_list_view(request):
    # This query now calculates the remaining balance for every agreement
    agreements = Agreement.objects.annotate(
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
    agreement = get_object_or_404(Agreement, pk=pk)

    # Get all transactions that are linked to this specific agreement
    transactions = agreement.transactions.all().order_by('-transaction_date')

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
    if request.method == 'POST':
        form = AgreementForm(request.POST)
        if form.is_valid():
            form.save()
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
        form = AgreementForm(initial=initial_data)
        # --- END OF CHANGES ---

    return render(request, 'accounting/add_agreement.html', {'form': form})

@login_required
def edit_agreement_view(request, pk):
    agreement_to_edit = get_object_or_404(Agreement, pk=pk)

    if request.method == 'POST':
        form = AgreementForm(request.POST, instance=agreement_to_edit)
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
            
            updated_agreement.save()
            
            return redirect('agreement-detail', pk=updated_agreement.pk)
    else:
        form = AgreementForm(instance=agreement_to_edit)
    
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
        form = TransferForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            transfer_uuid = uuid.uuid4() # A unique ID for this transfer

            # Create the EXPENSE transaction from the source account
            Transaction.objects.create(
                transaction_date=data['transfer_date'],
                description=f"Transfer to {data['to_account'].name}: {data['description']}",
                amount=data['amount'],
                cash_account=data['from_account'],
                transaction_type=Transaction.TransactionType.EXPENSE,
                transfer_id=transfer_uuid
            )

            # Create the INCOME transaction to the destination account
            Transaction.objects.create(
                transaction_date=data['transfer_date'],
                description=f"Transfer from {data['from_account'].name}: {data['description']}",
                amount=data['amount'],
                cash_account=data['to_account'],
                transaction_type=Transaction.TransactionType.INCOME,
                transfer_id=transfer_uuid
            )
            
            return redirect('transaction-list')
    else:
        form = TransferForm()

    return render(request, 'accounting/add_transfer.html', {'form': form})