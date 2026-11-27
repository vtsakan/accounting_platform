"""Bind the genuine CR012 success and clone only the CURRENT completed CR011 database."""
import json
from pathlib import Path
import re
import subprocess

import cr012_receipts as receipts
import preview_cr008_policy as foundation
import preview_cr011_policy as previous
from r1_gate import digest_bytes,digest_object,require

PROFILE='cr012-current40-to42-clone-4GiB-uploads'
BRANCH='release/cr012-preview-upgrade'
REPOSITORY=foundation.REPOSITORY
BOOTSTRAP=foundation.BOOTSTRAP
APP_REVISION='f4ce08871eae514d6d80fbf55c3d6b05c59bd227'  # pragma: allowlist secret -- genuine1393-test image source supplied by operator
CONTEXT='sha256:8f8341cba921c7eac3c100abb8bb20fbd5d8dada82087c3be4573c3293df34ad'
IMAGE_ID='sha256:996ff3c2ff17afb8e8ac20f83f868cf0520f78eed1b0d972314edfefc94cd42f'
DELIVERY_CANONICAL='sha256:0edbc23a740c12be55a640103eab778d2a16cabead81258148a9594ed17979f1'
RECEIPT='docs/implementation/evidence/CR012-verification.json'
BASELINE='docs/implementation/evidence/CR012-VM-operator-baseline.json'
VM_RECORD=receipts.CURRENT_RECORD
VM_DEPLOYMENT='446858b9d5142d220736088b177fe1e117f3cf03'  # pragma: allowlist secret -- actual completed CR011 deployment
OLD_APP=previous.APP_REVISION
OLD_CONTEXT=previous.CONTEXT
OLD_IMAGE_ID=previous.IMAGE_ID
OLD_IMAGE='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:04a6133c3c413da70e68e14a28dc8b274b59f3a0f196c1eb716c9cc3f30a71c9'
PRIOR_STATES=(*previous.PRIOR_STATES,Path('/etc/accounting/cr011-preview-state.json'))
PRIOR_HOLDS=(*previous.PRIOR_HOLDS,Path('/etc/accounting/cr011-preview-in-progress'))
NEW_TABLES=frozenset({'accounting_cashchargeselection'})


def operator_report(value):
    require(type(value) is dict and value.get('change')=='CR-012' and value.get('status')=='Verified',
        'The genuine complete CR012 result is required before deployment')
    suite=value['suite'];files=value['private_files'];selected=value['image'];source=value['source_commit']
    require(re.fullmatch(r'git:[0-9a-f]{40}',source) is not None
        and suite['tests_run']==suite['tests_passed']==1393 and len(suite['cases'])==36
        and all(c['outcome']=='passed' for c in suite['cases'])
        and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
        and selected['image_id']==IMAGE_ID and selected['revision']=='git:'+APP_REVISION
        and selected['verification_revision']==source and selected['context']['file_count']==409
        and selected['context']['digest']==value['application_context_digest']==CONTEXT
        and value['deployment_guard_tests_passed']==176 and value['new_test_methods']==86
        and value['retained_source_files_checked']==983,
        'Require the real1393/36/176 result and the exact409-input immutable image')
    reused=value['retained_successful_delivery']
    require(value['production_suite_rerun'] is False and reused['canonical_report_sha256']==DELIVERY_CANONICAL
        and reused['source_commit']=='git:'+APP_REVISION and reused['image_id']==IMAGE_ID
        and reused['application_context_digest']==CONTEXT and reused['tests_passed']==1393 and reused['financial_cases']==36,
        'Retain the genuine successful delivery identity and explicit suite reuse')
    require(all(value[k] is True for k in ('real_monthly_worker_and_commit_before_ack','revocation_blocks_execution',
        'second_scheduler_rejected','restricted_role_migrations','historical_receipts_unchanged','owned_resources_removed',
        'original_40_migrations_unchanged','docker_execution_by_operator'))
        and value['new_migrations']==2 and value['agent_native_execution'] is False
        and value['local_demo_or_vm_changed'] is False and value['github_updated'] is False
        and value['human_accounts_or_mfa_changed'] is False and value['secret_scan']['unreviewed_findings']==0,
        'Real restricted-role migrations, unchanged history and worker proof are required')
    require(files['all_public_tables_restored']==65 and files['restored_files']==10
        and all(files[k] is True for k in ('staff_credentials_recovered','excel_recovery_verified','demand_charges_recovered',
            'cash_charge_selection_recovered','antivirus_real_eicar_denied','scanner_unavailable_denied_without_storage',
            'all_public_tables_and_file_hashes_matched','separate_external_recovery_material_used','wrong_recovery_key_denied',
            'original_file_sha256_after_authenticated_download','sealed_bytes_in_database','owned_resources_removed'))
        and all(files['staff_credentials'].values()) and all(files['excel_import'].values())
        and all(files['charge_workflow'].get(k) is True for k in ('terms_do_not_post_cash',
            'arbitrary_charges_respect_gross_budget','only_selected_charge_settled','excess_kept_as_credit',
            'lower_terms_rejected','changed_choice_rejected','exact_replay_once','invalid_requests_have_no_partial_writes')),
        'Require real selected-charge/credit, credentials, AV and65-table encrypted recovery proof')
    require(value['prior_completed_vm_record']=='git:'+VM_RECORD
        and value['prior_cr011_record']=='git:'+receipts.NATIVE_RESULT
        and value['full_requirement_acceptances_pending']==85 and value['accountant_browser_acceptance']=='Pending'
        and value['g2_release_acceptance']=='Pending','Retain genuine prior VM history and the unaccepted business/browser scope')
    return value


