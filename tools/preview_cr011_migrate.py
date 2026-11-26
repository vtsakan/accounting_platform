"""Run only inside the exact target image against a newly cloned CURRENT preview database."""
import json
import os
import re
import sys


def need(value, message):
    if not value:
        raise RuntimeError(message)


def clone_guard(source, target, database, host, vendor, version):
    need(re.fullmatch(r'accounting_cr011_[0-9a-f]{12}', target) is not None and source != target
         and re.fullmatch(r'accounting_cr008_[0-9a-f]{12}',source) is not None
         and database == target and host == 'db' and vendor == 'postgresql' and version == 170011,
         'Only the new restricted-role PG17.11 clone is a migration target')


def snapshot(previous=None):
    from django.db import connection
    q = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute('SET extra_float_digits=3')
        if previous is None:
            cursor.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")
            tables = {}
            for table, name, kind in cursor.fetchall():
                tables.setdefault(table, {'columns': [], 'maximum': None})['columns'].append([name, kind])
            for table, row in tables.items():
                if table in {'django_migrations', 'django_content_type', 'auth_permission'}:
                    cursor.execute('SELECT coalesce(max(id),0) FROM ' + q(table))
                    row['maximum'] = cursor.fetchone()[0]
        else:
            tables = {table: {'columns': row['columns'], 'maximum': row['maximum']} for table, row in previous.items()}
        result = {}
        for table, row in tables.items():
            values = ['trim_scale(t.' + q(name) + ')' if kind == 'numeric' else 't.' + q(name) for name, kind in row['columns']]
            expression = 'jsonb_build_array(' + ','.join(values) + ')::text'
            where = ' WHERE t.id <= %s' if row['maximum'] is not None else ''
            cursor.execute('SELECT count(*),md5(coalesce(string_agg(md5(' + expression + "),'' ORDER BY md5(" + expression + ")),'')) FROM " + q(table) + ' t' + where,
                           [row['maximum']] if row['maximum'] is not None else [])
            count, checksum = cursor.fetchone()
            result[table] = {**row, 'rows': count, 'checksum': checksum}
    if previous is not None:
        need(result == previous, 'Original columns, people, passwords, MFA, sessions or finance changed')
    return result


def main(source, target, action):
    import django
    django.setup()
    from django.db import connection
    from django.core.management import call_command
    clone_guard(source, target, connection.settings_dict['NAME'], os.environ.get('DB_HOST'),
                connection.vendor, connection.pg_version)
    with connection.cursor() as cursor:
        cursor.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user')
        need(not any(cursor.fetchone()), 'Restricted application role required')
        cursor.execute("SELECT name FROM django_migrations WHERE app='accounting' ORDER BY name")
        applied = [r[0] for r in cursor.fetchall()]
    if action == 'migrate':
        need(len(applied) == 36 and applied[-1] == '0036_attachment_guards', 'Expected the exact36-migration CURRENT CR009 source')
        original = snapshot()
        need(len(original)==61,'Compare all61 CURRENT public tables')
        call_command('migrate', interactive=False, verbosity=0)
        snapshot(original)
        call_command('makemigrations', check=True, dry_run=True, verbosity=0)
        call_command('check', deploy=True, fail_level='ERROR', verbosity=0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT name FROM django_migrations WHERE app='accounting' ORDER BY name")
            applied = [r[0] for r in cursor.fetchall()]
            need(len(applied) == 40 and applied[-1] == '0040_staff_access_guards', 'Expected the full CR010/011 schema')
            cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            new_tables = sorted({r[0] for r in cursor.fetchall()} - set(original))
            need(new_tables == sorted(['accounting_agreementcreationreceipt','accounting_counterpartyimport',
                'accounting_staffcredentialrequirement']), 'Expected the exact three new empty CR010/011 tables')
            for table in new_tables:
                cursor.execute('SELECT count(*) FROM ' + connection.ops.quote_name(table))
                need(cursor.fetchone()[0] == 0, 'Migration created unreviewed business work')
        result = {'source_migrations': 36, 'target_migrations': 40, 'old_tables_checked': len(original),
                  'original_columns_rows_passwords_mfa_sessions_preserved': True,
                  'new_business_tables_empty': True, 'restricted_role_migrations': True,
                  'original_database_migrated': False, 'retained_snapshot': original}
    else:
        need(action == 'check', 'Unknown read-only clone check')
        expected = json.load(sys.stdin)
        snapshot(expected)
        result = {'original_columns_rows_passwords_mfa_sessions_preserved': True}
    from accounting.auth_models import AuthenticatorDevice
    devices = 0
    for device in AuthenticatorDevice.objects.all().iterator():
        need(bool(device.bin_key), 'An existing MFA seed cannot be decrypted with the pinned signing material')
        devices += 1
    result['existing_mfa_seeds_decrypted_without_writes'] = devices
    from accounting.models import TaxisCredential,ClientAttachment
    from core.taxis_crypto import open_sealed
    from core.attachment_crypto import unseal
    vaults=0;attachments=0
    for record in TaxisCredential.objects.all().iterator():
        need(len(open_sealed(record))==2,'A retained TaxisNet pair could not be decrypted')
        vaults+=1
    for record in ClientAttachment.objects.exclude(payload=b'').iterator():
        need(bool(unseal(record)),'A retained attachment could not be decrypted')
        attachments+=1
    result['existing_vaults_decrypted_without_writes']=vaults
    result['existing_attachments_decrypted_without_writes']=attachments
    print('CR011VM-RESULT:' + json.dumps(result))


if __name__ == '__main__':
    try:
        main(*sys.argv[1:4])
    except Exception as error:
        # Do not emit SQL, user identifiers, provider errors, keys or MFA material.
        reason = str(error) if isinstance(error, RuntimeError) else 'Clone operation failed; original retained'
        print('CR011VM-DIAG:' + json.dumps({'type': type(error).__name__, 'reason': reason}), file=sys.stderr)
        sys.exit(1)
