"""Exact CR010/0111307 gate, real native history and CURRENT36→40 clone policy."""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

import cr011_receipts as receipts
import preview_cr008_policy as foundation
import preview_cr009_policy as previous
from r1_gate import digest_bytes,digest_object,require

PROFILE='cr011-current36-to40-clone-4GiB-uploads'
BRANCH='release/cr011-preview-upgrade'
REPOSITORY=foundation.REPOSITORY
BOOTSTRAP=foundation.BOOTSTRAP
APP_REVISION='4fb2f5d454e6f96630c1e2960c5aa65243543eed'  # pragma: allowlist secret -- actual public1307-test source from operator
CONTEXT='sha256:0bbecb9086d84220a89a8b2bbe0c4d3582a852a5e3a1f148ccc82580e887b9aa'
IMAGE_ID='sha256:063fca90a92e757eb2141103991aa2e7e47ee8df8727d4dd719a45705f877186'
REPORT_SHA='sha256:faa2cc0cdb2ccfd62848c65df9632d1013ef74a253e47035f632ef00ebede959'
RECEIPT='docs/implementation/evidence/CR011-verification.json'
BASELINE='docs/implementation/evidence/CR011-VM-operator-baseline.json'
VM_RECORD='9dc666bf75aa597747ecd040da1e18fe32273675'  # pragma: allowlist secret -- independently read current GitHub main
VM_DEPLOYMENT='fe765f93d19ad8260b2f65c7f7f498ea329645da'  # pragma: allowlist secret -- actual completed CR009 deployment
OLD_APP=previous.APP_REVISION
OLD_CONTEXT=previous.CONTEXT
OLD_IMAGE_ID=previous.IMAGE_ID
OLD_IMAGE='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:6fa9439bf093f6efdeb2515b18ddcc404b98ebca0a30a71d96b02c26dbc301f8'
PRIOR_STATES=(*previous.PRIOR_STATES,Path('/etc/accounting/cr009-preview-state.json'))
PRIOR_HOLDS=(*previous.PRIOR_HOLDS,Path('/etc/accounting/cr009-preview-in-progress'))
NEW_TABLES=frozenset({'accounting_agreementcreationreceipt','accounting_counterpartyimport','accounting_staffcredentialrequirement'})


def operator_report(value):
    require(digest_object(value)==REPORT_SHA and value['change']=='CR-011' and value['status']=='Verified'
        and value['source_commit']=='git:'+APP_REVISION,'The genuine complete1307-test CR011 report is required')
    suite=value['suite'];files=value['private_files'];selected=value['image']
    require(suite['tests_run']==suite['tests_passed']==1307 and len(suite['cases'])==36
        and all(c['outcome']=='passed' for c in suite['cases'])
        and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
        and selected['image_id']==IMAGE_ID and selected['revision']=='git:'+APP_REVISION
        and selected['verification_revision']=='git:'+APP_REVISION and selected['context']['file_count']==400
        and selected['context']['digest']==CONTEXT and value['deployment_guard_tests_passed']==140,
        'Retain the actual1307/36/140 and exact400-input immutable image')
    require(all(value[k] is True for k in ('real_monthly_worker_and_commit_before_ack','revocation_blocks_execution',
        'second_scheduler_rejected','restricted_role_migrations','historical_receipts_unchanged','owned_resources_removed'))
        and value['secret_scan']['unreviewed_findings']==0 and files['all_public_tables_restored']==64
        and files['restored_files']==10 and files['staff_credentials_recovered'] is True
        and files['excel_recovery_verified'] is True and all(files['staff_credentials'].values()) and all(files['excel_import'].values())
        and all(files[k] is True for k in ('antivirus_real_eicar_denied','scanner_unavailable_denied_without_storage',
            'all_public_tables_and_file_hashes_matched','separate_external_recovery_material_used')),
        'Actual credentials, antivirus, sealed Excel/files,64-table recovery and worker proof are required')
    return value


def native_reports(root):
    root=Path(root);old=receipts.verify_binding(root);report=operator_report(json.loads((root/RECEIPT).read_text()))
    require(report['actual_prior_receipt_files_sha256']==old['files'],'The actual27 prior files differ from the CR011 success')
    record=subprocess.check_output(['git','rev-parse','--verify','81da3bc^{commit}'],cwd=root,text=True).strip()
    require(subprocess.check_output(['git','rev-list','--parents','-n','1',record],cwd=root,text=True).split()==[record,APP_REVISION],
        'Resolve the real81da3bc native child; never reconstruct an agent-side result commit')
    changed=set(subprocess.check_output(['git','diff-tree','--no-commit-id','--name-only','-r',record],cwd=root,text=True).splitlines())
    require(changed=={RECEIPT,'docs/implementation/state.md'} and subprocess.run(
        ['git','merge-base','--is-ancestor',record,'HEAD'],cwd=root,capture_output=True).returncode==0,
        'Retain the genuine two-file successful result in native Git history')
    require(subprocess.check_output(['git','show',record+':'+RECEIPT],cwd=root)==(root/RECEIPT).read_bytes(),
        'The real successful CR011 receipt changed after recording')
    paths=(*old['files'],receipts.BASELINE,RECEIPT);require(len(set(paths))==29,'Retain all29 real prior files')
    require(all((root/n).is_file() and not (root/n).is_symlink() for n in paths),'Retain regular genuine history files')
    return {'scope':PROFILE,'binding_schema':1,'native_source':'git:'+APP_REVISION,'native_result_commit':'git:'+record,
        'canonical_report_sha256':REPORT_SHA,'previous_vm_record':'git:'+VM_RECORD,
        'preserved_operator_files':old['preserved_operator_files'],
        'files':{name:digest_bytes((root/name).read_bytes()) for name in paths}}


