"""Exclusive real CR008 operator/VM history binding for the GSIS-only change."""
import argparse
import json
from pathlib import Path
import subprocess

import preview_cr008_policy as previous
from r1_gate import digest_bytes, digest_object, require

BASELINE = 'docs/implementation/evidence/CR009-operator-baseline.json'
VM_REPORT = 'docs/implementation/evidence/CR008-VM-verification.json'
VM_RECORD = '24b32799871d887878e06247bd1c351c16391527'  # pragma: allowlist secret -- actual published completed CR008 VM record
VM_REPORT_SHA = 'sha256:bb3fe31f400807469bd61fe0498fc1807af65be2fc50c0b6746c080702a0dd36'
PATHS = (*previous.RETAINED_REPORTS, previous.BASELINE, VM_REPORT)


def validate(root):
    root = Path(root).resolve()
    previous.verify_reports(root)
    previous.unchanged_acceptances(root)
    require(len(set(PATHS)) == 18 and all((root/name).is_file() and not (root/name).is_symlink()
        and (root/name).stat().st_size <= 2_000_000 for name in PATHS), 'Retain all18 genuine prior report/binding files')
    vm = json.loads((root/VM_REPORT).read_text())
    require(digest_object(vm) == VM_REPORT_SHA and vm['status'] == 'Verified' and vm['target_migrations'] == 36,
        'Retain the actual completed CR008 VM report without replacing or reconstructing it')
    require(subprocess.run(['git','merge-base','--is-ancestor',VM_RECORD,'HEAD'],cwd=root,
        capture_output=True).returncode == 0, 'Retain the genuine published CR008 VM result in native history')
    require(subprocess.check_output(['git','show',VM_RECORD+':'+VM_REPORT],cwd=root) == (root/VM_REPORT).read_bytes(),
        'The actual VM report changed after its published record')
    return {'change':'CR-009','schema':1,'previous_completed_vm_record':'git:'+VM_RECORD,
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
        print('Actual18 prior reports retained: '+args.action)
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
