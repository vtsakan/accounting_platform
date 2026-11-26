"""Private Excel workflow: upload, inspect changes, explicitly confirm or cancel."""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.db import DatabaseError
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .capabilities import office_view
from .client_import_services import cancel_import, confirm_import, current_preview, display_rows, owned_import, stage_import
from .entity_profile_models import PERSON_KINDS


class ImportForm(forms.Form):
    file = forms.FileField(label='Αρχείο πελατών', widget=forms.ClearableFileInput(attrs={'accept': '.xlsx'}))


def render_preview(request, row, data, error=None, status=200):
    return render(request, 'accounting/import/preview.html', {'batch': row,
        'rows': display_rows(row.office, data) if data else [], 'mappings': data['mappings'] if data else [],
        'person_kinds': PERSON_KINDS, 'error': error}, status=status)


@office_view('clients.write', mfa=True)
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def upload(request):
    form = ImportForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            batch = stage_import(request.user, form.cleaned_data['file'])
        except ValidationError as error:
            form.add_error(None, error.messages)
        else:
            return redirect('counterparty-import-preview', key=batch.pk)
    return render(request, 'accounting/import/upload.html', {'form': form})


@office_view('clients.write', mfa=True)
@never_cache
@require_GET
def preview(request, key):
    try:
        row, data = current_preview(request.user, key)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
        return redirect('counterparty-import')
    return render_preview(request, row, data)


@office_view('clients.write', mfa=True)
@never_cache
@sensitive_post_parameters()
@sensitive_variables('__ALL__')
@require_POST
def confirm(request, key):
    try:
        row, data = current_preview(request.user, key)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
        return redirect('counterparty-import')
    if data is None:
        return render_preview(request, row, None)
    decisions = []
    expected = {'csrfmiddlewaretoken'}
    for item in data['rows']:
        prefix = 'row_'+item['key']+'_'
        names = [prefix+'action', prefix+'kind', prefix+'replace']
        expected.update(names)
        if any(len(request.POST.getlist(name)) > 1 for name in names):
            return render_preview(request, row, data, 'Υποβάλετε μία τιμή ανά επιλογή.', status=400)
        decisions.append({'key': item['key'], 'action': request.POST.get(names[0], ''),
            'kind': request.POST.get(names[1], ''), 'replace_credentials': request.POST.get(names[2], '') == 'yes'})
    if set(request.POST) - expected:
        return render_preview(request, row, data, 'Η προεπισκόπηση περιέχει μη έγκυρες επιλογές.', status=400)
    try:
        confirm_import(request.user, key, decisions)
    except ValidationError as error:
        return render_preview(request, row, data, ' '.join(error.messages), status=409)
    except DatabaseError:
        return render_preview(request, row, data, 'Η εισαγωγή αναιρέθηκε. Ανεβάστε ξανά το αρχείο και ελέγξτε τις αλλαγές στις καρτέλες.', status=409)
    return redirect('counterparty-import-preview', key=key)


@office_view('clients.write', mfa=True)
@never_cache
@require_POST
def cancel(request, key):
    cancel_import(request.user, key)
    messages.success(request, 'Η προεπισκόπηση ακυρώθηκε.')
    return redirect('counterparty-list')
