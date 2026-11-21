"""GET confirmation is read-only; deletion requires owner, CSRF and version."""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .capabilities import office_view
from .counterparty_retirement_selectors import has_financial_history
from .counterparty_retirement_services import delete_counterparty
from .counterparty_views import form_error
from .models import Entity
from .office_access import record


class DeleteForm(forms.Form):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    confirm = forms.BooleanField(label='Επιβεβαιώνω τη διαγραφή αυτής της αρχειοθετημένης εγγραφής.')


@office_view('clients.delete')
@never_cache
@require_http_methods(['GET', 'POST'])
def delete(request, pk):
    entity = record(Entity, request.user, pk)
    allowed = entity.is_archived and not has_financial_history(entity)
    form = DeleteForm(request.POST if request.method == 'POST' else None,
        initial={'version': entity.record_version})
    if request.method == 'POST' and form.is_valid():
        try:
            delete_counterparty(request.user, pk, version=form.cleaned_data['version'],
                confirmed=form.cleaned_data['confirm'])
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, 'Η αρχειοθετημένη εγγραφή διαγράφηκε από την εφαρμογή.')
            return redirect('counterparty-list')
    return render(request, 'accounting/entity_delete.html',
        {'entity': entity, 'form': form, 'can_delete': allowed})
