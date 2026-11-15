#!/usr/bin/env python3
"""Explicit root S24 -> S24A image/static switch; never migrates/restores a database."""
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid

from cloud import require
import image
import preview_common as common
import preview_host as host
import preview_events as events
import operations_common as oc
import operations_host as ops
import operations_pg as pg
import vm_material_common as policy

STATE = Path('/etc/accounting/s24a-ui-release-state.json')
HOLD = Path('/etc/accounting/s24a-ui-release-in-progress')
CRITICAL = ('compose.production.yml', 'infrastructure/Caddyfile', 'docker/preview-pins.json',
            'docker/production-entrypoint.sh', 'requirements.txt', 'requirements-tools.txt',
            'tools/preview_host.py', 'tools/preview_common.py', 'tools/operations_host.py',
            'tools/operations_common.py', 'tools/operations_pg.py', 'tools/cloud.py',
            'tools/image.py', 'tools/static_export.py', 'tools/dev.py', 'tools/preview_events.py', 'tools/verify_s05.py')


def checkpoint(state, phase):
    state['phase'] = phase
    common.private_json(STATE, state)
    events.checkpoint(phase)


def container(config, name):
    identifier = host.compose(config, 'ps', '--all', '--quiet', name).decode().strip()
    require(identifier and '\n' not in identifier, 'ui_container_identity_mismatch')
    value = common.run(['docker', 'inspect', identifier], json_output=True)[0]
    labels = value['Config'].get('Labels', {})
    require(labels.get('com.docker.compose.project') == 'accounting-preview'
            and labels.get('com.docker.compose.service') == name, 'ui_container_identity_mismatch')
    if name != 'caddy': require(not value['HostConfig'].get('PortBindings'), 'ui_private_port_exposed')
    return value


def query(config, sql):
    return host.compose(config, 'exec', '-T', '--user', 'postgres', 'db', 'psql', '-X', '-qAt',
                        '--set=ON_ERROR_STOP=1', '--dbname=' + config['db_name'], payload=sql.encode()).decode().strip()


def inventory(config):
    return pg.fingerprints(query(config, 'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n' + pg.FINGERPRINT_SQL + '\nCOMMIT;\n'))


def schema(config, release):
    actual = json.loads(query(config, "SELECT coalesce(json_agg(name ORDER BY name),'[]') FROM django_migrations WHERE app='accounting';"))
    expected = sorted(path.stem for path in (release / 'accounting/migrations').glob('[0-9]*.py'))
    require(len(expected) == 20 and actual == expected, 'ui_schema_mismatch')
    return actual


def runtime_secrets():
    return {name: common.file_sha(common.RUN / name) for name in ('signing', 'database')}


def web_identity(config):
    environment = dict(item.split('=', 1) for item in container(config, 'web')['Config']['Env'] if '=' in item)
    require(all(environment.get(key) == value for key, value in {
        'DJANGO_SETTINGS_MODULE': 'core.settings.production', 'DB_NAME': config['db_name'],
        'DB_USER': config['db_user'], 'DB_HOST': 'db', 'DB_PORT': '5432',
        'DJANGO_SECRET_KEY_FILE': '/run/secrets/signing', 'DB_PASSWORD_FILE': '/run/secrets/database'}.items()),
        'ui_container_identity_mismatch')
    code = "import hashlib,json;from pathlib import Path;print(json.dumps({name:'sha256:'+hashlib.sha256(Path('/run/secrets/'+name).read_bytes()).hexdigest() for name in ('signing','database')}))"
    actual = json.loads(host.compose(config, 'exec', '-T', 'web', 'python', '-c', code))
    require(actual == runtime_secrets(), 'ui_runtime_secret_changed')


def database_unchanged(state, config):
    require(container(config, 'db')['Id'] == state['database_container'], 'ui_database_restarted')
    require(query(config, 'SELECT pg_postmaster_start_time()::text;') == state['database_started'], 'ui_database_restarted')
    require(runtime_secrets() == state['runtime_secrets'], 'ui_runtime_secret_changed')


def wait_web(config):
    for _ in range(90):
        data = container(config, 'web')
        if data['State'].get('Health', {}).get('Status') == 'healthy':
            host.running_image_check(config, host.image_check(config), data)
            web_identity(config)
            settings = host.settings_check(config)
            require(settings['debug'] is False and settings['hosts'] == [config['hostname']]
                    and settings['secure_cookies'] and settings['uid'] == 10001, 'ui_container_identity_mismatch')
            return
        time.sleep(1)
    raise RuntimeError('ui_web_not_healthy')


