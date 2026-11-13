"""Explicit staff confirmation posts an obligation; it never creates cash."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from .capabilities import office_view
from .charge_forms import ChargeForm
from .charge_services import post_charge
from .models import Agreement, AgreementTermsVersion
from .office_access import record


@office_view('finance.write')
@never_cache
@sensitive_post_parameters('reason', 'posting_key')
@require_http_methods(['GET', 'POST'])
def add(request, pk):
    agreement = record(Agreement, request.user, pk)
    terms = AgreementTermsVersion.objects.filter(office_id=agreement.office_id, agreement=agreement).first()
    day = timezone.localdate()
    form = ChargeForm(request.POST if request.method == 'POST' else None,
                      initial={'amount': agreement.total_amount, 'effective_date': day, 'due_date': day,
                               'terms_revision': terms.revision if terms else 0,
                               'period': day.strftime('%Y-%m') if terms and terms.billing_mode == 'MONTHLY' else ''})
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            charge = post_charge(request.user, agreement_id=agreement.pk, idempotency_key=str(data['posting_key']),
                                 **{key: data[key] for key in ('terms_revision', 'amount', 'effective_date', 'due_date', 'period', 'reason')})
        except ValidationError as error:
            form.add_error(None, error)
        except DatabaseError as error:
            if getattr(error.__cause__, 'sqlstate', None) not in {'23505', '23514', '40001', '40P01'}:
                raise
            form.add_error(None, 'Η χρέωση δεν ολοκληρώθηκε. Ανανεώστε τα στοιχεία ή επαναλάβετε την ίδια υποβολή.')
        else:
            messages.success(request, 'Η χρέωση καταχωρίστηκε χωρίς κίνηση ταμείου. Αναφορά: ' + str(charge.pk))
            return redirect('agreement-detail', pk=agreement.pk)
    return render(request, 'accounting/charges/add.html', {'agreement': agreement, 'terms': terms, 'form': form})
