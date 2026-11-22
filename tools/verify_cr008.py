#!/usr/bin/env python3
"""Operator-only CR-008 source, production/PG17 and real monthly-worker gate."""
import argparse
import ast
import csv
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
from cr008_receipts import BINDING, verify_binding

DOCS = ROOT / 'docs/implementation'
MANIFEST = DOCS / 'evidence/CR008-source-lock.json'


def retained_assertion_dump(node):
    """Keep the original Python 3.12 assertion representation on newer hosts."""
    options = {'include_attributes': False}
    # Python 3.13 changed dump's default to omit empty optional lists.
    # Explicitly retain them; the 33 frozen baseline digests stay unchanged.
    if sys.version_info >= (3, 13):
        options['show_empty'] = True
    return ast.dump(node, **options)


def source_check():
    from cr008_static_inputs import inspect
    inspect(ROOT)
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
    with (DOCS/'traceability.csv').open(newline='') as stream:
        requirements = list(csv.DictReader(stream))
    if len(requirements) != 85 or any(row['acceptance_status'] != 'Pending' for row in requirements):
        raise RuntimeError('Η αλλαγή δεν εγκρίνει τις 85 πλήρεις αποδοχές απαιτήσεων.')
    for name, expected_assertions in policy['retained_assertions'].items():
        tree = ast.parse((ROOT/name).read_text())
        assertions = [retained_assertion_dump(node) for node in ast.walk(tree)
            if isinstance(node,ast.Assert) or isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
            and node.func.attr.startswith('assert')]
        observed = 'sha256:'+hashlib.sha256(json.dumps(assertions,separators=(',',':')).encode()).hexdigest()
        if observed != expected_assertions:
            raise RuntimeError('Άλλαξαν αρχικές δοκιμαστικές απαιτήσεις: '+name)
    for name, digest in policy['retained_test_methods'].items():
        methods=[retained_assertion_dump(node) for node in ast.walk(ast.parse((ROOT/name).read_text()))
            if isinstance(node,ast.FunctionDef) and node.name.startswith('test_')]
        observed='sha256:'+hashlib.sha256(json.dumps(methods,separators=(',',':')).encode()).hexdigest()
        if observed!=digest:raise RuntimeError('Άλλαξε διατηρούμενη μέθοδος δοκιμής: '+name)
    for path in (ROOT/'accounting').glob('*.py'):
        if not path.name.startswith('tests') and any(name in path.read_text() for name in ('tests_cr005_support','tests_entity_profile_support','tests_attachment_support')):
            raise RuntimeError('Ιστορικά fixtures δεν επιτρέπονται σε κώδικα εφαρμογής.')
    context = image.candidate_context()[1]
    if context['digest'] != policy['application_context_digest'] or context['file_count'] != policy['application_inputs']:
        raise RuntimeError('Διαφέρει το ελεγμένο περιεχόμενο της νέας εφαρμογής.')
    methods = sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
        for name in policy['test_files'] for node in ast.walk(ast.parse((ROOT / name).read_text())))
    if methods != policy['new_test_methods']:
        raise RuntimeError('Διαφέρουν οι νέοι έλεγχοι CR-008.')
    return policy, len(expected)


def clean_source():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
        raise RuntimeError('Αποθηκεύστε πρώτα τις αλλαγές σε Git commit. Ο έλεγχος χρησιμοποιεί μόνο δεσμευμένη πηγή.')


