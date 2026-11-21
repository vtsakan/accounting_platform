#!/usr/bin/env python3
"""Explicit existing-preview clone upgrade; startup never migrates or bootstraps."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import image
import operations_common as oc
import operations_host as ops
import preview_common as common
import preview_host as host
import preview_cr004_policy as policy
from r1_gate import digest_object, require
from vm_material_common import release_context
from vm_material_host import merge_hashed_assets, static_assets, runtime_secrets, web_identity
from vm_upgrade_host import inventory, migrations, pause_timers, query, wait_web

PLAN = Path('/etc/accounting/cr004-preview-plan.json')
STATE = Path('/etc/accounting/cr004-preview-state.json')
HOLD = Path('/etc/accounting/cr004-preview-in-progress')
PHASE = 'preflight'


def checkpoint(state, phase):
    global PHASE
    PHASE = phase; state['phase'] = phase
    common.private_json(STATE, state)
    print('CR004VM-DIAG ' + json.dumps({'phase': phase}), file=sys.stderr, flush=True)


def command(config, *, staging=False):
    release = host.release_path(config)
    result = common.compose_command(release)
    if not (release / 'compose.preview-s31.yml').is_file():
        return result
    result.extend(['--profile', 'jobs', '--file', str(release / 'compose.preview-s31.yml')])
    if staging:
        result.extend(['--file', str(release / 'compose.preview-s31-hold.yml')])
    return result


def compose(config, *arguments, staging=False, payload=None, json_output=False):
    return common.run(command(config, staging=staging) + list(arguments), payload=payload,
                      environment=common.compose_environment(), json_output=json_output)


def container(config, service, *, required=True):
    ids = compose(config, 'ps', '--all', '--quiet', service).decode().splitlines()
    if not ids and not required:
        return None
    require(len(ids) == 1, 'Exactly one preview container is required per service: ' + service)
    value = common.run(['docker', 'inspect', ids[0]], json_output=True)[0]
    labels = value['Config'].get('Labels', {})
    require(labels.get('com.docker.compose.project') == 'accounting-preview'
            and labels.get('com.docker.compose.service') == service, 'Unexpected Compose container identity')
    if service != 'caddy':
        require(not value['HostConfig'].get('PortBindings'), 'An internal service exposes a host port')
    return value


def database_identity(config):
    value = container(config, 'db')
    return {'id': value['Id'], 'started_at': value['State']['StartedAt'], 'image': value['Image']}


def queue_storage(config):
    result = {}
    for service, destination, expected in (
            ('redis', '/data', 'accounting-preview_redis_jobs'),
            ('scheduler', '/app/run/beat', 'accounting-preview_scheduler_state')):
        mounts = container(config, service)['Mounts']
        matching = [row for row in mounts if row.get('Destination') == destination]
        require(len(matching) == 1 and matching[0].get('Type') == 'volume'
            and matching[0].get('Name') == expected, 'Unexpected durable queue/scheduler volume')
        result[service] = {'name': matching[0]['Name'], 'destination': destination}
    return result


def journal_static_assets(config):
    result = static_assets(config)
    directory = common.HOST_DATA / 'static' / config['published']['commit']
    name = json.loads((directory / 'staticfiles.json').read_text())['paths']['accounting/workspace/client-journal.css']
    from vm_material_common import static_file
    result.append({'path': '/static/' + name, 'sha256': common.file_sha(static_file(directory, name))})
    require(len(result) == 4, 'Expected the existing three assets plus the new client journal stylesheet')
    return result


def same_database_process(state):
    require(database_identity(state['source']) == state['database_process'],
            'The PostgreSQL container or start time changed; inspect before proceeding')
    require(runtime_secrets() == state['runtime_secrets'], 'Pinned runtime material changed')


def capacity(config):
    values = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        values[key] = int(value.strip().split()[0])
    size = int(query(config, 'postgres', 'SELECT pg_database_size(' + host.literal(config['db_name']) + ');'))
    free = shutil.disk_usage(common.HOST_DATA).free
    policy.same_capacity(values['MemTotal'], values['MemAvailable'], free, size)
    return {'memory_kib': values['MemTotal'], 'available_kib_before': values['MemAvailable'],
            'data_disk_free_before': free, 'source_database_bytes': size,
            'visible_cpus': os.cpu_count(), 'accepted_vm_workload': 'Pending D06'}


def source_check(source):
    policy.target_identity(source)
    require(host.load() == source and ops.load()['preview'] == source, 'Installed source or backup binding changed')
    host.mounted(source)
    require(common.metadata('instance/id') == '7685681393231055686'
            and common.metadata('instance/zone').endswith('/europe-west1-b'), 'Unexpected VM instance or zone')
    require(common.run(['docker', 'info', '--format', '{{.DockerRootDir}}']).decode().strip()
            == '/srv/accounting/docker', 'Unexpected Docker data root')
    require(not any((common.HOST_DATA / 'media').iterdir()),
            'Documents are present: their recovery must be covered before this database-only update')
    require(not any(p.exists() for p in (Path('/etc/accounting/demo-upgrade-in-progress'),
            Path('/etc/accounting/s24-upgrade-in-progress'), Path('/etc/accounting/s24a-ui-release-in-progress'), Path('/etc/accounting/s31-preview-in-progress'), HOLD)),
            'An unfinished release hold exists; use its recovery procedure')
    require(all(common.run(['systemctl', 'is-active', unit]).decode().strip() == 'active' for unit in oc.UNITS),
            'The existing backup and monitoring timers must be active')


def stage(value, bundle):
    require(not STATE.exists(), 'A preview upgrade journal exists; use status/resume/abort instead of overwriting it')
    source, target = value['source'], common.validate(value['target'], published=True)
    policy.transition(source, target); source_check(source); common.dns(source)
    require(source['published']['image'] == policy.OLD_IMAGE, 'Expected the currently deployed S31A preview source')
    for service in ('db', 'web', 'caddy'):
        item = container(source, service)
        require(item['State']['Running'], 'An original service is stopped')
    host.running_image_check(source, host.image_check(source), container(source, 'web'))
    web_identity(source)
    # Reuse the current durable queue; never delete/flush its volumes or
    # overlap the running source worker/scheduler with the new clone.
    for service in ('redis', 'worker', 'scheduler'):
        item = container(source, service)
        require(item['State']['Running'] and item['State'].get('Health', {}).get('Status') == 'healthy',
                'Current jobs service is not healthy: ' + service)
    original_queue = queue_storage(source)
    require(query(source, 'postgres', 'SELECT count(*) FROM pg_database WHERE datname='
                  + host.literal(target['db_name']) + ';') == '0', 'The new clone database already exists; refusing overwrite')
    available = capacity(source)
    release = host.unpack(bundle, value['bundle_sha256'], common.deployment_commit(target))
    previous = host.release_path(source)
    require(release_context(previous) == policy.OLD_CONTEXT and release_context(release) == policy.CONTEXT,
            'Source or target application bytes differ from the observed immutable contexts')
    policy.verified_report(json.loads((release / policy.RECEIPT).read_text()))
    expected = sorted(p.stem for p in (release / 'accounting/migrations').glob('[0-9]*.py'))
    require(len(expected) == 28 and migrations(source) == expected[:26], 'Expected the exact CURRENT26 to28 migration path')
    for name in expected[:26]:
        require((release / 'accounting/migrations' / (name + '.py')).read_bytes()
                == (previous / 'accounting/migrations' / (name + '.py')).read_bytes(), 'A retained migration changed')
    for name in ('docker/preview-pins.json', 'infrastructure/Caddyfile', *policy.QUEUE_CODE):
        require((release / name).read_bytes() == (previous / name).read_bytes(), 'Database/proxy pins or HTTPS policy changed')
    pins = json.loads((release / 'docker/preview-pins.json').read_text())
    require(container(source, 'db')['Config']['Image'] == pins['postgresql']['reference']
            and container(source, 'caddy')['Config']['Image'] == pins['caddy']['reference'], 'Running infrastructure image differs')
    with tempfile.TemporaryDirectory(prefix='s31-preview-registry-', dir=common.RUN) as directory:
        cli = ['docker', '--config', directory]
        common.run(cli + ['login', target['published']['image'].split('/')[0], '--username',
                         'oauth2accesstoken', '--password-stdin'], payload=common.access_token().encode())
        common.run(cli + ['pull', target['published']['image']])
    host.image_check(target)
    common.run(['docker', 'pull', '--platform=linux/amd64', policy.REDIS])
    static = common.HOST_DATA / 'static' / policy.APP_REVISION
    if not static.exists():
        image.export_static(target['published']['image'], static)
    merge_hashed_assets(common.HOST_DATA / 'static' / source['published']['commit'], static)
    host.environment_file(target)
    compose(target, 'config', '--quiet')
    resolved = compose(target, 'config', '--format', 'json', json_output=True)
    require(set(resolved['services']) == {'db', 'web', 'caddy', 'redis', 'worker', 'scheduler'}, 'Expected the six bounded preview services')
    require(resolved['services']['web']['environment']['GUNICORN_WORKERS'] == '4'
            and resolved['services']['redis']['image'] == policy.REDIS, 'Resolved workers or broker differ')
    value.update(created_at=oc.now(), capacity=available, source_operations=ops.load(),
                 database_process=database_identity(source), runtime_secrets=runtime_secrets(),
                 static_assets=journal_static_assets(target), queue_storage=original_queue,
                 source_boot_wrapper=Path('/usr/local/sbin/accounting-preview').read_text())
    common.private_json(PLAN, value)
    return {'status': 'Planned', 'plan_sha256': digest_object(value), 'source_migrations': 26, 'target_migrations': 28,
            'capacity': available, 'source_database_changed': False, 'services_restarted': False}


def hold():
    HOLD.write_text('Existing synthetic preview clone cutover in progress\n'); HOLD.chmod(0o600)
    for unit in ('accounting-preview.service', 'accounting-backup.service', 'accounting-monitor.service'):
        file = Path('/etc/systemd/system') / (unit + '.d') / 'cr004-preview.conf'
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('[Unit]\nConditionPathExists=!' + str(HOLD) + '\n')
    common.run(['systemctl', 'daemon-reload'])


def resume_operations():
    HOLD.unlink(missing_ok=True)
    common.run(['systemctl', 'start', *oc.UNITS])


def bind(config, operations, *, new_boot):
    common.private_json(common.HOST_CONFIG, config)
    common.private_json(oc.HOST_CONFIG, operations)
    common.private_json(common.HOST_DATA / 'preview-state.json',
                        {'commit': 'git:' + config['published']['commit'], 'initialised': True})
    host.install_units(host.release_path(config))
    if new_boot:
        wrapper = Path('/usr/local/sbin/accounting-preview')
        wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/local/lib/accounting/preview_cr004_host.py "$@"\n')
        wrapper.chmod(0o755)


def clone_program(state, action, expected=None):
    source, target = state['source'], state['target']
    program = (host.release_path(target) / 'tools/preview_cr004_migrate.py').read_text()
    args = command(target, staging=True) + ['run', '--rm', '--no-deps', '-T', '--entrypoint', 'python', 'web',
            '-c', program, source['db_name'], target['db_name'], action]
    result = subprocess.run(args, env=common.compose_environment(), capture_output=True,
                            input=json.dumps(expected).encode() if expected is not None else None)
    if result.returncode:
        raise RuntimeError('Restricted clone migration/preservation check failed; original retained (raw SQL and payloads omitted)')
    values = [r.removeprefix('CR004VM-RESULT:') for r in result.stdout.decode().splitlines() if r.startswith('CR004VM-RESULT:')]
    require(len(values) == 1, 'Missing clone migration or read-only preservation receipt')
    return json.loads(values[0])


def stop_writers(source):
    compose(source, 'stop', '--timeout', '90', 'scheduler')
    compose(source, 'stop', '--timeout', '90', 'worker')
    compose(source, 'stop', '--timeout', '90', 'caddy', 'web')
    require(all(not container(source, name)['State']['Running'] for name in ('web','caddy','worker','scheduler')),
        'All HTTP/job writers must stop before freezing the CURRENT database')
    require(query(source, source['db_name'], "SELECT count(*) FROM accounting_backgroundjob WHERE state='running';") == '0',
        'A job is still leased/running; retain the source and retry graceful shutdown')


def prepare(expected):
    require(not STATE.exists(), 'An attempt already exists; migrations are never repeated over its clone')
    state = json.loads(PLAN.read_text())
    require(digest_object(state) == expected, 'The planned source or target binding changed')
    policy.transition(state['source'], state['target']); source_check(state['source'])
    source, target = state['source'], state['target']
    same_database_process(state)
    require((host.release_path(target) / '.bundle.sha256').read_text().strip() == state['bundle_sha256'], 'Staged source differs')
    host.image_check(target)
    state['public_cutover_started'] = False
    checkpoint(state, 'preparing')
    try:
        hold(); pause_timers()
        checkpoint(state, 'stopping_old_requests')
        stop_writers(source)
        require(not container(source, 'web')['State']['Running'] and not container(source, 'caddy')['State']['Running'],
                'Original HTTP writers did not stop')
        state['frozen_snapshot'] = inventory(source)
        checkpoint(state, 'source_frozen')
        state['before_backup'] = ops.backup(state['source_operations'])['receipt']
        checkpoint(state, 'source_backed_up')
        require(inventory(source) == state['frozen_snapshot'], 'Frozen original changed during its backup')
        require(query(source, 'postgres', 'SELECT count(*) FROM pg_database WHERE datname='
                      + host.literal(target['db_name']) + ';') == '0', 'Clone already exists; refusing overwrite')
        require(query(source, 'postgres', 'SELECT count(*) FROM pg_stat_activity WHERE datname='
                      + host.literal(source['db_name']) + ';') == '0', 'Source still has active sessions; no forced termination performed')
        query(source, 'postgres', 'CREATE DATABASE "' + target['db_name'] + '" WITH TEMPLATE "'
              + source['db_name'] + '" OWNER "' + target['db_user'] + '";')
        checkpoint(state, 'clone_created')
        require(inventory(target) == state['frozen_snapshot'], 'New clone does not equal the frozen original')
        state['migration'] = clone_program(state, 'migrate')
        checkpoint(state, 'clone_migrated')
        same_database_process(state)
        require(inventory(source) == state['frozen_snapshot'], 'Original changed during clone migration')
        state['target_operations'] = policy.rebound_operations(state['source_operations'], target)
        oc.validate(state['target_operations'])
        checkpoint(state, 'binding_clone')
        bind(target, state['target_operations'], new_boot=True)
        # No worker/scheduler or public proxy is started before both restore proofs.
        compose(target, 'up', '--detach', '--no-deps', '--force-recreate', '--pull', 'never', 'web', staging=True)
        wait_web(target); web_identity(target)
        require(container(target, 'web')['HostConfig']['RestartPolicy']['Name'] == 'no', 'Candidate must remain stopped across a reboot')
        state['candidate_snapshot'] = inventory(target)
        clone_program(state, 'check', state['migration']['retained_snapshot'])
        state['after_backup'] = ops.backup(state['target_operations'])['receipt']
        require(inventory(target) == state['candidate_snapshot'], 'Candidate rows changed before public activation')
        same_database_process(state)
        checkpoint(state, 'awaiting_off_vm_restore')
        return state
    except Exception:
        checkpoint(state, 'prepare_failed')
        try:
            abort()
        except Exception:
            checkpoint(state, 'needs_operator_recovery')
        raise


def abort():
    state = json.loads(STATE.read_text()); policy.before_public(state)
    source, target = state['source'], state['target']
    hold(); pause_timers()
    compose(target, 'stop', 'scheduler', 'worker', 'redis', 'caddy', 'web')
    if 'frozen_snapshot' in state:
        require(inventory(source) == state['frozen_snapshot'], 'Original changed after freeze; automatic rollback refused')
    same_database_process(state)
    bind(source, state['source_operations'], new_boot=False)
    wrapper = Path('/usr/local/sbin/accounting-preview')
    wrapper.write_text(state['source_boot_wrapper']); wrapper.chmod(0o755)
    compose(source, 'up', '--detach', '--no-deps', '--pull', 'never', 'redis', 'web')
    wait_web(source)
    compose(source, 'up', '--detach', '--no-deps', '--pull', 'never', 'worker', 'scheduler', 'caddy')
    checkpoint(state, 'rolled_back_to_original'); resume_operations()
    return summary(state)


def runtime_check(state):
    target = state['target']; same_database_process(state)
    require(queue_storage(target) == state['queue_storage'], 'Durable Redis/scheduler storage changed')
    audited = host.image_check(target)
    limits = {'web': 1024, 'redis': 192, 'worker': 512, 'scheduler': 192, 'caddy': 256}
    for service in ('web', 'redis', 'worker', 'scheduler', 'caddy'):
        item = container(target, service)
        require(item['State']['Running'], 'A required preview service is stopped: ' + service)
        if service in ('web','redis','worker','scheduler'):
            require(item['State'].get('Health',{}).get('Status') == 'healthy', 'A runtime health check failed: '+service)
        require(item['HostConfig']['Memory'] == limits[service] * 1024**2,
                'A running preview memory cap differs: ' + service)
        if service in ('web', 'worker', 'scheduler'):
            host.running_image_check(target, audited, item)
            environment = dict(v.split('=', 1) for v in item['Config']['Env'] if '=' in v)
            require(environment.get('BACKGROUND_JOBS_ENABLED') == 'true'
                    and environment.get('FEE_AUTOMATION_ENABLED') == 'true', 'Runtime feature settings differ')
        if service == 'web':
            require(item['HostConfig']['NanoCpus'] == 2_000_000_000
                    and item['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped', 'Web CPU/restart policy differs')
        if service == 'redis':
            require(item['Config']['Image'] == policy.REDIS, 'Redis image differs')
        if service == 'worker':
            require('--concurrency=1' in item['Config']['Cmd'], 'Expected one worker process')
        if service == 'caddy':
            require(set(item['HostConfig'].get('PortBindings') or {}) == {'80/tcp', '443/tcp'}, 'Unexpected proxy ports')
    from s31_runtime_policy import PROC
    require(container(target, 'db')['HostConfig']['Memory'] == 768 * 1024**2, 'The retained database memory cap differs')
    workers = json.loads(compose(target, 'exec', '-T', 'web', 'python', '-c', PROC))
    require(workers == {'configured_workers': 4, 'live_worker_children': 4}, 'Four actual Gunicorn workers required')
    settings = host.settings_check(target)
    require(settings['debug'] is False and settings['uid'] == 10001 and settings['secure_cookies']
            and settings['hosts'] == [target['hostname']] and settings['origins'] == ['https://' + target['hostname']]
            and settings['proxy'] == ['HTTP_X_FORWARDED_PROTO', 'https'] and settings['media'] == '/app/media', 'Production security settings differ')
    web_identity(target)
    require(query(target, target['db_name'], "SELECT count(*) FROM pg_stat_activity WHERE application_name='accounting-s26-scheduler';") == '1',
            'Exactly one scheduler database session is required')
    health = json.loads(compose(target, 'exec', '-T', 'web', 'python', 'manage.py', 'background_jobs', 'health', '--strict'))
    require(health['status'] == 'ok', 'Background execution is not healthy')
    common.run(['iptables', '-w', '-C', 'DOCKER-USER', '-d', '169.254.169.254/32', '-j', 'REJECT'])
    return {'web_workers': 4, 'worker_concurrency': 1, 'scheduler_containers': 1,
            'observed_memory_caps_mib': {**limits, 'db': 768}, 'web_cpu_cap': 2,
            'broker': health['broker'], 'worker_healthy': health['worker'], 'scheduler_healthy': health['scheduler'],
            'internal_ports_private': True, 'same_database_container_and_start_time': True,
            'pinned_signing_and_database_material_retained': True, 'durable_queue_storage_retained': True, 'production_settings': settings,
            'vm_capacity_acceptance': 'Pending D06; preview health only, no 50-session VM load claim'}


def activate(restored):
    state = json.loads(STATE.read_text()); target = state['target']
    require(host.load() == target and ops.load() == state['target_operations'], 'Current clone or backup binding differs')
    if not state['public_cutover_started']:
        policy.ready_for_activation(state, restored)
        same_database_process(state)
        require(inventory(state['source']) == state['frozen_snapshot'] and inventory(target) == state['candidate_snapshot'],
                'Frozen source or candidate changed during off-VM recovery')
        clone_program(state, 'check', state['migration']['retained_snapshot'])
        state['off_vm_restored'] = restored
        # From this point jobs/new HTTP writes may occur. Never rewind to the old DB.
        state['public_cutover_started'] = True
        checkpoint(state, 'public_cutover_started')
    else:
        require(state.get('off_vm_restored') == restored, 'Resume requires the original exact pair of recovery proofs')
    try:
        compose(target, 'up', '--detach', '--no-deps', '--pull', 'never', 'web', 'redis')
        wait_web(target)
        for _ in range(60):
            if container(target, 'redis')['State'].get('Health', {}).get('Status') == 'healthy':
                break
            time.sleep(1)
        else:
            raise RuntimeError('Redis did not become healthy')
        compose(target, 'up', '--detach', '--no-deps', '--pull', 'never', 'worker', 'scheduler')
        for _ in range(90):
            if all(container(target, s)['State'].get('Health', {}).get('Status') == 'healthy' for s in ('worker', 'scheduler')):
                break
            time.sleep(2)
        else:
            raise RuntimeError('Worker or singleton scheduler did not become healthy')
        health = json.loads(compose(target, 'exec', '-T', 'web', 'python', 'manage.py', 'background_jobs', 'health', '--strict'))
        # Existing queued/retry jobs and their durable messages are retained.
        # Source and target job code/volumes are checked before the freeze.
        compose(target, 'up', '--detach', '--no-deps', '--pull', 'never', 'caddy')
        state['runtime'] = runtime_check(state)
        # Public TLS/CSRF/static checks run on the laptop before completion is recorded.
        checkpoint(state, 'needs_public_check'); resume_operations()
    except Exception:
        checkpoint(state, 'needs_public_check'); resume_operations()
        raise
    return state


def complete(checks):
    state = json.loads(STATE.read_text())
    require(state['public_cutover_started'] and state.get('off_vm_restored'), 'No activated restored target')
    required = ('public_https_readiness', 'greek_login', 'same_origin_form_post', 'null_foreign_origin_denied',
                'missing_csrf_denied', 'certificate_chain_and_hostname_verified', 'material_login')
    require(all(checks.get(k) is True for k in required) and checks.get('immutable_image_static_assets_verified') == 4,
            'Public HTTPS/Greek/CSRF/static checks are incomplete')
    state['runtime'] = runtime_check(state)
    state['public_checks'] = checks; state['completed_at'] = oc.now()
    state['monitor'] = ops.monitor(state['target_operations'])
    checkpoint(state, 'deployed_and_restored'); resume_operations()
    return state


def summary(state):
    return {'status': state['phase'], 'hostname': state['target']['hostname'],
            'deployment_commit': 'git:' + common.deployment_commit(state['target']),
            'application_commit': 'git:' + policy.APP_REVISION, 'image': state['target']['published']['image'],
            'active_database': host.load()['db_name'], 'retained_original_database': state['source']['db_name'],
            'public_cutover_started': state['public_cutover_started'], 'hold_active': HOLD.exists(),
            'completed_at': state.get('completed_at'), 'real_client_release': 'Blocked; R1/D05/D06/D07/G2 Pending',
            'existing_browser_login_and_mfa': 'Pending operator login; passwords and devices retained'}


def boot():
    require(not HOLD.exists(), 'Release hold is active; startup cannot migrate or promote a clone')
    state = json.loads(STATE.read_text())
    require(state['public_cutover_started'] and host.load() == state['target'], 'No authorised preview activation binding')
    host.mounted(state['target'])
    require((common.HOST_DATA / 'postgres17/PG_VERSION').read_text().strip() == '17', 'Existing PG17 data missing')
    database = container(state['target'], 'db')
    if not database['State']['Running']:
        common.run(['docker', 'start', database['Id']])
    compose(state['target'], 'up', '--detach', '--no-deps', '--wait', '--wait-timeout', '240', '--pull', 'never',
            'redis', 'web', 'worker', 'scheduler', 'caddy')
    return {'status': 'Resumed existing preview; no migrations or account creation'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('plan', 'prepare', 'state', 'status', 'abort', 'activate', 'complete', 'resume', 'secrets'))
    parser.add_argument('--input', type=Path); parser.add_argument('--bundle', type=Path)
    parser.add_argument('--plan-sha256'); parser.add_argument('--proof', type=Path)
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, 'Run the host helper with sudo')
        os.environ.pop('DOCKER_HOST', None); os.environ.pop('DOCKER_CONTEXT', None)
        with open('/run/accounting-preview.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if args.action == 'plan':
                result = stage(json.loads(args.input.read_text()), args.bundle)
            elif args.action == 'prepare':
                result = prepare(args.plan_sha256)
            elif args.action == 'state':
                result = json.loads(STATE.read_text())
            elif args.action == 'status':
                result = summary(json.loads(STATE.read_text())) if STATE.exists() else {'status': 'Not applied'}
            elif args.action == 'abort':
                result = abort()
            elif args.action == 'activate':
                result = activate(json.loads(args.proof.read_text()))
            elif args.action == 'complete':
                result = complete(json.loads(args.proof.read_text()))
            elif args.action == 'secrets':
                host.refresh(host.load()); result = {'status': 'Loaded the existing pinned runtime material'}
            else:
                result = boot()
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        reason = str(error) if isinstance(error, RuntimeError) else 'Operation stopped; private provider output omitted'
        print(json.dumps({'status': 'Stopped', 'phase': PHASE, 'reason': reason, 'error': type(error).__name__}))
        if args.action in ('resume', 'secrets'):
            sys.exit(1)


if __name__ == '__main__':
    main()