def maintenance():
    require(not HOLD.exists() and not Path('/etc/accounting/s24-upgrade-in-progress').exists(), 'ui_existing_maintenance_hold')
    HOLD.write_text('S24A image-only maintenance; database and keys retained\n'); HOLD.chmod(0o600)
    for name in ('accounting-preview.service', 'accounting-backup.service', 'accounting-monitor.service'):
        path = Path('/etc/systemd/system') / (name + '.d/s24a-ui-release.conf')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('[Unit]\nConditionPathExists=!' + str(HOLD) + '\n')
    common.run(['systemctl', 'daemon-reload'])
    common.run(['systemctl', 'stop', *oc.UNITS])
    for _ in range(60):
        busy = [common.run(['systemctl', 'show', name, '--property=ActiveState', '--value']).decode().strip()
                for name in ('accounting-backup.service', 'accounting-monitor.service')]
        if not any(value in {'active', 'activating', 'deactivating'} for value in busy): return
        time.sleep(1)
    raise RuntimeError('ui_operations_busy')


def resume_operations():
    HOLD.unlink(missing_ok=True)
    common.run(['systemctl', 'start', *oc.UNITS])


def bind(config, operations):
    common.private_json(common.HOST_CONFIG, config)
    common.private_json(oc.HOST_CONFIG, operations)
    common.private_json(common.HOST_DATA / 'preview-state.json',
                        {'commit': 'git:' + config['published']['commit'], 'initialised': True})


def merge_hashed_assets(source, destination):
    old = json.loads((source / 'staticfiles.json').read_text())['paths']
    for name in set(old.values()):
        original = policy.static_file(source, name)
        target = destination / original.relative_to(source.resolve())
        if target.exists():
            require(not target.is_symlink() and common.file_sha(target) == common.file_sha(original), 'ui_static_collision')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target); target.chmod(0o644)


def static_assets(config):
    directory = common.HOST_DATA / 'static' / config['published']['commit']
    manifest = json.loads((directory / 'staticfiles.json').read_text())['paths']
    return [{'path': '/static/' + manifest[name], 'sha256': common.file_sha(policy.static_file(directory, manifest[name]))}
            for name in policy.ASSETS]


def summary(state):
    return {'status': state['phase'], 'hostname': state['target']['hostname'],
            'source_image': state['source']['published']['image'], 'image': state['target']['published']['image'],
            'active_image': host.load()['published']['image'],
            'active_database': state['source']['db_name'], 'database_migrated': False, 'database_restored': False,
            'database_restart_requested': False, 'accounts_mfa_or_keys_reset': False,
            'tables_checked': len(state.get('snapshot', [])), 'all_original_rows_preserved': state.get('preserved', False),
            'before_backup': state.get('before_backup'), 'after_backup': state.get('after_backup'),
            'hold_active': HOLD.exists(), 'static_assets': state.get('static_assets', []),
            'completed_at': state.get('completed_at'),
            'off_vm_restore_attested': state.get('off_vm_restore_attested', False),
            'actual_browser_mfa_acceptance': 'Pending operator login'}


