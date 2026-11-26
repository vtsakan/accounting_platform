"""Bind the real completed CR009 history; never reconstruct operator receipts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

BASELINE = 'docs/implementation/evidence/CR010-operator-baseline.json'
VM_REPORT = 'docs/implementation/evidence/CR009-VM-verification.json'
CURRENT_RECORD = '9dc666bf75aa597747ecd040da1e18fe32273675'  # pragma: allowlist secret -- actual public completed CR009 record
VM_REPORT_SHA = 'sha256:33d1b49ad0bf528199db8e3a66013ee5ca0c25dc5007e6fb75f564fe82fe969d'


def preserved_operator_files(root):
    """Record operator instructions as found; never replace them with our copy."""
    from r1_gate import digest_bytes, require
    root = Path(root).resolve(); path = root/'AGENTS.md'
    require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),
        'Retain AGENTS.md as a regular operator-owned file')
    return {'AGENTS.md': digest_bytes(path.read_bytes())}


def validate(root):
    root = Path(root).resolve()
    sys.path.insert(0, str(root/'tools'))
    import preview_cr009_policy as previous
    from r1_gate import digest_bytes, digest_object, require
    previous.verify(root)
    paths = (*previous.REPORTS, previous.BASELINE, VM_REPORT)
    require(len(set(paths)) == 25, 'Retain all 25 genuine historical receipt/binding files')
    value = json.loads((root/VM_REPORT).read_text())
    require(digest_object(value) == VM_REPORT_SHA and value['step'] == 'CR009-VM' and value['status'] == 'Verified'
        and value['application_commit'] == 'git:'+previous.APP_REVISION
        and value['same_current_database'] is True and value['attachment_uploads_enabled'] is True,
        'The actual successful CR009 VM result is required without reconstruction')
    require(subprocess.run(['git', 'merge-base', '--is-ancestor', CURRENT_RECORD, 'HEAD'], cwd=root, capture_output=True).returncode == 0,
        'The actual completed 9dc666b record must remain in native Git history')
    require(subprocess.check_output(['git', 'show', CURRENT_RECORD+':'+VM_REPORT], cwd=root) == (root/VM_REPORT).read_bytes(),
        'The genuine CR009 VM receipt changed after its result commit')
    require(all((root/name).is_file() and not (root/name).is_symlink() for name in paths), 'Historical report paths must be regular files')
    return {'change': 'CR-010', 'binding_schema': 2, 'previous_completed_vm_record': 'git:'+CURRENT_RECORD,
        'previous_application_context': previous.CONTEXT, 'previous_vm_report_canonical_sha256': VM_REPORT_SHA,
        'preserved_operator_files': preserved_operator_files(root),
        'files': {name: digest_bytes((root/name).read_bytes()) for name in paths}}


def verify_binding(root):
    root = Path(root).resolve(); actual = validate(root); path = root/BASELINE
    if not path.is_file() or path.is_symlink() or json.loads(path.read_text()) != actual:
        raise RuntimeError('The exclusive CR010 historical binding differs; it was not refreshed')
    return actual


def bind(root):
    root = Path(root).resolve(); path = root/BASELINE
    if path.exists() or path.is_symlink():
        return verify_binding(root)
    value = validate(root)
    with path.open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('validate', 'check', 'bind')); parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    try:
        {'validate': validate, 'check': verify_binding, 'bind': bind}[args.action](args.root)
        print('CR010: actual 25-file history retained, '+args.action)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error)+'\n')
