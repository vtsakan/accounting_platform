"""Pinned rules for updating the existing preview after the actual1020-test gate."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import re

from r1_gate import digest_bytes, digest_object, require

BRANCH = 'release/cr005-preview-upgrade'
REPOSITORY = 'https://github.com/vtsakan/accounting_platform.git'
BOOTSTRAP = {'gcp': {'project_id': 'accounting-514109', 'vm_name': 'accounting-preview',
    'zone': 'europe-west1-b', 'ssh_user': 'vasilistsakanikas'}}
HOSTNAME = 'totalaccounting.duckdns.org'
OLD_CONTEXT = 'sha256:b72e10ff53dcc5613beba5f0126f8bddede58860b023e051f48c4ba7a86322a9'
OLD_IMAGE = ('europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@'
    'sha256:30597a05f45393d8d66ccc0f3924a2bdc38b007fab5c9f1755e22dfd652426a1')
OLD_APP_REVISION = 'edacf958f5dc427575b45725502b9048d2ca41bf'  # pragma: allowlist secret -- actual CR004 application revision
CONTEXT = 'sha256:5e2e455524a8a27e870f16bcb71b88918153d083b39d45e1f68bfea13442e684'
APP_REVISION = '7b5fcb0047cc48488721be63db73e96a8b7674b3'  # pragma: allowlist secret -- actual CR005 operator revision
VERIFIED_SOURCE = APP_REVISION
IMAGE_ID = 'sha256:3c8191b7d180ba7bcb238975074bb880cefdb69bc989c2f320ad7f2e62351f6e'
REPORT_SHA = 'sha256:b2295bb739b00796799016aa26d9ba1180a4aaf9e471de68aaa31fe51adc0896'
REDIS = ('redis:8.2.11-bookworm@'
    'sha256:b0b01167ff47bc3868e56a967895a26be4230891a1f42a78ab61cdd227accc8d')
RECEIPT = 'docs/implementation/evidence/CR005-verification.json'
RECORDED = (RECEIPT, 'docs/implementation/state.md')
BASELINE = 'docs/implementation/evidence/CR005-VM-operator-baseline.json'
from cr005_receipts import EXPECTED as PRIOR_RECEIPTS, BINDING as PRIOR_BINDING
RETAINED_REPORTS = (RECEIPT, *PRIOR_RECEIPTS, PRIOR_BINDING)
QUEUE_CODE = ('compose.production.yml', 'compose.preview-s31.yml', 'compose.preview-s31-hold.yml',
    'accounting/job_models.py', 'accounting/job_services.py',
    'accounting/fee_generation_models.py', 'accounting/fee_generation_services.py',
    'accounting/tasks.py', 'core/celery.py', 'core/job_scheduler.py')


def verified_report(report):
    require(isinstance(report, dict) and digest_object(report) == REPORT_SHA,
        'The actual successful CR005 receipt differs; no replacement or rebind is accepted')
    suite = report['suite']
    require(report['change'] == 'CR-005' and report['status'] == 'Verified'
        and report['source_commit'] == 'git:' + APP_REVISION
        and report['image']['image_id'] == IMAGE_ID and report['image']['revision'] == 'git:' + APP_REVISION
        and report['application_context_digest'] == CONTEXT
        and report['image']['context']['file_count'] == 317
        and suite['tests_run'] == suite['tests_passed'] == 1020
        and len(suite['cases']) == 36 and all(c['outcome'] == 'passed' for c in suite['cases'])
        and report['real_monthly_worker_and_commit_before_ack'] is True,
        'Retain the exact1020/36 and real-worker verified CR005 image')
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
        'The installed preview differs from the observed current CR004 release; no rewind is permitted')
    require(target['published']['context_digest'] == CONTEXT
        and target['published']['image_id'] == IMAGE_ID
        and target['published']['commit'] == APP_REVISION, 'Unverified CR005 target image')
    require(re.fullmatch(r'accounting_cr005_[0-9a-f]{12}', target['db_name']) is not None
        and target['db_name'] != source['db_name'], 'Use a new distinct clone of the CURRENT database')


def unchanged_acceptances(root):
    with (Path(root)/'docs/implementation/traceability.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 85 and all(row['acceptance_status'] == 'Pending' for row in rows),
        'A preview update cannot approve full requirements or real-client release')
    return rows


def recorded_state(original):
    body = ('\nCR-005 source Prepared; operator technical gate Verified: '
        '1020 tests, 36 financial cases, archive/open-contract/owner-deletion contracts and retained real monthly-worker/ack-loss gate passed. '
        'VM/GitHub rollout and accountant/browser acceptance remain Pending. All 85 full acceptances remain Pending.\n')
    updated, count = re.subn(r'(?s)(<!-- CR005-RESULT -->).*?(<!-- /CR005-RESULT -->)',
        lambda match:match.group(1)+body+match.group(2), original, count=1)
    require(count == 1, 'Missing CR005 result marker')
    return updated


def prior_files(root, report):
    from cr005_receipts import verify_binding
    previous = verify_binding(root)
    require(report['actual_prior_receipt_files_sha256'] == previous['files']
        and all(digest_bytes((Path(root)/name).read_bytes()) == value
                for name, value in previous['files'].items()),
        'The actual prior receipts no longer match the successful CR005 report')


def bind_reports(root):
    root = Path(root)
    require(all((root/name).is_file() and not (root/name).is_symlink()
        and (root/name).stat().st_size <= 2_000_000 for name in RETAINED_REPORTS),
        'Retain regular actual report files; symlinks or oversized files are not accepted')
    report = verified_report(json.loads((root/RECEIPT).read_text()))
    prior_files(root, report)
    value = {'scope':'existing-preview-cr005', 'operator_source':'git:'+APP_REVISION,
        'operator_report_canonical_sha256':REPORT_SHA,
        'files':{name:digest_bytes((root/name).read_bytes()) for name in RETAINED_REPORTS}}
    path = root/BASELINE
    if path.exists() or path.is_symlink():
        require(not path.is_symlink() and json.loads(path.read_text()) == value,
            'Existing CR005 deployment receipt binding differs; it was not refreshed')
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
    require(value.get('scope') == 'existing-preview-cr005' and value.get('operator_source') == 'git:'+APP_REVISION
        and value.get('operator_report_canonical_sha256') == REPORT_SHA
        and value.get('files') == {name:digest_bytes((root/name).read_bytes()) for name in RETAINED_REPORTS},
        'Bound actual CR002/003/004 reports changed; no recapture during publication')
    report = verified_report(json.loads((root/RECEIPT).read_text()))
    prior_files(root, report)
    return report


def before_public(state):
    require(state.get('public_cutover_started') is False,
        'Jobs or new HTTP writes may exist; automatic rollback to the old database is refused')


def same_capacity(memory_kib, available_kib, disk_free, database_bytes):
    require(memory_kib >= 3_500_000 and available_kib >= 1_000_000,
        'Insufficient free memory on the existing bounded VM; no resize was attempted')
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


def track(root, status, source, *, receipt=None):
    require(status in ('Prepared','Verified') and re.fullmatch(r'git:[0-9a-f]{40}',source), 'Concrete source/status required')
    root = Path(root); unchanged_acceptances(root)
    block = ('<!-- CR005-PREVIEW -->\n## Existing preview update — CR005\n\n'
        'Status: **'+status+'**. Reuse the actual1020/36 and real-worker verified image. '
        'Retain the CURRENT database and migrate a separate28→30 clone, preserving every original row, '
        'account, MFA seed, session, pinned key and existing durable queue. Both encrypted snapshots '
        'must restore off-VM before activation. GitHub publication uses ordinary fast-forward only. '
        'Human browser/MFA acceptance and real R1/D05/D06/D07/G2/full acceptance remain Pending. '
        'See [the procedure](cr005_preview_upgrade_el.md).\n<!-- /CR005-PREVIEW -->')
    path = root/'docs/implementation/state.md'; text = path.read_text()
    if '<!-- CR005-PREVIEW -->' in text:
        text = re.sub(r'<!-- CR005-PREVIEW -->.*?<!-- /CR005-PREVIEW -->',lambda _:block,text,flags=re.S)
    else:
        text = text.replace('# Implementation state\n','# Implementation state\n\n'+block+'\n',1)
    path.write_text(text)
