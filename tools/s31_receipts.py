"""Bind existing operator results once, without replacing or promoting them.

This module reads only local JSON/CSV and SHA-256 metadata. The sole write is
an exclusive new S31 binding file; historical results are never opened to write.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re

PREFIX = 'docs/implementation/evidence/'
BINDING = PREFIX + 'S31-operator-receipts.json'
RECEIPTS = tuple(sorted(
    [PREFIX + f'S{number:02}-verification.json' for number in range(1, 31)]
    + [PREFIX + name for name in ('S24A-verification.json', 'S24A-VM-verification.json',
                                  'G1-foundation.json', 'S16-office-boundary.csv', 'S19-office-boundary.csv')]))
SHA = re.compile(r'sha256:[0-9a-f]{64}')
CONTEXT = 'sha256:a3dbff49144c7072f8308ab50ca96f4c9ddb36c56eb873593b216dce2111329c'
SCOPE = 'operator-local-historical-receipts-captured-before-S31-without-rewriting'


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def canonical(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, 'Duplicate JSON receipt field')
            result[key] = value
        return result
    def invalid(value):
        raise RuntimeError('Non-finite JSON receipt number')
    try:
        return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError):
        raise RuntimeError('Malformed JSON receipt; original bytes were not changed') from None


def validate_policy(policy):
    need(isinstance(policy, dict) and set(policy) == {'schema', 'binding_file', 'paths'}, 'Invalid receipt policy')
    need(type(policy['schema']) is int and policy['schema'] == 1 and policy['binding_file'] == BINDING,
         'Only the published S31 receipt binding is permitted')
    need(isinstance(policy['paths'], list) and policy['paths'] == list(RECEIPTS),
         'Receipt paths must equal the exact published operator-output inventory')
    return policy


def read_regular(root, name, maximum=8 * 1024 * 1024):
    root = Path(root).resolve(); path = root / name
    need(not Path(name).is_absolute() and '..' not in Path(name).parts and path.is_file() and not path.is_symlink()
         and path.resolve().is_relative_to(root), 'Missing or unsafe historical receipt: ' + name)
    need(0 < path.stat().st_size <= maximum, 'Receipt size outside the bounded JSON/CSV budget: ' + name)
    data = path.read_bytes()
    need(0 < len(data) <= maximum, 'Receipt changed size during capture: ' + name)
    return data


def subset(value, expected, label):
    need(isinstance(value, dict), 'Invalid claimed Verified receipt: ' + label)
    for key, item in expected.items():
        actual = value.get(key)
        if isinstance(item, dict):
            subset(actual, item, label)
        else:
            need(type(actual) is type(item) and actual == item,
                 'Claimed Verified receipt conflicts with known operator proof: ' + label + '/' + key)


def validate_receipt(name, data):
    """Validate identity; never turn a Prepared result into Verified."""
    if name.endswith('.csv'):
        try:
            reader = csv.DictReader(io.StringIO(data.decode('utf-8')))
            need(reader.fieldnames == ['case_id', 'area', 'route', 'persona', 'scenario', 'observed', 'result'],
                 'Unexpected historical boundary CSV header')
            rows = list(reader)
            need(rows and all(set(row) == set(reader.fieldnames) and all(isinstance(v, str) for v in row.values())
                             and row['case_id'] and row['result'] for row in rows), 'Malformed historical boundary CSV')
            need(len({row['case_id'] for row in rows}) == len(rows), 'Duplicate historical boundary cases')
        except (UnicodeError, csv.Error):
            raise RuntimeError('Malformed historical boundary CSV; original bytes were not changed') from None
        return
    value = strict_json(data)
    need(isinstance(value, dict) and isinstance(value.get('status'), str) and 1 <= len(value['status']) <= 80,
         'Historical receipt identity/status missing: ' + name)
    if name == PREFIX + 'G1-foundation.json':
        need(value.get('gate') == 'G1', 'Historical G1 receipt identity mismatch')
    else:
        step = Path(name).name.removesuffix('-verification.json')
        need(value.get('step') == step, 'Historical receipt step identity mismatch: ' + name)
    if value['status'] != 'Verified':
        return  # Source-only/failed history is retained with its actual status.
    if name == PREFIX + 'S25-verification.json':
        subset(value, {'step': 'S25', 'scope': 'synthetic-isolated-migration-rehearsal',
            'source_sha256': 'sha256:05db5e158ce44fe6af3d2c638395b1280e5a6886e9be3e4c4087585c1de25540',
            'review_sha256': 'sha256:b2f264d76ebb2fafdd57c9bb73021b74757d240eb9106ff7190ef8c7768c0e9a',
            'plan_sha256': 'sha256:8db476c4345b1510144671ebe958798ab8dd93c1ae6ba2ce1c76d3da826041fc',
            'preserved_application_context': 'sha256:aa53c8f70d8ca11881457a7c80ee7e21684c8b4212a86fe9dbfe28ed95220ba0',
            'planner_tests_passed': 61, 'reconciliation_checks': 184,
            'all_financial_checks_matched': True, 'source_tables_compared': 14, 'target_tables_compared': 44,
            'concurrent_single_batch_and_replay_without_duplicates': True, 'atomic_failure_rollback': True,
            'changed_payload_denied_without_writes': True, 'source_original_unchanged': True,
            'source_pg15_native_restore_matched': True, 'target_starting_point_restore_matched': True,
            'reimport_after_restore_matched': True, 'owned_resources_removed': True, 'plaintext_removed': True,
            'postgres_versions': {'source_server': 150020, 'source_pg_dump': 150020, 'source_pg_restore': 150020,
                'target_server': 170012, 'target_pg_dump': 170012, 'target_pg_restore': 170012}}, 'S25')
    if name == PREFIX + 'S30-verification.json':
        subset(value, {'application_context_digest': CONTEXT, 'owned_resources_removed': True,
                       'real_redis_retry_one_effect': True, 'suite': {'tests_run': 848, 'tests_passed': 848,
                        'known_failures_reproduced': 0, 'unexpected_failures': 0, 'unexpected_errors': 0,
                        'unexpected_successes': 0, 'skips': 0}}, 'S30')
        cases = value['suite'].get('cases')
        need(isinstance(cases, list) and len(cases) == 36 and all(isinstance(c, dict) and c.get('outcome') == 'passed' for c in cases),
             'Claimed S30 Verified receipt needs all 36 passing finance cases')


def capture(root, policy, source_commit):
    """Read exact bytes before APPLY; no historical or binding writes here."""
    validate_policy(policy)
    need(isinstance(source_commit, str) and re.fullmatch(r'git:[0-9a-f]{40}', source_commit), 'Exact pre-apply source reference required')
    result = {}
    for name in policy['paths']:
        data = read_regular(root, name)
        validate_receipt(name, data)
        result[name] = sha(data)
    return {'schema': 1, 'step': 'S31', 'scope': SCOPE, 'captured_source_commit': source_commit,
            'policy_sha256': canonical(policy), 'sha256': result}


def check_snapshot(root, policy, record):
    validate_policy(policy)
    need(isinstance(record, dict) and set(record) == {'schema', 'step', 'scope', 'captured_source_commit', 'policy_sha256', 'sha256'},
         'Invalid S31 operator-receipt binding')
    need(type(record['schema']) is int and record['schema'] == 1 and record['step'] == 'S31' and record['scope'] == SCOPE
         and isinstance(record['captured_source_commit'], str) and re.fullmatch(r'git:[0-9a-f]{40}', record['captured_source_commit'])
         and record['policy_sha256'] == canonical(policy), 'Operator-receipt policy/provenance mismatch')
    hashes = record['sha256']
    need(isinstance(hashes, dict) and set(hashes) == set(RECEIPTS)
         and all(isinstance(v, str) and SHA.fullmatch(v) for v in hashes.values()), 'All exact historical receipt bindings are required')
    for name, expected in hashes.items():
        data = read_regular(root, name)
        need(sha(data) == expected, 'Bound historical operator receipt changed: ' + name)
        validate_receipt(name, data)
    return len(hashes)


def verify(root, policy):
    """Runtime checks never capture new hashes or create a missing binding."""
    validate_policy(policy)
    record = strict_json(read_regular(root, BINDING, maximum=256 * 1024))
    return check_snapshot(root, policy, record)


def bind_once(root, policy, captured):
    """Only the source-only installer invokes this once after its Git patch."""
    check_snapshot(root, policy, captured)
    path = Path(root) / BINDING
    if path.exists() or path.is_symlink():
        verify(root, policy)
        return False
    payload = (json.dumps(captured, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o644)
    except FileExistsError:
        verify(root, policy)
        return False
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(payload)
    verify(root, policy)
    return True
