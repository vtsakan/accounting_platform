"""Scoped task pages with POST-only versioned completion and reopen actions."""
from datetime import date
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .capabilities import office_view, require_capability
from .client_task_forms import TaskActionForm, TaskEditForm, TaskFields, TaskFilterForm
from .client_task_selectors import decorate, page_context, task_record, task_rows, today
from .client_task_services import change_task, convert_note, may_change
from .counterparty_views import form_error
from .models import ClientTask, CounterpartyNote, Entity
from .office_access import record
from .report_selectors import read_snapshot


def listing(request, *, office=False):
    with read_snapshot(request.user):
        rows = task_rows(request.user)
        if not office:
            rows = rows.filter(assignee_id=request.user.pk)
        form = TaskFilterForm(request.GET)
        if form.is_valid():
            status = form.cleaned_data['status']
            if status == 'ACTIVE':
                rows = rows.filter(status__in=['OPEN', 'WAIT'])
            elif status != 'ALL':
                rows = rows.filter(status=status)
        else:
            rows = rows.none()
        context = page_context(request.user, rows, request.GET.get('page'))
        params = request.GET.copy(); params.pop('page', None)
        return render(request, 'accounting/tasks/list.html', {**context, 'filter_form': form,
            'office_tasks': office, 'task_page_query': params.urlencode()})


@office_view('tasks.read')
@never_cache
@require_GET
def personal(request):
    return listing(request)


@office_view('tasks.office')
@never_cache
@require_GET
def office_tasks(request):
    return listing(request, office=True)


@office_view('tasks.read')
@never_cache
@require_GET
def detail(request, key):
    with read_snapshot(request.user):
        task = task_record(request.user, key)
        profile = require_capability(request.user, 'tasks.read')
        task = decorate(task, request.user, profile, today())
        page = Paginator(
            task.activities.filter(office_id=task.office_id).order_by('-created_at', '-pk'), 25).get_page(request.GET.get('page'))
        page.object_list = list(page.object_list)
        for event in page.object_list:
            event.deadline_day = date.fromisoformat(event.after['due_date'])
        return render(request, 'accounting/tasks/detail.html', {'task': task,
            'activity_page': page, 'action_form': TaskActionForm(initial={'version': task.version})})


@office_view('tasks.write')
@never_cache
@require_http_methods(['GET', 'POST'])
def from_note(request, pk, note_key):
    entity = record(Entity, request.user, pk)
    try:
        note = CounterpartyNote.objects.get(pk=note_key, office_id=entity.office_id, entity=entity)
    except (CounterpartyNote.DoesNotExist, ValueError, TypeError):
        raise Http404('Η σημείωση δεν βρέθηκε.') from None
    existing = task_rows(request.user).filter(source_note=note).first()
    if existing is not None and request.method == 'GET':
        return redirect('task-detail', key=existing.pk)
    form = TaskFields(request.POST if request.method == 'POST' else None, user=request.user,
        initial={'subject': note.subject, 'body': note.body})
    if request.method == 'POST' and form.is_valid():
        try:
            task, _ = convert_note(request.user, entity.pk, note.pk, **form.cleaned_data)
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, 'Η σημείωση συνδέθηκε με εργασία. Το αρχικό κείμενο διατηρήθηκε.')
            return redirect('task-detail', key=task.pk)
    return render(request, 'accounting/tasks/form.html', {'form': form, 'entity': entity, 'source_note': note,
        'task_today': today()}, status=409 if entity.is_archived and request.method == 'GET' else 200)


@office_view('tasks.write')
@never_cache
@require_http_methods(['GET', 'POST'])
def edit(request, key):
    task = task_record(request.user, key)
    if not may_change(task, request.user, require_capability(request.user, 'tasks.write')):
        raise PermissionDenied('Η εργασία αλλάζει μόνο από τον δημιουργό, τον υπεύθυνο ή τον ιδιοκτήτη.')
    form = TaskEditForm(request.POST if request.method == 'POST' else None, user=request.user,
        initial={'subject': task.subject, 'body': task.body, 'due_date': task.due_date, 'assignee': task.assignee_id, 'version': task.version})
    if request.method == 'POST' and form.is_valid():
        try:
            task, _ = change_task(request.user, key, action='UPDATE', **form.cleaned_data)
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, 'Η εργασία ενημερώθηκε. Η αλλαγή καταγράφηκε στο ιστορικό.')
            return redirect('task-detail', key=task.pk)
    return render(request, 'accounting/tasks/form.html', {'form': form, 'task': task, 'entity': task.entity,
        'source_note': task.source_note, 'task_today': today()}, status=409 if task.entity.is_archived and request.method == 'GET' else 200)


def transition(request, key, action):
    task = task_record(request.user, key)
    if not may_change(task, request.user, require_capability(request.user, 'tasks.write')):
        raise PermissionDenied('Η εργασία αλλάζει μόνο από τον δημιουργό, τον υπεύθυνο ή τον ιδιοκτήτη.')
    form = TaskActionForm(request.POST)
    if form.is_valid():
        try:
            task, replay = change_task(request.user, key, action=action, **form.cleaned_data)
        except ValidationError as error:
            form_error(form, error)
        else:
            messages.success(request, 'Η ενέργεια είχε ήδη καταγραφεί.' if replay else (
                {'COMPLETE': 'Η εργασία ολοκληρώθηκε.', 'PENDING': 'Η εργασία τέθηκε σε εκκρεμότητα.',
                 'RESUME': 'Η εργασία συνεχίζεται.', 'REOPEN': 'Η εργασία άνοιξε ξανά.'}[action]))
            return redirect('task-detail', key=task.pk)
    return render(request, 'accounting/tasks/action_error.html', {'task': task, 'form': form}, status=409)


@office_view('tasks.write')
@never_cache
@require_POST
def complete(request, key):
    return transition(request, key, 'COMPLETE')


@office_view('tasks.write')
@never_cache
@require_POST
def reopen(request, key):
    return transition(request, key, 'REOPEN')


@office_view('tasks.write')
@never_cache
@require_POST
def pending(request, key):
    return transition(request, key, 'PENDING')


@office_view('tasks.write')
@never_cache
@require_POST
def resume(request, key):
    return transition(request, key, 'RESUME')
