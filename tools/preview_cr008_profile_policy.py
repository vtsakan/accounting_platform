"""Same-database profile change after the actual completed CR008 deployment."""
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess

import preview_cr008_policy as prior
from r1_gate import digest_bytes, digest_object, require

PROFILE = 'cr008-existing-database-4GiB-test-uploads'
BRANCH = 'release/cr008-4gb-profile'
VM_RECORD = '24b32799871d887878e06247bd1c351c16391527'  # pragma: allowlist secret -- actual public completed deployment record
VM_DEPLOYMENT = 'ab10d6fc285be6b2be69b8891123e38e9ad57202'  # pragma: allowlist secret -- actual public active deployment revision
VM_REPORT = 'docs/implementation/evidence/CR008-VM-verification.json'
VM_REPORT_SHA = 'sha256:bb3fe31f400807469bd61fe0498fc1807af65be2fc50c0b6746c080702a0dd36'
VM_IMAGE = ('europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@'
    'sha256:5e787ba92a958a8928d72e321646466ee77b5e8e9f1589f4e2a11b2d1ad995e5')
BASELINE = 'docs/implementation/evidence/CR008-4GB-operator-baseline.json'
REPORTS = (*prior.RETAINED_REPORTS, prior.BASELINE, VM_REPORT)


def completed_report(value):
    require(digest_object(value) == VM_REPORT_SHA and value['step'] == 'CR008-VM'
        and value['status'] == 'Verified' and value['deployment_commit'] == 'git:' + VM_DEPLOYMENT
        and value['image'] == VM_IMAGE and value['application_context_digest'] == prior.CONTEXT
        and value['target_migrations'] == 36 and value['off_vm_target_restore_tables'] == 61
        and value['attachment_uploads_enabled'] is False and value['vm_resized'] is False,
        'Retain the exact actual completed CR008 deployment report')
    return value


def transition(source, target):
    prior.target_identity(source); prior.target_identity(target)
    require({k:v for k,v in source.items() if k != 'deployment_commit'}
        == {k:v for k,v in target.items() if k != 'deployment_commit'},
        'A profile change may alter only its deployment revision; preserve the current database and all published/key material')
    require(source['published']['image'] == VM_IMAGE and source['published']['commit'] == prior.APP_REVISION
        and source['published']['image_id'] == prior.IMAGE_ID
        and source['published']['context_digest'] == prior.CONTEXT,
        'The active application differs from the observed completed CR008 deployment')
    require(re.fullmatch(r'accounting_cr008_[0-9a-f]{12}', source['db_name']) is not None
        and source['db_name'] == target['db_name'] and source['db_user'] == target['db_user'],
        'Retain the SAME CURRENT schema36 database; never reactivate the retained schema30 database')
    require(source.get('deployment_commit') == VM_DEPLOYMENT
        and re.fullmatch(r'[0-9a-f]{40}', target.get('deployment_commit','')) is not None,
        'Expected the exact completed source and a concrete new profile revision')


def completed_journal(value, source):
    require(value.get('phase') == 'deployed_and_restored' and value.get('public_cutover_started') is True
        and value.get('target') == source and value.get('migration',{}).get('target_migrations') == 36
        and value.get('runtime',{}).get('attachment_uploads_enabled') is False,
        'The previous actual deployment is not completed on this current database; retain its recovery state')


def native_reports(root):
    root=Path(root)
    prior.verify_reports(root)
    completed_report(json.loads((root/VM_REPORT).read_text()))
    require(subprocess.run(['git','merge-base','--is-ancestor',VM_RECORD,'HEAD'],cwd=root,
        capture_output=True).returncode==0,'Keep the real completed CR008 deployment record in native history')
    require(subprocess.check_output(['git','show',VM_RECORD+':'+VM_REPORT],cwd=root)
        == (root/VM_REPORT).read_bytes(),'The actual completed VM report changed after its published record')
    require(len(set(REPORTS))==18 and all((root/name).is_file() and not (root/name).is_symlink()
        and (root/name).stat().st_size<=2_000_000 for name in REPORTS),'Retain all18 actual report/binding files')
    return {'scope':PROFILE,'previous_completed_record':'git:'+VM_RECORD,
        'files':{name:digest_bytes((root/name).read_bytes()) for name in REPORTS}}


def bind(root):
    root=Path(root);value=native_reports(root);path=root/BASELINE
    if path.exists() or path.is_symlink():
        require(path.is_file() and not path.is_symlink() and json.loads(path.read_text())==value,
            'An existing18-file profile binding differs; it was not refreshed')
    else:
        with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


def verify(root):
    root=Path(root);value=native_reports(root);path=root/BASELINE
    require(path.is_file() and not path.is_symlink() and json.loads(path.read_text())==value,
        'Actual18-file profile binding changed; never recapture historical receipts')
    return value


def ready(state, restored):
    require(state['phase']=='awaiting_off_vm_restore' and state['public_cutover_started'] is False,
        'This exact profile attempt must await both recovery proofs')
    require(set(restored)=={'before','after'},'Restore both encrypted current-database backups off-VM')
    for label in ('before','after'):
        value=restored[label]
        require(value['receipt']==state[label+'_backup'] and value['status']=='Restored'
            and value['tables_checked']==61 and all(value[k] is True for k in
                ('all_public_tables_match','separate_recovery_key_used','plaintext_removed','recovery_container_removed'))
            and value['preview_database_modified'] is False,'Exact61-table encrypted recovery proof is incomplete')


def rollback_database(source, target):
    transition(source,target)
    return source['db_name']  # Configuration rollback always keeps the current36 database.


def track(root, status):
    require(status in ('Prepared','Verified'),'Concrete profile status required')
    prior.unchanged_acceptances(root)
    path=Path(root)/'docs/implementation/state.md'
    require(path.is_file() and not path.is_symlink(),'Retain regular native implementation tracking')
    before=path.read_bytes();start=b'<!-- CR008-4GB-PROFILE -->';end=b'<!-- /CR008-4GB-PROFILE -->'
    require(before.count(start)==before.count(end) and before.count(start)<=1,'Ambiguous profile tracking markers; no bytes changed')
    block=(start.decode()+'\nStatus: **'+status+'**. Existing CR008 schema36 database and identical image retained; '
        '4GiB test uploads use a real private bounded scanner,2GiB swap and two web workers. '
        'No clone/migration or database rewind; actual61/61-table off-VM restores and clean/EICAR/memory proof required. '
        'Previous completed CR008 evidence and all85 acceptances/browser/business gates remain unchanged.\n'+end.decode()).encode()
    if start in before:
        a=before.index(start);b=before.index(end)+len(end)
        require(a<b,'Unordered profile markers; no bytes changed')
        after=before[:a]+block+before[b:]
    else:after=before+b'\n\n'+block+b'\n'
    if after!=before:path.write_bytes(after)
    return after
