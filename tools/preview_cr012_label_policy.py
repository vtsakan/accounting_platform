"""Genuine label result and same-CURRENT42/4GiB image-only transition."""
import json
from pathlib import Path
import re
import subprocess

import cr012_label as label
import preview_cr008_policy as prior
import preview_cr012_policy as previous
from r1_gate import digest_bytes,digest_object,require

PROFILE='cr012-label-same-current42-4GiB'
BRANCH='release/cr012-label-preview-upgrade'
REPOSITORY=prior.REPOSITORY
BOOTSTRAP=prior.BOOTSTRAP
CONTEXT='sha256:6452f9373016e8aed89c4bf810d3aeb43e3cb71f6fd39759a92918ca10891744'
VM_RECORD=label.COMPLETED
VM_DEPLOYMENT='3f8b685e64d0806ca1400c39bcf9305ced06d65d'  # pragma: allowlist secret -- actual completed CR012 deployment
OLD_IMAGE='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:38360ef25bdcf3017df90b939b4f618297b30336a54cfede26bee6ae8b166ce8'
OLD_CONTEXT=previous.CONTEXT
OLD_APP=previous.APP_REVISION
OLD_IMAGE_ID=previous.IMAGE_ID
RECEIPT=label.REPORT
BASELINE='docs/implementation/evidence/CR012-LABEL-VM-operator-baseline.json'
PRIOR_STATES=(*previous.PRIOR_STATES,Path('/etc/accounting/cr012-preview-state.json'))
PRIOR_HOLDS=(*previous.PRIOR_HOLDS,Path('/etc/accounting/cr012-preview-in-progress'))


def operator_report(value):
    require(value.get('change')=='CR012-LABEL' and value.get('status')=='Verified'
        and value.get('scope')=='ON_DEMAND-list-and-client-card-caption-production-image',
        'Require the genuine completed label-fix production-image report')
    suite=value['suite'];selected=value['image'];source=value['source_commit']
    require(re.fullmatch(r'git:[0-9a-f]{40}',source) is not None
        and re.fullmatch(r'git:[0-9a-f]{40}',selected['revision']) is not None
        and selected['verification_revision']==source
        and re.fullmatch(r'sha256:[0-9a-f]{64}',selected['image_id']) is not None
        and selected['context']['digest']==value['application_context_digest']==CONTEXT
        and selected['context']['file_count']==409 and suite['tests_run']==suite['tests_passed']==1393
        and len(suite['cases'])==36 and all(c['outcome']=='passed' for c in suite['cases'])
        and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
        and value['retained_deployment_contracts_passed']==224 and value['production_suite_rerun'] is True,
        'Require fresh1393/36/224 and this exact409-input label image')
    require(value['changed_application_files']==list(label.TEMPLATES) and value['new_migrations']==0
        and value['retained_migrations']==42 and value['new_native_test_methods']==0
        and value['historical_receipts_unchanged'] is True and value['secret_scan']['unreviewed_findings']==0
        and value['docker_execution_by_operator'] is True and all(value[k] is False for k in
            ('agent_native_execution','vm_changed','github_updated','human_accounts_or_mfa_changed',
             'existing_agreements_or_financial_data_changed','real_file_recovery_and_worker_rerun'))
        and value['full_requirement_acceptances_pending']==85,'Retain the narrow two-template scope and genuine prior evidence')
    return value


def native_reports(root):
    root=Path(root);label.source_check();old=label.check_binding(root)
    path=label.regular(root,RECEIPT);require(path.stat().st_size<=2_000_000,'Retain a bounded genuine label report')
    value=operator_report(json.loads(path.read_text()));source=value['source_commit'][4:];original=value['image']['revision'][4:]
    require(value['previous_native_files_sha256']==old['files']
        and value['preserved_operator_files_sha256']==old['preserved_operator_files']
        and value['previous_real_files_and_worker_report_sha256']==old['files']['docs/implementation/evidence/CR012-verification.json'],
        'The successful label result must retain the exact35 historical files')
    import image
    from cr008_delivery_resume import context_at
    require(root.resolve()==image.ROOT.resolve() and context_at(source)==context_at(original)==value['image']['context']==image.candidate_context()[1],
        'The report and cached image must match all409 current application inputs')
    candidates=[]
    for record in subprocess.check_output(['git','log','--format=%H','HEAD','--',RECEIPT],cwd=root,text=True).splitlines():
        parents=subprocess.check_output(['git','rev-list','--parents','-n','1',record],cwd=root,text=True).split()
        names=set(subprocess.check_output(['git','diff-tree','--no-commit-id','--name-only','-r',record],cwd=root,text=True).splitlines())
        if parents==[record,source] and names=={RECEIPT,label.STATE} and subprocess.check_output(['git','show',record+':'+RECEIPT],cwd=root)==path.read_bytes():candidates.append(record)
    require(len(candidates)==1,'Resolve the real two-file successful label result; never reconstruct it')
    names=(*old['files'],label.BASELINE,RECEIPT);require(len(set(names))==37,'Retain all37 genuine prior report/binding files')
    return {'scope':PROFILE,'binding_schema':1,'native_source':'git:'+source,'native_result_commit':'git:'+candidates[0],
        'image_source':'git:'+original,'image_id':value['image']['image_id'],'application_context_digest':CONTEXT,
        'canonical_report_sha256':digest_object(value),'previous_completed_vm_record':'git:'+VM_RECORD,
        'preserved_operator_files':old['preserved_operator_files'],
        'files':{n:digest_bytes(label.regular(root,n).read_bytes()) for n in names}}


