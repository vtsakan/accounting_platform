"""Pure rules for the explicitly requested existing synthetic VM update."""
from copy import deepcopy
import csv
import json
import io
from pathlib import Path
import re

from r1_gate import digest_object, require

BRANCH = 'step/s31a-preview-upgrade'
REPOSITORY = 'https://github.com/vtsakan/accounting_platform.git'
BOOTSTRAP = {'gcp': {'project_id': 'accounting-514109', 'vm_name': 'accounting-preview',
                     'zone': 'europe-west1-b', 'ssh_user': 'vasilistsakanikas'}}
HOSTNAME = 'totalaccounting.duckdns.org'
OLD_CONTEXT = 'sha256:aa53c8f70d8ca11881457a7c80ee7e21684c8b4212a86fe9dbfe28ed95220ba0'
CONTEXT = 'sha256:a3dbff49144c7072f8308ab50ca96f4c9ddb36c56eb873593b216dce2111329c'
OLD_IMAGE = ('europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@'
             'sha256:08cf99dc5ab117b08db3739600e4f6486611a6c63238cb4a2b9efba141b115b1')
APP_REVISION = 'git:605c6a5534fe9ad96185b8c2e1473ce41e406834'.removeprefix('git:')
IMAGE_ID = 'sha256:6795deceab7250e41f1465e792cde0efe818d89060e134ef7588ae2df04959eb'
VERIFIED_SOURCE = 'git:39a088ab36970ebe839624b28521adaf9f72d9fb'.removeprefix('git:')
REPORT_SHA = 'sha256:6efa8da5313cd4c8aa46dfd6ce96b110dabe0d81559de199e6ccfea478b548e3'
REDIS = ('redis:8.2.11-bookworm@'
         'sha256:b0b01167ff47bc3868e56a967895a26be4230891a1f42a78ab61cdd227accc8d')
RECEIPT = 'docs/implementation/evidence/S31-verification.json'
RECORDED = (RECEIPT, 'docs/implementation/state.md', 'docs/implementation/steps.csv',
            'docs/implementation/traceability.csv')
LINEAGE = ('docs/implementation/evidence/S31-operator-receipts.json',
           'docs/implementation/evidence/S31-historical-evidence.json',
           'docs/implementation/evidence/S31-initial-failure.json',
           'docs/implementation/evidence/S31-profile-lineage.json')


def verified_report(report):
    require(digest_object(report) == REPORT_SHA, 'The actual operator S31 workers4 receipt differs; no replacement or rebind')
    require(report['technical_status'] == 'Verified' and report['release_decision'] == 'Blocked'
            and report['workload_profile'] == 'workers4'
            and report['image']['image_id'] == IMAGE_ID
            and report['image']['revision'] == 'git:' + APP_REVISION
            and report['application_context_digest'] == CONTEXT,
            'Retain the exact successful S31 image and operator receipt')
    return report


def target_identity(source):
    require(source['hostname'] == HOSTNAME
            and all(source['gcp'].get(key) == value for key, value in BOOTSTRAP['gcp'].items())
            and source['gcp']['data_uuid'] == '22415b2c-1e1b-4e39-9ce5-5fb0c19dd663',
            'Only the existing selected preview VM and retained disk are supported')


def transition(source, target):
    target_identity(source); target_identity(target)
    changed = {'published', 'deployment_commit', 'db_name'}
    require({k: v for k, v in source.items() if k not in changed}
            == {k: v for k, v in target.items() if k not in changed},
            'Existing cloud, domain, accounts, database role and pinned secrets must stay equal')
    require(source['published']['image'] == OLD_IMAGE and source['published']['context_digest'] == OLD_CONTEXT,
            'The VM must still have the observed S24A release; inspect a different source separately')
    require(target['published']['context_digest'] == CONTEXT
            and target['published']['image_id'] == IMAGE_ID
            and target['published']['commit'] == APP_REVISION, 'Unverified target image')
    require(re.fullmatch(r'accounting_s31_[0-9a-f]{12}', target['db_name']) is not None
            and target['db_name'] != source['db_name'], 'Use a distinct new S31 clone; never overwrite a database')


def before_public(state):
    require(state.get('public_cutover_started') is False,
            'New writes may exist: automatic database rollback is refused; keep the current clone and backups')


def same_capacity(memory_kib, available_kib, disk_free, database_bytes):
    require(memory_kib >= 3_500_000 and available_kib >= 1_000_000,
            'The existing VM lacks free memory for the bounded services; no machine resize was attempted')
    require(disk_free >= max(2 * 1024**3, 3 * database_bytes),
            'Insufficient retained-disk space for the untouched original, clone and pulled image')


