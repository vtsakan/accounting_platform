"""Exclusive real CR008 operator/VM history binding for the GSIS-only change."""
import argparse
import json
from pathlib import Path
import subprocess

import preview_cr008_policy as previous
import preview_cr008_memory_policy as current
from r1_gate import digest_bytes, digest_object, require

BASELINE = 'docs/implementation/evidence/CR009-operator-baseline.json'
VM_REPORT = 'docs/implementation/evidence/CR008-VM-verification.json'
VM_RECORD = '24b32799871d887878e06247bd1c351c16391527'  # pragma: allowlist secret -- actual published completed CR008 VM record
VM_REPORT_SHA = 'sha256:bb3fe31f400807469bd61fe0498fc1807af65be2fc50c0b6746c080702a0dd36'
CURRENT_RECORD = '3eacfdabc4c81ae4270e802b3e8171c3f67644bc'  # pragma: allowlist secret -- actual public successful4GiB record
CURRENT_DEPLOYMENT = '679ad0ac1223b64cc6b345b1093766f2d1a83063'  # pragma: allowlist secret -- actual public active4GiB deployment
CURRENT_REPORT = 'docs/implementation/evidence/CR008-4GB-MEMORY-verification.json'
CURRENT_REPORT_SHA = 'sha256:588d7ab841b24b3dedcb26ddf4c80271e78a56da80171fa40e4a3bde3ca65d08'
PATHS = (*current.REPORTS, current.BASELINE, CURRENT_REPORT)


def validate(root):
    root = Path(root).resolve()
    previous.verify_reports(root)
    current.verify(root)
    previous.unchanged_acceptances(root)
    require(len(set(PATHS)) == 21 and all((root/name).is_file() and not (root/name).is_symlink()
        and (root/name).stat().st_size <= 2_000_000 for name in PATHS), 'Retain all21 genuine prior report/binding files')
    vm = json.loads((root/VM_REPORT).read_text())
    require(digest_object(vm) == VM_REPORT_SHA and vm['status'] == 'Verified' and vm['target_migrations'] == 36,
        'Retain the actual completed CR008 VM report without replacing or reconstructing it')
    require(subprocess.run(['git','merge-base','--is-ancestor',VM_RECORD,'HEAD'],cwd=root,
        capture_output=True).returncode == 0, 'Retain the genuine published CR008 VM result in native history')
    require(subprocess.check_output(['git','show',VM_RECORD+':'+VM_REPORT],cwd=root) == (root/VM_REPORT).read_bytes(),
        'The actual VM report changed after its published record')
    live = json.loads((root/CURRENT_REPORT).read_text())
    require(digest_object(live) == CURRENT_REPORT_SHA
        and live['step'] == 'CR008-4GB-MEMORY' and live['status'] == 'Verified'
        and live['deployment_commit'] == 'git:'+CURRENT_DEPLOYMENT
        and live['application_commit'] == 'git:'+previous.APP_REVISION
        and live['application_context_digest'] == previous.CONTEXT
        and live['image'] == current.VM_IMAGE and live['schema_before'] == live['schema_after'] == 36
        and live['attachment_uploads_enabled'] is True and live['vm_resized'] is False
        and live['same_current_database'] is True and live['database_cloned'] is False
        and live['database_migrated'] is False,
        'Retain the actual successful current4GiB uploads deployment; never fall back to an earlier profile')
    require(live['runtime']['observed_memory_caps_mib']['scheduler'] == 192
        and live['runtime']['web_workers'] == 2
        and live['runtime']['python_memory_cgroups'] == {
            service:{'oom':0,'oom_kill':0,'oom_group_kill':0}
            for service in ('web','worker','scheduler','scanner')}
        and live['off_vm_source_restore_tables'] == live['off_vm_target_restore_tables'] == 61
        and live['both_off_vm_restores_matched'] is True,
        'Retain the observed memory, antivirus and recovery baseline')
    require(subprocess.run(['git','merge-base','--is-ancestor',CURRENT_RECORD,'HEAD'],cwd=root,
        capture_output=True).returncode == 0, 'Retain the actual successful3eacfda native history')
    require(subprocess.check_output(['git','show',CURRENT_RECORD+':'+CURRENT_REPORT],cwd=root)
        == (root/CURRENT_REPORT).read_bytes(), 'The current4GiB report changed after its published record')
    return {'change':'CR-009','schema':2,'previous_completed_vm_record':'git:'+CURRENT_RECORD,
        'previous_deployment_commit':'git:'+CURRENT_DEPLOYMENT,
        'current_vm_report_canonical_sha256':CURRENT_REPORT_SHA,
        'legacy_completed_vm_record':'git:'+VM_RECORD,
        'previous_application_context':previous.CONTEXT,
        'files':{name:digest_bytes((root/name).read_bytes()) for name in PATHS}}


def verify_binding(root):
    root = Path(root).resolve(); value = validate(root); path = root/BASELINE
    require(path.is_file() and not path.is_symlink() and json.loads(path.read_text()) == value,
        'The exclusive CR009 prior-report binding differs; it was not refreshed')
    return value


def bind(root):
    root = Path(root).resolve(); value = validate(root); path = root/BASELINE
    if path.exists() or path.is_symlink():
        return verify_binding(root)
    with path.open('x') as stream:
        stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('bind','check','validate'));parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    try:
        {'bind':bind,'check':verify_binding,'validate':validate}[args.action](args.root)
        print('Actual21 prior reports retained: '+args.action)
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
