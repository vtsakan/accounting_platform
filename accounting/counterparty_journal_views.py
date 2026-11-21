"""Private, server-rendered journal and note workflow; no external requests."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from .capabilities import office_view
from .counterparty_journal_forms import JournalForm, NoteForm
from .counterparty_journal_selectors import journal_page
from .counterparty_note_services import add_note
from .counterparty_views import form_error
from .models import Entity
from .office_access import record
from .report_selectors import read_snapshot


def journal_links(request, context):
    params = request.GET.copy()
    params.pop('page', None)

    def query(**changes):
        updated = params.copy()
        for key, value in changes.items():
            updated[key] = value
        return '?' + updated.urlencode()

    context['list_url'] = query(view='list')
    context['month_url'] = query(view='month')
    context['page_query'] = params.urlencode()
    calendar = context['journal_calendar']
    calendar['previous_url'] = query(view='month', month=calendar['previous']) if calendar['previous'] else ''
    calendar['next_url'] = query(view='month', month=calendar['next']) if calendar['next'] else ''
    for week in calendar['weeks']:
        for cell in week:
            if cell:
                cell['url'] = query(view='list', start_date=cell['day'].isoformat(), end_date=cell['day'].isoformat())
    return context


@office_view('clients.read')
@never_cache
@require_GET
def journal(request, pk):
    form = JournalForm(request.GET)
    with read_snapshot(request.user):
        context = journal_page(request.user, pk, form, request.GET.get('page'))
        context.update(filter_form=form, note_form=NoteForm())
        return render(request, 'accounting/journal/page.html', journal_links(request, context))


@office_view('clients.write')
@never_cache
@require_http_methods(['GET', 'POST'])
def note_add(request, pk):
    entity = record(Entity, request.user, pk)
    form = NoteForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            note, replay = add_note(request.user, entity.pk, **form.cleaned_data)
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, 'Η σημείωση είχε ήδη αποθηκευτεί.' if replay else 'Η σημείωση αποθηκεύτηκε με ημερομηνία και λογιστή.')
            return redirect(reverse('entity-journal', args=[entity.pk]) + '?kind=note#journal-top')
    return render(request, 'accounting/journal/note_form.html', {'entity': entity, 'form': form},
        status=409 if entity.is_archived and request.method == 'GET' else 200)
