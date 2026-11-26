from .finance_services import legacy_settlement, submission_key, post_transfer
from . import counterparty_views
from django.core.exceptions import ValidationError
from django.contrib import messages
from django.db import DatabaseError
from .agreement_creation_forms import AgreementCreationForm
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
    from .report_views import overview
    return overview(request)


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
    from .report_views import period
    return period(request)

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
    from .settlement_selectors import allocation_history
    context['allocation_page'] = Paginator(allocation_history(request.user, agreement=agreement), 20).get_page(request.GET.get('allocation_page'))
    from .capabilities import require_capability
    from .correction_forms import ChargeCorrectionForm
    from .correction_selectors import correction_history
    context['can_correct'] = require_capability(request.user,'finance.read').role=='owner'
    for charge in context['charge_page']:
        charge.correction_form = ChargeCorrectionForm(auto_id='id_charge_'+charge.pk.hex+'_%s') if context['can_correct'] and not charge.reversed_by_day else None
    context['correction_history'] = correction_history(request.user,agreement=agreement)[:20]
    return render(request, 'accounting/agreement_detail.html', context)

@login_required
def add_agreement_view(request):
    validate_filter_ids(request)
    if request.method == 'POST':
        form = AgreementCreationForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                agreement = form.save()
            except ValidationError as error:
                form.add_error(None, error)
            except DatabaseError as error:
                if getattr(error.__cause__, 'sqlstate', None) not in {'23505', '23514', '40001', '40P01'}:
                    raise
                form.add_error(None, 'Η συμφωνία δεν ολοκληρώθηκε. Επαναλάβετε την ίδια υποβολή.')
            else:
                messages.success(request, 'Η συμφωνία καταχωρίστηκε. Μπορείτε να προσθέσετε χρέωση από την καρτέλα της.')
                return redirect('agreement-detail', pk=agreement.pk)
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
        form = AgreementCreationForm(user=request.user, initial=initial_data)
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
