"""Operator-only local synthetic migration/load/encrypted-recovery rehearsal."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import time

from dev import ROOT, compose_environment, require_local_docker
import operations_common as common
import operations_pg as pg
from r1_gate import digest_object, profile, require
from verify_s05 import HIDDEN_VALUES, redact

LABEL = 'com.docker.compose.project'


class Rehearsal:
    def __init__(self, directory, image_id, identity, workload):
        self.work = Path(directory)
        self.nonce = secrets.token_hex(10)
        self.project = 'accounting-s31-' + self.nonce
        self.identity = common.identity_file(identity)
        self.workload = profile(workload)
        self.image_id = image_id
        require(re.fullmatch(r'sha256:[0-9a-f]{64}', image_id), 'Immutable application image required')
        self.recipient = common.run(['age-keygen', '-y', self.identity]).decode().strip()
        require(re.fullmatch(r'age1[a-z0-9]{58}', self.recipient), 'Native age recovery identity required')
        self.password, self.initial, self.signing, self.owner_password = (secrets.token_urlsafe(64) for _ in range(4))
        HIDDEN_VALUES.update({self.password, self.initial, self.signing, self.owner_password})
        self.environment = {k: v for k, v in compose_environment().items()
                            if not k.startswith(('CELERY_', 'BACKGROUND_', 'FEE_', 'DEV_APP_', 'S31_', 'GUNICORN_', 'WEB_CONCURRENCY'))}
        self.base = {'DJANGO_SETTINGS_MODULE': 'core.settings.production', 'DJANGO_DEBUG': 'false',
            'DJANGO_SECRET_KEY': self.signing, 'DJANGO_ALLOWED_HOSTS': 's31.example.invalid,127.0.0.1',
            'DJANGO_CSRF_TRUSTED_ORIGINS': 'https://s31.example.invalid', 'DJANGO_TRUST_PROXY_HEADERS': 'true',
            'AUTH_MAIL_MODE': 'disabled', 'AUTH_MAIL_LIVE_ENABLED': 'false', 'AUTH_STAFF_MAIL_LIVE_ENABLED': 'false',
            'DB_NAME': self.dbname('base'), 'DB_USER': 's31_app', 'DB_PASSWORD': self.password, 'DB_HOST': 'db', 'DB_PORT': '5432',
            'S31_VERIFY_ID': self.nonce, 'S31_OWNER_PASSWORD': self.owner_password,
            'BACKGROUND_JOBS_ENABLED': 'false', 'FEE_AUTOMATION_ENABLED': 'false', 'GUNICORN_WORKERS': '2'}
        self.pg_image = json.loads((ROOT / 'docker/image-pins.json').read_text())['postgresql']['reference']
        envelope = workload['synthetic_envelope']
        database = {'image': self.pg_image, 'platform': 'linux/amd64', 'networks': ['private'],
            'environment': {'POSTGRES_PASSWORD': self.initial, 'S31_APP_PASSWORD': self.password},
            'tmpfs': ['/tmp:rw,nosuid,size=384m,mode=1777'], 'mem_limit': str(envelope['database_memory_mib']) + 'm',
            'cpus': envelope['database_cpus'],
            'healthcheck': {'test': ['CMD', 'pg_isready', '-U', 'postgres'], 'interval': '2s', 'timeout': '3s', 'retries': 60}}
        application = {'image': image_id, 'platform': 'linux/amd64', 'networks': ['private'],
            'read_only': True, 'tmpfs': ['/tmp:rw,nosuid,size=128m,mode=1777'], 'cap_drop': ['ALL'],
            'security_opt': ['no-new-privileges:true'], 'healthcheck': {'disable': True},
            'volumes': [str(ROOT / 'tools') + ':/opt/s31/tools:ro', str(ROOT / 'docs/implementation/r1_workload.json') + ':/opt/s31/workload.json:ro'],
            'mem_limit': str(envelope['web_memory_mib']) + 'm', 'cpus': envelope['web_cpus']}
        self.definition = {'services': {
            'db': {**database, 'volumes': ['source_database:/var/lib/postgresql/data']},
            'restore_db': {**database, 'volumes': ['recovery_database:/var/lib/postgresql/data']},
            'runner': {**application, 'entrypoint': ['python'], 'environment': self.base, 'command': ['--version']},
            'web': {**application, 'entrypoint': ['gunicorn'], 'command': ['core.wsgi:application', '--config', 'gunicorn.conf.py'],
                    'environment': self.base | {'DB_NAME': self.dbname('candidate')}},
            'restored_web': {**application, 'entrypoint': ['gunicorn'], 'command': ['core.wsgi:application', '--config', 'gunicorn.conf.py'],
                             'environment': self.base | {'DB_HOST': 'restore_db', 'DB_NAME': self.dbname('restored')}},
            }, 'networks': {'private': {'internal': True}}, 'volumes': {'source_database': {}, 'recovery_database': {}}}
        self.compose_file = self.work / 'compose.json'
        self.empty_env = self.work / 'empty.env'; self.empty_env.write_text(''); self.empty_env.chmod(0o600)
        self.command = ['docker', 'compose', '--file', str(self.compose_file), '--project-name', self.project, '--env-file', str(self.empty_env)]
        self.write_definition()
        archive_parent = Path.home() / '.config/totalaccounting/finance-release-rehearsals'
        require(not archive_parent.is_symlink() and not archive_parent.resolve().is_relative_to(ROOT.resolve()), 'Archive destination must stay outside Git')
        archive_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.archive_directory = archive_parent / self.nonce
        self.archive_directory.mkdir(mode=0o700)
        self.stage = 'fresh-resource-preflight'
        for kind in ('container', 'volume', 'network'):
            require(not self.resources(kind), 'Refusing pre-existing resources: ' + self.project)

    def dbname(self, suffix):
        require(suffix in {'base', 'candidate', 'rollback', 'restored'}, 'Unknown isolated database role')
        return 's31_' + self.nonce + '_' + suffix

    def write_definition(self):
        self.compose_file.write_text(json.dumps(self.definition)); self.compose_file.chmod(0o600)

    def resources(self, kind):
        args = ['docker', 'ps', '-aq'] if kind == 'container' else ['docker', kind, 'ls', '-q']
        return common.run(args + ['--filter', 'label=' + LABEL + '=' + self.project], environment=self.environment).decode().split()

    def compose(self, *arguments, checked=True, payload=None, timeout=600):
        result = subprocess.run(self.command + list(arguments), cwd=ROOT, env=self.environment, input=payload,
                                capture_output=True, timeout=timeout)
        if checked and result.returncode:
            diagnostic = redact(result.stderr.decode(errors='replace')[-2500:])
            raise RuntimeError('S31 isolated Docker operation failed at ' + self.stage + ': ' + diagnostic)
        return result

    def container(self, service):
        ids = self.compose('ps', '-q', service).stdout.decode().split()
        require(len(ids) == 1, 'One owned database container required')
        labels = json.loads(common.run(['docker', 'inspect', '--format', '{{json .Config.Labels}}', ids[0]], environment=self.environment))
        require(labels.get(LABEL) == self.project, 'Container ownership mismatch')
        return ids[0]

    def admin(self, service, sql):
        return self.compose('exec', '-T', service, 'psql', '-X', '-U', 'postgres', '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', payload=sql.encode()).stdout

    def create_databases(self, service, suffixes):
        # Password is taken inside the new container, never interpolated into a
        # host command line or printed in resolved Compose output.
        sql = "\\getenv pass S31_APP_PASSWORD\nCREATE ROLE s31_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'pass';\n"
        sql += ''.join('CREATE DATABASE ' + self.dbname(s) + ' OWNER s31_app;\n' for s in suffixes)
        self.admin(service, sql)

    def pg_command(self, service, suffix, executable):
        require(service in {'db', 'restore_db'} and executable in {'psql', 'pg_dump', 'pg_restore'}, 'Fixed PostgreSQL operation required')
        command = ['docker', 'exec', '-i', self.container(service), 'sh', '-c',
                   'PGPASSWORD="$S31_APP_PASSWORD" exec "$@"', 'sh', executable, '-w', '-h', '127.0.0.1', '-U', 's31_app']
        if executable == 'psql':
            command += ['-X', '-At', '-v', 'ON_ERROR_STOP=1', '-d', self.dbname(suffix)]
        elif executable == 'pg_dump':
            command += ['--dbname', self.dbname(suffix)]
        else:
            command += ['--dbname', self.dbname(suffix)]
        return command

    def manage(self, suffix, *arguments):
        return self.compose('run', '--rm', '--no-deps', '-T', '-e', 'DB_NAME=' + self.dbname(suffix),
                            'runner', 'manage.py', *arguments)

    def probe(self, action, *, suffix='candidate', host='db', running=None):
        script = '/opt/s31/tools/s31_runtime_probe.py'
        if running:
            result = self.compose('exec', '-T', running, 'python', script, action, timeout=1200)
        else:
            result = self.compose('run', '--rm', '--no-deps', '-T', '-e', 'DB_NAME=' + self.dbname(suffix),
                '-e', 'DB_HOST=' + host, 'runner', script, action, timeout=1200)
        rows = [line.removeprefix('S31-RESULT ') for line in result.stdout.decode().splitlines() if line.startswith('S31-RESULT ')]
        require(len(rows) == 1, 'Exactly one synthetic probe result required')
        return json.loads(rows[0])

    def ready(self, service):
        code = "import http.client,time\nfor _ in range(60):\n try:\n  c=http.client.HTTPConnection('127.0.0.1',8000,timeout=2);c.request('GET','/health/ready/',headers={'Host':'s31.example.invalid'});r=c.getresponse();r.read();c.close()\n  if r.status==200:break\n except OSError:pass\n time.sleep(1)\nelse:raise SystemExit(1)"
        self.compose('exec', '-T', service, 'python', '-c', code, timeout=150)

    def dump(self, suffix, name):
        path = self.work / (name + '.dump')
        result = pg.dump(self.pg_command('db', suffix, 'psql'), self.pg_command('db', suffix, 'pg_dump'), path, environment=self.environment)
        return path, result

    def encrypt(self, dump_path, snapshot, name):
        manifest = {'format': 'accounting-s10-v1', 'step': 'S31', 'nonce': self.nonce, 'scope': 'synthetic-only',
                    **snapshot, 'image': self.image_id, 'pg_image': self.pg_image,
                    'application_context_digest': self.context, 'workload_sha256': digest_object(self.workload)}
        # Only generated synthetic environment material is in the encrypted
        # archive. The private age identity never enters it or any container.
        recovery = {'schema': 1, 'synthetic_only': True, 'nonce': self.nonce,
                    'DJANGO_SECRET_KEY': self.signing, 'DB_PASSWORD': self.password, 'S31_OWNER_PASSWORD': self.owner_password}
        tar = self.work / (name + '.tar')
        with tar.open('xb') as stream:
            common.write_archive(stream, dump_path, manifest, recovery)
        tar.chmod(0o600)
        require(tar.stat().st_size <= common.MAX_ARCHIVE, 'Encrypted archive input exceeds tmpfs budget')
        encrypted = self.archive_directory / (name + '.tar.age')
        common.run(['age', '--recipient', self.recipient, '--output', encrypted, tar], environment=self.environment)
        encrypted.chmod(0o600)
        tar.unlink()
        return encrypted

    def decrypt(self, encrypted, name):
        tar = self.work / (name + '-decrypted.tar')
        common.run(['age', '--decrypt', '--identity', self.identity, '--output', tar, encrypted], environment=self.environment)
        tar.chmod(0o600)
        require(tar.stat().st_size <= common.MAX_ARCHIVE, 'Decrypted archive exceeds tmpfs budget')
        directory = self.work / (name + '-recovered'); directory.mkdir(mode=0o700)
        manifest, recovery = common.unpack(tar, directory)
        tar.unlink()
        require(manifest['step'] == 'S31' and manifest['nonce'] == self.nonce and manifest['scope'] == 'synthetic-only'
                and manifest['image'] == self.image_id and manifest['pg_image'] == self.pg_image
                and manifest['application_context_digest'] == self.context and manifest['workload_sha256'] == digest_object(self.workload),
                'Decrypted rehearsal provenance differs')
        require(recovery == {'schema': 1, 'synthetic_only': True, 'nonce': self.nonce,
                    'DJANGO_SECRET_KEY': self.signing, 'DB_PASSWORD': self.password, 'S31_OWNER_PASSWORD': self.owner_password},
                'Required synthetic recovery keys differ')
        return directory / 'database.dump', manifest, recovery

    def restore(self, service, suffix, dump_path, expected):
        command = self.pg_command(service, suffix, 'psql')
        raw = common.run(command, payload=b"SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema');\n", environment=self.environment)
        require(raw.decode().strip() == '0', 'Restore target must be empty')
        container = self.container(service)
        filename = '/tmp/s31-' + self.nonce + '-' + suffix + '.dump'
        try:
            # docker cp cannot reliably copy to tmpfs mounts. Use an exclusive,
            # positional writer, then hash and restore a seekable native file.
            with dump_path.open('rb') as stream:
                result = subprocess.run(['docker', 'exec', '-i', container, 'sh', '-c',
                    'set -eu; set -C; umask 077; cat > "$1"', 'sh', filename], stdin=stream,
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=self.environment, timeout=180)
            require(result.returncode == 0, 'Private tmpfs archive transfer failed')
            checksum = common.run(['docker', 'exec', container, 'sha256sum', filename], environment=self.environment).decode().split()[0]
            require('sha256:' + checksum == common.sha(dump_path), 'Private tmpfs archive hash differs')
            common.run(self.pg_command(service, suffix, 'pg_restore') + ['--list', filename], environment=self.environment)
            common.run(self.pg_command(service, suffix, 'pg_restore') +
                       ['--no-owner', '--no-acl', '--exit-on-error', '--single-transaction', filename], environment=self.environment)
        finally:
            common.run(['docker', 'exec', container, 'rm', '-f', '--', filename], environment=self.environment)
        return pg.verify_tables(command, expected, environment=self.environment)

    def execute(self, context):
        self.context = context
        print('[S31] Συνθετική βάση, φόρτος και επαναφορά: ' + self.project, flush=True)
        self.stage = 'start-restricted-source'; self.compose('up', '--detach', '--wait', '--wait-timeout', '180', 'db')
        self.create_databases('db', ['base', 'candidate'])
        versions = {}
        for executable in ('pg_dump', 'pg_restore'):
            value = common.run(['docker', 'exec', self.container('db'), executable, '--version'], environment=self.environment).decode().strip()
            require(re.search(r'\b17\.11\b', value), 'Pinned matching PostgreSQL 17.11 tools required')
            versions[executable] = value
        self.stage = 'baseline-20-migrations'
        for app in ('contenttypes', 'auth', 'sessions', 'admin'):
            self.manage('base', 'migrate', app, '--noinput')
        self.manage('base', 'migrate', 'accounting', '0020_financial_correction_guards', '--noinput')
        seed = self.probe('seed-base', suffix='base')
        baseline_dump, baseline = self.dump('base', 'baseline20')
        self.stage = 'encrypt-baseline-and-clone'
        baseline_archive = self.encrypt(baseline_dump, baseline, 'baseline20')
        restored_dump, baseline_manifest, _ = self.decrypt(baseline_archive, 'baseline20')
        self.restore('db', 'candidate', restored_dump, baseline_manifest['tables'])
        self.stage = 'real-forward-20-to-26-with-retained-data'
        migration = self.probe('migrate-forward')
        pg.verify_tables(self.pg_command('db', 'base', 'psql'), baseline['tables'], environment=self.environment)
        self.manage('candidate', 'makemigrations', '--check', '--dry-run')
        self.stage = 'complete-financial-cycle'; cycle = self.probe('cycle')
        self.stage = 'seed-unapproved-workload'; dataset = self.probe('seed-load')
        self.stage = 'production-http-50-session-benchmark'
        self.compose('up', '--detach', 'web'); self.ready('web')
        measured = self.probe('benchmark', running='web')
        ids = [self.container(service) for service in ('db', 'web')]
        stats = common.run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', *ids], environment=self.environment).decode()
        raw_stats = list(map(json.loads, stats.splitlines()))
        require(len(raw_stats) == 2, 'Both database and web resource samples required')
        resources = []
        for row in raw_stats:
            match = re.fullmatch(re.escape(self.project) + r'-(db|web)-1', row['Name'])
            require(match is not None, 'Unexpected isolated database/web resource identity')
            resources.append({'service': match.group(1), 'memory': row.get('MemUsage'), 'cpu': row.get('CPUPerc')})
        require({row['service'] for row in resources} == {'db', 'web'}, 'Database and web stats must be distinct')
        self.compose('stop', 'web')
        self.stage = 'current-26-encrypted-backup'
        current_dump, current = self.dump('candidate', 'current26')
        current_archive = self.encrypt(current_dump, current, 'current26')
        self.stage = 'recovery-clock-start-and-independent-target'
        began = time.monotonic()
        recovered_dump, current_manifest, recovery = self.decrypt(current_archive, 'current26')
        # Restore service environment is explicitly recovered from archive bytes.
        self.definition['services']['restore_db']['environment']['S31_APP_PASSWORD'] = recovery['DB_PASSWORD']
        self.definition['services']['restored_web']['environment'].update(
            {key: recovery[key] for key in ('DJANGO_SECRET_KEY', 'DB_PASSWORD', 'S31_OWNER_PASSWORD')})
        self.write_definition()
        self.compose('up', '--detach', '--wait', '--wait-timeout', '180', 'restore_db')
        self.create_databases('restore_db', ['rollback', 'restored'])
        self.stage = 'reject-candidate-and-restore-baseline20'
        rollback = self.restore('restore_db', 'rollback', restored_dump, baseline_manifest['tables'])
        self.stage = 'restore-current26-data-and-keys'
        restored = self.restore('restore_db', 'restored', recovered_dump, current_manifest['tables'])
        self.compose('up', '--detach', 'restored_web'); self.ready('restored_web')
        key_proof = self.probe('recovered', running='restored_web')
        rto = time.monotonic() - began
        # This is snapshot age in the rehearsal, not a demonstrated production
        # backup cadence, accepted RPO or recovery service-level commitment.
        age = datetime.now(timezone.utc).timestamp() - common.timestamp(current['snapshot_started_at'])
        require(age >= 0, 'Snapshot cannot be in the future')
        pg.verify_tables(self.pg_command('db', 'base', 'psql'), baseline['tables'], environment=self.environment)
        pg.verify_tables(self.pg_command('db', 'candidate', 'psql'), current['tables'], environment=self.environment)
        return {'nonce': self.nonce, 'migration': migration, 'cycle': cycle, 'dataset': dataset, 'performance': measured,
            'runtime': {'application_image': self.image_id, 'postgresql_image': self.pg_image, 'versions': versions,
                        'container_limits': self.workload['synthetic_envelope'], 'resource_sample': resources,
                        'vm_capacity_inferred': False, 'external_services': 'disabled; actual Redis regression runs separately'},
            'recovery': {'all_public_tables_matched': restored['all_public_tables_match'],
                'tables_checked': restored['tables_checked'], 'rows_checked': restored['rows_checked'],
                'baseline_20_rollback_matched': rollback['all_public_tables_match'], 'source_original_unchanged': True,
                'original_20_tables_checked': len(baseline['tables']), 'original_20_columns_rows_checked': len(seed['retained']),
                'synthetic_rto_seconds': round(rto, 3), 'synthetic_snapshot_age_seconds_at_completion': round(age, 3),
                'proposed_targets_met_in_this_rehearsal': rto <= 28800 and age <= 86400,
                'measurement_includes': 'archive decryption, new target cluster/start/roles, baseline rollback, current restore, all-table comparison, key and real Gunicorn HTTP check',
                'rollback_scope': 'candidate intentionally rejected after real forward migrations before any public exposure; fresh baseline20 logical restore; no old-image/public/DDL-failure rollback claim',
                'off_vm_real_dataset_restore': 'Pending', 'accepted_real_dataset_rpo_rto': 'Pending',
                'encrypted_archives': [str(baseline_archive), str(current_archive)],
                'encrypted_archive_sha256': [common.sha(baseline_archive), common.sha(current_archive)],
                'age_recipient_id': common.recipient_id(self.recipient),
                'recovery_identity_external_to_git_and_containers': True, 'independent_human_key_custody_accepted': False,
                **key_proof}}

    def cleanup(self):
        result = self.compose('down', '--volumes', '--remove-orphans', checked=False, timeout=240)
        require(result.returncode == 0 and not any(self.resources(k) for k in ('container', 'volume', 'network')),
                'S31 cleanup incomplete; inspect only ' + self.project)


def rehearse(image_id, context, identity, workload):
    require_local_docker(); common.check_age(); common.identity_file(identity)
    common.require_tmpfs('/dev/shm')
    require(shutil.disk_usage('/dev/shm').free >= 64 * 1024 * 1024, 'At least 64 MiB free host tmpfs required')
    # Secrets, manifests, dumps and decrypted archives exist only in private tmpfs.
    with tempfile.TemporaryDirectory(prefix='accounting-s31-', dir='/dev/shm') as directory:
        Path(directory).chmod(0o700)
        runner = Rehearsal(directory, image_id, identity, workload)
        try:
            report = runner.execute(context)
        except Exception as error:
            print('S31-REHEARSAL-DIAG ' + json.dumps({'stage': runner.stage, 'error': type(error).__name__}), flush=True)
            raise
        finally:
            runner.cleanup()
    require(not Path(directory).exists(), 'S31 tmpfs plaintext cleanup failed')
    return {**report, 'owned_resources_removed': True, 'plaintext_removed': True}
