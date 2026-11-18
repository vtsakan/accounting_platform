#!/usr/bin/env python3
"""Operator-only S31 technical rehearsal. Live release always remains Blocked."""
import argparse
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
import operations_common as common
from r1_gate import BASE_BLOCKERS, digest_bytes, digest_object, matrix, pending_review, preserved, profile, require, technical_valid
from s28_broker_gate import broker_gate
from s31_rehearsal import rehearse
from s31_receipts import BINDING
from s31_evidence import BINDING as EVIDENCE_BINDING

DOCS = ROOT / 'docs/implementation'


def receipts():
    return {p.name: digest_bytes(p.read_bytes()) for p in (DOCS / 'evidence').iterdir()
            if p.is_file() and not p.name.startswith('S31')}


def host_contracts():
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'tools'), '-p', 'test_s31.py'],
                            cwd=ROOT, text=True, capture_output=True)
    count = re.search(r'Ran (\d+) tests?', result.stdout + result.stderr)
    require(result.returncode == 0 and count and int(count.group(1)) == 20, 'Twenty S31 host contracts required:\n' + result.stderr[-3000:])
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'tools'), '-p', 'test_s31_receipts.py'],
                            cwd=ROOT, text=True, capture_output=True)
    count = re.search(r'Ran (\d+) tests?', result.stdout + result.stderr)
    require(result.returncode == 0 and count and int(count.group(1)) == 12,
            'Twelve operator-receipt contracts required:\n' + result.stderr[-3000:])
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT / 'tools'), '-p', 'test_s31_evidence.py'],
                            cwd=ROOT, text=True, capture_output=True)
    count = re.search(r'Ran (\d+) tests?', result.stdout + result.stderr)
    require(result.returncode == 0 and count and int(count.group(1)) == 8,
            'Eight supplementary-evidence contracts required:\n' + result.stderr[-3000:])
    return 40


def select_image(args):
    if args.image:
        return image.reuse_for_verification(args.image)
    previous = json.loads((DOCS / 'evidence/S30-verification.json').read_text())
    require(previous['status'] == 'Verified', 'Retain the actual S30 Verified receipt')
    reference = previous['image']['image_id']
    if image.inspect(reference) is not None:
        return image.reuse_for_verification(reference)
    if args.host_dns:
        from build_host_dns import build
        return build()
    return image.build()


def broker_resource_labels(proof):
    """Keep measured service stats without new random names in public receipts."""
    rows = []
    for row in proof['resource_sample']:
        match = re.fullmatch(r'accounting-s28-[0-9a-f]{20}-(worker|scheduler)-1', row['name'])
        require(match is not None, 'Unexpected real-broker resource identity')
        rows.append({'service': match.group(1), 'memory': row['memory'], 'cpu': row['cpu']})
    require(len(rows) == 2 and {row['service'] for row in rows} == {'worker', 'scheduler'}, 'Worker and scheduler resource samples required')
    return proof | {'resource_sample': rows}


