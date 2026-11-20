#!/usr/bin/env python3
"""Preserve the actual successful CR002 operator receipt; no app execution."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

RECEIPT = 'docs/implementation/evidence/CR002-verification.json'
BINDING = 'docs/implementation/evidence/CR003-operator-baseline.json'
SOURCE = 'git:ee73318b2b1af1c02e419ff9c7d1d8d029764b80'
CONTEXT = 'sha256:337b2f09354837bda7bdce366c5fcacbfbeba9c4bcbdc4b41d8d643ad3ada760'
IMAGE = 'sha256:4a486854b9c171f073f4bead9d02b21aaa00350f1bfaa00b45ae86a3ada66e21'


def digest(path):
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root):
    root = Path(root).resolve()
    path = root / RECEIPT
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise RuntimeError('Απαιτείται η πραγματική επιτυχής αναφορά CR002-verification.json.')
    report = json.loads(path.read_text())
    if not isinstance(report, dict):
        raise RuntimeError('Μη έγκυρη δομή της πραγματικής αναφοράς CR-002.')
    suite = report.get('suite', {})
    image = report.get('image', {})
    if not isinstance(suite, dict) or not isinstance(image, dict):
        raise RuntimeError('Μη έγκυρα αποτελέσματα της πραγματικής αναφοράς CR-002.')
    context = image.get('context', {})
    cases = suite.get('cases', [])
    if not all(isinstance(value, dict) for value in (suite, image, context)) or not isinstance(cases, list) or not all(isinstance(c, dict) for c in cases):
        raise RuntimeError('Μη έγκυρα αποτελέσματα της πραγματικής αναφοράς CR-002.')
    registry = json.loads((root / 'accounting/regression_cases.json').read_text())['cases']
    good = (report.get('change') == 'CR-002' and report.get('status') == 'Verified' and
        report.get('verified_at') == '2026-11-21T00:21:31+02:00' and report.get('source_commit') == SOURCE and
        report.get('application_context_digest') == CONTEXT and image.get('image_id') == IMAGE and
        context.get('digest') == CONTEXT and context.get('file_count') == 287 and
        suite.get('tests_run') == 878 and suite.get('tests_passed') == 878 and
        all(suite.get(key) == 0 for key in ('known_failures_reproduced', 'unexpected_failures',
            'unexpected_errors', 'unexpected_successes', 'skips')) and
        len(cases) == 36 and {c.get('case_id') for c in cases} == {c['case_id'] for c in registry} and
        all(c.get('outcome') == 'passed' for c in cases) and report.get('new_test_methods') == 30 and
        report.get('retained_source_files_checked') == 659 and report.get('old_migrations_unchanged') == 26 and
        report.get('new_migrations') == 0 and report.get('full_requirement_acceptances_pending') == 85 and
        all(report.get(key) is True for key in ('real_monthly_worker_and_commit_before_ack',
            'revocation_blocks_execution', 'second_scheduler_rejected', 'restricted_role_migrations',
            'historical_receipts_unchanged', 'owned_resources_removed', 'docker_execution_by_operator')) and
        all(report.get(key) is False for key in ('agent_native_execution', 'local_demo_or_vm_changed',
            'github_updated', 'human_accounts_or_mfa_changed')))
    if not good:
        raise RuntimeError('Η αναφορά δεν αντιστοιχεί στο πραγματικό επιτυχές CR-002 που δηλώθηκε.')
    revision = SOURCE.removeprefix('git:')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'HEAD'], cwd=root,
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise RuntimeError('Η πραγματική πηγή του επιτυχούς CR-002 δεν βρίσκεται στο τρέχον ιστορικό Git.')
    return report


def verify_binding(root):
    root = Path(root).resolve()
    validate(root)
    path = root / BINDING
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('Απουσιάζει η αποκλειστική δέσμευση της πραγματικής αναφοράς CR-002. Εκτελέστε το APPLY_CR003.sh.')
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError('Μη έγκυρη δέσμευση της πραγματικής αναφοράς CR-002.')
    expected = value.get('files', {})
    if (not isinstance(expected, dict) or value.get('schema') != 1 or value.get('change') != 'CR-003' or value.get('operator_source') != SOURCE or
            set(expected) != {RECEIPT} or not isinstance(expected[RECEIPT], str) or
            not re.fullmatch(r'sha256:[0-9a-f]{64}', expected[RECEIPT]) or
            expected[RECEIPT] != digest(root / RECEIPT)):
        raise RuntimeError('Η δεσμευμένη πραγματική αναφορά CR-002 άλλαξε. Δεν έγινε αυτόματη ανανέωση.')
    return value


def bind(root):
    root = Path(root).resolve()
    validate(root)
    path = root / BINDING
    if path.exists() or path.is_symlink():
        return verify_binding(root)
    value = {'schema': 1, 'change': 'CR-003', 'operator_source': SOURCE,
        'files': {RECEIPT: digest(root / RECEIPT)}, 'capture': 'actual operator receipt retained without alteration'}
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
        print('CR-002 actual operator receipt: ' + ('Bound' if args.action != 'validate' else 'Validated'))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, str(error) + '\n')
