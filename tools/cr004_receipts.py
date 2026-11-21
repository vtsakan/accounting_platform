#!/usr/bin/env python3
"""Bind the genuine successful CR003 report and its retained CR002 evidence."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

RECEIPT = 'docs/implementation/evidence/CR003-verification.json'
PRIOR_RECEIPT = 'docs/implementation/evidence/CR002-verification.json'
PRIOR_BINDING = 'docs/implementation/evidence/CR003-operator-baseline.json'
BINDING = 'docs/implementation/evidence/CR004-operator-baseline.json'
FILES = (RECEIPT, PRIOR_RECEIPT, PRIOR_BINDING)
SOURCE = 'git:bd541fb269343838e217c916cd7a83013baeb0c9'
CONTEXT = 'sha256:de928a2467826d60f2797c923ba46ee4c4cd908c6961cde1452e31e3fc8a22b0'
IMAGE = 'sha256:8ad766ad2ed0c624a6ed1bec8884d7cb554d4cc188191ab93cc5f1c6837f7a92'
PRIOR_SOURCE = 'git:ee73318b2b1af1c02e419ff9c7d1d8d029764b80'
PRIOR_SHA256 = 'sha256:b5accc113147abea0502f7f7a5367b68ff292bc859923a7f485634054579c891'


def digest(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise RuntimeError('Απαιτείται πραγματικό, κανονικό αρχείο αναφοράς: ' + path.name)
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root):
    root = Path(root).resolve()
    for name in FILES:
        digest(root / name)
    report = json.loads((root / RECEIPT).read_text())
    old = json.loads((root / PRIOR_BINDING).read_text())
    if not isinstance(report, dict) or not isinstance(old, dict):
        raise RuntimeError('Μη έγκυρη δομή πραγματικών αναφορών.')
    if (digest(root / PRIOR_RECEIPT) != PRIOR_SHA256 or old.get('schema') != 1 or
            old.get('change') != 'CR-003' or old.get('operator_source') != PRIOR_SOURCE or
            old.get('files') != {PRIOR_RECEIPT: PRIOR_SHA256}):
        raise RuntimeError('Διαφέρει η πραγματική αναφορά ή η δέσμευση CR-002.')
    suite = report.get('suite', {}); image = report.get('image', {})
    if not isinstance(suite, dict) or not isinstance(image, dict):
        raise RuntimeError('Μη έγκυρα αποτελέσματα CR-003.')
    context = image.get('context', {}); cases = suite.get('cases', [])
    if not isinstance(context, dict) or not isinstance(cases, list) or not all(isinstance(c, dict) for c in cases):
        raise RuntimeError('Μη έγκυρη δομή αποτελεσμάτων CR-003.')
    registry = json.loads((root / 'accounting/regression_cases.json').read_text())['cases']
    good = (report.get('change') == 'CR-003' and report.get('status') == 'Verified' and
        report.get('verified_at') == '2026-11-21T08:07:18+02:00' and report.get('source_commit') == SOURCE and
        report.get('application_context_digest') == CONTEXT and image.get('image_id') == IMAGE and
        image.get('revision') == SOURCE and context.get('digest') == CONTEXT and context.get('file_count') == 292 and
        suite.get('tests_run') == 917 and suite.get('tests_passed') == 917 and
        all(suite.get(key) == 0 for key in ('known_failures_reproduced', 'unexpected_failures',
            'unexpected_errors', 'unexpected_successes', 'skips')) and
        len(cases) == 36 and {c.get('case_id') for c in cases} == {c['case_id'] for c in registry} and
        all(c.get('outcome') == 'passed' for c in cases) and report.get('new_test_methods') == 39 and
        report.get('retained_source_files_checked') == 670 and report.get('old_migrations_unchanged') == 26 and
        report.get('new_migrations') == 0 and report.get('actual_cr002_receipt_sha256') == PRIOR_SHA256 and
        report.get('full_requirement_acceptances_pending') == 85 and
        all(report.get(key) is True for key in ('real_monthly_worker_and_commit_before_ack',
            'revocation_blocks_execution', 'second_scheduler_rejected', 'restricted_role_migrations',
            'historical_receipts_unchanged', 'owned_resources_removed', 'docker_execution_by_operator')) and
        all(report.get(key) is False for key in ('agent_native_execution', 'local_demo_or_vm_changed',
            'github_updated', 'human_accounts_or_mfa_changed')))
    if not good:
        raise RuntimeError('Απαιτείται η πραγματική επιτυχής αναφορά CR-003 με 917/917 και 36 οικονομικές περιπτώσεις.')
    lineage = subprocess.run(['git', 'merge-base', '--is-ancestor', SOURCE.removeprefix('git:'), 'HEAD'],
        cwd=root, capture_output=True)
    if lineage.returncode:
        raise RuntimeError('Η πηγή δεν περιέχει το πραγματικό επιτυχές commit CR-003 του χειριστή.')
    return report


def verify_binding(root):
    root = Path(root).resolve()
    validate(root)
    digest(root / BINDING)
    value = json.loads((root / BINDING).read_text())
    if not isinstance(value, dict):
        raise RuntimeError('Μη έγκυρη δέσμευση CR-004.')
    files = value.get('files', {})
    if (value.get('schema') != 1 or value.get('change') != 'CR-004' or value.get('operator_source') != SOURCE or
            not isinstance(files, dict) or set(files) != set(FILES) or any(
                not isinstance(files[name], str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', files[name]) or
                files[name] != digest(root / name) for name in FILES)):
        raise RuntimeError('Οι πραγματικές αναφορές CR002/CR003 άλλαξαν. Δεν έγινε αυτόματη ανανέωση.')
    return value


def bind(root):
    root = Path(root).resolve()
    validate(root)
    path = root / BINDING
    if path.exists() or path.is_symlink():
        return verify_binding(root)
    value = {'schema': 1, 'change': 'CR-004', 'operator_source': SOURCE,
        'files': {name: digest(root / name) for name in FILES},
        'capture': 'actual operator receipts and existing binding retained without alteration'}
    with path.open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    return verify_binding(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['validate', 'bind', 'check'])
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        {'validate': validate, 'bind': bind, 'check': verify_binding}[args.action](args.root)
        print('CR003 actual operator evidence: ' + ('Validated' if args.action == 'validate' else 'Bound'))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')
