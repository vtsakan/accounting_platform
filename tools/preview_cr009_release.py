#!/usr/bin/env python3
"""Operator CR009 image upgrade on the existing current4GiB database."""
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
import preview_cr009_policy as policy
import preview_cr008_memory_release as previous_profile
from r1_gate import digest_bytes,require

CONFIG=ROOT/'private/vm-cr009-preview.json'
RESULT=ROOT/'private/vm-cr009-preview-result.json'
STAGE='accounting-cr009-preview-stage'
PUBLIC='docs/implementation/evidence/CR009-VM-verification.json'
SOURCE=ROOT/'docs/implementation/evidence/CR009-VM-source.json'


def source_gate():
    from verify_cr009 import source_check
    _,count,_=source_check();require(count==876,'Retain all876 successful CR009 source bindings')
    policy.verify(ROOT);policy.prior.unchanged_acceptances(ROOT)
    revision,_,context=image.committed_context()
    require(context['digest']==policy.CONTEXT and context['file_count']==377,'The verified377-input GSIS image context changed')
    manifest=json.loads(SOURCE.read_text())
    require(manifest.get('step')=='CR009-VM' and manifest.get('status')=='Prepared'
        and manifest.get('profile')==policy.PROFILE and manifest.get('same_current_database') is True
        and manifest.get('new_migrations')==0 and manifest.get('application_context_digest')==policy.CONTEXT
        and manifest.get('operator_report_canonical_sha256')==policy.REPORT_SHA,
        'The CR009 deployment source binding differs')
    for name,expected in manifest['sha256'].items():
        path=ROOT/name
        require(path.is_file() and not path.is_symlink() and digest_bytes(path.read_bytes())==expected,
            'Prepared CR009 deployment source changed: '+name)
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
    scan=previous.secret_scan();common.private_json(ROOT/'private/vm-cr009-github-scan.json',scan)
    require(scan['unreviewed_findings']==0,'The native source/history scan has unreviewed findings')
    previous.git('push','-u','origin','HEAD:refs/heads/'+policy.BRANCH,capture=False)
    previous.git('push','origin','HEAD:refs/heads/main',capture=False)
    require(previous.git('ls-remote','--heads','origin','main').split()[0]==revision,'GitHub moved concurrently; inspect before deployment')
    return {'status':'GitHub updated','commit':'git:'+revision,'previous_main':'git:'+old,'force_push':False}


def load():
    require(CONFIG.is_file() and not CONFIG.is_symlink(),'Retain the regular separate CR009 configuration')
    value=json.loads(CONFIG.read_text());require(value.get('profile')==policy.PROFILE,'Unexpected CR009 configuration')
    require(previous_profile.CONFIG.is_file() and not previous_profile.CONFIG.is_symlink()
        and digest_bytes(previous_profile.CONFIG.read_bytes())==value.get('previous_local_config_sha256'),
        'The successful current CR008 local configuration changed; it was not overwritten')
    policy.transition(value['source'],value['target'])
    common.validate(value['source'],published=True);common.validate(value['target'],published=True)
    return value


def cached_image():
    existing=image.inspect(policy.IMAGE_ID)
    require(existing is not None,'The actual verified CR009 image is missing locally; no rebuild was attempted')
    built=image.reuse_for_verification(policy.IMAGE_ID)
    require(built['image_id']==policy.IMAGE_ID and built['revision']=='git:'+policy.APP_REVISION
        and built['context']['digest']==policy.CONTEXT,'The cached CR009 image differs from its1210-test gate')
    labels=existing['Config'].get('Labels',{})
    require(labels.get('org.opencontainers.image.revision')==policy.APP_REVISION
        and labels.get('gr.accounting.source-context')==policy.CONTEXT,'Cached CR009 labels differ')
    return built


