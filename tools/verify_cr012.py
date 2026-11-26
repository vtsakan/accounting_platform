#!/usr/bin/env python3
"""Operator gate for on-demand charges, agreement budgets and selected-charge cash credit."""
import argparse
import ast
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from dev import ROOT, require_local_docker
import image
from cr012_receipts import BASELINE, verify_binding
from cr010_receipts import preserved_operator_files
from cr012_static_inputs import inspect
from r1_gate import digest_bytes, require

LOCK = ROOT/'docs/implementation/evidence/CR012-source-lock.json'
MANIFEST = ROOT/'docs/implementation/evidence/CR012-source.json'
REPORT = 'docs/implementation/evidence/CR012-verification.json'
STATE = 'docs/implementation/state.md'


def method_digest(node):
    # Keep the frozen Python 3.12 representation on newer operator hosts.
    # Python 3.13+ omits optional empty lists unless explicitly requested.
    options = {'include_attributes': False}
    if sys.version_info >= (3, 13):
        options['show_empty'] = True
    return digest_bytes(ast.dump(node, **options).encode())


def test_methods(source):
    tree = ast.parse(source); result = {}
    for parent in ast.walk(tree):
        if not isinstance(parent, ast.ClassDef): continue
        for node in parent.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                result[parent.name+'.'+node.name] = method_digest(node)
    return result


def source_check():
    policy = json.loads(LOCK.read_text()); manifest = json.loads(MANIFEST.read_text())
    require(not LOCK.is_symlink() and not MANIFEST.is_symlink() and policy['change'] == manifest['change'] == 'CR-012'
        and policy['status'] == manifest['status'] == 'Prepared' and manifest['source_lock_sha256'] == digest_bytes(LOCK.read_bytes()),
        'The prepared CR012 source identity differs')
    require(policy['expected_suite'] == 1387 and policy['old_suite'] == 1307 and policy['new_test_methods'] == 80 and policy['old_migrations'] == 40
        and policy['new_migrations'] == 2 and policy['retained_tool_guards'] == 176, 'Keep the selected source/gate scope')
    require(policy.get('operator_preserved_paths') == ['AGENTS.md', STATE]
        and 'AGENTS.md' not in policy['files'] and 'AGENTS.md' not in policy['baseline_files']
        and not image.allowed('AGENTS.md'), 'Preserve operator instructions outside application source binding')
    retained_instructions = preserved_operator_files(ROOT)
    if (ROOT/BASELINE).exists():
        require((ROOT/BASELINE).is_file() and not (ROOT/BASELINE).is_symlink(), 'Retain the regular CR012 preparation binding')
        baseline = json.loads((ROOT/BASELINE).read_text())
        require(baseline.get('binding_schema') == 1 and baseline.get('preserved_operator_files') == retained_instructions,
            'Operator AGENTS.md changed after its preserved preparation binding')
    for name, digest in policy['files'].items():
        path = ROOT/name
        require(not Path(name).is_absolute() and '..' not in Path(name).parts and path.is_file()
            and not path.is_symlink() and path.resolve().is_relative_to(ROOT.resolve())
            and digest_bytes(path.read_bytes()) == digest, 'Prepared CR012 source changed: '+name)
    for name, methods in policy['retained_test_methods'].items():
        actual = test_methods((ROOT/name).read_text())
        require(all(actual.get(k) == v for k, v in methods.items()), 'An original contract method changed: '+name)
    for name, digest in policy['old_migration_files'].items():
        require(digest_bytes((ROOT/name).read_bytes()) == digest, 'An old migration changed: '+name)
    context = image.candidate_context()[1]
    require(context['digest'] == policy['application_context_digest'] and context['file_count'] == policy['application_inputs'],
        'The current prepared application context differs')
    count = sum(isinstance(n, ast.FunctionDef) and n.name.startswith('test_')
        for name in ('accounting/tests_demand_charges.py', 'accounting/tests_charge_cash.py', 'accounting/tests_demand_migration.py')
        for n in ast.walk(ast.parse((ROOT/name).read_text())))
    require(count == 80, 'Keep all new native contracts')
    from preview_cr008_policy import unchanged_acceptances
    unchanged_acceptances(ROOT)
    return policy, len(policy['files']), inspect(ROOT)


