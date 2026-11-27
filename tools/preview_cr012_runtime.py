#!/usr/bin/env python3
"""CR012 bounded4GiB runtime; explicit host clone migration is separate."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import image
import operations_common as oc
import operations_host as ops
import preview_common as common
import preview_host as host
import preview_cr008_policy as policy
import preview_cr008_scanner as scanner
from r1_gate import require
from vm_material_host import static_assets, runtime_secrets, web_identity
from vm_upgrade_host import query

HOLD=Path('/etc/accounting/cr012-preview-in-progress')


def clean_oom_counters(value):
    require(all(type(value.get(key)) is int and value[key]==0 for key in ('oom','oom_kill'))
        and value.get('oom_group_kill',0)==0,
        'A new profile memory cgroup recorded an OOM event; acceptance is blocked')


def cgroup_oom_proof(target):
    result={};root=Path('/sys/fs/cgroup').resolve()
    for service in ('web','worker','scheduler','scanner'):
        item=container(target,service);pid=item['State'].get('Pid')
        require(type(pid) is int and pid>0 and item.get('RestartCount')==0,
            'A new service restarted or has no live cgroup identity: '+service)
        memberships=(Path('/proc')/str(pid)/'cgroup').read_text().splitlines()
        paths=[row.split(':',2)[2] for row in memberships if row.startswith('0::')]
        require(len(paths)==1,'An exact cgroupv2 service path is required')
        require(item['Id'] in paths[0],'The cgroup path is not bound to the inspected container')
        directory=(root/paths[0].lstrip('/')).resolve()
        require(directory.is_relative_to(root),'Unexpected cgroup path')
        counters={key:int(value) for key,value in (row.split() for row in (directory/'memory.events').read_text().splitlines())}
        try:clean_oom_counters(counters)
        except RuntimeError:
            raise RuntimeError('A new service cgroup recorded an OOM event: '+service) from None
        result[service]={key:counters.get(key,0) for key in ('oom','oom_kill','oom_group_kill')}
    return result

def command(config, *, staging=False):
    release = host.release_path(config)
    result = common.compose_command(release)
    if not (release / 'compose.preview-s31.yml').is_file():
        return result
    result.extend(['--profile', 'jobs', '--file', str(release / 'compose.preview-s31.yml')])
    if (release/'compose.preview-cr008.yml').is_file():
        result.extend(['--file',str(release/'compose.preview-cr008.yml')])
    if staging:
        result.extend(['--file',str(release/('compose.preview-cr008-hold.yml' if (release/'compose.preview-cr008-hold.yml').is_file() else 'compose.preview-s31-hold.yml'))])
    if (release/'compose.preview-cr008-memory.yml').is_file():
        result.extend(['--file',str(release/'compose.preview-cr008-memory.yml')])
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
    result=static_assets(config);directory=common.HOST_DATA/'static'/config['published']['commit']
    manifest=json.loads((directory/'staticfiles.json').read_text())['paths']
    from vm_material_common import static_file
    for asset in ('cash-entry.js','client-journal.css','client-tasks.css','client-tasks.js',
            'entity-profile.css','entity-profile.js','client-attachments.css','gsis.js','gsis.css'):
        name=manifest['accounting/workspace/'+asset]
        result.append({'path':'/static/'+name,'sha256':common.file_sha(static_file(directory,name))})
    require(len(result)==12,'Expected all twelve immutable workspace assets including GSIS')
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
            and common.metadata('instance/zone').endswith('/europe-west1-b')
            and common.metadata('instance/machine-type').endswith('/e2-medium'),
            'Expected the same retained4GiB e2-medium VM and zone')
    require(common.run(['docker', 'info', '--format', '{{.DockerRootDir}}']).decode().strip()
            == '/srv/accounting/docker', 'Unexpected Docker data root')
    require(not any((common.HOST_DATA / 'media').iterdir()),
            'Documents are present: their recovery must be covered before this database-only update')
    require(not any(p.exists() for p in (Path('/etc/accounting/demo-upgrade-in-progress'),
            Path('/etc/accounting/s24-upgrade-in-progress'), Path('/etc/accounting/s24a-ui-release-in-progress'), Path('/etc/accounting/s31-preview-in-progress'), Path('/etc/accounting/cr004-preview-in-progress'), Path('/etc/accounting/cr005-preview-in-progress'), Path('/etc/accounting/cr008-preview-in-progress'), Path('/etc/accounting/cr008-4gb-profile-in-progress'), Path('/etc/accounting/cr008-4gb-memory-in-progress'), Path('/etc/accounting/cr009-preview-in-progress'), Path('/etc/accounting/cr011-preview-in-progress'), HOLD)),
            'An unfinished release hold exists; use its recovery procedure')
    require(all(common.run(['systemctl', 'is-active', unit]).decode().strip() == 'active' for unit in oc.UNITS),
            'The existing backup and monitoring timers must be active')

def bind(config, operations, *, new_boot):
    require(new_boot is False,'The memory retry retains its explicit existing boot wrapper')
    common.private_json(common.HOST_CONFIG, config)
    common.private_json(oc.HOST_CONFIG, operations)
    common.private_json(common.HOST_DATA / 'preview-state.json',
                        {'commit': 'git:' + config['published']['commit'], 'initialised': True})
    host.install_units(host.release_path(config))
    if new_boot:
        wrapper = Path('/usr/local/sbin/accounting-preview')
        wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/local/lib/accounting/preview_cr008_host.py "$@"\n')
        wrapper.chmod(0o755)
        scanner.install_timer()

def stop_writers(source):
    compose(source, 'stop', '--timeout', '90', 'scheduler')
    compose(source, 'stop', '--timeout', '90', 'worker')
    compose(source, 'stop', '--timeout', '90', 'caddy', 'web')
    require(all(not container(source, name)['State']['Running'] for name in ('web','caddy','worker','scheduler')),
        'All HTTP/job writers must stop before freezing the CURRENT database')
    require(query(source, source['db_name'], "SELECT count(*) FROM accounting_backgroundjob WHERE state='running';") == '0',
        'A job is still leased/running; retain the source and retry graceful shutdown')

def runtime_check(state):
    target = state['target']; same_database_process(state)
    require(queue_storage(target) == state['queue_storage'], 'Durable Redis/scheduler storage changed')
    audited = host.image_check(target)
    limits = {'web': 512, 'redis': 192, 'worker': 256, 'scheduler': 192, 'caddy': 128, 'scanner': scanner.MEMORY_MIB}
    for service in limits:
        item = container(target, service)
        require(item['State']['Running'], 'A required preview service is stopped: ' + service)
        if service in ('web','redis','worker','scheduler','scanner'):
            require(item['State'].get('Health',{}).get('Status') == 'healthy', 'A runtime health check failed: '+service)
        require(item['HostConfig']['Memory'] == limits[service] * 1024**2,
                'A running preview memory cap differs: ' + service)
        combined={'web':512,'worker':256,'scheduler':384,'caddy':128,'scanner':scanner.MEMORY_SWAP_MIB}
        if service in combined:
            require(item['HostConfig']['MemorySwap']==combined[service]*1024**2,
                'A running bounded memory/swap cap differs: '+service)
        if service in ('web', 'worker', 'scheduler'):
            host.running_image_check(target, audited, item)
            environment = dict(v.split('=', 1) for v in item['Config']['Env'] if '=' in v)
            require(environment.get('BACKGROUND_JOBS_ENABLED') == 'true'
                    and environment.get('FEE_AUTOMATION_ENABLED') == 'true', 'Runtime feature settings differ')
            require(environment.get('ATTACHMENT_SCANNER_HOST')=='scanner','New uploads require the private scanner on this4GiB test VM')
        if service == 'web':
            require(item['HostConfig']['NanoCpus'] == 1_000_000_000
                    and item['HostConfig']['RestartPolicy']['Name'] == 'unless-stopped', 'Web CPU/restart policy differs')
        if service=='scanner':
            require(item['Config']['Image']==scanner.IMAGE and item['HostConfig']['MemorySwap']==scanner.MEMORY_SWAP_MIB*1024**2
                and set(item['NetworkSettings']['Networks'])=={'accounting-preview_scanning'}
                and not item['State'].get('OOMKilled') and item.get('RestartCount',0)==0,
                'Private scanner identity, swap cap or stability differs')
        if service == 'redis':
            require(item['Config']['Image'] == policy.REDIS, 'Redis image differs')
        if service == 'worker':
            require('--concurrency=1' in item['Config']['Cmd'], 'Expected one worker process')
        if service == 'caddy':
            require(set(item['HostConfig'].get('PortBindings') or {}) == {'80/tcp', '443/tcp'}, 'Unexpected proxy ports')
    from s31_runtime_policy import PROC
    require(container(target, 'db')['HostConfig']['Memory'] == 768 * 1024**2, 'The retained database memory cap differs')
    workers = json.loads(compose(target, 'exec', '-T', 'web', 'python', '-c', PROC))
    require(workers == {'configured_workers': 2, 'live_worker_children': 2}, 'Two actual test-profile Gunicorn workers required')
    settings = host.settings_check(target)
    require(settings['debug'] is False and settings['uid'] == 10001 and settings['secure_cookies']
            and settings['hosts'] == [target['hostname']] and settings['origins'] == ['https://' + target['hostname']]
            and settings['proxy'] == ['HTTP_X_FORWARDED_PROTO', 'https'] and settings['media'] == '/app/media', 'Production security settings differ')
    web_identity(target)
    uploads=scanner.proof(target,compose)
    require(query(target, target['db_name'], "SELECT count(*) FROM pg_stat_activity WHERE application_name='accounting-s26-scheduler';") == '1',
            'Exactly one scheduler database session is required')
    health = json.loads(compose(target, 'exec', '-T', 'web', 'python', 'manage.py', 'background_jobs', 'health', '--strict'))
    require(health['status'] == 'ok', 'Background execution is not healthy')
    common.run(['iptables', '-w', '-C', 'DOCKER-USER', '-d', '169.254.169.254/32', '-j', 'REJECT'])
    require(common.run(['systemctl','is-active',scanner.TIMER]).decode().strip()=='active',
        'The serial signature update timer is not active')
    oom=cgroup_oom_proof(target)
    return {'python_memory_cgroups':oom,'web_workers': 2, 'worker_concurrency': 1, 'scheduler_containers': 1,
            'observed_memory_caps_mib': {**limits, 'db': 768}, 'web_cpu_cap': 1,
            'broker': health['broker'], 'worker_healthy': health['worker'], 'scheduler_healthy': health['scheduler'],
            'internal_ports_private': True, 'same_database_container_and_start_time': True,
            'pinned_signing_and_database_material_retained': True, 'durable_queue_storage_retained': True, 'production_settings': settings,
            'attachment_uploads_enabled':True,'scanner_containers':1,'scanner_memory_cap_mib':scanner.MEMORY_MIB,
            'scanner_memory_plus_swap_cap_mib':scanner.MEMORY_SWAP_MIB,'scanner_proof':uploads,
            'scanner_unavailable_denied_without_writes':uploads['scanner_unavailable_denied_without_writes'],
            'vm_resized':False,'retained_memory_kib':state['capacity']['memory_kib'],
            'vm_capacity_acceptance': 'Pending D06; preview health only, no 50-session VM load claim'}