def configure(identity):
    revision=source_gate();require_local_docker()
    if CONFIG.exists():return load()
    source=common.validate(previous.ssh(policy.prior.BOOTSTRAP,'sudo -n cat /etc/accounting/preview.json'),published=True)
    old=previous_profile.load()
    require(old['target']==source and source['deployment_commit']==policy.VM_DEPLOYMENT,
        'The live source must be the successful current679ad0a configuration')
    prior_journals={}
    for path in policy.PRIOR_STATES:
        raw=previous.ssh(source,'sudo -n cat '+str(path),json_output=False)
        prior_journals[str(path)]=digest_bytes(raw)
        if path==policy.PRIOR_STATES[-1]:policy.completed_journal(json.loads(raw),source)
    operations=previous.ssh(source,'sudo -n cat /etc/accounting/operations.json')
    require(operations['preview']==source,'The current backup configuration differs')
    previous.recovery_config(operations,identity);cached_image()
    repository='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web'
    tag=repository+':'+policy.APP_REVISION
    token=publisher.gcloud(source,'auth','print-access-token').strip()
    require(token and b'\n' not in token,'Unexpected access-token response')
    endpoint=os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
    if not endpoint:endpoint=json.loads(common.run(['docker','context','inspect','--format','{{json .Endpoints.docker.Host}}']))
    environment={k:v for k,v in os.environ.items() if k!='DOCKER_CONTEXT'};environment['DOCKER_HOST']=endpoint
    with tempfile.TemporaryDirectory(prefix='cr009-publish-') as private:
        cli=['docker','--config',private]
        common.run(cli+['login',tag.split('/')[0],'--username','oauth2accesstoken','--password-stdin'],payload=token,environment=environment)
        common.run(cli+['tag',policy.IMAGE_ID,tag],environment=environment)
        pushed=common.run(cli+['push',tag],environment=environment).decode()
    metadata=image.inspect(tag)
    digests=[ref for ref in metadata.get('RepoDigests',[]) if ref.startswith(repository+'@sha256:')]
    if not digests:
        matches=set(re.findall(r'\bdigest: (sha256:[0-9a-f]{64})\b',pushed))
        require(len(matches)==1,'An unambiguous registry digest is required');digests=[repository+'@'+matches.pop()]
    require(len(digests)==1,'Ambiguous published CR009 digest')
    target=deepcopy(source);target['deployment_commit']=revision
    target['published']={'commit':policy.APP_REVISION,'image':digests[0],'image_id':policy.IMAGE_ID,
        'context_digest':policy.CONTEXT,'delivery_evidence':policy.REPORT_SHA}
    policy.transition(source,target);common.validate(target,published=True)
    value={'profile':policy.PROFILE,'source':source,'target':target,'prior_journal_sha256':prior_journals,
        'previous_local_config_sha256':digest_bytes(previous_profile.CONFIG.read_bytes())}
    common.private_json(CONFIG,value,exclusive=True);return value


def host_action(config,action,*arguments):
    command=shlex.join(['sudo','-n','python3',STAGE+'/tools/preview_cr009_host.py',action,*map(str,arguments)])
    gcp=config['source']['gcp']
    result=subprocess.run(['gcloud','compute','ssh',gcp['ssh_user']+'@'+gcp['vm_name'],
        '--project='+gcp['project_id'],'--zone='+gcp['zone'],'--tunnel-through-iap',
        '--quiet','--command='+command],capture_output=True,
        env={**os.environ,'CLOUDSDK_CORE_LOG_HTTP':'false'})
    try:value=json.loads(result.stdout)
    except (ValueError,UnicodeDecodeError):
        raise RuntimeError('VM transport failed; private provider output omitted. Use the CR009 status before retrying') from None
    if result.returncode or value.get('status')=='Stopped':
        if value.get('status')=='Stopped':
            # The hash-bound host emits a value-free reviewed failure object.
            print('CR009-VM-FAILURE '+json.dumps(value,ensure_ascii=False),flush=True)
        raise RuntimeError('CR009 stopped; its public failure and retained journal identify the recovery path')
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
        print('[CR009-VM] Ελεγμένη νέα εικόνα στην ίδια τρέχουσα βάση36, χωρίς migration ή clone.',flush=True)
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
                    print('[CR009-VM] Πραγματική επαναφορά61 πινάκων εκτόςVM: '+label+'.',flush=True)
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
    report={'step':'CR009-VM','status':'Verified','verified_at':state['completed_at'],
        'scope':'verified-cr009-image-on-same-current-schema36-4GiB-database','previous_completed_vm_record':'git:'+policy.VM_RECORD,
        'application_commit':'git:'+policy.APP_REVISION,'deployment_commit':'git:'+common.deployment_commit(state['target']),
        'image':state['target']['published']['image'],'application_context_digest':policy.CONTEXT,
        'same_current_database':True,'database_cloned':False,'database_migrated':False,'schema_before':36,'schema_after':36,
        'previous_completed_journal_unchanged':True,'old_local_deployment_config_unchanged':True,
        'all_three_previous_journals_unchanged':True,'previous_journal_sha256':state['prior_journal_sha256'],
        'database_container_restarted':False,'accounts_mfa_or_keys_reset':False,'durable_queue_retained':True,
        'original_current_rows_preserved_during_maintenance':True,'runtime':runtime,
        'off_vm_source_restore_tables':61,'off_vm_target_restore_tables':61,'both_off_vm_restores_matched':True,
        'separate_recovered_key_used':True,'plaintext_removed':True,'public_checks':state['public_checks'],
        'production_suite_previously_passed':1210,'financial_cases_previously_passed':36,'production_suite_rerun':False,
        'attachment_uploads_enabled':True,'vm_resized':False,'retained_vm_memory_choice':'4GiB',
        'agent_native_execution':False,'full_requirement_acceptances_pending':85,
        'gsis_cross_origin_autofill':False,'actual_gsis_browser_clipboard_acceptance':'Pending operator test',
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
        previous.git('commit','-m','docs: record verified CR009 image upgrade on the current 4GiB database','--',*sorted(allowed),capture=False)
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
        parser.exit(1,'CR009-VM stopped: '+reason+'\n')
    finally:
        if previous.TOOLS_TEMP is not None:previous.TOOLS_TEMP.cleanup()


if __name__=='__main__':main()
