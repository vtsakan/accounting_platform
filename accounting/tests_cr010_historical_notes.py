"""Class-scoped old-schema note fixtures; never used by application code.

Migration contracts must insert/read the historical fields that existed before
0037. The current add_note service correctly requires the new subject column.
Keep the original test methods unchanged by binding only their local module
names for the duration of the three historical migration classes. Production
modules, current-schema contracts, SQL guards and migration targets stay intact.
"""
from contextlib import contextmanager
import sys
import uuid

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

from .counterparty_note_services import note_text
from .office_access import locked_office

HISTORICAL_CLASSES = {
    ('accounting.tests_counterparty_journal', 'NoteMigrationTests'),
    ('accounting.tests_counterparty_retirement', 'RetirementMigrationContracts'),
    ('accounting.tests_client_tasks', 'TaskMigrationContracts'),
}
NOTE_TARGET = [('accounting', '0028_counterparty_note_guards')]


def disposable_database():
    if connection.vendor != 'postgresql' or not str(connection.settings_dict.get('NAME', '')).startswith('test_'):
        raise RuntimeError('Historical note fixtures require the disposable PostgreSQL test database.')


@contextmanager
def historical_note_bindings(cls):
    disposable_database()
    if (cls.__module__, cls.__name__) not in HISTORICAL_CLASSES:
        raise RuntimeError('Historical note bindings are limited to the three retained migration classes.')
    if connection.in_atomic_block:
        raise RuntimeError('Bind historical notes before class transactions begin.')
    registry = MigrationExecutor(connection).loader.project_state(NOTE_TARGET).apps
    note_model = registry.get_model('accounting', 'CounterpartyNote')
    expected_columns = {field.column for field in note_model._meta.local_concrete_fields}
    if 'subject' in expected_columns:
        raise RuntimeError('The historical note model must predate subject fields.')

    @transaction.atomic
    def seed_note(user, entity_id, *, body, request_key):
        disposable_database()
        with connection.cursor() as cursor:
            columns = {field.name for field in connection.introspection.get_table_description(cursor, note_model._meta.db_table)}
        if columns != expected_columns:
            raise RuntimeError('Seed historical notes only in the exact old note table schema.')
        office = locked_office(user, 'clients.write')
        # Keep the real insert trigger: it supplies actor label/server clock and
        # enforces active same-office actors, non-archived parties and history.
        note = note_model.objects.create(office_id=office.pk, entity_id=entity_id,
            actor_id=user.pk, actor_label='', request_key=uuid.UUID(str(request_key)), body=note_text(body))
        note.refresh_from_db()
        return note, False

    module = sys.modules[cls.__module__]
    previous = {'CounterpartyNote': module.CounterpartyNote, 'add_note': module.add_note}
    module.CounterpartyNote = note_model
    module.add_note = seed_note
    try:
        yield
    finally:
        for name, value in previous.items():
            setattr(module, name, value)


class HistoricalNoteMigrationSupport:
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.enterClassContext(historical_note_bindings(cls))