def clean_source():
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(),
        'Commit source first; unrelated local changes were retained')


def record(report):
    clean_source(); source_check(); bound = verify_binding(ROOT)
    require(report['source_commit'] == 'git:'+subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        and report['status'] == 'Verified' and report['suite']['tests_run'] == report['suite']['tests_passed'] == 1387
        and report['actual_prior_receipt_files_sha256'] == bound['files']
        and report['preserved_operator_files_sha256'] == bound['preserved_operator_files'], 'Record only this actual successful result')
    target = ROOT/REPORT
    require(not target.exists() and not target.is_symlink(), 'An earlier CR012 result already exists; retain it for review')
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    state = ROOT/STATE; before = state.read_bytes()
    require(b'<!-- CR012-RESULT -->' not in before, 'Keep an existing CR012 result marker')
    state.write_bytes(before+b'\n\n<!-- CR012-RESULT -->\nVerified: 1387 isolated PG17 contracts, 36 financial cases, 176 retained deployment guards, demand charges/budget/selected-charge cash and credit contracts, retained direct credentials and real Excel/file antivirus,65-table encrypted recovery, retained real worker. New source verified by operator; VM upgrade and browser/business acceptance Pending; all85 full acceptances Pending.\n<!-- /CR012-RESULT -->\n')
    changed = set(subprocess.check_output(['git', 'diff', '--name-only', 'HEAD'], cwd=ROOT, text=True).splitlines())
    untracked = set(subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT, text=True).splitlines())
    allowed = {REPORT, STATE}
    require(changed|untracked == allowed, 'Only the exact native result and tracking may be committed')
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'add', '--', *sorted(allowed)], cwd=ROOT, check=True)
    subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'commit', '-m', 'docs: record actual successful CR012 operator verification', '--', *sorted(allowed)], cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only', action='store_true'); parser.add_argument('--record', action='store_true')
    option = parser.add_mutually_exclusive_group(); option.add_argument('--host-dns', action='store_true'); option.add_argument('--image')
    args = parser.parse_args()
    if args.source_only and (args.record or args.host_dns or args.image): parser.error('--source-only accepts no runtime options')
    stage = 'source-preflight'
    try:
        policy, count, static = source_check()
        bound = verify_binding(ROOT) if (ROOT/BASELINE).exists() else None
        if args.source_only:
            print(json.dumps({'change': 'CR-012', 'status': 'Prepared', 'source_files_checked': count,
                'application_inputs': policy['application_inputs'], 'runtime_executed': False,
                'actual31_prior_reports_bound': bound is not None, 'static': static}, ensure_ascii=False)); return
        clean_source(); bound = verify_binding(ROOT)
        if args.record:
            require(not (ROOT/REPORT).exists() and not (ROOT/REPORT).is_symlink()
                and b'<!-- CR012-RESULT -->' not in (ROOT/STATE).read_bytes(),
                'An earlier CR012 recording already exists; retain it for review before repeating --record')
        require_local_docker()
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        stage = 'retained176-deployment-guards'
        subprocess.run([sys.executable, str(ROOT/'tools/run_cr012_tool_guards.py')], cwd=ROOT, check=True)
        stage = 'new-production-image'
        if args.image: selected = image.reuse_for_verification(args.image)
        elif args.host_dns:
            from build_host_dns import build
            selected = build()
        else: selected = image.build()
        with tempfile.TemporaryDirectory(prefix='accounting-cr012-') as directory:
            folder = Path(directory); destination = folder/'delivery.json'; stage = 'full-production-pg17-delivery'
            subprocess.run([sys.executable, str(ROOT/'tools/verify_delivery.py'), '--report', str(destination), '--image', selected['image_id']], cwd=ROOT, check=True)
            delivery = json.loads(destination.read_text()); suite = delivery['suite']
            retained = ROOT/'private/cr012'/selected['image_id'].removeprefix('sha256:')
            retained.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(mode='w', prefix='delivery-'+revision+'-', suffix='.json', dir=retained, delete=False) as stream:
                json.dump(delivery, stream, ensure_ascii=False, indent=2); stream.write('\n')
            require(suite['tests_run'] == suite['tests_passed'] == 1387 and all(suite[k] == 0 for k in (
                'known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')),
                'Every retained and new contract must pass')
            require(len(suite['cases']) == 36 and all(c['outcome'] == 'passed' for c in suite['cases']), 'All36 finance cases must pass')
            require(len([n for n in delivery['applied_migrations'] if n.startswith('accounting.')]) == 42,
                'Exactly the retained40 and new0041/0042 migrations are required')
            require(delivery['image']['context']['digest'] == policy['application_context_digest'], 'Verify this exact source image')
            stage = 'real-selected-charge-and-retained-excel-files-recovery'
            from cr012_files_gate import files_gate
            files = files_gate(folder, selected['image_id'], host_dns=args.host_dns)
            require(files['all_public_tables_restored'] == 65 and files['restored_files'] == 10
                and files['demand_charges_recovered'] is True and files['cash_charge_selection_recovered'] is True
                and all(files['charge_workflow'].values()) and files['excel_recovery_verified'] is True
                and all(files['excel_import'].values()) and files['staff_credentials_recovered'] is True
                and all(files['staff_credentials'].values()), 'Real selected-charge cash/credit, credentials, Excel antivirus and all65-table recovery are required')
            stage = 'retained-real-monthly-worker'
            from s28_broker_gate import broker_gate
            broker = broker_gate(folder, selected['image_id'])
        source_check(); verify_binding(ROOT); clean_source()
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == revision, 'Source moved during verification')
        report = {'change': 'CR-012', 'status': 'Verified', 'source_status': 'Prepared',
            'scope': 'isolated-production-pg17-demand-charges-budget-selected-cash-credit-and-retained-excel-files-worker',
            'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit': 'git:'+revision, 'image': delivery['image'], 'application_context_digest': policy['application_context_digest'],
            'suite': suite, 'new_test_methods': 80, 'retained_source_files_checked': count, 'static': static,
            'secret_scan': delivery['secret_scan'], 'private_files': files,
            'real_monthly_worker_and_commit_before_ack': True, 'revocation_blocks_execution': broker['revocation_blocks_execution'],
            'second_scheduler_rejected': broker['second_scheduler_rejected'], 'restricted_role_migrations': broker['restricted_role_migrations'],
            'original_40_migrations_unchanged': True, 'new_migrations': 2, 'historical_receipts_unchanged': True,
            'actual_prior_receipt_files_sha256': bound['files'], 'docker_execution_by_operator': True, 'agent_native_execution': False,
            'preserved_operator_files_sha256': bound['preserved_operator_files'],
            'prior_completed_vm_record': bound['previous_completed_vm_record'],
            'prior_cr011_record': bound['previous_native_result'], 'deployment_guard_tests_passed': 176,
            'local_demo_or_vm_changed': False, 'github_updated': False, 'human_accounts_or_mfa_changed': False,
            'real_workbook_imported': False, 'owned_resources_removed': True, 'full_requirement_acceptances_pending': 85,
            'accountant_browser_acceptance': 'Pending', 'g2_release_acceptance': 'Pending', 'vm_upgrade': 'Pending separate rollout'}
        if args.record: record(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, AssertionError, subprocess.SubprocessError) as error:
        print('CR012-DIAG '+json.dumps({'stage': stage, 'error': type(error).__name__}), file=sys.stderr)
        parser.exit(1, 'CR-012 stopped: '+str(error)+'\n')


if __name__ == '__main__':
    main()