def record(report):
    from record_cr008 import STATE,REPORT,state_result,commit_actual_result
    destination=ROOT/REPORT
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    state=ROOT/STATE;text=state.read_text()
    pattern=r'(?s)(<!-- CR008-RESULT -->).*?(<!-- /CR008-RESULT -->)'
    updated,count=re.subn(pattern,lambda m:m[1]+'\n'+state_result(report)+'\n'+m[2],text,count=1)
    if count!=1:raise RuntimeError('Απουσιάζει η χωριστή καταγραφή CR008. Η αναφορά διατηρήθηκε.')
    state.write_text(updated)
    commit_actual_result()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--source-only', action='store_true')
    parser.add_argument('--resume-delivery', action='store_true',
        help='Continue only from the exact retained successful1186/36 operator delivery')
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--host-dns', action='store_true')
    choice.add_argument('--image')
    args = parser.parse_args()
    if args.source_only and (args.record or args.host_dns or args.image or args.resume_delivery):
        parser.error('--source-only cannot be combined with runtime/record options')
    if args.resume_delivery and args.image:
        parser.error('--resume-delivery selects the exact passed image; do not add --image')
    stage = 'source-preflight'
    try:
        policy, retained = source_check()
        bound = verify_binding(ROOT) if (ROOT / BINDING).exists() else None
        if args.source_only:
            print(json.dumps({'change': 'CR-008', 'status': 'Prepared', 'source_files_checked': retained,
                'application_inputs': policy['application_inputs'], 'runtime_executed': False,
                'actual_cr007_receipts_bound': bound is not None}, ensure_ascii=False))
            return
        clean_source()
        baseline = verify_binding(ROOT)
        require_local_docker()
        stage = 'new-production-image';resumed_proof=None
        if args.resume_delivery:
            stage = 'retained-successful-delivery-validation'
            from cr008_delivery_resume import load_retained_delivery
            delivery,resumed_proof=load_retained_delivery(policy)
            selected=image.reuse_for_verification(resumed_proof['image_id'])
        elif args.image:
            selected = image.reuse_for_verification(args.image)
        elif args.host_dns:
            from build_host_dns import build
            selected = build()
        else:
            selected = image.build()
        with tempfile.TemporaryDirectory(prefix='accounting-cr008-') as directory:
            if resumed_proof is None:
                stage = 'full-production-pg17-delivery'
                destination = Path(directory) / 'delivery.json'
                subprocess.run([sys.executable, str(ROOT / 'tools/verify_delivery.py'), '--report', str(destination),
                                '--image', selected['image_id']], cwd=ROOT, check=True)
                delivery = json.loads(destination.read_text())
                retained_report = ROOT/'private/cr008'/selected['image_id'].removeprefix('sha256:')/'delivery.json'
                retained_report.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                payload=json.dumps(delivery,ensure_ascii=False,indent=2)+'\n'
                if retained_report.exists() and retained_report.read_text()!=payload:
                    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
                    retained_report=retained_report.with_name('delivery-'+revision+'.json')
                if not retained_report.exists():
                    with retained_report.open('x') as stream:stream.write(payload)
                elif retained_report.read_text()!=payload:
                    raise RuntimeError('Διαφέρει προηγούμενη επιτυχής αναφορά. Δεν αντικαταστάθηκε.')
                retained_report.chmod(0o600)
                print('[CR008] Η αναφορά της σουίτας διατηρήθηκε τοπικά: '+str(retained_report),flush=True)
                current_scan=delivery['secret_scan']
            else:
                print('[CR008] Επιβεβαιώθηκαν η πραγματική1186/36 αναφορά και τα ίδια371 αρχεία εφαρμογής. Συνεχίζεται ο έλεγχος αρχείων με την ίδια εικόνα.',flush=True)
                stage='resumed-current-source-history-scan'
                from cr008_delivery_resume import scan_current_source
                current_scan=scan_current_source(Path(directory))
            suite = delivery['suite']
            expected = policy['retained_test_count'] + policy['new_test_methods']
            if (suite['tests_run'] != expected or suite['tests_passed'] != expected or any(suite[key] for key in
                    ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips'))):
                raise RuntimeError(f'Απαιτείται επιτυχία και των {expected} ελέγχων.')
            if len(suite['cases']) != 36 or any(row['outcome'] != 'passed' for row in suite['cases']):
                raise RuntimeError('Απαιτείται επιτυχία και των 36 οικονομικών περιπτώσεων.')
            migrations = delivery['applied_migrations']
            if (len([name for name in migrations if name.startswith('accounting.')]) != 36 or
                    not {'accounting.0035_client_attachments', 'accounting.0036_attachment_guards'} <= set(migrations)):
                raise RuntimeError('Απαιτούνται και οι 36 migrations μαζί με τα συνημμένα και τους νέους ελέγχους.')
            stage = 'real-private-files-antivirus-and-recovery'
            from cr008_files_gate import files_gate
            files = files_gate(Path(directory), selected['image_id'], host_dns=args.host_dns)
            stage = 'retained-real-monthly-worker-commit-before-ack'
            broker = broker_gate(Path(directory), selected['image_id'])
        source_check()
        verify_binding(ROOT)
        clean_source()
        if resumed_proof is not None:
            from cr008_delivery_resume import load_retained_delivery
            if load_retained_delivery(policy)[1]!=resumed_proof:
                raise RuntimeError('Η διατηρημένη επιτυχής αναφορά άλλαξε κατά την εκτέλεση.')
        report = {'change': 'CR-008', 'status': 'Verified', 'source_status': 'Prepared',
            'scope': 'isolated-production-pg17-private-client-attachments-and-retained-manual-tasks-and-monthly-worker',
            'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit': 'git:' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'image': selected if resumed_proof is not None else delivery['image'],
            'application_context_digest': policy['application_context_digest'],
            'production_suite_rerun':resumed_proof is None,'retained_successful_delivery':resumed_proof,
            'secret_scan':current_scan,
            'suite': suite, 'private_files':files, 'new_test_methods': policy['new_test_methods'], 'retained_source_files_checked': retained,
            'real_monthly_worker_and_commit_before_ack': True,
            'revocation_blocks_execution': broker['revocation_blocks_execution'],
            'second_scheduler_rejected': broker['second_scheduler_rejected'],
            'restricted_role_migrations': broker['restricted_role_migrations'],
            'original_34_migrations_unchanged': True, 'new_migrations': 2, 'historical_receipts_unchanged': True,
            'actual_prior_receipt_files_sha256': baseline['files'],
            'agent_native_execution': False, 'docker_execution_by_operator': True,
            'local_demo_or_vm_changed': False, 'github_updated': False, 'vm_github_hold_by_user': True, 'human_accounts_or_mfa_changed': False,
            'owned_resources_removed': True, 'full_requirement_acceptances_pending': 85,
            'accountant_browser_acceptance': 'Pending', 'g2_release_acceptance': 'Pending'}
        if args.record:
            record(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, AssertionError, subprocess.SubprocessError) as error:
        print('CR008-DIAG ' + json.dumps({'stage': stage, 'error': type(error).__name__}), file=sys.stderr)
        parser.exit(1, 'CR-008 stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
