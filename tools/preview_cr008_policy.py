"""Pinned existing4GiB preview upgrade after complete actual1186/36/files/worker proof."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import re
import subprocess

from r1_gate import digest_bytes, digest_object, require

BRANCH = 'release/cr008-preview-upgrade'
REPOSITORY = 'https://github.com/vtsakan/accounting_platform.git'
BOOTSTRAP = {'gcp': {'project_id': 'accounting-514109', 'vm_name': 'accounting-preview',
    'zone': 'europe-west1-b', 'ssh_user': 'vasilistsakanikas'}}
HOSTNAME = 'totalaccounting.duckdns.org'
OLD_CONTEXT = 'sha256:5e2e455524a8a27e870f16bcb71b88918153d083b39d45e1f68bfea13442e684'
OLD_IMAGE = ('europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@'
    'sha256:335827d3ce5b075f772fea1036e414e48a45ec235aecf57370df4967501dca85')
OLD_APP_REVISION = '7b5fcb0047cc48488721be63db73e96a8b7674b3'  # pragma: allowlist secret -- observed CR005 image revision
CONTEXT = 'sha256:9a530ae7855d8e5436dfbaf2a53c58591f62ff644fe2266e526948cf1d073248'
APP_REVISION = 'b493521e711f340f45aac16535e5935df52cce3b'  # pragma: allowlist secret -- actual1186-test image revision
VERIFIED_SOURCE = 'e7a02974d019d1b611a48c7c7c62b2d9b938e820'  # pragma: allowlist secret -- actual complete CR008 operator gate
IMAGE_ID = 'sha256:91ef03bf9cbd4cdc1e684a13a709095a0e0dac2af957b72558da14302d0cfdb0'
REPORT_SHA = 'sha256:51e01b03eafb309c4a525a35e0e84d453b0fc80ba706639837f4b5cb10c6ea75'
REDIS = ('redis:8.2.11-bookworm@'
    'sha256:b0b01167ff47bc3868e56a967895a26be4230891a1f42a78ab61cdd227accc8d')
RECEIPT = 'docs/implementation/evidence/CR008-verification.json'
RECORDED = (RECEIPT, 'docs/implementation/state.md')
BASELINE = 'docs/implementation/evidence/CR008-VM-operator-baseline.json'
from cr008_receipts import PATHS as PRIOR_RECEIPTS, BINDING as PRIOR_BINDING
RETAINED_REPORTS = (RECEIPT, *PRIOR_RECEIPTS, PRIOR_BINDING)
UPLOADS_ENABLED = False  # Explicit product-owner choice: retain4GiB, no scanner or resize.
QUEUE_CODE = ('compose.production.yml', 'compose.preview-s31.yml', 'compose.preview-s31-hold.yml',
    'accounting/job_models.py', 'accounting/job_services.py',
    'accounting/fee_generation_models.py', 'accounting/fee_generation_services.py',
    'accounting/tasks.py', 'core/celery.py', 'core/job_scheduler.py')


def verified_report(report):
    require(isinstance(report,dict) and digest_object(report)==REPORT_SHA,
        'The actual complete CR008 operator receipt differs; no replacement or rebind is accepted')
    suite=report['suite'];files=report['private_files'];selected=report['image']
    require(report['change']=='CR-008' and report['status']=='Verified'
        and report['source_commit']=='git:'+VERIFIED_SOURCE
        and selected['image_id']==IMAGE_ID and selected['revision']=='git:'+APP_REVISION
        and selected['verification_revision']=='git:'+VERIFIED_SOURCE
        and report['application_context_digest']==CONTEXT and selected['context']['file_count']==371
        and suite['tests_run']==suite['tests_passed']==1186
        and len(suite['cases'])==36 and all(c['outcome']=='passed' for c in suite['cases'])
        and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips')),
        'Retain the exact1186/36 complete CR008 result and identical immutable image')
    require(all(report[k] is True for k in ('real_monthly_worker_and_commit_before_ack','revocation_blocks_execution',
        'second_scheduler_rejected','restricted_role_migrations','historical_receipts_unchanged','owned_resources_removed',
        'docker_execution_by_operator')) and report['secret_scan']['unreviewed_findings']==0,
        'The complete actual CR008 worker/source gate is required')
    require(all(files[k] is True for k in ('original_file_sha256_after_authenticated_download','antivirus_real_eicar_denied',
        'scanner_unavailable_denied_without_storage','restricted_role_migrations','sealed_bytes_in_database',
        'all_public_tables_and_file_hashes_matched','wrong_recovery_key_denied','separate_external_recovery_material_used',
        'owned_resources_removed')) and files['restored_files']==10 and files['all_public_tables_restored']==61
        and set(files['formats_verified'])=={'pdf','doc','docx','png','jpg','gif','webp','tif','bmp'},
        'Retain the actual real antivirus and encrypted file recovery proof')
    require(all(report[k] is False for k in ('agent_native_execution','local_demo_or_vm_changed','github_updated','human_accounts_or_mfa_changed')),
        'The historical isolated operator scope differs')
    return report


def target_identity(config):
    require(config['hostname'] == HOSTNAME
        and all(config['gcp'].get(key) == value for key, value in BOOTSTRAP['gcp'].items())
        and config['gcp']['data_uuid'] == '22415b2c-1e1b-4e39-9ce5-5fb0c19dd663',
        'Only the existing selected preview VM and retained data disk are supported')


def transition(source, target):
    target_identity(source); target_identity(target)
    changed = {'published', 'deployment_commit', 'db_name'}
    require({k:v for k,v in source.items() if k not in changed}
        == {k:v for k,v in target.items() if k not in changed},
        'Retain cloud identity, database role, hostname and pinned material')
    require(source['published']['image'] == OLD_IMAGE
        and source['published']['context_digest'] == OLD_CONTEXT
        and source['published']['commit'] == OLD_APP_REVISION,
        'The installed preview differs from the observed current CR005 release; no rewind is permitted')
    require(target['published']['context_digest'] == CONTEXT
        and target['published']['image_id'] == IMAGE_ID
        and target['published']['commit'] == APP_REVISION, 'Unverified CR008 target image')
    require(re.fullmatch(r'accounting_cr008_[0-9a-f]{12}', target['db_name']) is not None
        and target['db_name'] != source['db_name'], 'Use a new distinct clone of the CURRENT database')


def unchanged_acceptances(root):
    with (Path(root)/'docs/implementation/traceability.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 85 and all(row['acceptance_status'] == 'Pending' for row in rows),
        'A preview update cannot approve full requirements or real-client release')
    return rows


def native_result_commit(root):
    root=Path(root);candidates=[]
    rows=subprocess.check_output(['git','rev-list','--parents','HEAD'],cwd=root,text=True).splitlines()
    for row in rows:
        fields=row.split()
        if fields[1:]!=[VERIFIED_SOURCE]:continue
        names=set(subprocess.check_output(['git','diff','--name-only',VERIFIED_SOURCE,fields[0]],cwd=root,text=True).splitlines())
        if names==set(RECORDED):candidates.append(fields[0])
    require(len(candidates)==1,'Retain the actual child commit of e7a02974 that recorded only the two successful CR008 outputs')
    commit=candidates[0]
    require(subprocess.check_output(['git','show',commit+':'+RECEIPT],cwd=root)==(root/RECEIPT).read_bytes(),
        'The real CR008 receipt changed after its actual result commit')
    return commit


def prior_files(root, report):
    from cr008_receipts import verify_binding
    previous = verify_binding(root)
    native_result_commit(root)
    require(report['actual_prior_receipt_files_sha256'] == previous['files']
        and all(digest_bytes((Path(root)/name).read_bytes()) == value
                for name, value in previous['files'].items()),
        'The actual prior receipts no longer match the successful CR008 report')


def bind_reports(root):
    root = Path(root)
    require(all((root/name).is_file() and not (root/name).is_symlink()
        and (root/name).stat().st_size <= 2_000_000 for name in RETAINED_REPORTS),
        'Retain regular actual report files; symlinks or oversized files are not accepted')
    report = verified_report(json.loads((root/RECEIPT).read_text()))
    prior_files(root, report)
    value = {'scope':'existing-preview-cr008', 'operator_source':'git:'+VERIFIED_SOURCE,
        'operator_report_canonical_sha256':REPORT_SHA,
        'files':{name:digest_bytes((root/name).read_bytes()) for name in RETAINED_REPORTS}}
    path = root/BASELINE
    if path.exists() or path.is_symlink():
        require(not path.is_symlink() and json.loads(path.read_text()) == value,
            'Existing CR008 deployment receipt binding differs; it was not refreshed')
        return value
    with path.open('x') as stream:
        stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


def verify_reports(root):
    root = Path(root); path = root/BASELINE
    require(all((root/name).is_file() and not (root/name).is_symlink()
        and (root/name).stat().st_size <= 2_000_000 for name in RETAINED_REPORTS),
        'A bound actual report is missing or no longer a regular file')
    require(path.is_file() and not path.is_symlink(), 'Run the Git/files-only preview installer to bind actual receipts')
    value = json.loads(path.read_text())
    require(value.get('scope') == 'existing-preview-cr008' and value.get('operator_source') == 'git:'+VERIFIED_SOURCE
        and value.get('operator_report_canonical_sha256') == REPORT_SHA
        and value.get('files') == {name:digest_bytes((root/name).read_bytes()) for name in RETAINED_REPORTS},
        'Bound actual16 prior/report files changed; no recapture during publication')
    report = verified_report(json.loads((root/RECEIPT).read_text()))
    prior_files(root, report)
    return report


def before_public(state):
    require(state.get('public_cutover_started') is False,
        'Jobs or new HTTP writes may exist; automatic rollback to the old database is refused')


def same_capacity(memory_kib, available_kib, disk_free, database_bytes):
    require(3_500_000 <= memory_kib < 4_500_000 and available_kib >= 1_000_000,
        'Expected the retained4GiB VM with sufficient free memory; no resize was attempted')
    require(disk_free >= max(2*1024**3, 3*database_bytes),
        'Insufficient retained-disk space for the current database, new clone and image')


def rebound_operations(original, target):
    result = deepcopy(original); result['preview'] = deepcopy(target)
    return result


def ready_for_activation(state, restored):
    require(state['phase'] == 'awaiting_off_vm_restore' and not state['public_cutover_started'],
        'This exact attempt is not awaiting both restore proofs')
    require(set(restored) == {'before','after'}, 'Restore both encrypted snapshots off this VM')
    for key,receipt in (('before',state['before_backup']),('after',state['after_backup'])):
        value = restored[key]
        require(value['status'] == 'Restored' and value['all_public_tables_match'] is True
            and value['separate_recovery_key_used'] is True and value['receipt'] == receipt
            and value['plaintext_removed'] is True and value['recovery_container_removed'] is True
            and value['preview_database_modified'] is False, 'Exact encrypted off-VM recovery proof is incomplete')


def track(root,status,source,*,receipt=None):
    require(status in ('Prepared','Verified') and re.fullmatch(r'git:[0-9a-f]{40}',source),'Concrete source/status required')
    root=Path(root);unchanged_acceptances(root)
    block=('<!-- CR008-PREVIEW -->\n## Existing preview update — CR008\n\n'
        'Status: **'+status+'**. Reuse the actual1186/36 plus antivirus/file-recovery/worker verified image. '
        'Clone the CURRENT30-migration database and migrate only the clone to36, preserving all original data, '
        'people, MFA, sessions, pinned keys and durable queue. Both encrypted backups must restore off-VM before activation. '
        'Explicit user choice: keep the same4GiB VM, no resize or scanner; new attachment uploads disabled, '
        'task and fiscal/profile functions enabled. GitHub publication is ordinary fast-forward only. '
        'Browser/MFA acceptance, real-client release and all85 full acceptances remain Pending. '
        'See [the procedure](cr008_preview_upgrade_el.md).\n<!-- /CR008-PREVIEW -->')
    path=root/'docs/implementation/state.md';text=path.read_text()
    if '<!-- CR008-PREVIEW -->' in text:
        text=re.sub(r'<!-- CR008-PREVIEW -->.*?<!-- /CR008-PREVIEW -->',lambda _:block,text,flags=re.S)
    else:text=text.replace('# Implementation state\n','# Implementation state\n\n'+block+'\n',1)
    path.write_text(text)