def bind(root):
    root=Path(root);value=native_reports(root);path=root/BASELINE
    if path.exists() or path.is_symlink():return verify(root)
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


def verify(root):
    root=Path(root);value=native_reports(root)
    require(json.loads(label.regular(root,BASELINE).read_text())==value,'The exclusive37-file label VM binding differs; no refresh')
    return value


def identity(root=None):
    root=Path(root) if root is not None else Path(__file__).resolve().parents[1]
    value=json.loads(label.regular(root,BASELINE).read_text())
    require(value['scope']==PROFILE and value['binding_schema']==1 and value['application_context_digest']==CONTEXT
        and re.fullmatch(r'git:[0-9a-f]{40}',value['image_source']) is not None
        and re.fullmatch(r'sha256:[0-9a-f]{64}',value['image_id']) is not None
        and re.fullmatch(r'sha256:[0-9a-f]{64}',value['canonical_report_sha256']) is not None,
        'A concrete genuine native image/report identity is required')
    return value


def app_revision():return identity()['image_source'][4:]
def image_id():return identity()['image_id']
def report_sha():return identity()['canonical_report_sha256']


def transition(source,target):
    prior.target_identity(source);prior.target_identity(target)
    require({k:v for k,v in source.items() if k not in {'deployment_commit','published'}}
        =={k:v for k,v in target.items() if k not in {'deployment_commit','published'}},
        'Change only image/deployment; keep the SAME CURRENT42 database, roles, keys and hostname')
    current=source['published']
    require(source['deployment_commit']==VM_DEPLOYMENT and current['commit']==OLD_APP
        and current['image']==OLD_IMAGE and current['image_id']==OLD_IMAGE_ID and current['context_digest']==OLD_CONTEXT
        and re.fullmatch(r'accounting_cr012_[0-9a-f]{12}',source['db_name']) is not None,
        'Require the actual completed CR012 CURRENT42 database and image')
    published=target['published'];prefix='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:'
    require(re.fullmatch(r'[0-9a-f]{40}',target.get('deployment_commit','')) is not None
        and published['commit']==app_revision() and published['image_id']==image_id()
        and published['context_digest']==CONTEXT and published.get('delivery_evidence')==report_sha()
        and re.fullmatch(re.escape(prefix)+r'[0-9a-f]{64}',published['image']) is not None,
        'Require only the exact freshly verified label image in the selected registry')


def completed_journal(value,source):
    require(value.get('phase')=='deployed_and_restored' and value.get('public_cutover_started') is True
        and value.get('target')==source and value.get('runtime',{}).get('attachment_uploads_enabled') is True,
        'The completed CR012 journal must remain the installed CURRENT42 source')
    previous.transition(value['source'],value['target']);previous.recovery_proofs(value,value['off_vm_restored'])


def recovery_proofs(state,restored):
    require(set(restored)=={'before','after'},'Restore both fresh encrypted CURRENT42 snapshots off-VM')
    for name in ('before','after'):
        proof=restored[name]
        require(proof['receipt']==state[name+'_backup'] and proof['status']=='Restored' and proof['tables_checked']==65
            and all(proof[k] is True for k in ('all_public_tables_match','separate_recovery_key_used','plaintext_removed','recovery_container_removed'))
            and proof['preview_database_modified'] is False,'Require the exact65/65-table independent-key restore proofs')


def ready(state,restored):
    prior.ready_for_activation(state,restored);recovery_proofs(state,restored)


def rollback_database(source,target):
    transition(source,target);return source['db_name']


def track(root,report):
    prior.unchanged_acceptances(root);path=Path(root)/label.STATE;before=path.read_bytes()
    require(b'<!-- CR012-LABEL-VM -->' not in before,'Retain an existing label deployment marker')
    path.write_bytes(before+b'\n\n<!-- CR012-LABEL-VM -->\nVerified operator label image rollout: same CURRENT42 database/65tables, fresh65/65 independent-key off-VM restores, unchanged4GiB scanner/memory/HTTPS profile, all prior journals/people/MFA/keys/queue retained. No clone/migration or data rewind. All85 full acceptances and browser/business/G2 Pending.\n<!-- /CR012-LABEL-VM -->\n')
