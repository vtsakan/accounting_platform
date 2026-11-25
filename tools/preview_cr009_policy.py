"""Exact CR009 image rollout on the CURRENT schema36 4GiB database."""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

import cr009_receipts as receipts
import preview_cr008_policy as prior
import preview_cr008_memory_policy as memory_policy
from r1_gate import digest_bytes,digest_object,require

PROFILE='cr009-current-schema36-4GiB-gsis-and-uploads'
BRANCH='release/cr009-preview-upgrade'
VM_RECORD=receipts.CURRENT_RECORD
VM_DEPLOYMENT=receipts.CURRENT_DEPLOYMENT
OLD_IMAGE=memory_policy.VM_IMAGE
OLD_CONTEXT=prior.CONTEXT
APP_REVISION='82ee33b36ff012fa139d97b9e8702c8786b1f1e2'  # pragma: allowlist secret -- actual public1210-test CR009 image revision
CONTEXT='sha256:f03b87ce384ee9b0eb6d07d946cd53c2d9ceb02d04ca2af772a55dfd70cf5931'
IMAGE_ID='sha256:917505cfa888f8993c3edf05c43468fab2ea4c9881ef52d3fd91a7dc408f1eb9'
REPORT_SHA='sha256:b63e243ae5423dc2ad5d7e19b4de86f1d3f4dd979b1a8c89be89758db3ff1342'
RECEIPT='docs/implementation/evidence/CR009-verification.json'
BASELINE='docs/implementation/evidence/CR009-VM-operator-baseline.json'
REPORTS=(*receipts.PATHS,receipts.BASELINE,RECEIPT)
RECORDED=(RECEIPT,'docs/implementation/state.md')
PRIOR_STATES=(Path('/etc/accounting/cr008-preview-state.json'),
    Path('/etc/accounting/cr008-4gb-profile-state.json'),Path('/etc/accounting/cr008-4gb-memory-state.json'))
PRIOR_HOLDS=(Path('/etc/accounting/cr008-preview-in-progress'),
    Path('/etc/accounting/cr008-4gb-profile-in-progress'),Path('/etc/accounting/cr008-4gb-memory-in-progress'))


def operator_report(value):
    require(digest_object(value)==REPORT_SHA and value['change']=='CR-009' and value['status']=='Verified'
        and value['source_commit']=='git:'+APP_REVISION,
        'Retain the exact actual successful CR009 operator report')
    suite=value['suite'];selected=value['image'];files=value['private_files']
    require(suite['tests_run']==suite['tests_passed']==1210 and len(suite['cases'])==36
        and all(row['outcome']=='passed' for row in suite['cases'])
        and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
        and selected['image_id']==IMAGE_ID and selected['revision']=='git:'+APP_REVISION
        and selected['verification_revision']=='git:'+APP_REVISION
        and selected['context']['digest']==CONTEXT and selected['context']['file_count']==377
        and value['deployment_guard_tests_passed']==115,
        'Require the real1210/36 gate,115 retained guards and identical377-input image')
    require(all(value[k] is True for k in ('real_monthly_worker_and_commit_before_ack','revocation_blocks_execution',
        'second_scheduler_rejected','restricted_role_migrations','historical_receipts_unchanged',
        'owned_resources_removed','deployment_guard_suite_passed','vm_github_upgrade_authorized_after_verification'))
        and value['secret_scan']['unreviewed_findings']==0
        and all(value[k] is False for k in ('agent_native_execution','local_demo_or_vm_changed','github_updated','human_accounts_or_mfa_changed')),
        'The complete actual CR009 worker/source gate is required')
    require(files['all_public_tables_restored']==61 and files['restored_files']==10
        and all(files[k] is True for k in ('original_file_sha256_after_authenticated_download','antivirus_real_eicar_denied',
            'scanner_unavailable_denied_without_storage','restricted_role_migrations','sealed_bytes_in_database',
            'all_public_tables_and_file_hashes_matched','wrong_recovery_key_denied','separate_external_recovery_material_used',
            'owned_resources_removed')),'The actual real file antivirus and encrypted recovery gate is required')
    return value


def native_result_commit(root):
    root=Path(root);candidates=[]
    for row in subprocess.check_output(['git','rev-list','--parents','HEAD'],cwd=root,text=True).splitlines():
        fields=row.split()
        if fields[1:]!=[APP_REVISION]:continue
        names=set(subprocess.check_output(['git','diff','--name-only',APP_REVISION,fields[0]],cwd=root,text=True).splitlines())
        if names==set(RECORDED):candidates.append(fields[0])
    require(len(candidates)==1 and candidates[0].startswith('a061a00'),
        'Retain the actual a061a00 child that recorded only the two successful CR009 outputs')
    require(subprocess.check_output(['git','show',candidates[0]+':'+RECEIPT],cwd=root)==(root/RECEIPT).read_bytes(),
        'The actual CR009 report changed after its result commit')
    return candidates[0]


