"""Historical archived-open fixture; the CR005 policy is never disabled in app flows.

Pre-CR005 archived parties can legitimately retain unpaid obligations. Old
replay/correction/report contracts still need this historical starting state.
Only the disposable PG test database may seed it, under an exclusive table
lock, without changing a single financial row or the old archive/audit guards.
Only the new archive-veto predicate is temporarily replaced by test DDL; its
exact function definition is restored before returning. Deleted-row protection
stays active. No production setting or API can request historical seeding.
New CR005 archive contracts call the real service and never use this helper.
"""
from django.db import connection, transaction
from django.utils import timezone

from .counterparty_retirement_selectors import archive_blockers
from .counterparty_services import actor_scope, archive_counterparty, event, locked_record
from .models import Entity


@transaction.atomic
def historical_archive(user, key, *, version, archive=True):
    if connection.vendor != 'postgresql' or not str(connection.settings_dict['NAME']).startswith('test_'):
        raise RuntimeError('Historical fixtures are restricted to the disposable PostgreSQL test database.')
    if archive is not True:
        return archive_counterparty(user, key, version=version, archive=archive)
    office = actor_scope(user)
    entity = locked_record(office, key, version)
    if not archive_blockers(entity):
        return archive_counterparty(user, key, version=version, archive=True)
    with connection.cursor() as cursor:
        cursor.execute('LOCK TABLE accounting_entity IN ACCESS EXCLUSIVE MODE')
        cursor.execute("SELECT pg_get_functiondef('accounting_cr005_entity_guard()'::regprocedure)")
        original = cursor.fetchone()[0]
        predicate = 'IF NOT OLD.is_archived AND NEW.is_archived AND EXISTS('
        if original.count(predicate) != 1:
            raise RuntimeError('The exact archive predicate is required for historical test fixtures.')
        cursor.execute(original.replace(predicate, 'IF false AND NOT OLD.is_archived AND NEW.is_archived AND EXISTS(', 1))
    try:
        Entity.objects.filter(pk=entity.pk, office=office).update(is_archived=True,
            archived_at=timezone.now(), archived_by=user)
        entity.refresh_from_db()
        event(entity, user, 'archive', ['is_archived'])
    finally:
        if not connection.needs_rollback:
            with connection.cursor() as cursor:
                cursor.execute(original)
    return entity