def bind(root):
    root=Path(root);actual=native_reports(root);path=root/BASELINE
    if path.exists() or path.is_symlink():return verify(root)
    with path.open('x') as stream:stream.write(json.dumps(actual,ensure_ascii=False,indent=2)+'\n')
    return actual


def verify(root):
    root=Path(root);actual=native_reports(root);path=root/BASELINE
    require(path.is_file() and not path.is_symlink() and json.loads(path.read_text())==actual,
        'The exclusive29-file deployment binding differs; it was not refreshed')
    return actual


def transition(source,target):
    foundation.target_identity(source);foundation.target_identity(target)
    changed={'published','deployment_commit','db_name'}
    require({k:v for k,v in source.items() if k not in changed}=={k:v for k,v in target.items() if k not in changed},
        'Preserve VM/disks/hostname/roles/pinned keys and all other configuration')
    require(source['deployment_commit']==VM_DEPLOYMENT and source['published']['image']==OLD_IMAGE
        and source['published']['commit']==OLD_APP and source['published']['context_digest']==OLD_CONTEXT
        and source['published']['image_id']==OLD_IMAGE_ID
        and re.fullmatch(r'accounting_cr008_[0-9a-f]{12}',source['db_name']) is not None,
        'Require the CURRENT completed CR009/schema36 database; never a retained older database')
    require(re.fullmatch(r'accounting_cr011_[0-9a-f]{12}',target['db_name']) is not None
        and target['db_name']!=source['db_name'],'Use a new distinct clone of the CURRENT source')
    current=source['published']
    require(source['deployment_commit']==VM_DEPLOYMENT and current['commit']==OLD_APP
        and current['context_digest']==OLD_CONTEXT and current['image_id']==OLD_IMAGE_ID and current['image']==OLD_IMAGE
        and re.fullmatch(r'accounting_cr008_[0-9a-f]{12}',source['db_name']) is not None,
        'The source must be the actual completed CR009 CURRENT36 database and immutable image')
    published=target['published'];prefix='europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:'
    require(published['commit']==APP_REVISION and published['image_id']==IMAGE_ID and published['context_digest']==CONTEXT
        and published['delivery_evidence']==REPORT_SHA and re.fullmatch(re.escape(prefix)+r'[0-9a-f]{64}',published['image']) is not None
        and re.fullmatch(r'[0-9a-f]{40}',target.get('deployment_commit','')) is not None,
        'Select only the exact verified CR011 image and a full deployment revision')


def completed_journal(value,source):
    require(value.get('phase')=='profile_verified' and value.get('public_cutover_started') is True
        and value.get('target')==source and value.get('runtime',{}).get('attachment_uploads_enabled') is True,
        'The retained CR009 journal must prove the installed completed source')
    previous.transition(value['source'],value['target'])
    require(set(value.get('off_vm_restored',{}))=={'before','after'},'Retain both actual CR009 restore proofs')
    for label in ('before','after'):
        proof=value['off_vm_restored'][label]
        require(proof['receipt']==value[label+'_backup'] and proof['status']=='Restored' and proof['tables_checked']==61
            and proof['all_public_tables_match'] is True and proof['separate_recovery_key_used'] is True,
            'The actual preceding61-table recovery differs')


def recovery_proofs(state,restored):
    require(set(restored)=={'before','after'},'Restore both encrypted snapshots off this VM')
    for label,count in (('before',61),('after',64)):
        proof=restored[label]
        require(proof['tables_checked']==count and proof['status']=='Restored'
            and proof['receipt']==state[label+'_backup'] and proof['all_public_tables_match'] is True
            and proof['separate_recovery_key_used'] is True and proof['plaintext_removed'] is True
            and proof['recovery_container_removed'] is True and proof['preview_database_modified'] is False,
            'Require the exact independent-key source61/target64 encrypted restore proofs')
    require(state['migration']['source_migrations']==36 and state['migration']['target_migrations']==40
        and state['migration']['old_tables_checked']==61
        and state['migration']['new_business_tables_empty'] is True
        and state['migration']['restricted_role_migrations'] is True
        and state['migration']['original_columns_rows_passwords_mfa_sessions_preserved'] is True
        and state['migration']['original_database_migrated'] is False,'Require the real restricted36→40 clone migration')


def ready(state,restored):
    foundation.ready_for_activation(state,restored)
    recovery_proofs(state,restored)


def before_public(state):
    foundation.before_public(state)


def rebound_operations(original,target):
    return foundation.rebound_operations(original,target)


def track(root,report):
    foundation.unchanged_acceptances(root);path=Path(root)/'docs/implementation/state.md';before=path.read_bytes()
    require(b'<!-- CR011-VM -->' not in before,'Retain an existing CR011 VM recording marker')
    block=b'\n\n<!-- CR011-VM -->\nVerified CR010/011 preview upgrade: exact1307/36/140 image, CURRENT36 clone to40, original retained,61/64 independent-key off-VM restores,4GiB private scanner/memory/HTTPS proof. People/MFA/keys/queue retained. All85 full acceptances and browser/business/G2 Pending.\n<!-- /CR011-VM -->\n'
    path.write_bytes(before+block)
