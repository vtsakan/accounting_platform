#!/usr/bin/env python3
"""Root-only, plan-bound S09 → S14 synthetic database-clone deployment."""
import argparse
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from cloud import require
import preview_common as common
import preview_host as host
import operations_common as ops_common
import operations_host as ops
import demo_release_common as policy
import preview_events as events

policy.register_diagnostics()

PLAN=Path('/etc/accounting/demo-release-plan.json')
JOURNAL=Path('/etc/accounting/demo-release-state.json')
HOLD=Path('/etc/accounting/demo-upgrade-in-progress')


def query(config,database,sql):
    return host.compose(config,'exec','-T','--user','postgres','db','psql','-X','-qAt','--set=ON_ERROR_STOP=1',
                        '--dbname='+database,payload=sql.encode()).decode().strip()


def snapshot(config,database):
    return json.loads(query(config,database,policy.snapshot_sql()),parse_float=str)


def operations_config():
    return ops_common.validate(json.loads(ops_common.HOST_CONFIG.read_text()))


def same_source(plan):
    require(host.load()==plan['source'],'The installed deployment changed; create a new plan')
    host.mounted(plan['source'])
    require(policy.digest(snapshot(plan['source'],plan['source']['db_name']))==plan['source_snapshot_sha256'],
            'Legacy rows changed; create and review a new plan')
    require(operations_config()['preview']==plan['source'],'Recovery binding differs from the source')


def stage(input,bundle):
    source=host.load();target=common.validate(input['target'],published=True)
    require(source==input['source'],'Source VM differs from the configured release')
    policy.compare_identity(source,target)
    host.mounted(source);common.dns(source)
    operations=operations_config();ops.check(operations)
    require(not any((common.HOST_DATA/'media').iterdir()),'Private media needs separate document recovery before upgrade')
    require(not JOURNAL.exists() or json.loads(JOURNAL.read_text())['phase']=='rolled_back','A demo release already exists; inspect its status')
    release=host.unpack(bundle,input['bundle_sha256'],common.deployment_commit(target))
    host.refresh(target)
    with tempfile.TemporaryDirectory(prefix='demo-registry-',dir=common.RUN) as private:
        registry=target['published']['image'].split('/',1)[0]
        cli=['docker','--config',private]
        common.run(cli+['login',registry,'--username','oauth2accesstoken','--password-stdin'],payload=common.access_token().encode())
        common.run(cli+['pull',target['published']['image']])
    host.image_check(target)
    sys.path.insert(0,str(release/'tools'))
    import image
    static=common.HOST_DATA/'static'/target['published']['commit']
    if not static.exists():image.export_static(target['published']['image'],static)
    require((static/'staticfiles.json').is_file(),'Image static manifest is missing')
    host.environment_file(target)
    host.compose(target,'config','--quiet')
    current=snapshot(source,source['db_name'])
    plan=policy.make_plan(source,target,current,input['bundle_sha256'],input['operator'],input['office_name'])
    common.private_json(PLAN,plan)
    return {'status':'Planned','plan_sha256':policy.digest(plan),'source_database':source['db_name'],
        'target_database':target['db_name'],'office_id':plan['office_id'],'office_name':plan['office_name'],
        'assignments':plan['assignments'],'source_users':current['users'],'target_image':target['published']['image'],
        'original_database_modified':False,'services_restarted':False,'backup_key_uploaded':False}


def hold_services():
    HOLD.write_text('S14 demo clone upgrade in progress\n');HOLD.chmod(0o600)
    for unit in ('accounting-preview.service','accounting-backup.service','accounting-monitor.service'):
        path=Path('/etc/systemd/system')/(unit+'.d')/'demo-upgrade.conf'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('[Unit]\nConditionPathExists=!'+str(HOLD)+'\n')
    common.run(['systemctl','daemon-reload'])


def resume_timers():
    HOLD.unlink(missing_ok=True)
    common.run(['systemctl','start',*ops_common.UNITS])


