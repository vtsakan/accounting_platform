#!/usr/bin/env python3
"""Operator existing-CR008 profile update; keep the old completed configuration."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from dev import ROOT,require_local_docker
import image
import preview as publisher
import preview_common as common
import preview_cr008_release as previous
import preview_cr008_memory_policy as policy
import preview_cr008_profile_release as previous_profile
from r1_gate import digest_bytes,require

CONFIG=ROOT/'private/vm-cr008-4gb-memory.json'
RESULT=ROOT/'private/vm-cr008-4gb-memory-result.json'
STAGE='accounting-cr008-4gb-memory-stage'
PUBLIC='docs/implementation/evidence/CR008-4GB-MEMORY-verification.json'
SOURCE=ROOT/'docs/implementation/evidence/CR008-4GB-MEMORY-source.json'


def source_gate():
    previous_profile.source_gate()  # Retain all27 preceding bound files verbatim.
    from verify_cr008 import source_check
    _,count=source_check();require(count==824,'Retain every824 original CR008 source binding')
    policy.verify(ROOT);policy.prior.unchanged_acceptances(ROOT)
    revision,_,context=image.committed_context()
    require(context['digest']==policy.prior.CONTEXT and context['file_count']==371,'The verified371-input image context changed')
    manifest=json.loads(SOURCE.read_text())
    require(manifest.get('step')=='CR008-4GB-MEMORY' and manifest.get('status')=='Prepared'
        and manifest.get('profile')==policy.PROFILE and manifest.get('same_current_database') is True
        and manifest.get('new_migrations')==0 and manifest.get('application_context_digest')==policy.prior.CONTEXT,
        'The existing-database profile source binding differs')
    for name,expected in manifest['sha256'].items():
        path=ROOT/name
        require(path.is_file() and not path.is_symlink() and digest_bytes(path.read_bytes())==expected,'Prepared profile source changed: '+name)
    require(not previous.git('ls-files','--','private/') and not previous.git('status','--porcelain'),
        'Retain a clean source and keep all private configuration outside Git')
    return revision


def github():
    revision=source_gate()
    require(previous.git('remote','get-url','origin') in (policy.prior.REPOSITORY,'git@github.com:vtsakan/accounting_platform.git'),
        'Unexpected GitHub origin')
    previous.git('fetch','origin','main',capture=False);old=previous.git('rev-parse','FETCH_HEAD')
    require(re.fullmatch(r'[0-9a-f]{40}',old) is not None and subprocess.run(
        ['git','merge-base','--is-ancestor',old,revision],cwd=ROOT,env=image.git_environment(),capture_output=True).returncode==0,
        'GitHub main has independent work; preserve it before updating')
    scan=previous.secret_scan();common.private_json(ROOT/'private/vm-cr008-memory-github-scan.json',scan)
    require(scan['unreviewed_findings']==0,'The native source/history scan has unreviewed findings')
    previous.git('push','-u','origin','HEAD:refs/heads/'+policy.BRANCH,capture=False)
    previous.git('push','origin','HEAD:refs/heads/main',capture=False)
    require(previous.git('ls-remote','--heads','origin','main').split()[0]==revision,'GitHub moved concurrently; inspect before deployment')
    return {'status':'GitHub updated','commit':'git:'+revision,'previous_main':'git:'+old,'force_push':False}


def load():
    value=json.loads(CONFIG.read_text());require(value.get('profile')==policy.PROFILE,'Unexpected separate profile configuration')
    require(previous.CONFIG.is_file() and not previous.CONFIG.is_symlink()
        and digest_bytes(previous.CONFIG.read_bytes())==value.get('legacy_local_config_sha256'),
        'The old completed local configuration changed; it was not overwritten')
    policy.transition(value['source'],value['target'])
    require(previous_profile.CONFIG.is_file() and not previous_profile.CONFIG.is_symlink()
        and digest_bytes(previous_profile.CONFIG.read_bytes())==value.get('failed_local_config_sha256'),
        'The preceding failed local configuration changed; it was not replaced')
    common.validate(value['source'],published=True);common.validate(value['target'],published=True)
    return value


def configure(identity):
    revision=source_gate();require_local_docker()
    if CONFIG.exists():return load()
    source=common.validate(previous.ssh(policy.prior.BOOTSTRAP,'sudo -n cat /etc/accounting/preview.json'),published=True)
    failed_raw=previous.ssh(source,'sudo -n cat '+str(policy.FAILED_STATE),json_output=False)
    policy.failed_attempt(json.loads(failed_raw),source)
    failed_local=previous_profile.load()
    require(failed_local['source']==source
        and failed_local['target']['deployment_commit']==policy.FAILED_DEPLOYMENT,
        'Retain the actual preceding failed local profile configuration')
    target=deepcopy(source);target['deployment_commit']=revision;policy.transition(source,target)
    operations=previous.ssh(source,'sudo -n cat /etc/accounting/operations.json')
    require(operations['preview']==source,'The active backup configuration differs')
    previous.recovery_config(operations,identity)
    require(previous.CONFIG.is_file() and not previous.CONFIG.is_symlink(),'Retain the old completed local configuration')
    value={'profile':policy.PROFILE,'source':source,'target':target,'previous_vm_record':'git:'+policy.VM_RECORD,
        'legacy_local_config_sha256':digest_bytes(previous.CONFIG.read_bytes()),
        'failed_local_config_sha256':digest_bytes(previous_profile.CONFIG.read_bytes()),
        'failed_attempt_sha256':digest_bytes(failed_raw)}
    common.private_json(CONFIG,value,exclusive=True);return value


def host_action(config,action,*arguments):
    command=shlex.join(['sudo','-n','python3',STAGE+'/tools/preview_cr008_memory_host.py',action,*map(str,arguments)])
    gcp=config['source']['gcp']
    result=subprocess.run(['gcloud','compute','ssh',gcp['ssh_user']+'@'+gcp['vm_name'],
        '--project='+gcp['project_id'],'--zone='+gcp['zone'],'--tunnel-through-iap',
        '--quiet','--command='+command],capture_output=True,
        env={**os.environ,'CLOUDSDK_CORE_LOG_HTTP':'false'})
    try:value=json.loads(result.stdout)
    except (ValueError,UnicodeDecodeError):
        raise RuntimeError('VM transport failed; private provider output omitted. Use this memory profile status before retrying') from None
    if result.returncode or value.get('status')=='Stopped':
        if value.get('status')=='Stopped':
            # The hash-bound host emits a value-free reviewed failure object.
            print('CR008-MEMORY-FAILURE '+json.dumps(value,ensure_ascii=False),flush=True)
        raise RuntimeError('The memory profile stopped; its public failure and retained journal identify the recovery path')
    return value


def transfer(config):
    source_gate();revision=common.deployment_commit(config['target'])
    require(subprocess.run(['git','merge-base','--is-ancestor',revision,'HEAD'],cwd=ROOT,
        env=image.git_environment(),capture_output=True).returncode==0,'Retain the exact configured profile revision')
    with tempfile.TemporaryDirectory(prefix='accounting-cr008-profile-transfer-') as temporary:
        directory=Path(temporary)/STAGE;(directory/'tools').mkdir(parents=True);(directory/'docs/implementation').mkdir(parents=True)
        bundle=directory/'source.tar';bundle.write_bytes(common.run(['git','archive','--format=tar',revision],environment=image.git_environment()))
        names=previous.git('ls-tree','-r','--name-only',revision,'--','tools').splitlines()
        for name in names:
            if name.endswith('.py'):
                path=directory/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(common.run(['git','show',revision+':'+name],environment=image.git_environment()))
        name='docs/implementation/cloud_inventory.json'
        (directory/name).write_bytes(common.run(['git','show',revision+':'+name],environment=image.git_environment()))
        common.private_json(directory/'input.json',{**config,'bundle_sha256':common.file_sha(bundle)})
        previous.ssh(config['source'],'umask 077; mkdir -p '+STAGE,json_output=False)
        gcp=config['source']['gcp']
        publisher.gcloud(config['source'],'compute','scp','--recurse',directory,gcp['ssh_user']+'@'+gcp['vm_name']+':~/',
            '--zone='+gcp['zone'],'--tunnel-through-iap')


def proof_file(config,name,value):
    require(name in ('restored.json','public.json'),'Fixed private profile proof path required')
    code='import pathlib,sys;p=pathlib.Path(sys.argv[1]);p.write_bytes(sys.stdin.buffer.read());p.chmod(0o600)'
    command=shlex.join(['python3','-c',code,STAGE+'/'+name]);gcp=config['source']['gcp']
    common.run(['gcloud','compute','ssh',gcp['ssh_user']+'@'+gcp['vm_name'],'--project='+gcp['project_id'],
        '--zone='+gcp['zone'],'--tunnel-through-iap','--quiet','--command='+command],payload=json.dumps(value).encode(),
        environment={**os.environ,'CLOUDSDK_CORE_LOG_HTTP':'false'})
    return STAGE+'/'+name


def deploy(config,identity):
    source_gate();require_local_docker();transfer(config)
    current=host_action(config,'status')
    if current['status']=='Not applied':
        plan=host_action(config,'plan','--input',STAGE+'/input.json','--bundle',STAGE+'/source.tar')
        operations=previous.ssh(config['source'],'sudo -n cat /etc/accounting/operations.json')
        previous.recovery_config(operations,identity)
        print('[CR008-4GB-MEMORY] Αλλαγή προφίλ στην ίδια τρέχουσα βάση36, χωρίς migration ή clone.',flush=True)
        state=host_action(config,'prepare','--plan-sha256',plan['plan_sha256'])
    else:state=host_action(config,'state')
    require(state.get('source')==config['source'] and state.get('target')==config['target'],
        'The retained profile attempt belongs to another configuration; preserve its recovery path')
    require(state['phase'] in ('awaiting_off_vm_restore','public_cutover_started','needs_public_check','profile_verified'),
        'The retained profile attempt requires review: '+state['phase'])
    if state['phase']!='profile_verified':
        try:
            if state['public_cutover_started']:restored=state['off_vm_restored']
            else:
                from operations_recovery import restore
                restored={}
                for label,operations in (('before',state['source_operations']),('after',state['target_operations'])):
                    print('[CR008-4GB-MEMORY] Πραγματική επαναφορά61 πινάκων εκτόςVM: '+label+'.',flush=True)
                    restored[label]=restore(previous.recovery_config(operations,identity),state[label+'_backup'],identity)
                policy.ready(state,restored)
            path=proof_file(config,'restored.json',restored);state=host_action(config,'activate','--proof',path)
            from demo_release import public_checks
            from vm_material_release import public_assets
            checks=public_checks(config['target']['hostname']);checks.update(public_assets(state))
            path=proof_file(config,'public.json',checks);state=host_action(config,'complete','--proof',path)
        except Exception:
            latest=host_action(config,'state')
            if latest['phase']!='configuration_rolled_back_current_database_retained':host_action(config,'rollback')
            raise
    common.private_json(RESULT,state);return record(state)


def record(state):
    require(state['phase']=='profile_verified' and state['public_cutover_started'],'No completed native profile proof')
    require(load()['target']==state['target'],'The completed profile differs from this separate local configuration')
    policy.transition(state['source'],state['target']);runtime=state['runtime']
    require(set(runtime.get('python_memory_cgroups',{}))=={'web','worker','scheduler','scanner'}
        and all(all(value.get(key)==0 for key in ('oom','oom_kill','oom_group_kill'))
            for value in runtime['python_memory_cgroups'].values()),
        'Actual new cgroup OOM counters must be zero before recording success')
    require(runtime['attachment_uploads_enabled'] is True and runtime['web_workers']==2 and runtime['scanner_containers']==1
        and runtime['vm_resized'] is False and all(runtime['scanner_proof'][k] is True for k in
            ('real_clean_stream_accepted','real_eicar_denied','scanner_unavailable_denied_without_writes')),
        'Actual profile scanner/memory proof is incomplete')
    for label in ('before','after'):
        recovery=state['off_vm_restored'][label]
        require(recovery['receipt']==state[label+'_backup'] and recovery['tables_checked']==61
            and all(recovery[k] is True for k in ('all_public_tables_match','plaintext_removed','separate_recovery_key_used')),
            'Actual61-table profile recovery proof differs')
    report={'step':'CR008-4GB-MEMORY','status':'Verified','verified_at':state['completed_at'],
        'scope':'existing-current-schema36-database-profile-only','previous_completed_vm_record':'git:'+policy.VM_RECORD,
        'application_commit':'git:'+policy.prior.APP_REVISION,'deployment_commit':'git:'+common.deployment_commit(state['target']),
        'image':policy.VM_IMAGE,'application_context_digest':policy.prior.CONTEXT,
        'same_current_database':True,'database_cloned':False,'database_migrated':False,'schema_before':36,'schema_after':36,
        'previous_completed_journal_unchanged':True,'old_local_deployment_config_unchanged':True,
        'previous_failed_deployment':'git:'+policy.FAILED_DEPLOYMENT,
        'previous_failed_journal_unchanged':True,'previous_failed_journal_sha256':state['failed_attempt_sha256'],
        'database_container_restarted':False,'accounts_mfa_or_keys_reset':False,'durable_queue_retained':True,
        'original_current_rows_preserved_during_maintenance':True,'runtime':runtime,
        'off_vm_source_restore_tables':61,'off_vm_target_restore_tables':61,'both_off_vm_restores_matched':True,
        'separate_recovered_key_used':True,'plaintext_removed':True,'public_checks':state['public_checks'],
        'production_suite_previously_passed':1186,'financial_cases_previously_passed':36,'production_suite_rerun':False,
        'attachment_uploads_enabled':True,'vm_resized':False,'retained_vm_memory_choice':'4GiB',
        'agent_native_execution':False,'full_requirement_acceptances_pending':85,
        'actual_browser_login_mfa':'Pending operator login','real_client_release':'Blocked; R1/D05/D06/D07/G2 Pending',
        'full_document_recovery_acceptance':'Pending S38; sealed bytes included in encrypted DB backups'}
    path=ROOT/PUBLIC
    if path.exists():require(json.loads(path.read_text())==report,'An existing real profile result differs; it was not replaced')
    else:
        with path.open('x') as stream:stream.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    policy.track(ROOT,'Verified');print(json.dumps(report,ensure_ascii=False,indent=2));return report


def push_result():
    changed=set(filter(None,previous.git('diff','--name-only','HEAD').splitlines()))
    extra=set(filter(None,previous.git('ls-files','--others','--exclude-standard').splitlines()))
    allowed={PUBLIC,'docs/implementation/state.md'}
    require(changed|extra<=allowed,'Unrelated changes were preserved; only this exact profile result/tracking may be committed')
    if changed or extra:
        previous.git('add','--',*sorted(allowed),capture=False)
        previous.git('commit','-m','docs: record verified current-database CR008 4GiB upload profile','--',*sorted(allowed),capture=False)
    return github()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('source','all','github','deploy','resume','status','rollback','record','scanner-refresh'))
    parser.add_argument('--identity',type=Path,default=Path.home()/'.config/totalaccounting/recovered-backup-age.key');args=parser.parse_args()
    os.chdir(ROOT)
    try:
        if args.action=='source':result={'status':'Prepared','profile':policy.PROFILE,'deployment_commit':'git:'+source_gate(),'runtime_executed':False}
        elif args.action=='github':result=github()
        elif args.action=='status':
            result=host_action(load(),'status') if CONFIG.exists() else previous.ssh(policy.prior.BOOTSTRAP,'sudo -n /usr/local/sbin/accounting-preview status')
        elif args.action in ('rollback','scanner-refresh'):result=host_action(load(),args.action)
        elif args.action=='record':record(host_action(load(),'state'));result=push_result()
        else:
            if args.action=='all':print(json.dumps(github(),ensure_ascii=False));config=configure(args.identity)
            else:config=load()
            deploy(config,args.identity);result=push_result()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        reason=str(error) if isinstance(error,RuntimeError) else 'Profile operation stopped; private input/provider output omitted'
        parser.exit(1,'CR008-4GB-MEMORY stopped: '+reason+'\n')
    finally:
        if previous.TOOLS_TEMP is not None:previous.TOOLS_TEMP.cleanup()


if __name__=='__main__':main()
