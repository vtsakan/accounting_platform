#!/usr/bin/env python3
"""Exclusive binding of actual CR005 application/VM and retained prior receipts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

SOURCE = 'git:12ed590084dd777a6d09ab8d9ee8337abf12da66'
BINDING = 'docs/implementation/evidence/CR007-operator-baseline.json'
EXPECTED = {'docs/implementation/evidence/CR005-verification.json': 'sha256:a80df898d1f26378bc4685841c7753ffd249b95e0495addf0c7c3cd5af082274', 'docs/implementation/evidence/CR004-verification.json': 'sha256:a0a2731f76ed5a56e8e2a3bfd4bd970cdf7bb5d7da2531a24ea4ab47fe216cc4', 'docs/implementation/evidence/CR003-verification.json': 'sha256:1f8feac780aa893a9bf8dd7c970ed0a32a553b97b5ce598c217431d590421706', 'docs/implementation/evidence/CR002-verification.json': 'sha256:b5accc113147abea0502f7f7a5367b68ff292bc859923a7f485634054579c891', 'docs/implementation/evidence/CR003-operator-baseline.json': 'sha256:d0077c3bcfb36803475e47a0bfc9098753bfd9277648ca7153d0220278c18088', 'docs/implementation/evidence/CR004-operator-baseline.json': 'sha256:dfec50f4305696f4e950e6d44ba66a25bdc4babadf435834bfb729f8b5cb933a', 'docs/implementation/evidence/CR004-VM-verification.json': 'sha256:4ef12db035b7f93e42730a38ca39fa18fd2a747db5f34d915e74322f5feafa4e', 'docs/implementation/evidence/CR004-VM-operator-baseline.json': 'sha256:1593e2378a3c7e6adb5c71405bbfa73b968680fb2810d20eb6c32304efd35eaa', 'docs/implementation/evidence/CR005-operator-baseline.json': 'sha256:63129cd558fbe5af29723c29d7e5588ee6c414bcd7627495cecbe800d4ccad14', 'docs/implementation/evidence/CR005-VM-verification.json': 'sha256:b141e22eec872577f965ef7539a4ee275563098b6b527cf7bd47468b492c2a01', 'docs/implementation/evidence/CR005-VM-operator-baseline.json': 'sha256:f020550f933e561c948d248b841268e7604df01fdfa93947c9ee519ddf84e208', 'docs/implementation/evidence/CR006-operator-baseline.json': 'sha256:cd8ce51414a35ff94b061cd0f37417813a9ee8bc3f0ce0a10da789babceb5503'}


def digest(root, name):
    root = Path(root).resolve(); path = root/name
    if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size > 2_000_000:
        raise RuntimeError('Απαιτείται η πραγματική κανονική αναφορά: '+name)
    return 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root):
    root=Path(root).resolve()
    for name,value in EXPECTED.items():
        if digest(root,name)!=value:
            raise RuntimeError('Άλλαξε πραγματική αναφορά ή παλιά δέσμευση: '+name)
    from preview_cr005_policy import verify_reports
    verify_reports(root)
    if subprocess.run(['git','merge-base','--is-ancestor',SOURCE.removeprefix('git:'),'HEAD'],
            cwd=root,capture_output=True).returncode:
        raise RuntimeError('Η πηγή πρέπει να περιέχει το πραγματικό CR006 commit του χειριστή με την επιτυχή σουίτα και αποτυχία broker.')
    vm=json.loads((root/'docs/implementation/evidence/CR005-VM-verification.json').read_text())
    if vm.get('status')!='Verified' or vm.get('target_migrations')!=30 or vm.get('off_vm_all_public_tables_match') is not True:
        raise RuntimeError('Απαιτείται το πραγματικό Verified CR005 VM και οι δύο επιτυχείς επαναφορές.')
    return {'change':'CR-007','schema':1,'operator_source':SOURCE,'files':EXPECTED}


def verify_binding(root):
    root=Path(root).resolve();value=validate(root);path=root/BINDING
    digest(root,BINDING)
    if json.loads(path.read_text())!=value:
        raise RuntimeError('Η δέσμευση CR007 άλλαξε. Δεν έγινε αυτόματη ανανέωση.')
    return value


def bind(root):
    root=Path(root).resolve();value=validate(root);path=root/BINDING
    if path.exists() or path.is_symlink():return verify_binding(root)
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return verify_binding(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['validate','bind','check']);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    try:
        {'validate':validate,'bind':bind,'check':verify_binding}[args.action](args.root)
        print('Actual CR005 application/VM and prior evidence retained: '+args.action)
    except (RuntimeError,OSError,ValueError,KeyError,TypeError) as error:
        parser.exit(1,str(error)+'\n')
