"""Preserve supplementary historical metadata as data, never as source hashes.

The original 35 operator-result contracts stay in s31_receipts unchanged.
This separate inventory covers the preparation/fix/provenance documents too.
"""
import csv
import io
import json
import os
from pathlib import Path
import re
from s31_receipts import SHA, RECEIPTS, canonical, need, read_regular, sha, strict_json

BINDING = 'docs/implementation/evidence/S31-historical-evidence.json'
SCOPE = 'supplementary-historical-evidence-captured-before-S31-without-new-acceptance'
PATHS = (
    'docs/implementation/evidence/S05-native-provenance.json',
    'docs/implementation/evidence/S06-regression-baseline.csv',
    'docs/implementation/evidence/S07-configuration-checks.json',
    'docs/implementation/evidence/S07-download-timeout-fix.json',
    'docs/implementation/evidence/S07-static-export-fix.json',
    'docs/implementation/evidence/S09-deployment-retry.json',
    'docs/implementation/evidence/S09-image-identity.json',
    'docs/implementation/evidence/S10-cloud-request-fix.json',
    'docs/implementation/evidence/S10-systemd-status-fix.json',
    'docs/implementation/evidence/S13-dependencies.json',
    'docs/implementation/evidence/S13-environment-fix.json',
    'docs/implementation/evidence/S14-referrer-fix.json',
    'docs/implementation/evidence/S14A-demo-preparation.json',
    'docs/implementation/evidence/S14A-operator-report.json',
    'docs/implementation/evidence/S15-browser-attempt.json',
    'docs/implementation/evidence/S16-baseline-findings.json',
    'docs/implementation/evidence/S17-checker-controls.json',
    'docs/implementation/evidence/S17-product-owner-acceptance.json',
    'docs/implementation/evidence/S17-reference-checks.csv',
    'docs/implementation/evidence/S20-template-fix.json',
    'docs/implementation/evidence/S21-fixture-fix.json',
    'docs/implementation/evidence/S22-context-fix.json',
    'docs/implementation/evidence/S23-preserved-source.json',
    'docs/implementation/evidence/S23-test-fix.json',
    'docs/implementation/evidence/S24-VM-deployment.json',
    'docs/implementation/evidence/S24-VM-preparation.json',
    'docs/implementation/evidence/S24-VM-retry.json',
    'docs/implementation/evidence/S24-locking-csrf-fix.json',
    'docs/implementation/evidence/S24-preserved-source.json',
    'docs/implementation/evidence/S24A-VM-preparation.json',
    'docs/implementation/evidence/S24A-local-deployment.json',
    'docs/implementation/evidence/S24A-local-preview-fix.json',
    'docs/implementation/evidence/S24A-local-upgrade.json',
    'docs/implementation/evidence/S25-allocation-key-fix.json',
    'docs/implementation/evidence/S25-operator-completion.json',
    'docs/implementation/evidence/S25-postgres-pair-fix.json',
    'docs/implementation/evidence/S25-restore-fix.json',
    'docs/implementation/evidence/S25-tmpfs-fix.json',
    'docs/implementation/evidence/S26-hash-fix-source.json',
    'docs/implementation/evidence/S26-hash-fix.json',
    'docs/implementation/evidence/S26-migration-fix-source.json',
    'docs/implementation/evidence/S26-migration-fix.json',
    'docs/implementation/evidence/S26-preserved-source.json',
    'docs/implementation/evidence/S26-probe-path-fix-source.json',
    'docs/implementation/evidence/S26-probe-path-fix.json',
    'docs/implementation/evidence/S26-redelivery-fix-source.json',
    'docs/implementation/evidence/S26-redelivery-fix.json',
    'docs/implementation/evidence/S26-source.json',
    'docs/implementation/evidence/S26-static-checks.json',
    'docs/implementation/evidence/S27-preserved-source.json',
    'docs/implementation/evidence/S27-quote-input-fix-source.json',
    'docs/implementation/evidence/S27-quote-input-fix.json',
    'docs/implementation/evidence/S27-source-check-fix-source.json',
    'docs/implementation/evidence/S27-source-check-fix.json',
    'docs/implementation/evidence/S27-source.json',
    'docs/implementation/evidence/S27-static-checks.json',
    'docs/implementation/evidence/S27-static-secret-review.json',
    'docs/implementation/evidence/S27-test-source-bindings.json',
    'docs/implementation/evidence/S28-cli-boundary-fix-source.json',
    'docs/implementation/evidence/S28-cli-boundary-fix.json',
    'docs/implementation/evidence/S28-preserved-source.json',
    'docs/implementation/evidence/S28-source.json',
    'docs/implementation/evidence/S28-static-checks.json',
    'docs/implementation/evidence/S29-adjustment-date-fix-source.json',
    'docs/implementation/evidence/S29-adjustment-date-fix.json',
    'docs/implementation/evidence/S29-preserved-source.json',
    'docs/implementation/evidence/S29-source.json',
    'docs/implementation/evidence/S29-static-checks.json',
    'docs/implementation/evidence/S30-preserved-source.json',
    'docs/implementation/evidence/S30-source.json',
    'docs/implementation/evidence/S30-static-checks.json',
)
CSV_HEADERS = {
    'docs/implementation/evidence/S06-regression-baseline.csv':
        ['case_id','issue_id','test','expected_outcome','outcome','required','observed','requirements','fix_steps'],
    'docs/implementation/evidence/S17-reference-checks.csv':
        ['example','check','formula','expected','observed','result','business_approval','application_execution'],
}


