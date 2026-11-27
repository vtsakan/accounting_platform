#!/usr/bin/env python3
"""Operator CR012 clone40→42 upgrade on the existing4GiB preview."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import tempfile

from dev import ROOT,require_local_docker
import image
import preview as publisher
import preview_common as common
import preview_cr008_release as previous
import preview_cr012_policy as policy
import preview_cr011_release as previous_profile
from r1_gate import digest_bytes,require

CONFIG=ROOT/'private/vm-cr012-preview.json'
RESULT=ROOT/'private/vm-cr012-preview-result.json'
STAGE='accounting-cr012-preview-stage'
PUBLIC='docs/implementation/evidence/CR012-VM-verification.json'
SOURCE=ROOT/'docs/implementation/evidence/CR012-VM-source.json'
GUARDS=ROOT/'private/vm-cr012-deployment-guards.json'


def run_tool_guards():
    source_gate()
    result=subprocess.run([sys.executable,str(ROOT/'tools/run_cr012_vm_guards.py')],cwd=ROOT,
        env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
    print(result.stderr,end='',file=sys.stderr,flush=True)
    require(result.returncode==0,'The224 native deployment contracts did not all pass; VM remains unchanged')
    proof=json.loads(result.stdout)
    require(proof=={'tests_run':224,'tests_passed':224,'skips':0,'status':'Passed'},
        'Require the exact176 retained plus48 new deployment results')
    proof.update(source_commit='git:'+previous.git('rev-parse','HEAD'),
        deployment_manifest_sha256=digest_bytes(SOURCE.read_bytes()),application_context_digest=policy.CONTEXT)
    common.private_json(GUARDS,proof)


def guard_proof():
    require(GUARDS.is_file() and not GUARDS.is_symlink(),'Execute the224 native deployment contracts first')
    proof=json.loads(GUARDS.read_text())
    require(proof.get('tests_run')==proof.get('tests_passed')==224 and proof.get('skips')==0
        and proof.get('status')=='Passed' and proof.get('application_context_digest')==policy.CONTEXT
        and proof.get('deployment_manifest_sha256')==digest_bytes(SOURCE.read_bytes()),
        'The actual224-test proof differs from the prepared deployment source')
    require(subprocess.run(['git','merge-base','--is-ancestor',proof['source_commit'][4:],'HEAD'],
        cwd=ROOT,capture_output=True).returncode==0,'Retain the genuine native guard source in Git ancestry')
    return proof


def source_gate(*,clean=True):
    from verify_cr012 import source_check
    _,count,_=source_check();require(count==983,'Retain all983 successful CR012 source bindings')
    from cr012_vm_static import inspect
    inspect(ROOT)
    policy.verify(ROOT);policy.foundation.unchanged_acceptances(ROOT)
    if clean:revision,_,context=image.committed_context()
    else:revision=None;_,context=image.candidate_context()
    require(context['digest']==policy.CONTEXT and context['file_count']==409,'The actual409-input application changed')
    manifest=json.loads(SOURCE.read_text())
    require(manifest.get('step')=='CR012-VM' and manifest.get('status')=='Prepared'
        and manifest.get('profile')==policy.PROFILE and manifest.get('source_migrations')==40
        and manifest.get('target_migrations')==42 and manifest.get('application_context_digest')==policy.CONTEXT
        and manifest.get('operator_delivery_canonical_sha256')==policy.DELIVERY_CANONICAL
        and manifest.get('operator_report_binding')==policy.BASELINE,'The prepared deployment identity differs')
    for name,expected in manifest['sha256'].items():
        path=ROOT/name
        require(path.is_file() and not path.is_symlink() and digest_bytes(path.read_bytes())==expected,'Prepared deployment source changed: '+name)
    require(not previous.git('ls-files','--','private/'),'Private operational material cannot be tracked')
    if clean:require(not previous.git('status','--porcelain'),'Commit reviewed source first; unrelated changes retained')
    return revision


def github():
    revision=source_gate()
    guard_proof()
    require(previous.git('remote','get-url','origin') in (policy.REPOSITORY,'git@github.com:vtsakan/accounting_platform.git'),
        'Unexpected GitHub origin')
    previous.git('fetch','origin','main',capture=False);old=previous.git('rev-parse','FETCH_HEAD')
    require(re.fullmatch(r'[0-9a-f]{40}',old) is not None and subprocess.run(
        ['git','merge-base','--is-ancestor',old,revision],cwd=ROOT,env=image.git_environment(),capture_output=True).returncode==0,
        'GitHub main has independent work; preserve it before updating')
    scan=previous.secret_scan();common.private_json(ROOT/'private/vm-cr012-github-scan.json',scan)
    require(scan['unreviewed_findings']==0,'The native source/history scan has unreviewed findings')
    previous.git('push','-u','origin','HEAD:refs/heads/'+policy.BRANCH,capture=False)
    previous.git('push','origin','HEAD:refs/heads/main',capture=False)
    require(previous.git('ls-remote','--heads','origin','main').split()[0]==revision,'GitHub moved concurrently; inspect before deployment')
    return {'status':'GitHub updated','commit':'git:'+revision,'previous_main':'git:'+old,'force_push':False}


def load():
    require(CONFIG.is_file() and not CONFIG.is_symlink(),'Retain the separate regular CR012 configuration')
    value=json.loads(CONFIG.read_text());require(value.get('profile')==policy.PROFILE,'Unexpected CR012 deployment profile')
    require(previous_profile.CONFIG.is_file() and not previous_profile.CONFIG.is_symlink()
        and digest_bytes(previous_profile.CONFIG.read_bytes())==value.get('previous_local_config_sha256'),
        'The preceding CR011 local configuration changed; it was not overwritten')
    require(digest_bytes(SOURCE.read_bytes())==value.get('deployment_manifest_sha256'),
        'The retained attempt belongs to a different prepared revision; inspect its status')
    policy.transition(value['source'],value['target'])
    common.validate(value['source'],published=True);common.validate(value['target'],published=True)
    return value


def cached_image():
    existing=image.inspect(policy.IMAGE_ID)
    require(existing is not None,'The actual verified CR012 image is missing locally; no rebuild was attempted')
    built=image.reuse_for_verification(policy.IMAGE_ID)
    require(built['image_id']==policy.IMAGE_ID and built['revision']=='git:'+policy.APP_REVISION
        and built['context']['digest']==policy.CONTEXT,'The cached CR012 image differs from its1393-test gate')
    labels=existing['Config'].get('Labels',{})
    require(labels.get('org.opencontainers.image.revision')==policy.APP_REVISION
        and labels.get('gr.accounting.source-context')==policy.CONTEXT,'Cached CR012 labels differ')
    return built


def configure(identity):
    revision=source_gate();require_local_docker()
    guard_proof()
    if CONFIG.exists():return load()
    source=common.validate(previous.ssh(policy.BOOTSTRAP,'sudo -n cat /etc/accounting/preview.json'),published=True)
    old=previous_profile.load()
    require(old['target']==source and source['deployment_commit']==policy.VM_DEPLOYMENT,
        'The live source must be the successful current CR011 configuration')
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
    with tempfile.TemporaryDirectory(prefix='cr012-publish-') as private:
        cli=['docker','--config',private]
        common.run(cli+['login',tag.split('/')[0],'--username','oauth2accesstoken','--password-stdin'],payload=token,environment=environment)
        common.run(cli+['tag',policy.IMAGE_ID,tag],environment=environment)
        pushed=common.run(cli+['push',tag],environment=environment).decode()
    metadata=image.inspect(tag)
    digests=[ref for ref in metadata.get('RepoDigests',[]) if ref.startswith(repository+'@sha256:')]
    if not digests:
        matches=set(re.findall(r'\bdigest: (sha256:[0-9a-f]{64})\b',pushed))
        require(len(matches)==1,'An unambiguous registry digest is required');digests=[repository+'@'+matches.pop()]
    require(len(digests)==1,'Ambiguous published CR012 digest')
    target=deepcopy(source);target['deployment_commit']=revision;target['db_name']='accounting_cr012_'+secrets.token_hex(6)
    target['published']={'commit':policy.APP_REVISION,'image':digests[0],'image_id':policy.IMAGE_ID,
        'context_digest':policy.CONTEXT,'delivery_evidence':policy.report_sha()}
    policy.transition(source,target);common.validate(target,published=True)
    value={'profile':policy.PROFILE,'source':source,'target':target,'prior_journal_sha256':prior_journals,
        'previous_local_config_sha256':digest_bytes(previous_profile.CONFIG.read_bytes()),
        'deployment_manifest_sha256':digest_bytes(SOURCE.read_bytes())}
    common.private_json(CONFIG,value,exclusive=True);return value


def host_action(config,action,*arguments):
    command=shlex.join(['sudo','-n','python3',STAGE+'/tools/preview_cr012_host.py',action,*map(str,arguments)])
    gcp=config['source']['gcp']
    result=subprocess.run(['gcloud','compute','ssh',gcp['ssh_user']+'@'+gcp['vm_name'],
        '--project='+gcp['project_id'],'--zone='+gcp['zone'],'--tunnel-through-iap',
        '--quiet','--command='+command],capture_output=True,
        env={**os.environ,'CLOUDSDK_CORE_LOG_HTTP':'false'})
    try:value=json.loads(result.stdout)
    except (ValueError,UnicodeDecodeError):
        raise RuntimeError('VM transport failed; private provider output omitted. Use the CR012 status before retrying') from None
    if result.returncode or value.get('status')=='Stopped':
        if value.get('status')=='Stopped':
            # The hash-bound host emits a value-free reviewed failure object.
            print('CR012-VM-FAILURE '+json.dumps(value,ensure_ascii=False),flush=True)
        raise RuntimeError('CR012 stopped; its public failure and retained journal identify the recovery path')
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
        for name in (policy.BASELINE,policy.RECEIPT):
            path=directory/name;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(common.run(['git','show',revision+':'+name],environment=image.git_environment()))
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
    source_gate();guard_proof();require_local_docker();transfer(config)
    current=host_action(config,'status')
    if current['status']=='Not applied':
        plan=host_action(config,'plan','--input',STAGE+'/input.json','--bundle',STAGE+'/source.tar')
        operations=previous.ssh(config['source'],'sudo -n cat /etc/accounting/operations.json')
        previous.recovery_config(operations,identity)
        print('[CR012-VM] Κρυπτογραφημένα backup, αντίγραφο της ΤΡΕΧΟΥΣΑΣ βάσης και migrations40→42.',flush=True)
        state=host_action(config,'prepare','--plan-sha256',plan['plan_sha256'])
    else:state=host_action(config,'state')
    require(state.get('source')==config['source'] and state.get('target')==config['target'],'Retain this exact attempt and its recovery path')
    require(state['phase'] in ('awaiting_off_vm_restore','public_cutover_started','needs_public_check','deployed_and_restored'),
        'The retained attempt requires inspection: '+state['phase'])
    if state['phase']!='deployed_and_restored':
        try:
            if state['public_cutover_started']:restored=state['off_vm_restored']
            else:
                from operations_recovery import restore
                restored={}
                for label,operations in (('before',state['source_operations']),('after',state['target_operations'])):
                    count=64 if label=='before' else 65
                    print('[CR012-VM] Πραγματική επαναφορά'+str(count)+' πινάκων εκτόςVM: '+label+'.',flush=True)
                    restored[label]=restore(previous.recovery_config(operations,identity),state[label+'_backup'],identity)
                policy.ready(state,restored)
            path=proof_file(config,'restored.json',restored);state=host_action(config,'activate','--proof',path)
            from demo_release import public_checks
            from vm_material_release import public_assets
            checks=public_checks(config['target']['hostname']);checks.update(public_assets(state))
            path=proof_file(config,'public.json',checks);state=host_action(config,'complete','--proof',path)
        except Exception:
            latest=host_action(config,'state')
            if not latest['public_cutover_started'] and latest['phase']!='rolled_back_to_original':host_action(config,'abort')
            # Never select source40 after jobs/HTTP may have written to target42.
            raise
    common.private_json(RESULT,state);return record(state)


def record(state):
    native_guards=guard_proof()
    require(state['phase']=='deployed_and_restored' and state['public_cutover_started'],'No completed native clone rollout proof')
    require(load()['target']==state['target'],'The completed target differs from this separate configuration')
    policy.transition(state['source'],state['target']);policy.recovery_proofs(state,state['off_vm_restored'])
    runtime=state['runtime']
    require(set(runtime.get('python_memory_cgroups',{}))=={'web','worker','scheduler','scanner'}
        and all(all(v.get(k)==0 for k in ('oom','oom_kill','oom_group_kill')) for v in runtime['python_memory_cgroups'].values()),'Actual new cgroup OOM counters must be zero')
    require(runtime['attachment_uploads_enabled'] is True and runtime['web_workers']==2 and runtime['vm_resized'] is False
        and all(runtime['scanner_proof'][k] is True for k in ('real_clean_stream_accepted','real_eicar_denied','scanner_unavailable_denied_without_writes')),
        'The actual4GiB upload/memory proof is incomplete')
    report={'step':'CR012-VM','status':'Verified','verified_at':state['completed_at'],'scope':'existing-preview-CURRENT40-clone-to42-4GiB',
        'previous_completed_vm_record':'git:'+policy.VM_RECORD,'application_commit':'git:'+policy.APP_REVISION,
        'deployment_commit':'git:'+common.deployment_commit(state['target']),'image':state['target']['published']['image'],
        'application_context_digest':policy.CONTEXT,'operator_report_canonical_sha256':policy.report_sha(),
        'operator_result_commit':policy.verify(ROOT)['native_result_commit'],
        'deployment_guard_tests_passed':224,
        'deployment_guard_manifest_sha256':native_guards['deployment_manifest_sha256'],
        'source_migrations':40,'target_migrations':42,'source_tables':64,'target_tables':65,
        'original_database_retained_unmigrated':True,'original_columns_rows_passwords_mfa_sessions_preserved':True,
        'new_business_tables_empty':True,'automatic_financial_posting_during_migration':False,
        'database_container_restarted':False,'accounts_mfa_or_keys_reset':False,'durable_queue_retained':True,
        'previous_deployment_journals_unchanged':True,'previous_local_deployment_config_unchanged':True,
        'previous_journal_sha256':state['prior_journal_sha256'],'runtime':runtime,
        'off_vm_source_restore_tables':64,'off_vm_target_restore_tables':65,'both_off_vm_restores_matched':True,
        'source_restore_seconds':state['off_vm_restored']['before']['restore_seconds'],
        'target_restore_seconds':state['off_vm_restored']['after']['restore_seconds'],
        'separate_recovered_key_used':True,'plaintext_removed':True,'public_checks':state['public_checks'],
        'existing_mfa_seeds_decrypted_without_writes':state['migration']['existing_mfa_seeds_decrypted_without_writes'],
        'existing_vaults_decrypted_without_writes':state['migration']['existing_vaults_decrypted_without_writes'],
        'existing_attachments_decrypted_without_writes':state['migration']['existing_attachments_decrypted_without_writes'],
        'production_suite_previously_passed':1393,'financial_cases_previously_passed':36,'production_suite_rerun':False,
        'attachment_uploads_enabled':True,'vm_resized':False,'retained_vm_memory_choice':'4GiB',
        'agent_native_execution':False,'full_requirement_acceptances_pending':85,
        'actual_browser_login_mfa':'Pending operator login','actual_excel_import_acceptance':'Pending operator preview/confirmation',
        'actual_gsis_browser_clipboard_acceptance':'Pending operator test','real_client_release':'Blocked; R1/D05/D06/D07/G2 Pending',
        'full_document_recovery_acceptance':'Pending S38; existing sealed attachment bytes retained in DB backups'}
    path=ROOT/PUBLIC
    if path.exists():require(json.loads(path.read_text())==report,'An existing real rollout report differs; it was retained')
    else:
        with path.open('x') as stream:stream.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if b'<!-- CR012-VM -->' not in (ROOT/'docs/implementation/state.md').read_bytes():policy.track(ROOT,report)
    print(json.dumps(report,ensure_ascii=False,indent=2));return report


def push_result():
    changed=set(filter(None,previous.git('diff','--name-only','HEAD').splitlines()))
    extra=set(filter(None,previous.git('ls-files','--others','--exclude-standard').splitlines()))
    allowed={PUBLIC,'docs/implementation/state.md'}
    require(changed|extra<=allowed,'Unrelated changes were preserved; only this exact profile result/tracking may be committed')
    if changed or extra:
        previous.git('add','--',*sorted(allowed),capture=False)
        previous.git('commit','-m','docs: record CR012 clone upgrade and both64/65-table off-VM restores','--',*sorted(allowed),capture=False)
    return github()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('source','all','github','deploy','resume','status','abort','record','scanner-refresh'))
    parser.add_argument('--identity',type=Path,default=Path.home()/'.config/totalaccounting/recovered-backup-age.key');args=parser.parse_args()
    os.chdir(ROOT)
    try:
        if args.action in ('all','github','deploy','resume','record'):run_tool_guards()
        if args.action=='source':result={'status':'Prepared','profile':policy.PROFILE,'deployment_commit':'git:'+source_gate(),'runtime_executed':False}
        elif args.action=='github':result=github()
        elif args.action=='status':
            result=host_action(load(),'status') if CONFIG.exists() else previous.ssh(policy.BOOTSTRAP,'sudo -n /usr/local/sbin/accounting-preview status')
        elif args.action in ('abort','scanner-refresh'):result=host_action(load(),args.action)
        elif args.action=='record':record(host_action(load(),'state'));result=push_result()
        else:
            if args.action=='all':config=configure(args.identity);print(json.dumps(github(),ensure_ascii=False))
            else:config=load()
            deploy(config,args.identity);result=push_result()
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        reason=str(error) if isinstance(error,RuntimeError) else 'Profile operation stopped; private input/provider output omitted'
        parser.exit(1,'CR012-VM stopped: '+reason+'\n')
    finally:
        if previous.TOOLS_TEMP is not None:previous.TOOLS_TEMP.cleanup()


if __name__=='__main__':main()