def native_reports(root):
    root=Path(root);old=receipts.verify_binding(root);path=root/RECEIPT
    require(path.is_file() and not path.is_symlink() and path.stat().st_size<=2_000_000,'Retain the real regular CR012 report')
    report=operator_report(json.loads(path.read_text()));source=report['source_commit'][4:]
    require(report['actual_prior_receipt_files_sha256']==old['files']
        and report['preserved_operator_files_sha256']==old['preserved_operator_files'],
        'The actual31 prior files or preserved operator instructions changed')
    def git(*args):return subprocess.check_output(['git',*args],cwd=root,text=True).strip()
    require(subprocess.run(['git','merge-base','--is-ancestor',APP_REVISION,source],cwd=root,capture_output=True).returncode==0,
        'Retain the genuine1393-test image source in native ancestry; never reconstruct it')
    from cr008_delivery_resume import context_at
    import image
    # context_at uses the same ROOT as the deployment tools; no application setup.
    require(root.resolve()==image.ROOT.resolve(),'Use the actual native repository')
    require(context_at(source)==context_at(APP_REVISION)==report['image']['context']==image.candidate_context()[1],
        'Application bytes differ from the actual successful1393-test image')
    candidates=[]
    for record in git('log','--format=%H','HEAD','--',RECEIPT).splitlines():
        if git('rev-list','--parents','-n','1',record).split()!=[record,source]:continue
        changed=set(git('diff-tree','--no-commit-id','--name-only','-r',record).splitlines())
        if changed!={RECEIPT,'docs/implementation/state.md'}:continue
        if subprocess.check_output(['git','show',record+':'+RECEIPT],cwd=root)==path.read_bytes():candidates.append(record)
    require(len(candidates)==1,'Record the genuine successful two-file CR012 result once; no fabricated native child')
    names=(*old['files'],receipts.BASELINE,RECEIPT)
    require(len(set(names))==33,'Retain every33 genuine prior receipt and binding files')
    require(all((root/n).is_file() and not (root/n).is_symlink() for n in names),'Retain regular native history files')
    return {'scope':PROFILE,'binding_schema':1,'native_source':'git:'+source,'native_result_commit':'git:'+candidates[0],
        'image_source':'git:'+APP_REVISION,'canonical_report_sha256':digest_object(report),'previous_vm_record':'git:'+VM_RECORD,
        'preserved_operator_files':old['preserved_operator_files'],
        'files':{name:digest_bytes((root/name).read_bytes()) for name in names}}


def bind(root):
    root=Path(root);actual=native_reports(root);path=root/BASELINE
    if path.exists() or path.is_symlink():return verify(root)
    with path.open('x') as stream:stream.write(json.dumps(actual,ensure_ascii=False,indent=2)+'\n')
    return actual


def verify(root):
    root=Path(root);actual=native_reports(root);path=root/BASELINE
    require(path.is_file() and not path.is_symlink() and json.loads(path.read_text())==actual,
        'The exclusive33-file CR012 deployment binding differs; it was not refreshed')
    return actual


