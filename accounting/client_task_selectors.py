"""Office-scoped reads; personal defaults and explicit owner-only overview."""
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Count, Q
from django.http import Http404
from django.utils import timezone

from .capabilities import require_capability
from .models import ClientTask


def today():
    return timezone.localdate(timezone=ZoneInfo('Europe/Athens'))


def tasks_installed():
    if connection.vendor != 'postgresql':
        return False
    with connection.cursor() as cursor:
        cursor.execute("""SELECT (to_regclass('accounting_clienttask') IS NOT NULL)::int
         +(to_regclass('accounting_clienttaskactivity') IS NOT NULL)::int,
         (SELECT count(*) FROM pg_trigger WHERE tgenabled='O' AND NOT tgisinternal AND
          (tgname IN('cr006_task_guard','cr006_task_activity') AND tgrelid=to_regclass('accounting_clienttask')
           OR tgname='cr006_activity_guard' AND tgrelid=to_regclass('accounting_clienttaskactivity')
           OR tgname='cr006_archive_guard' AND tgrelid=to_regclass('accounting_entity')
           OR tgname='cr006_delete_guard' AND tgrelid=to_regclass('accounting_counterpartydeletion'))),
         (SELECT count(*) FROM django_migrations WHERE app='accounting'
          AND name IN('0031_client_tasks','0032_client_task_guards'))""")
        tables, guards, migrations = cursor.fetchone()
    if (tables or guards or migrations) and (tables != 2 or guards != 5 or migrations != 2):
        raise RuntimeError('Η αναβάθμιση του χώρου εργασιών δεν έχει ολοκληρωθεί.')
    return tables == 2


def active_members(user):
    profile = require_capability(user, 'tasks.write')
    return get_user_model().objects.filter(is_active=True, accountant_profile__office_id=profile.office_id,
        accountant_profile__is_active=True, accountant_profile__role__in=['owner', 'accountant']).order_by('username', 'pk')


def task_rows(user):
    profile = require_capability(user, 'tasks.read')
    if not tasks_installed():
        return ClientTask.objects.none()
    from .counterparty_retirement_selectors import visible_counterparties
    from .models import Entity
    visible = visible_counterparties(Entity.objects.filter(office_id=profile.office_id)).values('pk')
    return ClientTask.objects.filter(office_id=profile.office_id, entity_id__in=visible).select_related(
        'entity', 'assignee', 'creator', 'source_note', 'completed_by').order_by('due_date', 'created_at', 'pk')


def task_record(user, key):
    try:
        return task_rows(user).get(pk=key)
    except (ClientTask.DoesNotExist, ValueError, TypeError):
        raise Http404('Η εργασία δεν βρέθηκε.') from None


def decorate(task, user, profile, day):
    task.days_left = (task.due_date - day).days
    task.overdue_days = max(0, -task.days_left)
    task.can_change = (profile.role == 'owner' or user.pk in (task.creator_id, task.assignee_id)) and not task.entity.is_archived
    return task


def page_context(user, queryset, number=None):
    profile = require_capability(user, 'tasks.read'); day = today()
    totals = queryset.aggregate(total=Count('pk'), open=Count('pk', filter=Q(status='OPEN')),
        overdue=Count('pk', filter=Q(status='OPEN', due_date__lt=day)), due_today=Count('pk', filter=Q(status='OPEN', due_date=day)))
    page = Paginator(queryset, 25).get_page(number)
    page.object_list = [decorate(t, user, profile, day) for t in page.object_list]
    return {'task_page': page, 'task_totals': totals, 'task_today': day, 'task_owner': profile.role == 'owner'}


def dashboard_tasks(user):
    profile = require_capability(user, 'tasks.read')
    rows = task_rows(user).filter(assignee_id=user.pk, status='OPEN'); day = today()
    totals = rows.aggregate(total=Count('pk'), overdue=Count('pk', filter=Q(due_date__lt=day)),
        due_today=Count('pk', filter=Q(due_date=day)))
    return {'my_tasks': [decorate(t, user, profile, day) for t in rows[:8]], 'my_task_totals': totals,
        'task_today': day, 'task_owner': profile.role == 'owner'}


def client_tasks(user, entity, number=None):
    return page_context(user, task_rows(user).filter(entity=entity).order_by('-status', 'due_date', 'created_at', 'pk'), number)


def open_client_tasks(entity):
    if not tasks_installed():
        return ClientTask.objects.none()
    return ClientTask.objects.filter(office_id=entity.office_id, entity=entity, status='OPEN').order_by('due_date', 'created_at', 'pk')
