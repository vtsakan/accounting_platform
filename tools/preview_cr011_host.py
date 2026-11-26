#!/usr/bin/env python3
"""Explicit CURRENT36 clone→40 rollout; no old database rollback after public writes."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import tempfile

import image
import operations_common as oc
import operations_host as ops
import preview_common as common
import preview_host as host
import preview_cr011_runtime as runtime
import preview_cr008_scanner as scanner
import preview_cr011_policy as policy
from r1_gate import digest_bytes, digest_object, require
from vm_material_common import release_context
from vm_material_host import merge_hashed_assets, runtime_secrets, web_identity
from vm_upgrade_host import inventory, migrations, pause_timers, wait_web, query

PLAN=Path('/etc/accounting/cr011-preview-plan.json')
STATE=Path('/etc/accounting/cr011-preview-state.json')
HOLD=Path('/etc/accounting/cr011-preview-in-progress')
LEGACY_STATE=Path('/etc/accounting/cr009-preview-state.json')
LAST_COMMAND_FAILURE=None


def prior_journals_unchanged(state):
    expected=state.get('prior_journal_sha256',{})
    require(set(expected)=={str(path) for path in policy.PRIOR_STATES},
        'Retain all four concrete preceding deployment journals')
    require(not any(path.exists() for path in policy.PRIOR_HOLDS),
        'A previous deployment still has an active hold')
    for path in policy.PRIOR_STATES:
        require(path.is_file() and not path.is_symlink()
            and digest_bytes(path.read_bytes())==expected[str(path)],
            'A retained previous journal changed; no overwrite or new attempt is allowed')
    policy.completed_journal(json.loads(LEGACY_STATE.read_text()),state['source'])


def public_failure(error):
    message=str(error)
    allowed={
        'The retained worker/scheduler did not become healthy',
        'A new profile memory cgroup recorded an OOM event; acceptance is blocked',
        'Insufficient remaining real test-VM headroom',
        'The inspected failed journal changed; no new attempt is allowed',
        'The retained database process changed between profile attempts',
        'The scheduler memory retry must resolve to192/384MiB',
        'The cgroup path is not bound to the inspected container',
        'An exact cgroupv2 service path is required',
        'A profile journal exists; retain it and use status/resume/abort',
        'Retain the inspected failed attempt without an active hold',
        'Current rows changed before activation',
        'Public HTTPS/CSRF/static proof is incomplete',
        'The serial signature update timer is not active',
        'Two actual test-profile Gunicorn workers required',
        'Exactly one scheduler database session is required',
        'Background execution is not healthy',
        'Retain all four concrete preceding deployment journals',
        'A previous deployment still has an active hold',
        'A retained previous journal changed; no overwrite or new attempt is allowed',
        'Require the exact previous CR009 and verified CR011 application contexts',
    }
    record={'error':type(error).__name__,
        'reason':message if type(error) is RuntimeError and message in allowed else 'CR011 operation failed; private provider output omitted'}
    prefix='A new service cgroup recorded an OOM event: '
    if type(error) is RuntimeError and message in {prefix+service for service in ('web','worker','scheduler','scanner')}:
        record['reason']=message
    if isinstance(error,common.CommandFailure):
        record.update(reason='A reviewed host command failed',program=error.program,exit_code=error.exit_code)
    if LAST_COMMAND_FAILURE is not None:record['command_failure']=LAST_COMMAND_FAILURE
    try:
        if STATE.is_file():
            phase=json.loads(STATE.read_text()).get('phase')
            if phase in {'preparing','source_frozen','source_backed_up','clone_created','clone_migrated',
                    'awaiting_off_vm_restore','prepare_failed','needs_operator_recovery','rolled_back_to_original',
                    'public_cutover_started','needs_public_check','deployed_and_restored'}:record['phase']=phase
    except (OSError,ValueError):pass
    return record


def observed_run(*args,**kwargs):
    # Capture only failing provider stderr privately; preserve execution/results.
    global LAST_COMMAND_FAILURE
    command=args[0] if args else kwargs.get('args')
    result=None
    try:
        result=ORIGINAL_RUN(*args,**kwargs)
        return result
    except subprocess.CalledProcessError as error:
        result=error
        raise
    finally:
        if result is not None and result.returncode and isinstance(command,(list,tuple)) and command:
            program=Path(str(command[0])).name
            if program in {'docker','systemctl','iptables','findmnt'}:
                words=[str(value) for value in command[1:]]
                verbs={'compose','up','stop','exec','run','ps','inspect','pull','info','config','image','volume','is-active','enable','start','disable','daemon-reload'}
                operation=[value for value in words if value in verbs][:3]
                record={'program':program,'operation':operation,'exit_code':result.returncode}
                frames=[{'file':Path(frame.filename).name,'function':frame.name,'line':frame.lineno}
                    for frame in traceback.extract_stack() if Path(frame.filename).name in
                    {'preview_cr011_host.py','preview_cr011_runtime.py','preview_common.py','preview_cr008_scanner.py'}]
                record['caller']=frames[-4:]
                try:
                    raw=result.stderr or b''
                    if isinstance(raw,bytes):raw=raw.decode('utf-8',errors='replace')
                    fd,path=tempfile.mkstemp(prefix='cr011-command-',suffix='.json',dir='/etc/accounting')
                    with os.fdopen(fd,'w') as stream:
                        json.dump({**record,'stderr_private':raw[-16384:]},stream);stream.write('\n')
                    record['private_log']=path
                except OSError:record['private_log']='unavailable'
                LAST_COMMAND_FAILURE=record


def checkpoint(state, phase):
    state['phase']=phase;common.private_json(STATE,state)
    print('CR011VM-DIAG '+json.dumps({'phase':phase}),file=sys.stderr,flush=True)


def legacy_unchanged(state):
    prior_journals_unchanged(state)
    require(LEGACY_STATE.is_file() and digest_bytes(LEGACY_STATE.read_bytes())==state['legacy_journal_sha256'],
        'The previous completed journal changed; it was not overwritten')
    runtime.same_database_process(state)


def scheduler_memory_limits(service):
    # compose-go UnitBytes.MarshalJSON returns decimal strings; Docker inspect
    # uses integers. Accept both exact representations without coercing floats,
    # booleans, units, fractions, missing values or unbounded memory limits.
    require(type(service) is dict,'The scheduler memory retry must resolve to192/384MiB')
    result={}
    for name,expected in (('mem_limit',192*1024**2),('memswap_limit',384*1024**2)):
        value=service.get(name)
        if type(value) is str and re.fullmatch(r'[0-9]{1,12}',value):
            value=int(value)
        require(type(value) is int and value==expected,
            'The scheduler memory retry must resolve to192/384MiB')
        result[name]=value
    return result


def stage(value,bundle):
    require(not STATE.exists() and not HOLD.exists(),'A profile journal exists; retain it and use status/resume/abort')
    prior_journals_unchanged(value)
    require(value.get('profile')==policy.PROFILE,'A concrete existing-database profile is required')
    source,target=value['source'],value['target'];policy.transition(source,target)
    runtime.source_check(source)
    require(LEGACY_STATE.is_file() and not LEGACY_STATE.is_symlink(),'Retain the actual previous completed journal')
    legacy=LEGACY_STATE.read_bytes();policy.completed_journal(json.loads(legacy),source)
    require(not runtime.HOLD.exists(),'The prior deployment has an active hold; retain its recovery path')
    for service in ('db','web','caddy','redis','worker','scheduler','scanner'):
        item=runtime.container(source,service)
        require(item['State']['Running'],'An existing service is stopped: '+service)
        if service in ('web','redis','worker','scheduler','scanner'):
            require(item['State'].get('Health',{}).get('Status')=='healthy','An existing service is unhealthy: '+service)
    for service in ('web','worker','scheduler'):
        env=dict(s.split('=',1) for s in runtime.container(source,service)['Config']['Env'] if '=' in s)
        require(env.get('ATTACHMENT_SCANNER_HOST')=='scanner','Retain the active private scanner setting')
    host.running_image_check(source,host.image_check(source),runtime.container(source,'web'))
    queue=runtime.queue_storage(source);capacity=runtime.capacity(source)
    release=host.unpack(bundle,value['bundle_sha256'],common.deployment_commit(target))
    previous=host.release_path(source)
    require(release_context(previous)==policy.OLD_CONTEXT and release_context(release)==policy.CONTEXT,
        'Require the exact previous CR009 and verified CR011 application contexts')
    policy.operator_report(json.loads((release/policy.RECEIPT).read_text()))
    expected=sorted(p.stem for p in (release/'accounting/migrations').glob('[0-9]*.py'))
    require(len(expected)==40 and migrations(source)==expected[:36],'The current database must have the exact36 and target the full40 migrations')
    for name in expected[:36]:
        relative='accounting/migrations/'+name+'.py'
        require((release/relative).read_bytes()==(previous/relative).read_bytes(),'A retained migration changed')
    for name in ('docker/preview-pins.json','infrastructure/Caddyfile',*policy.foundation.QUEUE_CODE,
            'compose.preview-cr008.yml','compose.preview-cr008-memory.yml',
            'docker/preview-cr008-clamd.conf','docker/preview-cr008-freshclam.conf',
            'infrastructure/Caddyfile.cr008-test'):
        require((release/name).read_bytes()==(previous/name).read_bytes(),'An existing queue/database/proxy foundation changed')
    with tempfile.TemporaryDirectory(prefix='cr011-registry-',dir=common.RUN) as private:
        cli=['docker','--config',private]
        common.run(cli+['login',target['published']['image'].split('/')[0],'--username',
            'oauth2accesstoken','--password-stdin'],payload=common.access_token().encode())
        common.run(cli+['pull',target['published']['image']])
    host.image_check(target)
    static=common.HOST_DATA/'static'/policy.APP_REVISION
    if not static.exists():image.export_static(target['published']['image'],static)
    old_static=common.HOST_DATA/'static'/source['published']['commit']
    merge_hashed_assets(old_static,static)
    merge_hashed_assets(static,old_static)
    host.environment_file(target)
    runtime.compose(target,'config','--quiet')
    resolved=runtime.compose(target,'config','--format','json',json_output=True)
    require(set(resolved['services'])=={'db','web','caddy','redis','worker','scheduler','scanner'},'Expected exactly seven bounded services')
    require(resolved['services']['scanner']['image']==scanner.IMAGE
        and resolved['services']['web']['environment']['GUNICORN_WORKERS']=='2','Pinned scanner/two-worker profile differs')
    scheduler_memory_limits(resolved['services']['scheduler'])
    resources=scanner.prepare(target)
    runtime.compose(target,'run','--rm','--no-deps','-T','--entrypoint','caddy','caddy','validate',
        '--config','/etc/caddy/Caddyfile','--adapter','caddyfile')
    require(query(source,'postgres','SELECT count(*) FROM pg_database WHERE datname='+host.literal(target['db_name'])+';')=='0','The new clone already exists; it was not overwritten')
    value.update(created_at=oc.now(),source_operations=ops.load(),capacity=capacity,scanner_resources=resources,
        database_process=runtime.database_identity(source),runtime_secrets=runtime_secrets(),queue_storage=queue,
        static_assets=runtime.journal_static_assets(target),legacy_journal_sha256=digest_bytes(legacy),
        source_boot_wrapper=Path('/usr/local/sbin/accounting-preview').read_text(),public_cutover_started=False)
    common.private_json(PLAN,value)
    return {'status':'Planned','plan_sha256':digest_object(value),'schema_before':36,'schema_after':40,
        'same_current_database':False,'source_database_migrated':False,'services_restarted':False}


def hold():
    HOLD.write_text('CURRENT36 clone to40 CR011 upgrade in progress\n');HOLD.chmod(0o600)
    for unit in ('accounting-preview.service','accounting-backup.service','accounting-monitor.service'):
        path=Path('/etc/systemd/system')/(unit+'.d')/'cr011-preview.conf'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('[Unit]\nConditionPathExists=!'+str(HOLD)+'\n')
    common.run(['systemctl','daemon-reload'])


def resume_operations(*,active):
    HOLD.unlink(missing_ok=True)
    common.run(['systemctl','start',*oc.UNITS])
    scanner.start_timer()


def bind_target(state):
    runtime.bind(state['target'],state['target_operations'],new_boot=False)
    wrapper=Path('/usr/local/sbin/accounting-preview')
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/local/lib/accounting/preview_cr011_host.py "$@"\n')
    wrapper.chmod(0o755)
    scanner.install_timer()
    drop=Path('/etc/systemd/system')/(scanner.SERVICE+'.d')/'cr011-hold.conf'
    drop.parent.mkdir(parents=True,exist_ok=True)
    drop.write_text('[Unit]\nConditionPathExists=!'+str(HOLD)+'\n')
    common.run(['systemctl','daemon-reload'])



def clone_program(state,action,expected=None):
    source,target=state['source'],state['target']
    program=(host.release_path(target)/'tools/preview_cr011_migrate.py').read_text()
    command=runtime.command(target,staging=True)+['run','--rm','--no-deps','-T','--entrypoint','python','web','-c',program,source['db_name'],target['db_name'],action]
    result=subprocess.run(command,env=common.compose_environment(),capture_output=True,input=json.dumps(expected).encode() if expected is not None else None)
    require(result.returncode==0,'Restricted clone migration/preservation failed; private diagnostic retained')
    values=[row.removeprefix('CR011VM-RESULT:') for row in result.stdout.decode().splitlines() if row.startswith('CR011VM-RESULT:')]
    require(len(values)==1,'A genuine restricted clone receipt is required')
    return json.loads(values[0])

def prepare(expected):
    require(not STATE.exists(),'A clone attempt exists; retain its journal instead of repeating migrations')
    state=json.loads(PLAN.read_text());require(digest_object(state)==expected,'The reviewed clone plan changed')
    source,target=state['source'],state['target']
    policy.transition(source,target);runtime.source_check(source);legacy_unchanged(state)
    require((host.release_path(target)/'.bundle.sha256').read_text().strip()==state['bundle_sha256'],'Staged source changed')
    checkpoint(state,'preparing')
    try:
        hold();pause_timers();scanner.stop_timer();runtime.stop_writers(source)
        state['frozen_snapshot']=inventory(source);require(len(state['frozen_snapshot'])==61,'Compare all61 current public tables')
        checkpoint(state,'source_frozen')
        state['before_backup']=ops.backup(state['source_operations'])['receipt']
        require(inventory(source)==state['frozen_snapshot'],'Frozen source changed during backup')
        checkpoint(state,'source_backed_up')
        require(query(source,'postgres','SELECT count(*) FROM pg_database WHERE datname='+host.literal(target['db_name'])+';')=='0','The new clone already exists; it was not overwritten')
        require(query(source,'postgres','SELECT count(*) FROM pg_stat_activity WHERE datname='+host.literal(source['db_name'])+';')=='0','Source still has active sessions; no forced termination was performed')
        query(source,'postgres','CREATE DATABASE "'+target['db_name']+'" WITH TEMPLATE "'+source['db_name']+'" OWNER "'+target['db_user']+'";')
        checkpoint(state,'clone_created')
        require(inventory(target)==state['frozen_snapshot'],'Clone differs from frozen source')
        state['migration']=clone_program(state,'migrate');checkpoint(state,'clone_migrated')
        require(inventory(source)==state['frozen_snapshot'],'Original source changed during clone migration')
        state['target_operations']=policy.rebound_operations(state['source_operations'],target)
        oc.validate(state['target_operations']);bind_target(state)
        scanner.update(target,runtime.compose,staging=True);scanner.wait(target,runtime.container)
        runtime.compose(target,'up','--detach','--no-deps','--force-recreate','--pull','never','web',staging=True)
        wait_web(target);web_identity(target)
        require(runtime.container(target,'web')['HostConfig']['RestartPolicy']['Name']=='no','Candidate must remain stopped across reboot')
        state['scanner_pre_activation']=scanner.proof(target,runtime.compose)
        state['candidate_snapshot']=inventory(target);require(len(state['candidate_snapshot'])==64,'Compare all64 candidate public tables')
        clone_program(state,'check',state['migration']['retained_snapshot'])
        legacy_unchanged(state)
        state['after_backup']=ops.backup(state['target_operations'])['receipt']
        require(inventory(target)==state['candidate_snapshot'],'Candidate changed before both restore proofs')
        checkpoint(state,'awaiting_off_vm_restore');return state
    except Exception as error:
        state['last_failure']=public_failure(error);checkpoint(state,'prepare_failed')
        try:abort()
        except Exception:checkpoint(state,'needs_operator_recovery')
        raise


def abort():
    state=json.loads(STATE.read_text());policy.before_public(state);legacy_unchanged(state)
    require(host.load() in (state['source'],state['target']),'Installed configuration belongs to another attempt')
    source,target=state['source'],state['target'];hold();pause_timers();scanner.stop_timer()
    runtime.compose(target,'stop','--timeout','90','scheduler','worker','caddy','web','scanner')
    if 'frozen_snapshot' in state:require(inventory(source)==state['frozen_snapshot'],'Original changed; abort cannot select it automatically')
    runtime.bind(source,state['source_operations'],new_boot=False)
    wrapper=Path('/usr/local/sbin/accounting-preview');wrapper.write_text(state['source_boot_wrapper']);wrapper.chmod(0o755)
    runtime.compose(source,'up','--detach','--no-deps','--pull','never','redis','scanner','web');wait_web(source)
    scanner.wait(source,runtime.container)
    runtime.compose(source,'up','--detach','--no-deps','--pull','never','worker','scheduler','caddy')
    checkpoint(state,'rolled_back_to_original');resume_operations(active=True);return summary(state)


def activate(restored):
    state=json.loads(STATE.read_text());target=state['target']
    require(host.load()==target and ops.load()==state['target_operations'],'Candidate or backup binding differs')
    legacy_unchanged(state)
    if not state['public_cutover_started']:
        policy.ready(state,restored)
        require(inventory(state['source'])==state['frozen_snapshot'] and inventory(target)==state['candidate_snapshot'],'Frozen source or candidate changed during recovery')
        clone_program(state,'check',state['migration']['retained_snapshot'])
        state['off_vm_restored']=restored
        # Persist BEFORE starting any jobs/HTTP writes. From now on the target
        # is authoritative; no automatic old database or image rollback exists.
        state['public_cutover_started']=True;checkpoint(state,'public_cutover_started')
    else:require(state.get('off_vm_restored')==restored,'Resume requires the original exact recovery proof pair')
    try:
        runtime.compose(target,'up','--detach','--no-deps','--pull','never','web','redis','scanner')
        wait_web(target);scanner.wait(target,runtime.container);scanner.start_timer()
        runtime.compose(target,'up','--detach','--no-deps','--pull','never','worker','scheduler')
        for _ in range(90):
            if all(runtime.container(target,s)['State'].get('Health',{}).get('Status')=='healthy' for s in ('worker','scheduler')):break
            time.sleep(2)
        else:raise RuntimeError('The retained worker/scheduler did not become healthy')
        runtime.compose(target,'up','--detach','--no-deps','--pull','never','caddy')
        state['runtime']=runtime.runtime_check(state);checkpoint(state,'needs_public_check');resume_operations(active=True);return state
    except Exception as error:
        state['last_failure']=public_failure(error);checkpoint(state,'needs_public_check')
        # Keep the authoritative40 database even when public/health proof fails.
        resume_operations(active=True);raise


def complete(checks):
    state=json.loads(STATE.read_text());require(state['public_cutover_started'] and state.get('off_vm_restored'),'No restored active profile')
    names=('public_https_readiness','greek_login','same_origin_form_post','null_foreign_origin_denied',
        'missing_csrf_denied','certificate_chain_and_hostname_verified','material_login')
    require(all(checks.get(k) is True for k in names) and checks.get('immutable_image_static_assets_verified')==12,
        'Public HTTPS/CSRF/static proof is incomplete')
    legacy_unchanged(state);state['runtime']=runtime.runtime_check(state)
    state.update(public_checks=checks,completed_at=oc.now());state['monitor']=ops.monitor(state['target_operations'])
    checkpoint(state,'deployed_and_restored');resume_operations(active=True);return state


def summary(state):
    return {'status':state['phase'],'profile':policy.PROFILE,'active_database':host.load()['db_name'],
        'retained_original_database':state['source']['db_name'],'schema_before':36,'schema_after':40,
        'public_cutover_started':state['public_cutover_started'],'hold_active':HOLD.exists(),
        'completed_at':state.get('completed_at'),'old_deployment_journals_retained':True,
        'last_failure':state.get('last_failure')}


def boot():
    require(not HOLD.exists(),'Profile hold is active; startup cannot promote or migrate anything')
    state=json.loads(STATE.read_text());require(state['public_cutover_started'] and host.load()==state['target'],'No active profile binding')
    prior_journals_unchanged({key:value for key,value in state.items() if key!='database_process'})
    host.mounted(state['target']);scanner.ensure_swap();scanner.volume()
    require((common.HOST_DATA/'postgres17/PG_VERSION').read_text().strip()=='17','Retained PG17 data is missing')
    require(digest_bytes(LEGACY_STATE.read_bytes())==state['legacy_journal_sha256'],'Previous completed journal changed')
    db=runtime.container(state['target'],'db')
    if not db['State']['Running']:common.run(['docker','start',db['Id']])
    runtime.compose(state['target'],'up','--detach','--no-deps','--wait','--wait-timeout','900','--pull','never',
        'redis','web','worker','scheduler','scanner','caddy')
    scanner.start_timer();return {'status':'Resumed the bound schema40 database; no migrations or account reset'}


def refresh_scanner():
    state=json.loads(STATE.read_text());require(not HOLD.exists() and state['public_cutover_started']
        and host.load()==state['target'],'Only refresh the active existing-database profile')
    scanner.update(state['target'],runtime.compose);scanner.wait(state['target'],runtime.container)
    proof=scanner.proof(state['target'],runtime.compose)
    common.private_json(Path('/etc/accounting/cr011-scanner-refresh.json'),{'at':oc.now(),**proof});return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','prepare','state','status','activate','complete','abort','resume','secrets','scanner-refresh'))
    parser.add_argument('--input',type=Path);parser.add_argument('--bundle',type=Path)
    parser.add_argument('--plan-sha256');parser.add_argument('--proof',type=Path);args=parser.parse_args()
    try:
        require(os.geteuid()==0,'Use the existing root-operated VM helper')
        os.environ.pop('DOCKER_HOST',None);os.environ.pop('DOCKER_CONTEXT',None)
        with open('/run/accounting-preview.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.action=='plan':result=stage(json.loads(args.input.read_text()),args.bundle)
            elif args.action=='prepare':result=prepare(args.plan_sha256)
            elif args.action=='state':result=json.loads(STATE.read_text())
            elif args.action=='status':result=summary(json.loads(STATE.read_text())) if STATE.exists() else {'status':'Not applied'}
            elif args.action=='activate':result=activate(json.loads(args.proof.read_text()))
            elif args.action=='complete':result=complete(json.loads(args.proof.read_text()))
            elif args.action=='abort':result=abort()
            elif args.action=='secrets':host.refresh(host.load());result={'status':'Existing pinned runtime material loaded'}
            elif args.action=='scanner-refresh':result=refresh_scanner()
            else:result=boot()
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status':'Stopped',**public_failure(error)}));sys.exit(1)


ORIGINAL_RUN=subprocess.run
if __name__=='__main__':
    subprocess.run=observed_run
    try:main()
    finally:subprocess.run=ORIGINAL_RUN
