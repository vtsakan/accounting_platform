"""S14 -> S24 clone-only migration and original-column preservation proof.

Executed explicitly by the operator inside the pinned production image. Never
called by application startup, package apply, or by the implementation agent.
"""
import json
import os
import sys
import django
from django.core.management import call_command
from django.db import connection


def require(value, reason):
    if not value: raise RuntimeError(reason)


def snapshot(table, columns, maximum=None):
    q = connection.ops.quote_name
    expressions = ['trim_scale(t.' + q(name) + ')' if kind == 'numeric' else 't.' + q(name) for name, kind in columns]
    value = 'jsonb_build_array(' + ','.join(expressions) + ')::text'
    where = ' WHERE t.id <= %s' if maximum is not None else ''
    sql = 'SELECT count(*),md5(coalesce(string_agg(md5(' + value + "),'' ORDER BY md5(" + value + ")),'')) FROM " + q(table) + ' t' + where
    with connection.cursor() as cursor:
        cursor.execute(sql, [maximum] if maximum is not None else [])
        return cursor.fetchone()


def migrate_clone(source, target):
    django.setup()
    require(connection.vendor == 'postgresql' and connection.pg_version == 170011, 'PostgreSQL 17.11 required')
    require(connection.settings_dict['NAME'] == target and target != source and target.startswith('accounting_s24_'), 'Refusing migration of the original database')
    with connection.cursor() as cursor:
        cursor.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user')
        require(not any(cursor.fetchone()), 'Migration requires the restricted application role')
        cursor.execute("SELECT name FROM django_migrations WHERE app='accounting' ORDER BY name")
        old = [row[0] for row in cursor.fetchall()]
        require(len(old) == 8 and old[-1] == '0008_office_workflow_guards', 'Clone is not the observed S14 schema')
        cursor.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")
        tables = {}
        for table, column, kind in cursor.fetchall(): tables.setdefault(table, []).append((column, kind))
    before = {}
    append_only = {'django_migrations', 'django_content_type', 'auth_permission'}
    for table, columns in tables.items():
        maximum = None
        if table in append_only:
            with connection.cursor() as cursor:
                cursor.execute('SELECT coalesce(max(id),0) FROM ' + connection.ops.quote_name(table)); maximum = cursor.fetchone()[0]
        before[table] = (columns, maximum, snapshot(table, columns, maximum))
    # Each migration retains its own atomic guards. A failed clone is never
    # promoted, repaired automatically, reverse-migrated or used as the source.
    call_command('migrate', interactive=False, verbosity=1)
    call_command('makemigrations', check=True, dry_run=True, verbosity=0)
    call_command('check', deploy=True, fail_level='ERROR', verbosity=0)
    for table, (columns, maximum, expected) in before.items():
        require(snapshot(table, columns, maximum) == expected, 'Original table columns or rows changed: ' + table)
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM django_migrations WHERE app='accounting' ORDER BY name"); applied = [row[0] for row in cursor.fetchall()]
        require(len(applied) == 20 and applied[-1] == '0020_financial_correction_guards', 'S24 migration leaf not reached')
        for table in ('accounting_financecommand', 'accounting_charge', 'accounting_cashallocation', 'accounting_allocationrelease', 'accounting_financecorrection', 'accounting_cashrefund', 'accounting_financeperiodclose'):
            cursor.execute('SELECT count(*) FROM ' + connection.ops.quote_name(table)); require(cursor.fetchone()[0] == 0, 'Migration inferred financial work: ' + table)
        cursor.execute("SELECT count(*) FROM accounting_agreementtermsversion WHERE billing_mode<>'UNREVIEWED' OR revision<>0")
        require(cursor.fetchone()[0] == 0, 'Legacy terms were implicitly reviewed')
        cursor.execute('SELECT count(*) FROM accounting_cashaccount WHERE opening_date IS NOT NULL')
        require(cursor.fetchone()[0] == 0, 'Migration inferred a legacy opening date')
    return {'migrations': applied, 'original_tables_checked': len(before), 'original_columns_rows_and_people_preserved': True,
            'mfa_and_password_rows_preserved': True, 'restricted_role_migration': True,
            'automatic_financial_posting': False, 'original_database_migrated': False}


if __name__ == '__main__':
    try:
        print('VMUP-RESULT:' + json.dumps(migrate_clone(*sys.argv[1:3])))
    except Exception as error:
        # Whitelisted migration stop messages contain record IDs, not payloads.
        message = str(error)[:280] if isinstance(error, RuntimeError) else 'Clone migration failed; original retained'
        print('VMUP-DIAG:' + json.dumps({'error': type(error).__name__, 'reason': message}), file=sys.stderr)
        sys.exit(1)
