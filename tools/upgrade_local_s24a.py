#!/usr/bin/env python3
"""Operator-only retained local demo upgrade: encrypted backup, S24 migrations, preview.

Uses only accounting-client-demo on a local Docker Engine. Never invoked by
package apply or application startup. Does not use SSH, GCP or the VM installers.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from dev import ROOT, compose_command, compose_environment, require_local_docker
from image import candidate_context
import operations_common as common
import operations_pg as pg
from preview_s24a import compose_failure_reason

PROJECT = 'accounting-client-demo'
CONTEXT = 'sha256:aa53c8f70d8ca11881457a7c80ee7e21684c8b4212a86fe9dbfe28ed95220ba0'

# Executed only inside the operator's local one-off web container. All retained
# columns are compared, including password hashes, encrypted MFA and session rows.
MIGRATE = r'''
import json
from pathlib import Path
import sys
import django
from django.core.management import call_command
from django.db import connection

def need(ok, reason):
    if not ok: raise RuntimeError(reason)

def snapshot(table, columns, maximum):
    q = connection.ops.quote_name
    expressions = ['trim_scale(t.' + q(name) + ')' if kind == 'numeric' else 't.' + q(name) for name, kind in columns]
    value = 'jsonb_build_array(' + ','.join(expressions) + ')::text'
    where = ' WHERE t.id <= %s' if maximum is not None else ''
    sql = 'SELECT count(*),md5(coalesce(string_agg(md5(' + value + "),'' ORDER BY md5(" + value + ")),'')) FROM " + q(table) + ' t' + where
    with connection.cursor() as cursor:
        cursor.execute(sql, [maximum] if maximum is not None else [])
        return cursor.fetchone()

phase = 'migration-preflight'
try:
    django.setup()
    expected = sorted(path.stem for path in Path('/app/accounting/migrations').glob('[0-9]*.py'))
    need(connection.vendor == 'postgresql' and connection.pg_version // 10000 == 17, 'postgresql_17_required')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(724240012)')
        need(cursor.fetchone()[0], 'another_local_upgrade_is_running')
        cursor.execute("SET lock_timeout='30s'")
        cursor.execute("SET statement_timeout='120s'")
        cursor.execute("SELECT name FROM django_migrations WHERE app='accounting' ORDER BY name")
        old = [row[0] for row in cursor.fetchall()]
        need(len(expected) == 20 and 12 <= len(old) < 20 and old == expected[:len(old)], 'schema_changed_before_migration')
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute("SET extra_float_digits=3")
        cursor.execute("SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")
        tables = {}
        for table, column, kind in cursor.fetchall(): tables.setdefault(table, []).append((column, kind))
    before = {}
    for table, columns in tables.items():
        maximum = None
        if table in {'django_migrations', 'django_content_type', 'auth_permission'}:
            with connection.cursor() as cursor:
                cursor.execute('SELECT coalesce(max(id),0) FROM ' + connection.ops.quote_name(table))
                maximum = cursor.fetchone()[0]
        before[table] = (columns, maximum, snapshot(table, columns, maximum))
    phase = 'apply-versioned-migrations'
    call_command('migrate', interactive=False, verbosity=0)
    phase = 'retained-records-check'
    for table, (columns, maximum, original) in before.items():
        need(snapshot(table, columns, maximum) == original, 'retained_table_changed:' + table)
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM django_migrations WHERE app='accounting' ORDER BY name")
        need([row[0] for row in cursor.fetchall()] == expected, 's24_leaf_not_reached')
        for table in ('accounting_charge', 'accounting_cashallocation', 'accounting_allocationrelease',
                      'accounting_settlementcommand', 'accounting_financecorrection', 'accounting_cashrefund',
                      'accounting_financeperiodclose'):
            if table not in before:
                cursor.execute('SELECT count(*) FROM ' + connection.ops.quote_name(table))
                need(cursor.fetchone()[0] == 0, 'migration_inferred_financial_work')
        if not any(name == 'opening_date' for name, kind in tables.get('accounting_cashaccount', [])):
            cursor.execute('SELECT count(*) FROM accounting_cashaccount WHERE opening_date IS NOT NULL')
            need(cursor.fetchone()[0] == 0, 'migration_inferred_opening_date')
    print('S24A-UPGRADE-RESULT:' + json.dumps({'source_migrations': len(old), 'target_migrations': 20,
        'original_tables_checked': len(before), 'original_columns_and_rows_preserved': True,
        'accounts_passwords_mfa_and_sessions_preserved': True, 'automatic_financial_posting': False}))
except Exception as error:
    reason = str(error) if isinstance(error, RuntimeError) else 'versioned_migration_or_database_check_failed'
    print('S24A-UPGRADE-DIAG:' + json.dumps({'stage': phase, 'error': type(error).__name__, 'reason': reason}), file=sys.stderr)
    sys.exit(1)
'''


def require(value, reason):
    if not value: raise RuntimeError(reason)


class Runner:
    def __init__(self, port):
        self.command = compose_command(ROOT / '.env', PROJECT)
        self.environment = {**compose_environment(), 'WEB_PORT': str(port)}
        self.stage = 'preflight'

    def run(self, stage, command, payload=None, timeout=300):
        self.stage = stage
        print('[S24A LOCAL] ' + stage, flush=True)
        stdin = {'input': payload} if payload is not None else {'stdin': subprocess.DEVNULL}
        result = subprocess.run([str(value) for value in command], cwd=ROOT, env=self.environment,
                                capture_output=True, timeout=timeout, **stdin)
        if result.returncode:
            reason = compose_failure_reason(result.stdout + b'\n' + result.stderr)
            # Only our own data-free migration diagnostics may be forwarded.
            for line in result.stderr.decode(errors='replace').splitlines():
                preview = re.match(r'^S24A local preview stopped at ([a-z-]{1,40}):', line)
                if preview:
                    reason = 'preview_' + preview.group(1)
                if line.startswith('S24A-UPGRADE-DIAG:'):
                    row = json.loads(line.split(':', 1)[1])
                    if row.get('stage') in {'migration-preflight', 'apply-versioned-migrations', 'retained-records-check'}:
                        reason = row['stage'] + '; ' + row.get('error', 'Error')
                        if row.get('reason', '').startswith('retained_table_changed:'):
                            reason += '; retained_table_changed'
            raise RuntimeError('Command exit=' + str(result.returncode) + '; reason=' + reason + '; raw output omitted')
        return result.stdout

    def compose(self, stage, *arguments, **kwargs):
        return self.run(stage, [*self.command, *arguments], **kwargs)

    def pg_command(self, program):
        # pg_dump never needs stdin; keep Docker from consuming a caller's batch.
        interactive = ['--interactive=false'] if program == 'pg_dump' else []
        return [*self.command, 'exec', '-T', *interactive, 'db', 'sh', '-c',
                'set -eu; export PGPASSWORD="$POSTGRES_PASSWORD"; exec ' + program +
                ' --no-password --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" "$@"', 's24a-local']

    def query(self, sql):
        return self.run('database-schema', self.pg_command('psql') + ['-X', '-qAt', '--set=ON_ERROR_STOP=1'],
                        payload=sql.encode()).decode()


def source_context():
    proof = json.loads((ROOT / 'docs/implementation/evidence/S24A-verification.json').read_text())
    require(proof['status'] == 'Verified' and proof['suite']['tests_run'] == proof['suite']['tests_passed'] == 661,
            'Keep the successful S24A production-image receipt')
    require(len(proof['financial_cases']) == 36 and all(case['outcome'] == 'passed' for case in proof['financial_cases'])
            and all(proof['suite'][key] == 0 for key in ('known_failures_reproduced', 'unexpected_failures',
                'unexpected_errors', 'unexpected_successes', 'skips')), 'Keep the complete successful financial/suite proof')
    require(proof['application_context_digest'] == candidate_context()[1]['digest'] == CONTEXT,
            'Application bytes differ from the verified S24A; no local migration was started')


def backup(runner, config, identity, env_digest):
    root = (Path.home() / '.config/totalaccounting/local-demo-backups').resolve()
    require(not root.is_relative_to(ROOT.resolve()), 'Keep encrypted backups outside the Git repository')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    attempt = Path(tempfile.mkdtemp(prefix='s18-before-s24a.', dir=root))
    encrypted = attempt / 'backup.tar.age'
    runner.stage = 'encrypted-backup'
    print('[S24A LOCAL] encrypted-backup', flush=True)
    common.require_tmpfs('/dev/shm')
    budget = min(common.MAX_DUMP, (shutil.disk_usage('/dev/shm').free - 8 * 1024**2) // 3)
    require(budget >= 1024**2, 'Insufficient private tmpfs space for a bounded local backup')
    with tempfile.TemporaryDirectory(prefix='accounting-s24a-', dir='/dev/shm') as directory:
        work = Path(directory)
        psql = runner.pg_command('psql') + ['-X', '-qAt', '--set=ON_ERROR_STOP=1']
        snapshot = pg.dump(psql, runner.pg_command('pg_dump'), work / 'database.dump',
                           environment=runner.environment, max_bytes=budget)
        shutil.copyfile(ROOT / '.env', work / 'environment.env')
        (work / 'environment.env').chmod(0o600)
        require(common.sha(work / 'environment.env') == env_digest, 'Local .env changed during backup')
        manifest = {'project': PROJECT, 'application_context_digest': CONTEXT, 'snapshot': snapshot,
                    'environment_sha256': env_digest, 'recipient_id': config['recipient_id']}
        (work / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        archive = work / 'backup.tar'
        with tarfile.open(archive, 'w') as tar:
            for name in ('database.dump', 'environment.env', 'manifest.json'):
                tar.add(work / name, arcname=name, recursive=False)
        runner.run('encrypt-backup', ['age', '--recipient', config['recipient'], '--output', encrypted, archive])
        encrypted.chmod(0o600)
        require(encrypted.stat().st_size > 100, 'Encrypted backup is empty')
        archive.unlink()
        runner.run('check-backup-decryption', ['age', '--decrypt', '--identity', identity, '--output', archive, encrypted])
        # Validate only the three files this tool just created; never extract a tar.
        with tarfile.open(archive, 'r:') as tar:
            members = tar.getmembers()
            names = {'database.dump', 'environment.env', 'manifest.json'}
            require(len(members) == 3 and {member.name for member in members} == names
                    and all(member.isfile() and member.size <= budget + 1024**2 for member in members), 'Unexpected backup archive members')
            for member in members:
                with tar.extractfile(member) as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                require('sha256:' + digest == common.sha(work / member.name), 'Decrypted backup differs from source')
        runner.stage = 'source-snapshot-check'
        pg.verify_tables(psql, snapshot['tables'], environment=runner.environment)
    receipt = {'path': str(encrypted), 'sha256': common.sha(encrypted), 'decryption_checked': True,
               'database_dump_and_environment_included': True, 'full_database_restore_rehearsal': False,
               'plaintext_removed': True}
    (attempt / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8003)
    args = parser.parse_args()
    runner = Runner(args.port)
    record = {'status': 'Not started', 'project': PROJECT, 'cloud_or_vm_changed': False,
              'accounts_mfa_or_keys_reset': False, 'volumes_removed': False}
    private = ROOT / 'private/s24a-local-upgrade.json'
    try:
        require(1024 <= args.port <= 65535, 'Choose a local port between 1024 and 65535')
        os.umask(0o077)
        require_local_docker()
        source_context()
        require((ROOT / '.env').is_file(), 'Retained local .env is required; no credentials were generated')
        env_digest = common.sha(ROOT / '.env')
        resolved = json.loads(runner.compose('compose-config', 'config', '--format', 'json'))['services']
        require(not resolved['db'].get('ports') and len(resolved['web']['ports']) == 1
                and all(port.get('host_ip') == '127.0.0.1' and int(port['published']) == args.port for port in resolved['web']['ports']),
                'Only the loopback-bound local demo is supported')
        containers = runner.compose('database-container', 'ps', '--all', '--quiet', 'db').decode().splitlines()
        require(len(containers) == 1, 'Exactly one existing demo database container is required')
        info = json.loads(runner.run('database-identity', ['docker', 'inspect', containers[0]]))[0]
        labels = info['Config'].get('Labels', {})
        db_env = dict(item.split('=', 1) for item in info['Config']['Env'] if '=' in item)
        require(labels.get('com.docker.compose.project') == PROJECT and labels.get('com.docker.compose.service') == 'db'
                and info['Config']['Image'] == resolved['db']['image'], 'Unexpected retained database container/image')
        require(all(db_env.get(key) == str(resolved['db']['environment'][key]) for key in ('POSTGRES_DB', 'POSTGRES_USER', 'POSTGRES_PASSWORD')),
                'Local .env differs from the retained database configuration; no credentials were changed')
        web_env = resolved['web']['environment']
        require(web_env['DJANGO_SETTINGS_MODULE'] == 'core.settings.local' and web_env['DB_HOST'] == 'db'
                and str(web_env['DB_PORT']) == '5432'
                and all(str(web_env['DB_' + suffix]) == db_env['POSTGRES_' + target]
                        for suffix, target in (('NAME', 'DB'), ('USER', 'USER'), ('PASSWORD', 'PASSWORD'))),
                'Web must target only this retained local database with the existing credentials')
        require(any(mount['Type'] == 'volume' and mount['Destination'] == '/var/lib/postgresql/data' for mount in info['Mounts']),
                'Expected the retained project database volume')
        runner.compose('database-start', 'start', '--wait', '--wait-timeout', '120', 'db')
        actual = json.loads(runner.query("SELECT json_build_object('version',current_setting('server_version_num')::integer,"
            "'migrations',(SELECT coalesce(json_agg(name ORDER BY name),'[]') FROM django_migrations WHERE app='accounting'));\n"))
        expected = sorted(path.stem for path in (ROOT / 'accounting/migrations').glob('[0-9]*.py'))
        old = actual['migrations']
        require(actual['version'] // 10000 == 17 and len(expected) == 20 and 12 <= len(old) <= 20 and old == expected[:len(old)],
                'Expected the observed S18/0012 local schema or its exact forward S24 migration prefix')
        previous = json.loads(private.read_text()) if private.exists() else {}
        require(not previous.get('migration_attempted')
                or previous.get('migration', {}).get('original_columns_and_rows_preserved') is True,
                'A previous migration lacks a preservation receipt; keep the retained backup and report its stopped stage before retrying')
        if old != expected:
            old_web = runner.compose('retained-web-container', 'ps', '--all', '--quiet', 'web').decode().splitlines()
            require(len(old_web) == 1, 'Keep the retained demo web container so its original secret-key binding can be checked')
            web_info = json.loads(runner.run('retained-web-identity', ['docker', 'inspect', old_web[0]]))[0]
            web_labels = web_info['Config'].get('Labels', {})
            previous_env = dict(item.split('=', 1) for item in web_info['Config']['Env'] if '=' in item)
            require(web_labels.get('com.docker.compose.project') == PROJECT and web_labels.get('com.docker.compose.service') == 'web'
                    and all(previous_env.get(key) == str(web_env[key]) for key in ('DJANGO_SECRET_KEY', 'DB_NAME', 'DB_USER', 'DB_PASSWORD')),
                    'Retained local web secret/database binding differs; no keys or credentials were changed')
            runner.stage = 'recovery-preflight'
            config = json.loads((ROOT / 'private/operations.json').read_text())
            require(config['separate_key_copy_confirmed'] is True, 'Keep the already confirmed independent recovery copy')
            identity = Path(config['local_identity']).expanduser().resolve()
            require(not identity.is_relative_to(ROOT.resolve()), 'Keep the existing decryption identity outside Git')
            common.identity_file(identity)
            common.check_age()
            recipient = runner.run('recovery-key-check', ['age-keygen', '-y', identity]).decode().strip()
            require(recipient == config['recipient'] and common.recipient_id(recipient) == config['recipient_id'],
                    'Existing recovery identity does not match the configured recipient')
            # Build first, before stopping a usable retained web container.
            runner.compose('development-image-build', 'build', 'web', timeout=3600)
            runner.compose('stop-local-web', 'stop', 'web')
            record.update(status='Web stopped; backup pending', source_migration_count=len(old))
            private.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            private.write_text(json.dumps(record, indent=2) + '\n')
            record['encrypted_backup'] = backup(runner, config, identity, env_digest)
            record['status'] = 'Encrypted backup checked; migration pending'
            private.write_text(json.dumps(record, indent=2) + '\n')
            source_context()
            record['migration_attempted'] = True
            private.write_text(json.dumps(record, indent=2) + '\n')
            output = runner.compose('migrate-and-preserve-records', 'run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'web', '-',
                                    payload=MIGRATE.encode(), timeout=600).decode()
            results = [json.loads(line.split(':', 1)[1]) for line in output.splitlines() if line.startswith('S24A-UPGRADE-RESULT:')]
            require(len(results) == 1, 'Migration preservation receipt missing; web remains stopped')
            record.update(status='Database upgraded', migration=results[0])
            private.write_text(json.dumps(record, indent=2) + '\n')
        else:
            if previous: record = previous
            record['status'] = 'Schema already at S24'
        require(common.sha(ROOT / '.env') == env_digest, 'Local .env changed; inspect before restarting web')
        source_context()
        runner.run('start-material-preview', [sys.executable, ROOT / 'tools/preview_s24a.py', '--port', args.port], timeout=3600)
        record.update(status='Local preview started', url='http://localhost:' + str(args.port) + '/',
                      completed_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
        private.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        private.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__ + '; raw output omitted'
        print(json.dumps({'status': 'Stopped', 'stage': runner.stage, 'reason': reason,
                          'encrypted_backup': record.get('encrypted_backup', {}).get('path'),
                          'cloud_or_vm_changed': False, 'automatic_restore_or_downgrade': False}), file=sys.stderr)
        parser.exit(1, 'S24A local upgrade stopped; preserve the database volume and backup. No accounts or keys were reset.\n')


if __name__ == '__main__': main()