def operations_wrapper(commit):
    file=Path('/usr/local/sbin/accounting-operations')
    script=host.RELEASES/commit/'tools/operations_host.py'
    require(script.is_file(),'Operations release is missing')
    file.write_text('#!/bin/sh\nset -eu\nexec /usr/bin/python3 '+str(script)+' "$@"\n');file.chmod(0o755)


def checkpoint(state,phase):
    state['phase']=phase
    common.private_json(JOURNAL,state)
    print('DEMO-DIAG '+json.dumps({'phase':phase}),file=sys.stderr,flush=True)


def rollback(state):
    source=state['plan']['source'];target=state['plan']['target']
    # Never discard a database or silently hide demo identities/new work.
    if state.get('cutover_started'):
        count=query(target,target['db_name'],'SELECT count(*) FROM auth_user;')
        require(count=='0','Demo accounts already exist; preserve them and review rollback separately')
    common.run(['systemctl','stop',*ops_common.UNITS])
    hold_services()
    for config in (target,source):
        try:host.compose(config,'stop','web','caddy')
        except Exception:pass
    require(policy.digest(snapshot(source,source['db_name']))==state['plan']['source_snapshot_sha256'],
            'Original data changed; inspect before automatic rollback')
    common.private_json(common.HOST_CONFIG,source)
    common.private_json(ops_common.HOST_CONFIG,state['source_operations'])
    host.install_units(host.release_path(source));operations_wrapper(state['source_operations']['code_commit'])
    host.compose(source,'up','--detach','--wait','--wait-timeout','180','--pull','never')
    state['rollback_backup']=ops.backup(state['source_operations'])['receipt']
    ops.monitor(state['source_operations'])
    checkpoint(state,'rolled_back');resume_timers()
    return {'status':'Rolled back','original_database_preserved':True,'demo_database_retained':target['db_name']}


def apply(expected):
    plan=policy.validate_plan(json.loads(PLAN.read_text()),expected)
    require(not JOURNAL.exists() or json.loads(JOURNAL.read_text())['phase']=='rolled_back','A prior attempt exists; inspect status/rollback rather than repeat migrations')
    same_source(plan)
    source,target=plan['source'],plan['target']; operations=operations_config()
    require((host.release_path(target)/'.bundle.sha256').read_text().strip()==plan['bundle_sha256'],
            'Release bundle hash differs')
    host.image_check(target)
    host.compose(target,'config','--quiet')
    require(query(source,'postgres','SELECT count(*) FROM pg_database WHERE datname='+host.literal(target['db_name'])+';')=='0',
            'Target database exists; it will not be overwritten')
    require(all(common.run(['systemctl','is-active',unit]).decode().strip()=='active' for unit in ops_common.UNITS),'Expected active backup/monitor timers')
    common.run(['systemctl','stop',*ops_common.UNITS])
    # Wait for an already-running backup; never terminate its snapshot process.
    for attempt in range(30):
        active=common.run(['systemctl','show','accounting-backup.service','--property=ActiveState','--value']).decode().strip()
        if active not in {'active','activating','deactivating'}:break
        time.sleep(1)
    else:
        common.run(['systemctl','start',*ops_common.UNITS]);raise RuntimeError('Backup still running; retry after it completes')
    state={'plan':plan,'source_operations':operations,'phase':'prebackup','cutover_started':False}
    try:
        receipt=ops.backup(operations)['receipt']
        state['before_backup']=receipt
        checkpoint(state,'backed_up')
        hold_services()
        host.compose(source,'stop','web','caddy')
        same_source(plan)
        clone='CREATE DATABASE '+policy.identifier(target['db_name'])+' WITH TEMPLATE '+policy.identifier(source['db_name'])+' OWNER '+policy.identifier(target['db_user'])+';'
        query(source,'postgres',clone)
        checkpoint(state,'cloned')
        require(snapshot(source,target['db_name'])==plan['source_snapshot'],'Clone differs from reviewed source')
        program=(host.release_path(target)/'tools/demo_release_migrate.py').read_text()
        output=host.compose(target,'run','--rm','--no-deps','web','python','-c',program,json.dumps(plan,ensure_ascii=False)).decode()
        migration=json.loads(output[output.index('{'):])
        state['migration']=migration
        after=snapshot(source,target['db_name'])
        require(after['business']==plan['source_snapshot']['business'] and after['users']==0,'Clone changed original record values or created users')
        require(policy.S14_MIGRATION in after['migrations'],'S14 migration not applied')
        require(snapshot(source,source['db_name'])==plan['source_snapshot'],'Original database changed during clone migration')
        checkpoint(state,'migrated')
        rebound=deepcopy(operations);rebound['preview']=target;rebound['code_commit']=common.deployment_commit(target)
        ops_common.validate(rebound)
        state['target_operations']=rebound;state['cutover_started']=True;checkpoint(state,'cutover')
        common.private_json(common.HOST_CONFIG,target);common.private_json(ops_common.HOST_CONFIG,rebound)
        host.install_units(host.release_path(target));operations_wrapper(rebound['code_commit'])
        host.compose(target,'up','--detach','--wait','--wait-timeout','180','--pull','never')
        host.inspect(target)
        state['after_backup']=ops.backup(rebound)['receipt']
        state['monitor']=ops.monitor(rebound)
        checkpoint(state,'awaiting_off_vm_restore');resume_timers()
        return {'status':'Deployed demo clone','image':target['published']['image'],'hostname':target['hostname'],
            'office_id':plan['office_id'],'before_backup':state['before_backup'],'after_backup':state['after_backup'],
            'original_database_preserved':source['db_name'],'demo_database':target['db_name'],
            'human_accounts_created':False,'off_vm_restore':'Pending','public_login':'Pending'}
    except Exception:
        if JOURNAL.exists() and HOLD.exists():
            try:rollback(state)
            except Exception:
                checkpoint(state,'needs_operator_recovery')
                raise RuntimeError('Upgrade stopped; original database and journal retained. Inspect before recovery') from None
        else:common.run(['systemctl','start',*ops_common.UNITS])
        raise