def prepare(value, bundle):
    events.checkpoint('ui-preflight')
    if STATE.exists():
        state = json.loads(STATE.read_text())
        require(state['source'] == value['source'] and state['target'] == value['target'], 'ui_source_changed')
        require(state['phase'] in {'ui-awaiting-restore', 'ui-activate', 'ui-public-check', 'ui-complete'}, 'ui_previous_attempt_needs_review')
        return state
    source, target = value['source'], value['target']
    policy.same_database(source, target)
    require(host.load() == source, 'ui_source_changed')
    host.mounted(source)
    common.dns(source)
    require(common.run(['docker', 'info', '--format', '{{.DockerRootDir}}']).decode().strip() == '/srv/accounting/docker', 'ui_wrong_target')
    old_operations = ops.load()
    require(old_operations['preview'] == source, 'ui_source_changed')
    require(not HOLD.exists() and not Path('/etc/accounting/s24-upgrade-in-progress').exists(), 'ui_existing_maintenance_hold')
    require(shutil.disk_usage(common.HOST_DATA).free > 1024**3, 'ui_insufficient_data_space')
    release = host.unpack(bundle, value['bundle_sha256'], common.deployment_commit(target))
    previous = host.release_path(source)
    require(policy.release_context(previous) == policy.PREVIOUS_CONTEXT
            and policy.release_context(release) == policy.CONTEXT, 'ui_wrong_application_context')
    for name in CRITICAL:
        require((release / name).read_bytes() == (previous / name).read_bytes(), 'ui_infrastructure_changed')
    migrations = schema(source, release)
    for name in migrations:
        require((release / 'accounting/migrations' / (name + '.py')).read_bytes()
                == (previous / 'accounting/migrations' / (name + '.py')).read_bytes(), 'ui_schema_mismatch')
    for service in ('db', 'web', 'caddy'):
        require(container(source, service)['State']['Running'], 'ui_container_identity_mismatch')
    host.running_image_check(source, host.image_check(source), container(source, 'web'))
    web_identity(source)
    pins = json.loads((release / 'docker/preview-pins.json').read_text())
    require(container(source, 'db')['Config']['Image'] == pins['postgresql']['reference']
            and container(source, 'caddy')['Config']['Image'] == pins['caddy']['reference'], 'ui_container_identity_mismatch')
    events.checkpoint('ui-image-pull')
    with tempfile.TemporaryDirectory(prefix='accounting-s24a-registry-', dir=common.RUN) as directory:
        cli = ['docker', '--config', directory]
        common.run(cli + ['login', target['published']['image'].split('/')[0], '--username', 'oauth2accesstoken', '--password-stdin'],
                   payload=common.access_token().encode())
        common.run(cli + ['pull', target['published']['image']])
    host.image_check(target)
    events.checkpoint('ui-static')
    static = common.HOST_DATA / 'static' / target['published']['commit']
    if not static.exists(): image.export_static(target['published']['image'], static)
    old_static = common.HOST_DATA / 'static' / source['published']['commit']
    merge_hashed_assets(old_static, static)
    # Preserve both generations of hashed links for cached pages/image rollback.
    merge_hashed_assets(static, old_static)
    host.environment_file(target)
    host.compose(target, 'config', '--quiet')
    new_operations = deepcopy(old_operations); new_operations['preview'] = target
    oc.validate(new_operations)
    state = {'source': source, 'target': target, 'source_operations': old_operations, 'target_operations': new_operations,
             'database_container': container(source, 'db')['Id'],
             'database_started': query(source, 'SELECT pg_postmaster_start_time()::text;'),
             'runtime_secrets': runtime_secrets(), 'migrations': migrations, 'static_assets': static_assets(target)}
    checkpoint(state, 'ui-maintenance')
    try:
        maintenance()
        host.compose(source, 'stop', 'caddy', 'web')
        require(not container(source, 'caddy')['State']['Running'] and not container(source, 'web')['State']['Running'],
                'ui_container_identity_mismatch')
        state['snapshot'] = inventory(source)
        checkpoint(state, 'ui-backup-before')
        state['before_backup'] = ops.backup(old_operations)['receipt']
        require(inventory(source) == state['snapshot'], 'ui_retained_rows_changed')
        checkpoint(state, 'ui-rebind')
        bind(target, new_operations)
        checkpoint(state, 'ui-web')
        host.compose(target, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'web')
        wait_web(target)
        checkpoint(state, 'ui-preservation')
        database_unchanged(state, target)
        require(inventory(target) == state['snapshot'], 'ui_retained_rows_changed')
        state['preserved'] = True
        checkpoint(state, 'ui-backup-after')
        state['after_backup'] = ops.backup(new_operations)['receipt']
        require(inventory(target) == state['snapshot'], 'ui_retained_rows_changed')
        checkpoint(state, 'ui-awaiting-restore')
        return state
    except Exception:
        checkpoint(state, 'ui-failed')
        # Same-schema image rollback never restores or replaces the live DB.
        try: rollback(state)
        except Exception: checkpoint(state, 'ui-failed')
        raise


