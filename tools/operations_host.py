#!/usr/bin/env python3
"""S10 root operations on the existing preview; never restore into its database."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import uuid

from cloud import require
import operations_common as common
import operations_pg as pg
import preview_common as preview
import preview_host as host

RUNTIME = Path('/run/accounting-s10')
DATA = common.STATE.parent
STAGE = 'initialise'


def checkpoint(value):
    global STAGE
    STAGE = value
    print('S10-DIAG ' + json.dumps({'stage': value}), file=sys.stderr, flush=True)


def check(config):
    host.mounted(config['preview'])
    current = host.load()
    require(current == config['preview'] and config['bucket'] == current['gcp']['backup_bucket'],
            'S09 deployment changed; review the recovery configuration')


def load():
    return common.validate(json.loads(common.HOST_CONFIG.read_text()))


def runtime():
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUNTIME.chmod(0o700)
    common.require_tmpfs(RUNTIME)
    require(shutil.disk_usage(RUNTIME).free >= common.MAX_DUMP + 16 * 1024 * 1024, 'Insufficient tmpfs capacity for the preview backup')


@contextmanager
def lock():
    runtime()
    with (RUNTIME / 'backup.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another backup is already running') from None
        yield


def state():
    return json.loads(common.STATE.read_text()) if common.STATE.exists() else {}


def psql_command(config):
    return preview.compose_command(host.release_path(config['preview'])) + ['exec', '-T', '--user', 'postgres', 'db',
        'psql', '--no-psqlrc', '--quiet', '--tuples-only', '--no-align', '--set=ON_ERROR_STOP=1',
        '--dbname=' + config['preview']['db_name']]


def encrypt(dump, manifest, recovery, recipient, output):
    with output.open('xb') as destination:
        output.chmod(0o600)
        process = subprocess.Popen(['age', '--encrypt', '--recipient', recipient], stdin=subprocess.PIPE,
                                   stdout=destination, stderr=subprocess.DEVNULL)
        try:
            common.write_archive(process.stdin, dump, manifest, recovery)
            process.stdin.close()
            require(process.wait(timeout=300) == 0, 'Backup encryption failed')
            destination.flush(); os.fsync(destination.fileno())
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)
    with output.open('rb') as stream:
        require(stream.read(22) == b'age-encryption.org/v1\n', 'Encrypted archive signature missing')


def backup(config):
    checkpoint('backup-guards'); check(config)
    require(not any((preview.HOST_DATA / 'media').iterdir()), 'Private media is nonempty; implement document recovery before backing it up')
    common.check_age()
    with lock():
        DATA.mkdir(mode=0o700, parents=True, exist_ok=True); DATA.chmod(0o700)
        previous = state()
        attempt = common.now()
        # A killed process cannot leave the previous attempt appearing successful.
        preview.private_json(common.STATE, {**previous, 'last_attempt_at': attempt, 'last_attempt_ok': False})
        try:
            with tempfile.TemporaryDirectory(prefix='plaintext-', dir=RUNTIME) as temporary:
                directory = Path(temporary); dump = directory / 'database.dump'
                checkpoint('database-snapshot')
                psql = psql_command(config)
                pg_dump = preview.compose_command(host.release_path(config['preview'])) + ['exec', '-T', '--user', 'postgres',
                          'db', 'pg_dump', '--username=postgres', '--dbname=' + config['preview']['db_name']]
                environment = preview.compose_environment()
                environment['DOCKER_CONFIG'] = str(RUNTIME / 'docker-client')
                pg_version = common.run(psql, payload=b'SHOW server_version_num;\n', environment=environment).decode().strip()
                require(re.fullmatch(r'17[0-9]{4}', pg_version), 'PostgreSQL 17 server required')
                manifest = pg.dump(psql, pg_dump, dump, environment)
                manifest.update(format='accounting-s10-v1', postgresql_version_num=int(pg_version),
                    project_id=config['preview']['gcp']['project_id'], bucket=config['bucket'], recipient_id=config['recipient_id'],
                    operations_commit=config['code_commit'], image=config['preview']['published'],
                    deployment_commit=preview.deployment_commit(config['preview']), private_media='empty; document recovery deferred to S38')
                recovery = {'preview': config['preview'], 'operations': config,
                            'runtime_material_recovery': 'Recreate pinned Secret Manager versions through an authorised custodian; payloads are excluded',
                            'certificate_recovery': 'Caddy may reissue for the controlled hostname; private ACME/certificate keys are excluded'}
                checkpoint('archive-encryption')
                encrypted = DATA / ('pending-' + uuid.uuid4().hex + '.tar.age')
                try:
                    encrypt(dump, manifest, recovery, config['recipient'], encrypted)
                    checkpoint('backup-upload')
                    name = config['prefix'] + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex + '.tar.age'
                    receipt = common.upload(config, encrypted, name)
                finally:
                    encrypted.unlink(missing_ok=True)
                receipt.update(snapshot_started_at=manifest['snapshot_started_at'], uploaded_at=common.now(),
                    recipient_id=config['recipient_id'], project_id=manifest['project_id'],
                    operations_commit=config['code_commit'], image=config['preview']['published']['image'],
                    manifest_sha256='sha256:' + __import__('hashlib').sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()).hexdigest())
                common.validate_receipt(receipt, config)
                checkpoint('receipt-upload')
                common.upload_receipt(config, receipt)
            preview.private_json(common.STATE, {**previous, 'last_success': receipt, 'last_attempt_at': attempt, 'last_attempt_ok': True})
            return {'status': 'Uploaded', 'receipt': receipt, 'plaintext_removed': True, 'cloud_read_or_delete_used': False}
        except Exception:
            preview.private_json(common.STATE, {**previous, 'last_attempt_at': attempt, 'last_attempt_ok': False})
            raise


def metric_payload(config, values, at=None):
    instant = at or common.now()
    resource = {'type': 'gce_instance', 'labels': {'project_id': config['preview']['gcp']['project_id'],
                 'instance_id': config['instance_id'], 'zone': config['preview']['gcp']['zone']}}
    return {'timeSeries': [{'metric': {'type': common.METRIC_PREFIX + name}, 'resource': resource,
             'metricKind': 'GAUGE', 'valueType': 'DOUBLE', 'points': [{'interval': {'endTime': instant},
                 'value': {'doubleValue': float(value)}}]} for name, value in values.items()]}


def observe(config, previous, memory, disks, certificate_seconds, ready, at=None):
    at = time.time() if at is None else at
    last = previous.get('last_success')
    age = at - common.timestamp(last['snapshot_started_at']) if last else 1e9
    require(age >= 0, 'Backup timestamp is in the future')
    values = {'heartbeat': 1, 'backup_age_seconds': age, 'disk_used_ratio': max(disks),
              'memory_used_ratio': 1 - memory['MemAvailable'] / memory['MemTotal'],
              'certificate_seconds': max(0, certificate_seconds), 'readiness': int(ready),
              'backup_last_attempt_ok': int(previous.get('last_attempt_ok', False)),
              'alert_probe': int(previous.get('alert_probe_until', 0) > at)}
    return values


def monitor(config):
    checkpoint('monitor-guards'); check(config)
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        name, value = line.split(':', 1)
        if name in {'MemAvailable', 'MemTotal'}:
            memory[name] = int(value.split()[0])
    disks = [1 - (usage.free / usage.total) for usage in (shutil.disk_usage('/'), shutil.disk_usage('/srv/accounting'))]
    hostname, certificate_seconds, ready = config['preview']['hostname'], 0, False
    try:
        with socket.create_connection((hostname, 443), timeout=10) as raw:
            with ssl.create_default_context().wrap_socket(raw, server_hostname=hostname) as connection:
                certificate_seconds = ssl.cert_time_to_seconds(connection.getpeercert()['notAfter']) - time.time()
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open('https://' + hostname + '/health/ready/', timeout=10) as response:
            ready = response.status == 200 and json.loads(response.read(4096)) == {'status': 'ready'}
    except (OSError, ValueError):
        pass
    previous = state()
    service_result = common.run(['systemctl', 'show', 'accounting-backup.service', '--property=Result', '--value']).decode().strip()
    previous['last_attempt_ok'] = previous.get('last_attempt_ok', False) and service_result == 'success'
    values = observe(config, previous, memory, disks, certificate_seconds, ready)
    checkpoint('monitor-publish')
    common.api('POST', 'https://monitoring.googleapis.com/v3/projects/' + config['preview']['gcp']['project_id'] + '/timeSeries',
               preview.access_token(), metric_payload(config, values))
    report = {'observed_at': common.now(), 'metrics_published': True, 'values': values}
    preview.private_json(common.METRICS, report)
    return {'status': 'Published', **report}


def install(config, bundle, digest):
    checkpoint('install-guards'); check(config)
    runtime()
    require(preview.metadata('instance/id') == config['instance_id'], 'Unexpected VM instance ID')
    require(config.get('code_commit'), 'An operations source commit is required')
    if common.HOST_CONFIG.exists():
        old = load()
        require(all(old.get(k) == config[k] for k in ('recipient', 'bucket', 'prefix', 'retention_days', 'preview')),
                'Existing recovery identity/policy differs; review changes explicitly')
    release = host.unpack(bundle, digest, config['code_commit'])
    # Install only this pinned tool, after VM/mount/release guards. No apt
    # distribution upgrade, application rebuild or Docker restart is performed.
    common.run([sys.executable, release / 'tools/install_age.py', '--directory', '/usr/local/bin'], timeout=180)
    common.check_age()
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    preview.private_json(common.HOST_CONFIG, config)
    launcher = '#!/bin/sh\nset -eu\nexec /usr/bin/python3 ' + str(release / 'tools/operations_host.py') + ' "$@"\n'
    target = Path('/usr/local/sbin/accounting-operations'); target.write_text(launcher); target.chmod(0o755)
    for name in (*common.UNITS, 'accounting-backup.service', 'accounting-monitor.service'):
        target = Path('/etc/systemd/system') / name
        target.write_bytes((release / 'infrastructure/operations' / name).read_bytes()); target.chmod(0o644)
    journal = Path('/etc/systemd/journald@accounting-ops.conf')
    journal.write_bytes((release / 'infrastructure/operations/journald.conf').read_bytes()); journal.chmod(0o644)
    common.run(['systemctl', 'daemon-reload'])
    common.run(['systemctl', 'enable', '--now', *common.UNITS])
    return {'status': 'Installed', 'operations_commit': config['code_commit'], 'app_restarted': False,
            'database_migrated_or_restored': False, 'first_backup_and_recovery': 'Pending'}


def timer_has_triggered(value):
    """Accept raw microseconds or systemctl's finite formatted time span."""
    value = value.strip()
    if value in {'', 'n/a'}:
        return False
    require(len(value) <= 256, 'Backup timer trigger value exceeds its size limit')
    if re.fullmatch(r'[0-9]+', value):
        return int(value) > 0
    # Formatting is locale-independent; accept systemd's documented unit aliases
    # and both Unicode microsecond spellings. Only positivity is needed here.
    units = ('years', 'year', 'y', 'months', 'month', 'M', 'weeks', 'week', 'w',
             'days', 'day', 'd', 'hours', 'hour', 'hr', 'h', 'minutes', 'minute', 'min', 'm',
             'seconds', 'second', 'sec', 's', 'msec', 'ms', 'usec', 'us', '\u00b5s', '\u03bcs', 'nsec', 'ns')
    suffixes = '|'.join(re.escape(unit) for unit in sorted(units, key=len, reverse=True))
    part = re.compile(r'([0-9]+(?:\.[0-9]+)?)\s*(?:' + suffixes + ')')
    require(re.fullmatch(r'(?:' + part.pattern + r'\s*)+', value), 'Unrecognized systemd backup trigger format')
    return any(Decimal(match.group(1)) > 0 for match in part.finditer(value))


