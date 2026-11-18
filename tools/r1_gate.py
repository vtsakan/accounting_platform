"""Pure R1 acceptance/provenance rules. No application or deployment actions."""
import csv
import hashlib
import json
import math
from pathlib import Path
import re

USER_IDS = frozenset(
    [f'UR-OFF-{n:02}' for n in range(1, 8)]
    + [f'UR-CRM-{n:02}' for n in (1, 2, 3, 6, 7)]
    + [f'UR-CSH-{n:02}' for n in range(1, 8)]
    + [f'UR-AGR-{n:02}' for n in range(1, 6)]
    + [f'UR-BIL-{n:02}' for n in range(1, 5)]
    + [f'UR-REP-{n:02}' for n in range(1, 5)] + ['UR-LOC-01'])
QUALITY_IDS = frozenset(f'QR-{n:02}' for n in (1, 2, 3, 4, 5, 7, 9, 12, 14))
R1_IDS = USER_IDS | QUALITY_IDS
SHA = re.compile(r'sha256:[0-9a-f]{64}')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest_bytes(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def digest_object(value):
    return digest_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())


def preserved(root, manifest):
    value = json.loads(Path(manifest).read_text())
    entries = value.get('sha256')
    require(isinstance(entries, dict) and entries, 'Invalid nonempty S31 preservation manifest')
    for name, digest in entries.items():
        require(isinstance(name, str) and not Path(name).is_absolute() and '..' not in Path(name).parts
                and isinstance(digest, str) and SHA.fullmatch(digest), 'Invalid retained source binding')
        path = Path(root) / name
        require(path.is_file() and not path.is_symlink() and digest_bytes(path.read_bytes()) == digest,
                'Retained source or historical receipt changed: ' + name)
    extensions = value.get('append_only_files', {})
    require(isinstance(extensions, dict), 'Invalid append-only source bindings')
    for name, row in extensions.items():
        require(name == 'docs/security/secret_scan_allowlist.csv' and name not in entries
                and isinstance(row, dict) and set(row) == {'original_bytes', 'original_sha256', 'suffix_sha256', 'after_sha256'},
                'Only the published exact scanner-review append is permitted')
        require(type(row['original_bytes']) is int and row['original_bytes'] > 0
                and all(isinstance(row[k], str) and SHA.fullmatch(row[k]) for k in ('original_sha256', 'suffix_sha256', 'after_sha256')),
                'Invalid canonical append-only binding')
        path = Path(root) / name
        require(path.is_file() and not path.is_symlink(), 'Missing append-only review source')
        data = path.read_bytes(); boundary = row['original_bytes']
        require(len(data) > boundary and digest_bytes(data[:boundary]) == row['original_sha256']
                and digest_bytes(data[boundary:]) == row['suffix_sha256'] and digest_bytes(data) == row['after_sha256'],
                'Historical scanner reviews or exact published additions changed')
    return len(entries) + len(extensions)


def matrix(root):
    docs = Path(root) / 'docs/implementation'
    rows = json.loads((docs / 'r1_acceptance_matrix.json').read_text())['requirements']
    ids = [row['requirement_id'] for row in rows]
    require(len(ids) == 42 and len(set(ids)) == 42 and set(ids) == R1_IDS, 'All 33 R1 UR and nine QR are required')
    with (docs / 'traceability.csv').open(newline='') as stream:
        trace = {row['requirement_id']: row for row in csv.DictReader(stream)}
    require(len(trace) == 85 and all(row['acceptance_status'] == 'Pending' for row in trace.values()),
            'This source-only gate preserves all 85 Pending acceptances; review any actual acceptance change explicitly')
    require({key for key, row in trace.items() if row['release'] == 'R1' and row['priority'] == 'Must'} == R1_IDS,
            'The effective R1 baseline changed; review it explicitly')
    for row in rows:
        source = trace[row['requirement_id']]
        for key in ('acceptance_test_id', 'statement', 'acceptance_check'):
            require(row[key] == source[key], 'Acceptance criterion changed: ' + row['requirement_id'])
        require(row['acceptance_status'] == 'Pending' and row['manual_procedure_el'] and row['candidate_evidence'],
                'A proposed procedure is not acceptance')
        for name in row['candidate_evidence']:
            require(not Path(name).is_absolute() and '..' not in Path(name).parts and (Path(root) / name).is_file(),
                    'Missing candidate evidence: ' + name)
    return rows