def rollback(state):
    events.checkpoint('ui-rollback')
    source, target = state['source'], state['target']
    policy.same_database(source, target)
    require(host.load() in (source, target), 'ui_source_changed')
    host.mounted(source)
    # The database is deliberately never stopped, cloned, restored or rewound.
    host.compose(target, 'stop', 'caddy', 'web')
    bind(source, state['source_operations'])
    host.compose(source, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'web')
    wait_web(source)
    host.compose(source, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'caddy')
    state['rollback_image_only'] = True
    try:
        state['rollback_backup'] = ops.backup(state['source_operations'])['receipt']
        state['rollback_backup_pending'] = False
    except Exception:
        state['rollback_backup_pending'] = True
    checkpoint(state, 'ui-rollback')
    resume_operations()
    return state


def activate(state, restored):
    if state['phase'] == 'ui-complete': return state
    require(state['phase'] in {'ui-awaiting-restore', 'ui-activate', 'ui-public-check'}, 'ui_wrong_release_state')
    require(restored == state['after_backup']['sha256'], 'ui_restore_binding_mismatch')
    target = state['target']
    require(host.load() == target and ops.load() == state['target_operations'], 'ui_source_changed')
    if state['phase'] == 'ui-public-check': return state
    if state['phase'] == 'ui-awaiting-restore':
        database_unchanged(state, target)
        require(inventory(target) == state['snapshot'], 'ui_retained_rows_changed')
    state['off_vm_restore_attested'] = True
    checkpoint(state, 'ui-activate')
    try:
        host.compose(target, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'caddy')
        require(set(container(target, 'caddy')['HostConfig'].get('PortBindings') or {}) == {'80/tcp', '443/tcp'}, 'ui_private_port_exposed')
        database_unchanged(state, target)
        common.run(['iptables', '-w', '-C', 'DOCKER-USER', '-d', '169.254.169.254/32', '-j', 'REJECT'])
        checkpoint(state, 'ui-public-check')
    finally:
        # Public requests may now exist. Keep this DB; never auto-restore it.
        resume_operations()
    return state


def retry(state):
    require(state['phase'] == 'ui-rollback' and host.load() == state['source']
            and ops.load() == state['source_operations'] and not HOLD.exists(), 'ui_wrong_release_state')
    wait_web(state['source'])
    require(container(state['source'], 'caddy')['State']['Running'], 'ui_container_identity_mismatch')
    history = STATE.parent / 's24a-ui-release-history'
    history.mkdir(mode=0o700, exist_ok=True)
    archive = history / (uuid.uuid4().hex + '.json')
    common.private_json(archive, state, exclusive=True)
    require(json.loads(archive.read_text()) == state, 'ui_source_changed')
    STATE.unlink()  # Only the archived attempt journal; no DB/image/backup is removed.
    return {'status': 'Retry prepared', 'previous_attempt_archived': True, 'database_or_backups_changed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'state', 'status', 'activate', 'finish', 'rollback', 'retry'))
    parser.add_argument('--input', type=Path); parser.add_argument('--bundle', type=Path)
    parser.add_argument('--restored-sha256')
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, 'ui_wrong_target')
        os.environ.pop('DOCKER_HOST', None); os.environ.pop('DOCKER_CONTEXT', None)
        events.checkpoint('ui-status')
        with open('/run/accounting-preview.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'prepare': state = prepare(json.loads(args.input.read_text()), args.bundle)
            elif not STATE.exists():
                require(args.action in {'state', 'status'}, 'ui_wrong_release_state')
                print(json.dumps({'status': 'Not applied'})); return
            else:
                state = json.loads(STATE.read_text())
                if args.action == 'retry':
                    print(json.dumps(retry(state))); return
                if args.action == 'activate': state = activate(state, args.restored_sha256)
                elif args.action == 'rollback': state = rollback(state)
                elif args.action == 'finish':
                    require(state['phase'] == 'ui-public-check' and state.get('preserved') is True
                            and state.get('off_vm_restore_attested') is True and host.load() == state['target'], 'ui_wrong_release_state')
                    wait_web(state['target'])
                    database_unchanged(state, state['target'])
                    require(container(state['target'], 'caddy')['State']['Running'], 'ui_container_identity_mismatch')
                    state['monitor'] = ops.monitor(state['target_operations'])
                    state['completed_at'] = oc.now()
                    checkpoint(state, 'ui-complete')
            print(json.dumps(state if args.action in {'prepare', 'state'} else summary(state), ensure_ascii=False))
    except Exception as error:
        events.failure(error)
        parser.exit(1, 'S24A VM operation stopped; private journal/database/backups retained.\n')


if __name__ == '__main__': main()
