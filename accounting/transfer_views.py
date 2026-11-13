"""Greek transfer entry; no edit/delete path for either posted leg."""
import uuid
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from .capabilities import office_view, require_capability
from .finance_services import fingerprint, post_transfer, submission_key
from .forms import TransferForm
from .models import FinanceCommand, Transaction
from .office_access import records


def existing_submission(form, user):
    """Only a completed transfer may restore its own retired account choices.

    This makes an unchanged browser retry work after account retirement. The
    atomic service still checks fresh authority and the full canonical payload;
    restoring a choice does not authorize new work on a retired account.
    """
    if not form.is_bound or not form.data.get('posting_key'):
        return
    try:
        key = str(uuid.UUID(form.data['posting_key']))
    except (ValueError, TypeError, AttributeError):
        return
    office = require_capability(user, 'finance.write').office_id
    command = FinanceCommand.objects.filter(office_id=office, operation='cash.transfer',
                                            key_digest=fingerprint(key), state='completed').first()
    if command is None:
        return
    pair = list(Transaction.objects.filter(office_id=office, command=command, posting_kind='TRANSFER'))
    if len(pair) != 2:
        return
    form.replay_transfer = True
    for name, direction in (('from_account', 'EXPENSE'), ('to_account', 'INCOME')):
        entry = next((entry for entry in pair if entry.transaction_type == direction), None)
        if entry is not None:
            field = form.fields[name]
            field.queryset = records(field.queryset.model, user).filter(
                Q(pk__in=field.queryset.values('pk')) | Q(pk=entry.cash_account_id))


@office_view('finance.write')
@never_cache
@sensitive_post_parameters('description', 'posting_key')
@require_http_methods(['GET', 'POST'])
def transfer(request):
    form = TransferForm(request.POST if request.method == 'POST' else None, user=request.user,
                        initial={'transfer_date': timezone.localdate()})
    if request.method == 'POST':
        existing_submission(form, request.user)
        if form.is_valid():
            data = form.cleaned_data
            try:
                pair = post_transfer(request.user, idempotency_key=submission_key(request, data),
                                     **{name: data[name] for name in
                                        ('from_account', 'to_account', 'amount', 'transfer_date', 'description')})
            except ValidationError as error:
                form.add_error(None, error)
            except DatabaseError as error:
                if getattr(error.__cause__, 'sqlstate', None) not in {'23505', '23514', '40001', '40P01'}:
                    raise
                form.add_error(None, 'Η μεταφορά δεν ολοκληρώθηκε. Επαναλάβετε με την ίδια ταυτότητα καταχώρισης· δεν καταχωρίζεται μόνο το ένα σκέλος.')
            else:
                messages.success(request, 'Η μεταφορά καταχωρίστηκε και στα δύο ταμεία. Αναφορά: ' + str(pair[0].command_id) + '. Η ίδια υποβολή δεν δημιουργεί δεύτερη μεταφορά.')
                return redirect('transaction-list')
    return render(request, 'accounting/add_transfer.html', {'form': form})