def profile(value):
    require(isinstance(value, dict) and value.get('schema') == 1 and value.get('approval') == 'Pending',
            'S31 uses an explicitly unapproved synthetic workload')
    expected = {'sessions': 50, 'cycles_per_session': 3, 'clients': 200, 'charges': 200,
                'ordinary_movements': 2000, 'window_days': 365, 'request_timeout_seconds': 45,
                'web_workers': 2, 'web_memory_mib': 1024, 'database_memory_mib': 1024,
                'web_cpus': 2, 'database_cpus': 2}
    require(value.get('synthetic_envelope') == expected, 'Review a changed workload; do not lower the supplied gate')
    require(value.get('proposed_p95_seconds') == {'list': 2, 'detail': 2, 'annual_report': 10}, 'Unexpected p95 targets')
    require(value.get('proposed_recovery') == {'rpo_seconds': 86400, 'rto_seconds': 28800}, 'Unexpected recovery targets')
    require(value.get('model') == 'closed-loop-barrier-50-distinct-sessions-one-synthetic-accountant', 'Unknown workload model')
    return value


def percentile95(samples):
    require(isinstance(samples, list) and samples and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in samples),
            'p95 needs nonempty finite nonnegative elapsed seconds')
    return sorted(samples)[math.ceil(len(samples) * .95) - 1]


def performance_result(samples, errors, workload):
    profile(workload)
    expected = workload['synthetic_envelope']['sessions'] * workload['synthetic_envelope']['cycles_per_session']
    require(set(samples) == {'list', 'detail', 'annual_report'} and isinstance(errors, list), 'Incomplete HTTP measurement')
    rows = {}
    for key, values in samples.items():
        require(len(values) == expected, 'Every attempt including failures must contribute elapsed time')
        p95 = percentile95(values)
        rows[key] = {'attempts': len(values), 'p95_seconds': p95, 'max_seconds': max(values),
                     'target_seconds': workload['proposed_p95_seconds'][key],
                     'target_met': p95 <= workload['proposed_p95_seconds'][key]}
    return {'operations': rows, 'errors': len(errors), 'thresholds_passed': not errors and all(r['target_met'] for r in rows.values()),
            'workload_approval': 'Pending', 'production_capacity_accepted': False,
            'timing_scope': 'loopback HTTP through production Gunicorn; queueing and complete body read included; TLS excluded',
            'arrival_model': workload['model'], 'percentile_method': 'nearest-rank ceil(0.95*N), no discarded slow or failed attempts'}