def private_review(report):
    directory = ROOT / 'private/s31' / report['rehearsal']['nonce']
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    template = pending_review(report['source_commit'], report['application_context_digest'], digest_object(report),
                              report['matrix_sha256'], report['workload_sha256'])
    path = directory / 'R1-review.json'
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + '\n'); path.chmod(0o600)
    # Review references contain names/observations; this directory stays ignored.
    ignored = subprocess.run(['git', 'check-ignore', '--quiet', str(path.relative_to(ROOT))], cwd=ROOT)
    require(ignored.returncode == 0, 'Private named reviews must stay ignored by Git')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true')
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--image'); selection.add_argument('--host-dns', action='store_true')
    parser.add_argument('--identity', default=str(Path.home() / '.config/totalaccounting/recovered-backup-age.key'))
    args = parser.parse_args(); stage = 'source-preflight'
    try:
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(), 'Commit source before S31 verification')
        source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        retained = preserved(ROOT, DOCS / 'evidence/S31-preserved-source.json')
        require(retained == 592, 'Every original S31 source/receipt binding must remain protected')
        rows = matrix(ROOT); workload = profile(json.loads((DOCS / 'r1_workload.json').read_text()))
        contracts = host_contracts(); historical = receipts()
        context = image.candidate_context()[1]
        require(context['file_count'] == 284 and context['digest'] == json.loads((DOCS / 'evidence/S30-verification.json').read_text())['application_context_digest'],
                'S31 must preserve the exact S30 application context')
        # Fast failure before the lengthy delivery suite if the operator's
        # independently recovered, externally stored age identity is unavailable.
        common.check_age(); common.identity_file(args.identity); common.require_tmpfs('/dev/shm')
        require_local_docker(); stage = 'immutable-production-image'; selected = select_image(args)
        with tempfile.TemporaryDirectory(prefix='accounting-s31-delivery-') as directory:
            stage = 'full-retained-production-848-and-36'
            destination = Path(directory) / 'delivery.json'
            subprocess.run([sys.executable, str(ROOT / 'tools/verify_delivery.py'), '--report', str(destination), '--image', selected['image_id']], cwd=ROOT, check=True)
            delivery = json.loads(destination.read_text()); suite = delivery['suite']
            require(suite['tests_run'] == 848 and suite['tests_passed'] == 848 and not any(suite[k] for k in
                ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')),
                'Every retained application test must pass')
            require(len(suite['cases']) == 36 and all(c['outcome'] == 'passed' for c in suite['cases']), 'All 36 financial cases must pass')
            require(delivery['secret_scan']['unreviewed_findings'] == 0 and delivery['dependency_locks_reproduced'] is True
                    and delivery['compiled_catalog_in_sync'] is True, 'Current source scan, reproduced locks and Greek catalog required')
            stage = 'retained-real-scheduler-redis-commit-before-ack'
            broker = broker_resource_labels(broker_gate(Path(directory), selected['image_id']))
        stage = 'synthetic-migration-cycle-http-load-and-encrypted-recovery'
        rehearsal = rehearse(selected['image_id'], context['digest'], args.identity, workload)
        preserved(ROOT, DOCS / 'evidence/S31-preserved-source.json')
        require(historical == receipts(), 'Historical evidence changed')
        require(image.candidate_context()[1]['digest'] == context['digest']
                and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == source
                and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(),
                'Source changed during verification')
        passed = rehearsal['performance']['thresholds_passed'] and rehearsal['recovery']['proposed_targets_met_in_this_rehearsal']
        report = {'step': 'S31', 'status': 'Prepared', 'technical_status': 'Verified' if passed else 'Failed',
            'scope': 'synthetic-isolated-finance-release-rehearsal',
            'checked_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit': 'git:' + source,
            'application_context_digest': context['digest'], 'image': delivery['image'], 'suite': suite,
            'delivery_proof': {key: delivery[key] for key in ('secret_scan', 'deployment_checks', 'dependency_locks_reproduced',
                'compiled_catalog_in_sync', 'static_export_host_checks', 'committed_context_policy', 'applied_migrations',
                'gunicorn_http_verified', 'readiness_outage_recovery_verified', 'greek_login_verified',
                'query_string_excluded_from_access_log', 'admin_manifest_references_verified',
                'container_uid', 'image_private_file_audit_passed', 'untracked_source_canary_excluded',
                'static_export_from_same_image_verified')},
            'retained_source_files_checked': retained, 'host_contracts_passed': contracts,
            'operator_receipt_binding_sha256': digest_bytes((ROOT / BINDING).read_bytes()),
            'historical_evidence_binding_sha256': digest_bytes((ROOT / EVIDENCE_BINDING).read_bytes()),
            'r1_user_requirements': 33, 'r1_quality_requirements': 9, 'r1_acceptance_rows': len(rows),
            'matrix_sha256': digest_object(json.loads((DOCS / 'r1_acceptance_matrix.json').read_text())),
            'workload_sha256': digest_object(workload), 'rehearsal': rehearsal,
            'release_decision': 'Blocked', 'release_blockers': BASE_BLOCKERS + ([] if passed else ['Synthetic performance/recovery targets did not pass']),
            'full_requirement_acceptance': 'Pending', 'full_requirement_acceptances_pending': 85,
            'd05_real_migration_review': 'Pending', 'g2_release_acceptance': 'Pending', 'accepted_dataset_rpo_rto': 'Pending',
            'document_recovery': 'Pending S38; synthetic media empty', 'Greek_browser_email_PDF_visual_acceptance': 'Pending',
            'historical_receipts_unchanged': True, 'owned_resources_removed': True,
            'docker_execution_by_operator': True, 'agent_tests_builds_docker_migrations_run': False,
            'local_demo_or_vm_changed': False, 'human_accounts_or_mfa_changed': False, 'real_client_data_imported': False,
            'live_cutover_executed': False, **broker}
        if passed:
            technical_valid(report)
        review_path = private_review(report)
        if args.record:
            from prepare_s31 import record_result
            record_result(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print('[S31] Πρότυπο ιδιωτικής ανθρώπινης αποδοχής: ' + str(review_path), flush=True)
        print('[S31] Πραγματική έκδοση: Blocked. Δεν έγινε μετάβαση τοπικού demo ή VM.', flush=True)
        if not passed:
            parser.exit(1, 'S31: οι συνθετικοί στόχοι δεν πέρασαν· οι μετρήσεις καταγράφηκαν χωρίς αλλαγή στόχων.\n')
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, AssertionError) as error:
        from verify_s05 import redact
        print('S31-DIAG ' + json.dumps({'stage': stage, 'error': type(error).__name__}), file=sys.stderr)
        parser.exit(1, 'S31 stopped: ' + redact(str(error)) + '\n')


if __name__ == '__main__':
    main()
