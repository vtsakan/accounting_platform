#!/usr/bin/env python3
"""Operator-only S14 -> S24 clone cutover on the already selected VM."""
import argparse
from copy import deepcopy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

from cloud import require
import preview_common as common
import preview_host as host
import operations_common as oc
import operations_host as ops
import operations_pg as pg

PLAN = Path('/etc/accounting/s24-vm-upgrade-plan.json')
STATE = Path('/etc/accounting/s24-vm-upgrade-state.json')
HOLD = Path('/etc/accounting/s24-upgrade-in-progress')
SOURCE_IMAGE = 'europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:04f9de7016ff1b579d2b6597d8bad3257f890ba3307d4bf9edd3e2fce1168991'
PHASE = 'initialise'


def digest(value): return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def checkpoint(state, phase):
    global PHASE
    PHASE = phase; state['phase'] = phase
    common.private_json(STATE, state)
    print('VMUP-DIAG ' + json.dumps({'phase': phase}), flush=True, file=__import__('sys').stderr)


def query(config, database, sql):
    return host.compose(config, 'exec', '-T', '--user', 'postgres', 'db', 'psql', '-X', '-qAt', '--set=ON_ERROR_STOP=1',
                        '--dbname=' + database, payload=sql.encode()).decode().strip()


def inventory(config):
    return pg.fingerprints(query(config, config['db_name'], 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n' + pg.FINGERPRINT_SQL + '\nCOMMIT;\n'))


def migrations(config):
    return json.loads(query(config, config['db_name'], "SELECT coalesce(json_agg(name ORDER BY name),'[]') FROM django_migrations WHERE app='accounting';"))


def same_source(plan):
    source = plan['source']
    require(host.load() == source, 'Installed release differs from the planned source')
    host.mounted(source)
    require(ops.load()['preview'] == source, 'Backup binding differs from the installed source')
    require(inventory(source) == plan['source_snapshot'], 'Source data changed after planning; rerun plan before deploy')


def stage(value, bundle):
    source = host.load(); target = common.validate(value['target'], published=True)
    require(value['source'] == source and source['published']['image'] == SOURCE_IMAGE, 'This upgrade requires the observed S14 source image')
    require(source['gcp'] == target['gcp'] and all(source[k] == target[k] for k in ('hostname', 'acme_email', 'external_ipv4', 'db_user')), 'Cloud, credential or hostname identity changed')
    require(target['db_name'].startswith('accounting_s24_') and target['db_name'] != source['db_name'], 'A distinct S24 clone database is required')
    require(not STATE.exists(), 'An upgrade attempt already exists; use status rather than overwrite its journal')
    host.mounted(source); ops.check(ops.load()); common.dns(source)
    require(common.run(['docker', 'info', '--format', '{{.DockerRootDir}}']).decode().strip() == '/srv/accounting/docker', 'Unexpected Docker data root')
    source_web = host.compose(source, 'ps', '--quiet', 'web').decode().strip()
    require(source_web, 'The observed S14 web service is missing')
    running_source = common.run(['docker', 'inspect', source_web], json_output=True)[0]
    require(running_source['State']['Running'] and running_source['Config']['Image'] == source['published']['image'], 'Running source image differs from the installed release')
    host.running_image_check(source, host.image_check(source), running_source)
    require(not any((common.HOST_DATA / 'media').iterdir()), 'Private media requires its own recovery plan before this database-only upgrade')
    require(not Path('/etc/accounting/demo-upgrade-in-progress').exists() and not HOLD.exists(), 'An unfinished host upgrade hold exists')
    require(all(common.run(['systemctl', 'is-active', unit]).decode().strip() == 'active' for unit in oc.UNITS), 'Expected active backup and monitoring timers')
    require(len(migrations(source)) == 8 and migrations(source)[-1] == '0008_office_workflow_guards', 'Expected the observed eight S14 migrations')
    size = int(query(source, 'postgres', 'SELECT pg_database_size(' + host.literal(source['db_name']) + ');'))
    require(shutil.disk_usage(common.HOST_DATA).free > max(1024**3, 3 * size), 'Insufficient free data-disk space for a retained database clone')
    require(query(source, 'postgres', 'SELECT count(*) FROM pg_database WHERE datname=' + host.literal(target['db_name']) + ';') == '0', 'Target database already exists; it will not be overwritten')
    release = host.unpack(bundle, value['bundle_sha256'], common.deployment_commit(target))
    require(json.loads((release / 'docker/preview-pins.json').read_text()) ==
            json.loads((host.release_path(source) / 'docker/preview-pins.json').read_text()), 'Database/proxy image changes require a separate reviewed upgrade')
    with tempfile.TemporaryDirectory(prefix='s24-registry-', dir=common.RUN) as directory:
        cli = ['docker', '--config', directory]; registry = target['published']['image'].split('/', 1)[0]
        common.run(cli + ['login', registry, '--username', 'oauth2accesstoken', '--password-stdin'], payload=common.access_token().encode())
        common.run(cli + ['pull', target['published']['image']])
    host.image_check(target)
    from image import export_static
    static = common.HOST_DATA / 'static' / target['published']['commit']
    if not static.exists(): export_static(target['published']['image'], static)
    require((static / 'staticfiles.json').is_file(), 'Static manifest missing')
    host.environment_file(target); host.compose(target, 'config', '--quiet')
    require(set(host.compose(target, 'config', '--services').decode().split()) == {'db', 'web', 'caddy'}, 'Unexpected production service set')
    snapshot = inventory(source)
    plan = {'schema': 1, 'source': source, 'target': target, 'bundle_sha256': value['bundle_sha256'], 'source_snapshot': snapshot,
            'created_at': oc.now(), 'source_migrations': migrations(source), 'source_database_bytes': size}
    common.private_json(PLAN, plan)
    counts = {row['table']: row['rows'] for row in snapshot}
    return {'status': 'Planned', 'plan_sha256': digest(plan), 'source_database': source['db_name'], 'target_database': target['db_name'],
            'source_migrations': plan['source_migrations'], 'users': counts.get('public.auth_user', 0),
            'offices': counts.get('public.accounting_office', 0), 'target_image': target['published']['image'],
            'source_database_changed': False, 'services_restarted': False}


def hold():
    HOLD.write_text('S24 database clone cutover in progress\n'); HOLD.chmod(0o600)
    for unit in ('accounting-preview.service', 'accounting-backup.service', 'accounting-monitor.service'):
        path = Path('/etc/systemd/system') / (unit + '.d') / 's24-upgrade.conf'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[Unit]\nConditionPathExists=!' + str(HOLD) + '\n')
    common.run(['systemctl', 'daemon-reload'])


def pause_timers():
    common.run(['systemctl', 'stop', *oc.UNITS])
    for _ in range(60):
        states = [common.run(['systemctl', 'show', unit, '--property=ActiveState', '--value']).decode().strip()
                  for unit in ('accounting-backup.service', 'accounting-monitor.service')]
        if not any(state in {'active', 'activating', 'deactivating'} for state in states): return
        time.sleep(1)
    common.run(['systemctl', 'start', *oc.UNITS])
    raise RuntimeError('An operations service is still running; retry after it completes')


def resume_timers():
    HOLD.unlink(missing_ok=True)
    common.run(['systemctl', 'start', *oc.UNITS])


def wrapper(commit):
    path = host.RELEASES / commit / 'tools/operations_host.py'
    require(path.is_file(), 'Operations source is missing')
    executable = Path('/usr/local/sbin/accounting-operations')
    executable.write_text('#!/bin/sh\nset -eu\nexec /usr/bin/python3 ' + str(path) + ' "$@"\n'); executable.chmod(0o755)


def migrate(plan):
    source, target = plan['source'], plan['target']
    program = (host.release_path(target) / 'tools/vm_upgrade_migrate.py').read_text()
    command = common.compose_command(host.release_path(target)) + ['run', '--rm', '--no-deps', 'web', 'python', '-c', program, source['db_name'], target['db_name']]
    result = subprocess.run(command, env=common.compose_environment(), capture_output=True)
    if result.returncode:
        safe = [line[len('VMUP-DIAG:'):] for line in result.stderr.decode(errors='replace').splitlines() if line.startswith('VMUP-DIAG:')]
        raise RuntimeError('Clone migration stopped; original retained. ' + (safe[-1] if safe else 'Inspect the retained clone; provider output omitted'))
    lines = [line[len('VMUP-RESULT:'):] for line in result.stdout.decode().splitlines() if line.startswith('VMUP-RESULT:')]
    require(len(lines) == 1, 'Clone migration receipt missing')
    return json.loads(lines[0])


def wait_web(config):
    for _ in range(60):
        identifier = host.compose(config, 'ps', '--quiet', 'web').decode().strip()
        if identifier:
            value = common.run(['docker', 'inspect', identifier], json_output=True)[0]
            if value['State'].get('Health', {}).get('Status') == 'healthy':
                host.running_image_check(config, host.image_check(config), value)
                require(not value['HostConfig'].get('PortBindings'), 'Web must have no published port')
                return
        time.sleep(2)
    raise RuntimeError('New web service did not become healthy')


def prepare(expected):
    require(not STATE.exists(), 'An upgrade attempt exists; inspect status or recover it instead of repeating migrations')
    plan = json.loads(PLAN.read_text()); require(digest(plan) == expected, 'Reviewed plan hash differs')
    same_source(plan); source, target = plan['source'], plan['target']
    require((host.release_path(target) / '.bundle.sha256').read_text().strip() == plan['bundle_sha256'], 'Staged bundle differs')
    host.image_check(target)
    state = {'plan': plan, 'source_operations': ops.load(), 'public_cutover_started': False, 'phase': 'preparing'}
    pause_timers()
    try:
        hold(); checkpoint(state, 'stopping_source')
        host.compose(source, 'stop', 'caddy', 'web')
        state['frozen_snapshot'] = inventory(source); checkpoint(state, 'source_frozen')
        same_source(plan)
        state['before_backup'] = ops.backup(state['source_operations'])['receipt']; checkpoint(state, 'source_backed_up')
        require(query(source, 'postgres', 'SELECT count(*) FROM pg_database WHERE datname=' + host.literal(target['db_name']) + ';') == '0', 'Clone already exists; refusing overwrite')
        query(source, 'postgres', 'CREATE DATABASE "' + target['db_name'] + '" WITH TEMPLATE "' + source['db_name'] + '" OWNER "' + target['db_user'] + '";')
        checkpoint(state, 'cloned')
        require(pg.fingerprints(query(source, target['db_name'], pg.FINGERPRINT_SQL)) == plan['source_snapshot'], 'Clone rows differ from the frozen original')
        state['migration'] = migrate(plan); checkpoint(state, 'migrated_clone')
        require(inventory(source) == plan['source_snapshot'], 'Original database changed during clone migration')
        rebound = deepcopy(state['source_operations']); rebound.update(preview=target, code_commit=common.deployment_commit(target)); oc.validate(rebound)
        state['target_operations'] = rebound; checkpoint(state, 'binding_target')
        common.private_json(common.HOST_CONFIG, target); common.private_json(oc.HOST_CONFIG, rebound)
        host.install_units(host.release_path(target)); wrapper(rebound['code_commit'])
        host.compose(target, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'web')
        wait_web(target)
        settings = host.settings_check(target)
        require(settings['debug'] is False and settings['uid'] == 10001 and settings['secure_cookies'] and settings['hosts'] == [target['hostname']]
                and settings['origins'] == ['https://' + target['hostname']] and settings['proxy'] == ['HTTP_X_FORWARDED_PROTO', 'https']
                and settings['media'] == '/app/media', 'Production settings differ')
        state['after_backup'] = ops.backup(rebound)['receipt']
        checkpoint(state, 'awaiting_off_vm_restore')
        return status()
    except Exception:
        if STATE.exists():
            try: abort()
            except Exception:
                checkpoint(state, 'needs_operator_recovery')
                raise RuntimeError('Upgrade stopped; original database, clone and boot hold retained. Inspect status before recovery') from None
        else: resume_timers()
        raise


def status():
    if not STATE.exists(): return {'status': 'Not applied'}
    state = json.loads(STATE.read_text()); plan = state['plan']
    return {'status': state['phase'], 'source': plan['source'], 'target': plan['target'], 'before_backup': state.get('before_backup'),
            'after_backup': state.get('after_backup'), 'operations': state.get('target_operations'), 'migration': state.get('migration'),
            'public_cutover_started': state.get('public_cutover_started', False), 'original_database_preserved': plan['source']['db_name'],
            'original_database_unchanged': inventory(plan['source']) == plan['source_snapshot'], 'hold_active': HOLD.exists()}


def abort():
    state = json.loads(STATE.read_text()); source, target = state['plan']['source'], state['plan']['target']
    require(not state.get('public_cutover_started'), 'Public target may have new writes; automatic rollback is refused')
    pause_timers(); hold()
    for config in (target, source):
        try: host.compose(config, 'stop', 'caddy', 'web')
        except Exception: pass
    require(inventory(source) == state.get('frozen_snapshot', state['plan']['source_snapshot']), 'Original changed after the freeze; manual recovery review required')
    common.private_json(common.HOST_CONFIG, source); common.private_json(oc.HOST_CONFIG, state['source_operations'])
    host.install_units(host.release_path(source)); wrapper(state['source_operations']['code_commit'])
    host.compose(source, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'web')
    wait_web(source)
    host.compose(source, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'caddy')
    checkpoint(state, 'rolled_back_to_original'); resume_timers()
    return {'status': 'Rolled back to original', 'original_database': source['db_name'], 'clone_retained': target['db_name']}


def activate(restored_sha):
    state = json.loads(STATE.read_text()); target = state['plan']['target']
    require(state['phase'] in {'awaiting_off_vm_restore', 'public_cutover_started', 'needs_public_check'}, 'Target is not awaiting activation')
    require(restored_sha == state['after_backup']['sha256'], 'Off-VM recovery attestation differs from the exact new backup')
    require(host.load() == target and ops.load() == state['target_operations'], 'Target or backup binding changed')
    require(inventory(state['plan']['source']) == state['plan']['source_snapshot'], 'Original changed during recovery')
    wait_web(target)
    state['off_vm_restore_operator_attested_at'] = oc.now()
    state['public_cutover_started'] = True; checkpoint(state, 'public_cutover_started')
    try:
        host.compose(target, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'caddy')
        for attempt in range(45):
            try:
                with urllib.request.urlopen('https://' + target['hostname'] + '/health/ready/', timeout=10) as response:
                    require(response.status == 200 and json.load(response) == {'status': 'ready'}, 'Public readiness differs')
                break
            except Exception:
                if attempt == 44: raise RuntimeError('Public HTTPS readiness is not available') from None
                time.sleep(2)
        caddy_id = host.compose(target, 'ps', '--quiet', 'caddy').decode().strip()
        caddy = common.run(['docker', 'inspect', caddy_id], json_output=True)[0]
        pins = json.loads((host.release_path(target) / 'docker/preview-pins.json').read_text())
        require(caddy['Config']['Image'] == pins['caddy']['reference'], 'Running proxy image differs')
        require(set(caddy['HostConfig'].get('PortBindings') or {}) == {'80/tcp', '443/tcp'}, 'Proxy ports differ')
        db_id = host.compose(target, 'ps', '--quiet', 'db').decode().strip()
        db = common.run(['docker', 'inspect', db_id], json_output=True)[0]
        require(db['Config']['Image'] == pins['postgresql']['reference'], 'Running database image differs')
        require(not db['HostConfig'].get('PortBindings'), 'Database port must remain private')
        common.run(['iptables', '-w', '-C', 'DOCKER-USER', '-d', '169.254.169.254/32', '-j', 'REJECT'])
        state['monitor'] = ops.monitor(state['target_operations'])
        checkpoint(state, 'deployed_and_restored'); resume_timers()
    except Exception:
        checkpoint(state, 'needs_public_check')
        # The verified clone may already have human writes: keep its binding,
        # preserve both databases and resume its backup/alert timers.
        resume_timers()
        raise
    return status()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'prepare', 'status', 'activate', 'abort'))
    parser.add_argument('--input', type=Path); parser.add_argument('--bundle', type=Path)
    parser.add_argument('--plan-sha256'); parser.add_argument('--restored-sha256')
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, 'Run the host command with sudo')
        os.environ.pop('DOCKER_HOST', None); os.environ.pop('DOCKER_CONTEXT', None)
        with open('/run/accounting-preview.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'plan': result = stage(json.loads(args.input.read_text()), args.bundle)
            elif args.action == 'prepare': result = prepare(args.plan_sha256)
            elif args.action == 'activate': result = activate(args.restored_sha256)
            elif args.action == 'abort': result = abort()
            else: result = status()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        print(json.dumps({'status': 'Stopped', 'phase': PHASE, 'error': type(error).__name__,
                          'reason': str(error) if isinstance(error, RuntimeError) else 'Host operation stopped; source data retained'}, ensure_ascii=False))


if __name__ == '__main__': main()