def technical_valid(report):
    require(report.get('step') == 'S31' and report.get('scope') == 'synthetic-isolated-finance-release-rehearsal', 'Not an S31 receipt')
    require(report.get('status') == 'Prepared' and report.get('release_decision') == 'Blocked', 'Synthetic proof cannot accept a live release')
    require(report.get('full_requirement_acceptance') == 'Pending' and report.get('full_requirement_acceptances_pending') == 85,
            'Full acceptances must remain pending')
    suite = report.get('suite', {})
    require(suite.get('tests_run') == 848 and suite.get('tests_passed') == 848 and len(suite.get('cases', [])) == 36
            and all(row.get('outcome') == 'passed' for row in suite['cases'])
            and not any(suite.get(key, 1) for key in ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')),
            'The complete retained 848/36 gate is required')
    generation = report.get('s28_generation', {})
    ack = generation.get('commit_before_ack', {})
    require(report.get('technical_status') == 'Verified' and generation.get('automatic', {}).get('scheduler_discovered') is True
            and ack.get('committed_receipt_survived_child_sigkill') is True and ack.get('task_deliveries', 0) >= 2
            and ack.get('charge_count') == 1 and generation.get('reconciliation', {}).get('cash_entries') == 0,
            'Current technical and real worker evidence required')
    rehearsal = report.get('rehearsal', {})
    require(rehearsal.get('performance', {}).get('thresholds_passed') is True and rehearsal.get('cycle', {}).get('passed') is True,
            'Measured performance or complete cycle did not pass')
    recovery = rehearsal.get('recovery', {})
    require(all(recovery.get(k) is True for k in ('all_public_tables_matched', 'required_synthetic_key_material_recovered',
            'wrong_signing_key_denied', 'restored_http_200', 'baseline_20_rollback_matched', 'source_original_unchanged')),
            'Complete encrypted data/key/rollback recovery required')
    require(recovery.get('proposed_targets_met_in_this_rehearsal') is True, 'Measured synthetic recovery targets required')
    require(report.get('owned_resources_removed') is True and rehearsal.get('plaintext_removed') is True, 'Owned cleanup required')
    return True


BASE_BLOCKERS = [
    'Named accountant and product-owner application acceptance of all 42 R1 checks is Pending',
    'D06 workload/dataset, p95, availability and budget approval is Pending',
    'D07 operational responsibilities, accepted real-data recovery/key custody and retention are Pending',
    'D05 real ownership/opening/exception mapping and reconciled totals or explicitly approved new-office scope are Pending',
    'Greek browser/email/PDF visual review and actual HTTPS/privileged-MFA review are Pending',
    'A named authorised first-office environment, freeze/window, current backup and controlled live cutover are Pending',
    'G2 release acceptance is Pending; a synthetic gate never authorises live use',
]


def pending_review(source_commit, context_digest, report_digest, matrix_digest, workload_digest):
    return {'schema': 1, 'scope': 'declared-human-R1-application-review',
            'bindings': {'source_commit': source_commit, 'application_context_digest': context_digest,
                         'technical_report_sha256': report_digest, 'matrix_sha256': matrix_digest, 'workload_sha256': workload_digest},
            'accountant': {'name': '', 'role': 'accountant', 'reviewed_at': '', 'reference': ''},
            'product_owner': {'name': '', 'role': 'product-owner', 'reviewed_at': '', 'reference': ''},
            'same_person_for_both_roles_explicitly_confirmed': False,
            'requirements': {key: {'status': 'Pending', 'observed_reference': '', 'observed_sha256': '', 'reviewed_at': ''} for key in sorted(R1_IDS)},
            'approvals': {key: {'status': 'Pending', 'reference': '', 'sha256': ''} for key in
                          ('workload_and_targets', 'real_data_recovery_and_keys', 'incident_and_restore_owners',
                           'retention', 'd05_ownership_and_reconciliation', 'greek_visual_and_https_mfa', 'g2')},
            'first_office': {'status': 'Blocked', 'environment': '', 'office': '', 'window': '', 'freeze_owner': '',
                             'rollback_owner': '', 'authorisation_reference': '', 'authorisation_sha256': '',
                             'backup_reference': '', 'backup_sha256': '', 'cutover_executed': False}}


def review_blockers(review, expected):
    """A declared review is not independently authenticated identity or a cutover."""
    require(isinstance(review, dict) and review.get('schema') == 1 and review.get('scope') == expected['scope'], 'Unknown review schema/scope')
    require(review.get('bindings') == expected['bindings'], 'Stale review source/image/report/matrix/workload binding')
    require(isinstance(review.get('requirements'), dict) and set(review['requirements']) == R1_IDS, 'All 42 review rows are mandatory')
    require(isinstance(review.get('approvals'), dict) and set(review['approvals']) == set(expected['approvals']), 'Missing approval categories')
    blockers = []
    def text(value):
        return isinstance(value, str) and 1 <= len(value) <= 500 and not any(ord(c) < 32 for c in value)
    def dated(value):
        from datetime import datetime
        try:
            moment = datetime.fromisoformat(value)
            return moment.tzinfo is not None
        except (ValueError, TypeError):
            return False
    for role in ('accountant', 'product_owner'):
        person = review.get(role, {})
        if person.get('role') != expected[role]['role'] or not all(text(person.get(k)) for k in ('name', 'reference')) or not dated(person.get('reviewed_at')):
            blockers.append(role + ': named, dated declared application review required')
    if review.get('accountant', {}).get('name') == review.get('product_owner', {}).get('name') and review.get('same_person_for_both_roles_explicitly_confirmed') is not True:
        blockers.append('Explicit confirmation required if one person acts in both reviewer roles')
    for key, row in review['requirements'].items():
        if not isinstance(row, dict) or row.get('status') != 'Passed' or not text(row.get('observed_reference')) or not SHA.fullmatch(str(row.get('observed_sha256', ''))) or not dated(row.get('reviewed_at')):
            blockers.append(key + ': actual bound observation and dated human acceptance required')
    for key, row in review['approvals'].items():
        if not isinstance(row, dict) or row.get('status') != 'Approved' or not text(row.get('reference')) or not SHA.fullmatch(str(row.get('sha256', ''))):
            blockers.append(key + ': explicit approval evidence required')
    office = review.get('first_office', {})
    if not all(text(office.get(k)) for k in ('environment', 'office', 'window', 'freeze_owner', 'rollback_owner', 'authorisation_reference', 'backup_reference')) or not all(SHA.fullmatch(str(office.get(k, ''))) for k in ('authorisation_sha256', 'backup_sha256')):
        blockers.append('First-office identity, freeze/window, owners, authorisation and exact backup references required')
    # This source-only evaluator never operates an environment or converts a
    # self-declared JSON flag into evidence that a live cutover succeeded.
    blockers.append('Controlled live cutover and post-cutover accountant/G2 decision require separately observed execution')
    return blockers
