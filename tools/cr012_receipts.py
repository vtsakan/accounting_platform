"""Bind the genuine published CR011 result, completed VM record and all31 prior files."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

BASELINE='docs/implementation/evidence/CR012-operator-baseline.json'
VM_REPORT='docs/implementation/evidence/CR011-VM-verification.json'
CURRENT_RECORD='08ad19063de7bf47de385ffdf5f30f45738d701b'  # pragma: allowlist secret -- actual public completed CR011 VM recording commit
NATIVE_RESULT='81da3bca37662779f4507ae52460aceb7610c5af'  # pragma: allowlist secret -- actual native CR011 result, resolved from published binding
VM_REPORT_SHA='sha256:2cb62f1ab7ee45fe95916b910e3bf410ba8364e5d71db1f89895298d4621efc6'
VM_BASELINE_SHA='sha256:ef40d6f1fcc3fa9b96d034def9d44d44f326d6f276c3c51929379e6799ea484d'
VM_CANONICAL_SHA='sha256:944d91b363acfc21a28b3af38775a4ce57679853f2cb7ca20209b05730874b09'


def validate(root):
    root=Path(root).resolve();sys.path.insert(0,str(root/'tools'))
    import preview_cr011_policy as previous
    from r1_gate import digest_bytes,digest_object,require
    old=previous.verify(root)
    require(old['native_result_commit']=='git:'+NATIVE_RESULT,'Retain the real full CR011 native result object')
    require(digest_bytes((root/previous.BASELINE).read_bytes())==VM_BASELINE_SHA
        and digest_bytes((root/VM_REPORT).read_bytes())==VM_REPORT_SHA,'The actual completed CR011 VM history changed')
    report=json.loads((root/VM_REPORT).read_text())
    require(digest_object(report)==VM_CANONICAL_SHA and report['step']=='CR011-VM' and report['status']=='Verified'
        and report['application_commit']=='git:'+previous.APP_REVISION and report['application_context_digest']==previous.CONTEXT
        and report['source_migrations']==36 and report['target_migrations']==40 and report['target_tables']==64
        and report['both_off_vm_restores_matched'] is True and report['accounts_mfa_or_keys_reset'] is False
        and report['attachment_uploads_enabled'] is True and report['vm_resized'] is False,
        'The genuine successful CR011/schema40/4GiB VM and recovery report is required')
    require(subprocess.run(['git','merge-base','--is-ancestor',CURRENT_RECORD,'HEAD'],cwd=root,capture_output=True).returncode==0,
        'Retain the actual published completed CR011 VM record in native history')
    names=(*old['files'],previous.BASELINE,VM_REPORT)
    require(len(set(names))==31,'Retain every31 genuine prior verification and binding files')
    require(all((root/name).is_file() and not(root/name).is_symlink() for name in names),'Retain regular prior receipt files')
    return {'change':'CR-012','binding_schema':1,'previous_source_commit':'git:'+previous.APP_REVISION,
        'previous_native_result':'git:'+NATIVE_RESULT,'previous_completed_vm_record':'git:'+CURRENT_RECORD,
        'previous_vm_report_canonical_sha256':VM_CANONICAL_SHA,'preserved_operator_files':old['preserved_operator_files'],
        'files':{name:digest_bytes((root/name).read_bytes()) for name in names}}


def verify_binding(root):
    root=Path(root).resolve();actual=validate(root);path=root/BASELINE
    from r1_gate import require
    require(path.is_file() and not path.is_symlink() and json.loads(path.read_text())==actual,
        'The exclusive CR01231-file binding differs; it was retained without refresh')
    return actual


def bind(root):
    root=Path(root).resolve();path=root/BASELINE
    if path.exists() or path.is_symlink():return verify_binding(root)
    value=validate(root)
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=('validate','check','bind'))
    parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    try:
        {'validate':validate,'check':verify_binding,'bind':bind}[args.action](args.root)
        print('CR012: actual31 prior files and completed CR011 native/VM history retained; '+args.action)
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
