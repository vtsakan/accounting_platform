"""Exclusively bind the actual CR010 source/result lineage and all27 native files."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

BASELINE = 'docs/implementation/evidence/CR011-operator-baseline.json'
PREVIOUS_REPORT = 'docs/implementation/evidence/CR010-verification.json'
SOURCE = 'eca5b4b6db1c0d20fdedeee9bb695019b1dbab8f'  # pragma: allowlist secret -- real public CR010 source printed by operator
RECORD_PREFIX = 'f72cdde'
REPORT_DIGEST = 'sha256:6aadfdac291ec27554d0cfa74883623784214160660e94043a7b11167ee74fca'
CONTEXT = 'sha256:ea036ea033b7a897b96352d041254d4ef4f6272cf55c02f5f31399a1f9cdcee8'


def validate(root):
    root = Path(root).resolve(); sys.path.insert(0, str(root/'tools'))
    import cr010_receipts as previous
    from r1_gate import digest_bytes, digest_object, require
    retained = previous.verify_binding(root)
    paths = (*retained['files'], previous.BASELINE, PREVIOUS_REPORT)
    require(len(set(paths)) == 27, 'Retain all27 actual CR010 and earlier receipt/binding files')
    require(all((root/name).is_file() and not (root/name).is_symlink() for name in paths), 'Native history paths must be regular files')
    result = json.loads((root/PREVIOUS_REPORT).read_text()); suite = result['suite']; files = result['private_files']
    require(digest_object(result) == REPORT_DIGEST and result['change'] == 'CR-010' and result['status'] == 'Verified'
        and result['source_commit'] == 'git:'+SOURCE and result['application_context_digest'] == CONTEXT
        and suite['tests_run'] == suite['tests_passed'] == 1254 and len(suite['cases']) == 36
        and all(c['outcome'] == 'passed' for c in suite['cases']) and result['deployment_guard_tests_passed'] == 140
        and files['all_public_tables_restored'] == 63 and files['restored_files'] == 10
        and all(result[k] is True for k in ('real_monthly_worker_and_commit_before_ack', 'revocation_blocks_execution',
            'second_scheduler_rejected', 'restricted_role_migrations', 'historical_receipts_unchanged')),
        'The genuine completed CR0101254/36/140 and real recovery/worker report is required')
    # The console printed ONLY this short result commit. Resolve the real native
    # object, then verify its exact parent/paths; never invent an agent-side ID.
    record = subprocess.check_output(['git','rev-parse','--verify',RECORD_PREFIX+'^{commit}'],cwd=root,text=True).strip()
    require(subprocess.check_output(['git','rev-list','--parents','-n','1',record],cwd=root,text=True).split() == [record,SOURCE],
        'The real CR010 result must be the exact child of its verified source')
    changed = set(subprocess.check_output(['git','diff-tree','--no-commit-id','--name-only','-r',record],cwd=root,text=True).splitlines())
    require(changed == {PREVIOUS_REPORT,'docs/implementation/state.md'}, 'Retain the actual two-file CR010 recording commit')
    require(subprocess.run(['git','merge-base','--is-ancestor',record,'HEAD'],cwd=root,capture_output=True).returncode == 0,
        'The genuine CR010 record must be an ancestor of this preparation')
    require(subprocess.check_output(['git','show',record+':'+PREVIOUS_REPORT],cwd=root) == (root/PREVIOUS_REPORT).read_bytes(),
        'The actual CR010 receipt bytes changed after recording')
    return {'change':'CR-011','binding_schema':1,'previous_source_commit':'git:'+SOURCE,
        'previous_record_commit':'git:'+record,'previous_report_canonical_sha256':REPORT_DIGEST,
        'previous_completed_vm_record':retained['previous_completed_vm_record'],
        'preserved_operator_files':previous.preserved_operator_files(root),
        'files':{name:digest_bytes((root/name).read_bytes()) for name in paths}}


def verify_binding(root):
    root=Path(root).resolve();actual=validate(root);path=root/BASELINE
    if not path.is_file() or path.is_symlink() or json.loads(path.read_text()) != actual:
        raise RuntimeError('The exclusive CR011 native history binding differs; it was not refreshed')
    return actual


def bind(root):
    root=Path(root).resolve();path=root/BASELINE
    if path.exists() or path.is_symlink():return verify_binding(root)
    value=validate(root)
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return value


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('validate','check','bind'));parser.add_argument('--root',required=True,type=Path)
    args=parser.parse_args()
    try:
        {'validate':validate,'check':verify_binding,'bind':bind}[args.action](args.root)
        print('CR011: actual27 native files and CR010 recording lineage retained; '+args.action)
    except (OSError,RuntimeError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:
        parser.exit(1,str(error)+'\n')