def status():
    if not JOURNAL.exists():return {'status':'Not applied'}
    state=json.loads(JOURNAL.read_text());plan=state['plan']
    return {'status':state['phase'],'target':plan['target'],'source':plan['source'],
        'office_id':plan['office_id'],'after_backup':state.get('after_backup'),'operations':state.get('target_operations'),
        'original_database_unchanged':snapshot(plan['source'],plan['source']['db_name'])==plan['source_snapshot']}


def confirm_restore(receipt_sha):
    state=json.loads(JOURNAL.read_text())
    require(state['phase']=='awaiting_off_vm_restore' and state['after_backup']['sha256']==receipt_sha,
            'Restore attestation differs from the deployed clone backup')
    require(host.load()==state['plan']['target'],'Installed deployment differs from restored backup')
    state['off_vm_restore_operator_confirmed_at']=ops_common.now()
    checkpoint(state,'demo_ready')
    return {'status':'Demo ready for account bootstrap','operator':state['plan']['operator']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('plan','apply','status','rollback','confirm-restore'))
    parser.add_argument('--input',type=Path);parser.add_argument('--bundle',type=Path);parser.add_argument('--plan-sha256')
    parser.add_argument('--receipt-sha256')
    args=parser.parse_args()
    require(os.geteuid()==0,'Run through the reviewed sudo SSH command')
    events.checkpoint('vm-preflight')
    Path('/run/accounting').mkdir(mode=0o700,parents=True,exist_ok=True)
    with Path('/run/accounting/demo-release.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            if args.action=='plan':result=stage(json.loads(args.input.read_text()),args.bundle)
            elif args.action=='apply':result=apply(args.plan_sha256)
            elif args.action=='rollback':result=rollback(json.loads(JOURNAL.read_text()))
            elif args.action=='confirm-restore':result=confirm_restore(args.receipt_sha256)
            else:result=status()
            print(json.dumps(result,ensure_ascii=False,indent=2))
        except Exception as error:
            # Provider errors, SQL text and credential material remain on-host.
            print('DEMO-DIAG '+json.dumps({'error':type(error).__name__}),file=sys.stderr)
            events.failure(error)
            parser.exit(1,'Demo release stopped; existing data and private journal retained.\n')


if __name__=='__main__':main()