def status(config):
    checkpoint('status')
    check(config)
    enabled = {unit: common.run(['systemctl', 'is-enabled', unit]).decode().strip() for unit in common.UNITS}
    active = {unit: common.run(['systemctl', 'is-active', unit]).decode().strip() for unit in common.UNITS}
    trigger = common.run(['systemctl', 'show', 'accounting-backup.timer', '--property=LastTriggerUSecMonotonic', '--value']).decode().strip()
    triggered = timer_has_triggered(trigger)
    token = preview.access_token()
    base = 'https://storage.googleapis.com/storage/v1/b/' + config['bucket']
    permissions = ['storage.objects.' + verb for verb in ('create', 'get', 'list', 'update', 'delete')]
    allowed = common.api('GET', base + '/iam/testPermissions?' + urllib.parse.urlencode({'permissions': permissions}, doseq=True), token).get('permissions', [])
    require(set(allowed) == {'storage.objects.create'}, 'Effective VM backup permissions are not create-only')
    last = state().get('last_success')
    if last:
        for url in (base + '/o?maxResults=1&prefix=' + urllib.parse.quote(common.PREFIX, safe=''),
                    base + '/o/' + urllib.parse.quote(last['object'], safe='') + '?generation=' + last['generation']):
            try:
                common.api('GET', url, token)
            except common.APIError as error:
                require(error.status == 403, 'Unexpected VM backup denial status')
            else:
                raise RuntimeError('VM unexpectedly read or listed backups')
    return {'status': 'Inspected', 'operations_commit': config['code_commit'], 'timers_enabled': enabled,
            'timers_active': active, 'backup': state(),
            'effective_backup_permissions': sorted(allowed), 'backup_read_and_list_denied': bool(last),
            'scheduled_backup_trigger_observed': triggered,
            'backup_service_result': common.run(['systemctl', 'show', 'accounting-backup.service', '--property=Result', '--value']).decode().strip(),
            'backup_service_state': common.run(['systemctl', 'show', 'accounting-backup.service', '--property=ActiveState', '--value']).decode().strip(),
            'monitor': json.loads(common.METRICS.read_text()) if common.METRICS.exists() else None,
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'backup', 'monitor', 'status', 'alert-test'))
    parser.add_argument('--config', type=Path, default=common.HOST_CONFIG)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, 'Run the reviewed VM operations wrapper through sudo')
        config = common.validate(json.loads(args.config.read_text()))
        if args.action == 'install':
            result = install(config, args.bundle, args.sha256)
        elif args.action == 'backup':
            result = backup(config)
        elif args.action == 'monitor':
            result = monitor(config)
        elif args.action == 'alert-test':
            check(config)
            # Operator explicitly requests one bounded test at the configured channel.
            with lock():
                previous = state(); previous['alert_probe_until'] = time.time() + 900
                preview.private_json(common.STATE, previous)
            result = monitor(config)
            result['notification_receipt'] = 'Pending operator observation'
        else:
            result = status(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        record = {'stage': STAGE, 'error': type(error).__name__}
        if type(error) in (ValueError, RuntimeError) or isinstance(error, (common.APIError, common.CommandFailure)):
            record['reason'] = str(error)[:300]
        if isinstance(error, common.APIError):
            record['http_status'] = error.status
        print('S10-DIAG ' + json.dumps(record), file=sys.stderr)
        parser.exit(1, 'S10 VM operation stopped; credentials and provider output omitted.\n')


if __name__ == '__main__':
    main()