def validate_policy(policy):
    need(isinstance(policy, dict) and set(policy) == {'schema','binding_file','paths'}, 'Invalid historical evidence policy')
    need(type(policy['schema']) is int and policy['schema'] == 1 and policy['binding_file'] == BINDING,
         'Only the published supplementary-evidence binding is permitted')
    need(isinstance(policy['paths'], list) and policy['paths'] == list(PATHS)
         and not set(PATHS) & set(RECEIPTS), 'Supplementary paths must equal the exact published disjoint inventory')
    return policy


def validate_document(name, data):
    if name in CSV_HEADERS:
        try:
            reader = csv.DictReader(io.StringIO(data.decode('utf-8')))
            need(reader.fieldnames == CSV_HEADERS[name], 'Unexpected historical evidence CSV header')
            rows = list(reader)
            need(rows and all(set(row) == set(reader.fieldnames) and
                 all(isinstance(value, str) for value in row.values()) for row in rows), 'Malformed historical evidence CSV')
        except (UnicodeError, csv.Error):
            raise RuntimeError('Malformed historical evidence CSV') from None
    else:
        need(name.endswith('.json'), 'Only enumerated historical JSON/CSV metadata is supported')
        value = strict_json(data)
        need(isinstance(value, dict) and value, 'Historical evidence must be a nonempty JSON object')
    # No status, commit, result or old manifest digest is changed or promoted.
    # In particular, these documents NEVER supply current source/test hashes.


def capture(root, policy, source_commit):
    validate_policy(policy)
    need(isinstance(source_commit, str) and re.fullmatch(r'git:[0-9a-f]{40}', source_commit), 'Exact pre-apply source reference required')
    hashes, problems = {}, []
    for name in policy['paths']:
        try:
            data = read_regular(root, name); validate_document(name, data); hashes[name] = sha(data)
        except (RuntimeError, OSError) as error:
            # Filenames and structural reasons only; never document values.
            problems.append(name + ': ' + type(error).__name__)
    need(not problems, 'Historical evidence metadata problems (no files changed):\n' + '\n'.join(problems))
    return {'schema':1,'step':'S31','scope':SCOPE,'captured_source_commit':source_commit,
            'policy_sha256':canonical(policy),'sha256':hashes}


def check_snapshot(root, policy, record):
    validate_policy(policy)
    need(isinstance(record, dict) and set(record) == {'schema','step','scope','captured_source_commit','policy_sha256','sha256'},
         'Invalid supplementary historical-evidence binding')
    need(type(record['schema']) is int and record['schema'] == 1 and record['step'] == 'S31' and record['scope'] == SCOPE
         and isinstance(record['captured_source_commit'], str) and re.fullmatch(r'git:[0-9a-f]{40}', record['captured_source_commit'])
         and record['policy_sha256'] == canonical(policy), 'Historical evidence policy/provenance mismatch')
    hashes = record['sha256']
    need(isinstance(hashes, dict) and set(hashes) == set(PATHS)
         and all(isinstance(v, str) and SHA.fullmatch(v) for v in hashes.values()), 'All exact supplementary evidence hashes are required')
    problems = []
    for name, expected in hashes.items():
        try:
            data = read_regular(root, name)
            need(sha(data) == expected, 'Bound supplementary historical evidence changed')
            validate_document(name, data)
        except (RuntimeError, OSError) as error:
            problems.append(name + ': ' + type(error).__name__)
    need(not problems, 'Bound historical evidence changed or missing (no rebind):\n' + '\n'.join(problems))
    return len(hashes)


def verify(root, policy):
    validate_policy(policy)
    return check_snapshot(root, policy, strict_json(read_regular(root, BINDING, maximum=256 * 1024)))


def bind_once(root, policy, captured):
    check_snapshot(root, policy, captured)
    path = Path(root) / BINDING
    if path.exists() or path.is_symlink():
        verify(root, policy); return False
    data = (json.dumps(captured, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    except FileExistsError:
        verify(root, policy); return False
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(data)
    verify(root, policy)
    return True