def unchanged_acceptances(root):
    with (Path(root) / 'docs/implementation/traceability.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == 85 and all(row['acceptance_status'] == 'Pending' for row in rows),
            'Preview deployment cannot approve full requirements or a real first office')
    return rows


def rebound_operations(original, target):
    # S10 keeps its original proven code, owners, recipient, retention and units.
    result = deepcopy(original); result['preview'] = deepcopy(target)
    return result


def ready_for_activation(state, restored):
    require(state['phase'] == 'awaiting_off_vm_restore' and not state['public_cutover_started'],
            'This attempt is not awaiting its exact recovery proofs')
    require(set(restored) == {'before', 'after'}, 'Restore both frozen source and migrated clone off the VM')
    for key, receipt in (('before', state['before_backup']), ('after', state['after_backup'])):
        value = restored[key]
        require(value['status'] == 'Restored' and value['all_public_tables_match'] is True
                and value['separate_recovery_key_used'] is True
                and value['receipt'] == receipt and value['plaintext_removed'] is True
                and value['recovery_container_removed'] is True
                and value['preview_database_modified'] is False,
                'An exact encrypted off-VM restore attestation is missing')


def track(root, status, source, *, receipt=None):
    require(status in ('Prepared', 'Verified') and re.fullmatch(r'git:[0-9a-f]{40}', source), 'Concrete preview source/status required')
    root = Path(root); docs = root / 'docs/implementation'
    before_trace = (docs / 'traceability.csv').read_bytes()
    unchanged_acceptances(root)
    block = ('<!-- S31A-PREVIEW -->\n## Current preview update — S31A\n\n'
             'Existing synthetic VM update: **' + status + '**. Application source remains the exact S30 image; '
             'the operator S31 workers4 gate passed 848/36. Source/history goes to GitHub by ordinary fast-forward only. '
             'The selected VM retains its original database and migrates a separate clone 20→26; '
             'both encrypted snapshots must restore off-VM before activation. Four web workers, one worker process and '
             'one scheduler are bounded preview settings, not an accepted shared-CPU workload. '
             'Accounts/MFA, pinned keys, disk, certificate data and backup policy are retained. '
             'Browser login/MFA and real R1/D05/D06/D07/G2/full acceptance remain Pending. '
             'See [the update procedure](s31a_preview_upgrade_el.md).\n<!-- /S31A-PREVIEW -->')
    path = docs / 'state.md'; text = path.read_text()
    if '<!-- S31A-PREVIEW -->' in text:
        text = re.sub(r'<!-- S31A-PREVIEW -->.*?<!-- /S31A-PREVIEW -->', lambda _: block, text, flags=re.S)
    else:
        text = text.replace('# Implementation state\n', '# Implementation state\n\n' + block + '\n', 1)
    path.write_text(text)
    path = docs / 'steps.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    original = [dict(row) for row in rows if row['step_id'] != 'S31A']
    require(sum(r['step_id'] == 'S31A' for r in rows) <= 1, 'Duplicate S31A tracking row')
    row = {key: '' for key in rows[0]}
    row.update(step_id='S31A', stage='P4', title='Update the existing synthetic preview and GitHub',
               dependencies='S31 S24A', status=status, branch=BRANCH,
               code_reference_commit=source.removeprefix('git:'),
               requirements='QR-01 QR-02 QR-03 QR-04 QR-09 QR-12 UR-LOC-01',
               evidence='docs/implementation/evidence/S31A-source.json; docs/implementation/s31a_preview_upgrade_el.md',
               manual_acceptance='Existing browser login/MFA; no real-client R1/G2 acceptance inferred',
               blocker='Operator preview deployment Pending' if status == 'Prepared' else 'Preview only; real R1/D05/D06/D07/G2 remain Pending',
               next_step='Named R1 acceptance; S32 independent source work when selected')
    if receipt:
        row['evidence'] += '; ' + receipt
    rows = [r for r in rows if r['step_id'] != 'S31A']
    position = next(i for i, r in enumerate(rows) if r['step_id'] == 'S31') + 1
    rows.insert(position, row)
    require([r for r in rows if r['step_id'] != 'S31A'] == original, 'An existing step row changed')
    output = io.StringIO(newline=''); writer = csv.DictWriter(output, fieldnames=rows[0], lineterminator='\n')
    writer.writeheader(); writer.writerows(rows); path.write_text(output.getvalue())
    require((docs / 'traceability.csv').read_bytes() == before_trace, 'Full acceptance tracking changed')
