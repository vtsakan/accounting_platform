#!/usr/bin/env python3
"""Operator-only CR-003 source, production/PG17 and real monthly-worker gate."""
import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from dev import ROOT, require_local_docker
import image
from s28_broker_gate import broker_gate
from cr003_receipts import BINDING, verify_binding

DOCS = ROOT / 'docs/implementation'
MANIFEST = DOCS / 'evidence/CR003-source-lock.json'


def source_check():
    policy = json.loads(MANIFEST.read_text())
    expected = {}
    for section in ('unchanged_files', 'changed_files', 'added_files'):
        entries = policy[section]
        if not isinstance(entries, dict) or not entries:
            raise RuntimeError('Απουσιάζει η δέσμευση αρχείων πηγής.')
        for name, digest in entries.items():
            path = Path(name)
            if (name in expected or path.is_absolute() or '..' in path.parts or
                    not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)):
                raise RuntimeError('Μη έγκυρη δέσμευση πηγής.')
            expected[name] = digest
    different = []
    for name, digest in expected.items():
        path = ROOT / name
        if (path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT.resolve()) or
                'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            different.append(name)
    if different:
        raise RuntimeError('Διαφέρουν δεσμευμένα αρχεία:\n' + '\n'.join(different))
    context = image.candidate_context()[1]
    if context['digest'] != policy['application_context_digest'] or context['file_count'] != policy['application_inputs']:
        raise RuntimeError('Διαφέρει το ελεγμένο περιεχόμενο της νέας εφαρμογής.')
    tree = ast.parse((ROOT / 'accounting/tests_cash_agreement_entry.py').read_text())
    methods = sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_') for node in ast.walk(tree))
    if methods != policy['new_test_methods']:
        raise RuntimeError('Διαφέρουν οι νέοι έλεγχοι CR-003.')
    return policy, len(expected)


def clean_source():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise RuntimeError('Αποθηκεύστε πρώτα τις αλλαγές σε Git commit. Ο έλεγχος χρησιμοποιεί μόνο δεσμευμένη πηγή.')


def record(report):
    destination = DOCS / 'evidence/CR003-verification.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    state = DOCS / 'state.md'
    text = state.read_text()
    pattern = r'(?s)(<!-- CR003-RESULT -->).*?(<!-- /CR003-RESULT -->)'
    replacement = (r'\1\nCR-003 source Prepared; operator technical gate Verified: '
        f"{report['suite']['tests_passed']} tests, 36 financial cases and retained real monthly-worker/ack-loss gate passed. "
        'VM/GitHub rollout and accountant/browser acceptance remain Pending. All 85 full acceptances remain Pending.\n'
        r'\2')
    updated, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError('Απουσιάζει η ξεχωριστή καταγραφή CR-003· το αποτέλεσμα σώθηκε στο νέο αρχείο τεκμηρίωσης.')
    state.write_text(updated)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--source-only', action='store_true')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--host-dns', action='store_true')
    choice.add_argument('--image')
    args = parser.parse_args()
    if args.source_only and (args.record or args.host_dns or args.image):
        parser.error('--source-only cannot be combined with runtime/record options')
    stage = 'source-preflight'
    try:
        policy, retained = source_check()
        bound = verify_binding(ROOT) if (ROOT / BINDING).exists() else None
        if args.source_only:
            print(json.dumps({'change': 'CR-003', 'status': 'Prepared', 'source_files_checked': retained,
                'application_inputs': policy['application_inputs'], 'runtime_executed': False,
                'actual_cr002_receipt_bound': bound is not None}, ensure_ascii=False))
            return
        clean_source()
        baseline = verify_binding(ROOT)
        require_local_docker()
        stage = 'new-production-image'
        if args.image:
            selected = image.reuse_for_verification(args.image)
        elif args.host_dns:
            from build_host_dns import build
            selected = build()
        else:
            selected = image.build()
        with tempfile.TemporaryDirectory(prefix='accounting-cr003-') as directory:
            stage = 'full-production-pg17-delivery'
            destination = Path(directory) / 'delivery.json'
            subprocess.run([sys.executable, str(ROOT / 'tools/verify_delivery.py'), '--report', str(destination),
                            '--image', selected['image_id']], cwd=ROOT, check=True)
            delivery = json.loads(destination.read_text())
            suite = delivery['suite']
            expected = policy['retained_test_count'] + policy['new_test_methods']
            if (suite['tests_run'] != expected or suite['tests_passed'] != expected or any(suite[key] for key in
                    ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips'))):
                raise RuntimeError(f'Απαιτείται επιτυχία και των {expected} ελέγχων.')
            if len(suite['cases']) != 36 or any(row['outcome'] != 'passed' for row in suite['cases']):
                raise RuntimeError('Απαιτείται επιτυχία και των 36 οικονομικών περιπτώσεων.')
            stage = 'retained-real-monthly-worker-commit-before-ack'
            broker = broker_gate(Path(directory), selected['image_id'])
        source_check()
        verify_binding(ROOT)
        clean_source()
        report = {'change': 'CR-003', 'status': 'Verified', 'source_status': 'Prepared',
            'scope': 'isolated-production-pg17-cash-entry-auto-settlement-and-retained-monthly-worker',
            'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit': 'git:' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'image': delivery['image'], 'application_context_digest': policy['application_context_digest'],
            'suite': suite, 'new_test_methods': policy['new_test_methods'], 'retained_source_files_checked': retained,
            'real_monthly_worker_and_commit_before_ack': True,
            'revocation_blocks_execution': broker['revocation_blocks_execution'],
            'second_scheduler_rejected': broker['second_scheduler_rejected'],
            'restricted_role_migrations': broker['restricted_role_migrations'],
            'old_migrations_unchanged': 26, 'new_migrations': 0, 'historical_receipts_unchanged': True,
            'actual_cr002_receipt_sha256': next(iter(baseline['files'].values())),
            'agent_native_execution': False, 'docker_execution_by_operator': True,
            'local_demo_or_vm_changed': False, 'github_updated': False, 'human_accounts_or_mfa_changed': False,
            'owned_resources_removed': True, 'full_requirement_acceptances_pending': 85,
            'accountant_browser_acceptance': 'Pending', 'g2_release_acceptance': 'Pending'}
        if args.record:
            record(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as error:
        print('CR003-DIAG ' + json.dumps({'stage': stage, 'error': type(error).__name__}), file=sys.stderr)
        parser.exit(1, 'CR-003 stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
