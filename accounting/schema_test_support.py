"""Restore the complete discovered schema in the disposable PostgreSQL test DB."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def restore_current_test_schema():
    # A historical migration contract may deliberately leave an older leaf.
    # Ordinary HTTP/concurrency fixtures need the current model schema, not a
    # second hard-coded migration number that can silently downgrade the DB.
    name = str(connection.settings_dict.get('NAME', ''))
    if connection.vendor != 'postgresql' or not name.startswith('test_'):
        raise RuntimeError('Schema restoration is restricted to the disposable PostgreSQL test database.')
    if connection.in_atomic_block:
        raise RuntimeError('Restore the test schema before TestCase class transactions begin.')
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