def native_reports(root):
    root=Path(root);bound=receipts.verify_binding(root)
    value=operator_report(json.loads((root/RECEIPT).read_text()));native_result_commit(root)
    require(value['actual_prior_receipt_files_sha256']==bound['files'],
        'All21 actual earlier files must match the successful CR009 gate')
    require(len(set(REPORTS))==23 and all((root/name).is_file() and not (root/name).is_symlink()
        and (root/name).stat().st_size<=2_000_000 for name in REPORTS),'Retain all23 actual receipt/binding files')
    prior.unchanged_acceptances(root)
    return {'scope':PROFILE,'operator_source':'git:'+APP_REVISION,'operator_report_canonical_sha256':REPORT_SHA,
        'previous_vm_record':'git:'+VM_RECORD,'files':{name:digest_bytes((root/name).read_bytes()) for name in REPORTS}}


def bind(root):
    root=Path(root);value=native_reports(root);path=root/BASELINE
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink() and json.loads(path.read_text())==value,
            'The existing CR009 deployment binding differs; it was not refreshed')
    else:
        with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


def verify(root):
    root=Path(root);value=native_reports(root);path=root/BASELINE
    require(path.is_file() and not path.is_symlink() and json.loads(path.read_text())==value,
        'The exact23-file CR009 deployment binding is required')
    return value


def transition(source,target):
    prior.target_identity(source);prior.target_identity(target)
    require({k:v for k,v in source.items() if k not in {'deployment_commit','published'}}
        =={k:v for k,v in target.items() if k not in {'deployment_commit','published'}},
        'Change only the image/deployment; keep the SAME CURRENT database, hostname, roles and keys')
    require(source.get('deployment_commit')==VM_DEPLOYMENT and source['published']['image']==OLD_IMAGE
        and source['published']['commit']==prior.APP_REVISION and source['published']['image_id']==prior.IMAGE_ID
        and source['published']['context_digest']==OLD_CONTEXT,
        'Require the observed successful current679ad0a source, never an earlier profile or database')
    require(re.fullmatch(r'accounting_cr008_[0-9a-f]{12}',source['db_name']) is not None,
        'Retain the current schema36 database; no clone or schema30 reactivation')
    require(re.fullmatch(r'[0-9a-f]{40}',target.get('deployment_commit','')) is not None,
        'Require a complete committed deployment revision')
    published=target['published'];prefix='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:'
    require(published['commit']==APP_REVISION and published['image_id']==IMAGE_ID
        and published['context_digest']==CONTEXT and published.get('delivery_evidence')==REPORT_SHA
        and re.fullmatch(re.escape(prefix)+r'[0-9a-f]{64}',published['image']) is not None,
        'Use only the exact verified CR009 image in the selected registry')


def completed_journal(value,source):
    require(value.get('phase')=='profile_verified' and value.get('public_cutover_started') is True
        and value.get('target')==source and value.get('runtime',{}).get('attachment_uploads_enabled') is True,
        'The successful current CR008 uploads profile must remain the installed source')
    memory_policy.transition(value['source'],value['target'])
    require(set(value.get('off_vm_restored',{}))=={'before','after'},'Retain both preceding61-table recovery proofs')
    for label in ('before','after'):
        proof=value['off_vm_restored'][label]
        require(proof.get('receipt')==value[label+'_backup'] and proof.get('status')=='Restored'
            and proof.get('tables_checked')==61 and proof.get('all_public_tables_match') is True
            and proof.get('separate_recovery_key_used') is True,'The preceding current database recovery proof changed')


def ready(state,restored):
    memory_policy.ready(state,restored)


def rollback_database(source,target):
    transition(source,target)
    return source['db_name']


def track(root,status):
    require(status in ('Prepared','Verified'),'Concrete CR009 deployment status required')
    prior.unchanged_acceptances(root);path=Path(root)/'docs/implementation/state.md';before=path.read_bytes()
    start=b'<!-- CR009-VM -->';end=b'<!-- /CR009-VM -->'
    require(before.count(start)==before.count(end) and before.count(start)<=1,'Ambiguous CR009 VM markers')
    block=(start.decode()+'\nStatus: **'+status+'**. CR009 verified1210/36 GSIS image, same CURRENTschema36 '
        'database and4GiB memory/AV profile. Fresh61/61 independent-key restores and liveAV/OOM/HTTPS proof required. '
        'No migration, clone, resize, account/MFA reset or history overwrite. All85 full acceptances and '
        'actual GSIS/browser/clipboard/D06/S38/R1/G2 remain Pending.\n'+end.decode()).encode()
    if start in before:
        a=before.index(start);b=before.index(end)+len(end);require(a<b,'Unordered CR009 VM markers')
        after=before[:a]+block+before[b:]
    else:after=before+b'\n\n'+block+b'\n'
    if after!=before:path.write_bytes(after)
    return after