def report_sha(root=None):
    if root is None:root=Path(__file__).resolve().parents[1]
    path=Path(root)/BASELINE
    require(path.is_file() and not path.is_symlink(),'Require the separate genuine CR012 deployment binding')
    value=json.loads(path.read_text())
    require(value['scope']==PROFILE and re.fullmatch(r'sha256:[0-9a-f]{64}',value['canonical_report_sha256']) is not None,
        'A concrete CR012 report digest is required')
    return value['canonical_report_sha256']


def transition(source,target):
    foundation.target_identity(source);foundation.target_identity(target)
    changed={'published','deployment_commit','db_name'}
    require({k:v for k,v in source.items() if k not in changed}=={k:v for k,v in target.items() if k not in changed},
        'Preserve VM/disks/hostname/roles/pinned keys and all other configuration')
    require(source['deployment_commit']==VM_DEPLOYMENT and source['published']['image']==OLD_IMAGE
        and source['published']['commit']==OLD_APP and source['published']['context_digest']==OLD_CONTEXT
        and source['published']['image_id']==OLD_IMAGE_ID
        and re.fullmatch(r'accounting_cr011_[0-9a-f]{12}',source['db_name']) is not None,
        'Require the CURRENT completed CR011/schema40 database; never a retained older database')
    require(re.fullmatch(r'accounting_cr012_[0-9a-f]{12}',target['db_name']) is not None
        and target['db_name']!=source['db_name'],'Use a new distinct clone of the CURRENT source')
    published=target['published'];prefix='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:'
    require(published['commit']==APP_REVISION and published['image_id']==IMAGE_ID and published['context_digest']==CONTEXT
        and published['delivery_evidence']==report_sha() and re.fullmatch(re.escape(prefix)+r'[0-9a-f]{64}',published['image']) is not None
        and re.fullmatch(r'[0-9a-f]{40}',target.get('deployment_commit','')) is not None,
        'Select only the exact verified CR012 image and a full deployment revision')


def completed_journal(value,source):
    require(value.get('phase')=='deployed_and_restored' and value.get('public_cutover_started') is True
        and value.get('target')==source and value.get('runtime',{}).get('attachment_uploads_enabled') is True,
        'The retained CR011 journal must prove the installed completed source')
    previous.transition(value['source'],value['target'])
    previous.recovery_proofs(value,value['off_vm_restored'])
    require(value['migration']['source_migrations']==36 and value['migration']['target_migrations']==40,
        'Retain the actual completed CR011/schema40 journal')


def recovery_proofs(state,restored):
    require(set(restored)=={'before','after'},'Restore both encrypted snapshots off this VM')
    for label,count in (('before',64),('after',65)):
        proof=restored[label]
        require(proof['tables_checked']==count and proof['status']=='Restored'
            and proof['receipt']==state[label+'_backup'] and proof['all_public_tables_match'] is True
            and proof['separate_recovery_key_used'] is True and proof['plaintext_removed'] is True
            and proof['recovery_container_removed'] is True and proof['preview_database_modified'] is False,
            'Require exact independent-key source64/target65 encrypted restore proofs')
    require(state['migration']['source_migrations']==40 and state['migration']['target_migrations']==42
        and state['migration']['old_tables_checked']==64 and state['migration']['new_business_tables_empty'] is True
        and state['migration']['restricted_role_migrations'] is True
        and state['migration']['original_columns_rows_passwords_mfa_sessions_preserved'] is True
        and state['migration']['original_database_migrated'] is False,'Require the real restricted40→42 clone migration')


def ready(state,restored):
    foundation.ready_for_activation(state,restored);recovery_proofs(state,restored)


def before_public(state):foundation.before_public(state)


def rebound_operations(original,target):return foundation.rebound_operations(original,target)


def track(root,report):
    foundation.unchanged_acceptances(root);path=Path(root)/'docs/implementation/state.md';before=path.read_bytes()
    require(b'<!-- CR012-VM -->' not in before,'Retain an existing CR012 VM recording marker')
    block=b'\n\n<!-- CR012-VM -->\nVerified CR012 preview upgrade: exact1393/36 image, CURRENT40 clone to42, original retained,64/65 independent-key off-VM restores,4GiB private scanner/memory/HTTPS proof. People/MFA/keys/queue retained. All85 full acceptances and browser/business/G2 Pending.\n<!-- /CR012-VM -->\n'
    path.write_bytes(before+block)
