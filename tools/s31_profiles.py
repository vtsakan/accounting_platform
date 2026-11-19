"""Fixed synthetic profiles and exclusive retention of the initial S31 failure.

Stdlib/local-file operations only. No native application, Docker or test calls.
"""
import csv
import io
import json
import os
from pathlib import Path
import re

from s31_receipts import canonical, need, read_regular, sha, strict_json

PROFILE_FILES = {
    'legacy': ('docs/implementation/r1_workload.json',
               'sha256:1f5e01ceaa9bf13889b2b4e8f49b1fc0c608e394f592653b16a70ab5ab467bda',
               'sha256:68cc3f2edfb2ef0ed6757d1927a7a103ba4a41d34ec3bc1c039bd966835a31b5', 2),
    'workers4': ('docs/implementation/r1_workload_workers4.json',
                 'sha256:9653d120d59d61466a3d2f4df94c7e16cfa5a82ca44f44413f99d63c9ade0d9e',
                 'sha256:d5dc158ab64e61514d6d717c21719030e7c0d96aa3da8396b6bff1aaff58386f', 4),
}
CURRENT = 'docs/implementation/evidence/S31-verification.json'
ARCHIVE = 'docs/implementation/evidence/S31-initial-failure.json'
LINEAGE = 'docs/implementation/evidence/S31-profile-lineage.json'
INITIAL = 'sha256:3687f5aba1d8714b1819c1451066dc889dc139823afbff683e2398737f11ed47'
SCOPE = 'original-operator-S31-failure-retained-before-explicit-profile-retry'


def candidate_profile(value):
    need(isinstance(value, dict) and canonical(value) == PROFILE_FILES['workers4'][2],
         'Only the exact published unapproved workers4 profile is allowed')
    return value


def identify(value):
    digest = canonical(value)
    matches = [name for name, row in PROFILE_FILES.items() if digest == row[2]]
    need(len(matches) == 1, 'Unknown or changed synthetic workload profile')
    return matches[0]


def load_workload(root, name):
    need(name in PROFILE_FILES, 'Only legacy or workers4 may be selected')
    path, expected, digest, _ = PROFILE_FILES[name]
    data = read_regular(root, path)
    need(sha(data) == expected, 'Published workload file changed: ' + path)
    value = strict_json(data)
    need(canonical(value) == digest and identify(value) == name, 'Workload profile identity changed')
    return Path(root) / path, value


def initial_failure(data):
    value = strict_json(data)
    need(isinstance(value, dict) and canonical(value) == INITIAL and value.get('step') == 'S31'
         and value.get('status') == 'Prepared' and value.get('technical_status') == 'Failed'
         and value.get('release_decision') == 'Blocked', 'Retain the exact supplied original Failed S31 result')
    return value


def safe_path(root, name):
    root = Path(root).resolve(); path = root / name
    need(path.parent.is_dir() and path.parent.resolve().is_relative_to(root), 'Unsafe lineage directory')
    need(not any(p.is_symlink() for p in [path, *path.parents] if p != root and p.is_relative_to(root)),
         'Lineage paths must not contain symlinks')
    return path


def verify_lineage(root):
    data = read_regular(root, ARCHIVE)
    original = initial_failure(data)
    binding = strict_json(read_regular(root, LINEAGE, maximum=32768))
    keys = {'schema', 'step', 'scope', 'archive_path', 'archive_sha256', 'initial_canonical_sha256',
            'original_report_source', 'captured_from_git'}
    need(isinstance(binding, dict) and set(binding) == keys and type(binding['schema']) is int
         and binding['schema'] == 1 and binding['step'] == 'S31' and binding['scope'] == SCOPE
         and binding['archive_path'] == ARCHIVE and binding['archive_sha256'] == sha(data)
         and binding['initial_canonical_sha256'] == INITIAL
         and binding['original_report_source'] == original['source_commit']
         and isinstance(binding['captured_from_git'], str)
         and re.fullmatch(r'git:[0-9a-f]{40}', binding['captured_from_git']) is not None,
         'Initial failure archive or its exclusive binding changed; no rebind')
    safe_path(root, ARCHIVE); safe_path(root, LINEAGE)
    return binding


def capture_initial(root, reference):
    need(isinstance(reference, str) and re.fullmatch(r'git:[0-9a-f]{40}', reference), 'Actual pre-APPLY Git reference required')
    need(not any((Path(root) / name).exists() or (Path(root) / name).is_symlink() for name in (ARCHIVE, LINEAGE)),
         'Initial lineage already or partially exists; verify it, never recapture')
    data = read_regular(root, CURRENT); original = initial_failure(data)
    safe_path(root, ARCHIVE); safe_path(root, LINEAGE)
    return {'data': data, 'binding': {'schema': 1, 'step': 'S31', 'scope': SCOPE, 'archive_path': ARCHIVE,
            'archive_sha256': sha(data), 'initial_canonical_sha256': INITIAL,
            'original_report_source': original['source_commit'], 'captured_from_git': reference}}


def bind_initial(root, snapshot):
    if any((Path(root) / name).exists() or (Path(root) / name).is_symlink() for name in (ARCHIVE, LINEAGE)):
        binding = verify_lineage(root)
        need(binding == snapshot['binding'] and read_regular(root, ARCHIVE) == snapshot['data'], 'Existing lineage differs; no overwrite')
        return binding
    data = snapshot['data']; original = initial_failure(data)
    need(read_regular(root, CURRENT) == data and snapshot['binding']['archive_sha256'] == sha(data)
         and snapshot['binding']['original_report_source'] == original['source_commit'], 'Original failure changed during APPLY')
    for name, payload in ((ARCHIVE, data), (LINEAGE, (json.dumps(snapshot['binding'], ensure_ascii=False, indent=2) + '\n').encode())):
        path = safe_path(root, name)
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o644)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
    return verify_lineage(root)


def validate_runtime(value, workers, image_id, service):
    need(workers in (2, 4) and service in ('web', 'restored_web') and isinstance(value, dict), 'Invalid selected runtime proof')
    need(value.get('service') == service and value.get('image') == image_id
         and value.get('configured_workers') == workers and type(value.get('configured_workers')) is int
         and value.get('live_worker_children') == workers and type(value.get('live_worker_children')) is int
         and value.get('worker_class') == 'sync' and value.get('effective_cpu_limit') == 2
         and value.get('memory_bytes') == 1024 * 1024 * 1024
         and value.get('entrypoint') == ['gunicorn']
         and value.get('command') == ['core.wsgi:application', '--config', 'gunicorn.conf.py'],
         'Actual image, worker population or fixed resource limits do not match the selected profile')
    return value


def validate_rehearsal(value, workload, image_id):
    name = identify(workload); workers = PROFILE_FILES[name][3]
    runtime = value['runtime']
    need(runtime.get('workload_profile') == name and runtime['container_limits'] == workload['synthetic_envelope'],
         'Rehearsal differs from the explicitly selected profile')
    for service in ('web', 'restored_web'):
        validate_runtime(runtime['effective_' + service], workers, image_id, service)
    return True


def record_prepared(root, source):
    need(isinstance(source, str) and re.fullmatch(r'[0-9a-f]{40}', source), 'Applied source commit required')
    docs = Path(root) / 'docs/implementation'
    references = ['docs/implementation/evidence/' + name for name in (
        'S31-worker-comparison-observed.json', 'S31-profile-source.json', 'S31-initial-failure.json', 'S31-profile-lineage.json')]
    references += ['docs/implementation/r1_workload_workers4.json', 'docs/implementation/s31_workers4_el.md']
    block = '''<!-- S31-WORKERS4-PREPARED -->
### Explicit workers4 full retry — Prepared

The operator 2/4/2 comparison at 2026-11-19T11:36:54+02:00 is Observed:
four-worker p95 1.673/1.712/1.872 s met unchanged targets; both two-worker
controls still failed list/detail. All 1,350 requests, 39 business tables,
recovery and cleanup passed. CPU throttling was observed; no VM margin claim.

Separate schema-2 workers4 profile Prepared; legacy profile/default unchanged.
Full 848/36, real broker, 48 host contracts and migration/recovery retry Pending:
`python3 tools/verify_s31.py --record --host-dns --profile workers4`.
Actual initial Failed evidence is retained exclusively before a current update.
Source Prepared, formal prior Failed, release Blocked; all 85 acceptances Pending.
<!-- /S31-WORKERS4-PREPARED -->'''
    state = docs / 'state.md'; text = state.read_text(); pending = {}
    if '<!-- S31-WORKERS4-PREPARED -->' in text:
        need(block in text, 'Preserve an independently changed profile note')
    else:
        marker = '<!-- /S31-RESULT -->'; need(text.count(marker) == 1, 'One S31 state marker required')
        pending[state] = text.replace(marker, marker + '\n\n' + block, 1)
    for name in ('steps.csv', 'traceability.csv'):
        path = docs / name
        with path.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        before = [dict(row) for row in rows]
        if name == 'steps.csv':
            matches = [row for row in rows if row['step_id'] == 'S31']
            need(len(matches) == 1 and matches[0]['status'] == 'Prepared', 'Prepared S31 source tracking required')
            row = matches[0]; allowed = {'code_reference_commit', 'evidence', 'next_step'}
            row['code_reference_commit'] = source
            row['next_step'] = 'Explicit workers4 full S31 retry; original Failed retained; human R1/D05/D06/D07/G2 Pending'
        else:
            need(len(rows) == 85 and all(row['acceptance_status'] == 'Pending' for row in rows), '85 Pending acceptances required')
            matches = [row for row in rows if row['requirement_id'] == 'QR-05']; need(len(matches) == 1, 'One QR-05 row required')
            row = matches[0]; allowed = {'evidence', 'notes', 'last_reviewed'}
            note = ' S31 workers4: explicit profile Prepared after measured comparison; full retry Pending, initial Failed retained, release Blocked.'
            if note not in row['notes']:
                row['notes'] += note
            row['last_reviewed'] = '2026-11-19'
        for reference in references:
            if reference not in row['evidence'].split('; '):
                row['evidence'] += '; ' + reference
        for old, current in zip(before, rows):
            need(all(old[key] == current[key] for key in old.keys() - allowed), 'Protected tracking field changed')
            need(old == current or current is row, 'Unrelated tracking row changed')
        stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows); pending[path] = stream.getvalue()
    for path, text in pending.items():
        path.write_text(text)


def record_prepared(root, source):
    """Only current S31/QR-05 tracking, never the formal receipt or old evidence."""
    need(re.fullmatch(r'[0-9a-f]{40}', source) is not None, 'Applied source commit required')
    root = Path(root); docs = root / 'docs/implementation'; pending = {}
    references = [ARCHIVE, LINEAGE, 'docs/implementation/r1_workload_workers4.json',
                  'docs/implementation/evidence/S31-profile-source.json',
                  'docs/implementation/evidence/S31-worker-comparison-observed.json',
                  'docs/implementation/s31_workers4_el.md']
    block = '''<!-- S31-WORKERS4-PROFILE -->
### S31 explicit workers4 retry Prepared

Operator 2/4/2 comparison Observed on 2026-11-19 at 11:36:54 Europe/Athens:
four-worker p95 1.673/1.712/1.872 s; both two-worker controls failed list/detail.
All 1,350 HTTP requests passed; 39 business tables unchanged, recovery/cleanup
passed. Four-worker CPU throttling was observed; real VM capacity remains Pending.

Separate workers4 profile Prepared with original caps, dataset and 2/2/10 s
targets. Legacy two-worker file remains exact. The initial formal Failed report
is retained byte for byte in S31-initial-failure.json with an exclusive binding.
Full retry Pending: `python3 tools/verify_s31.py --record --host-dns --profile workers4`.
This must repeat 848/36, real Redis, migration/cycle/load/encrypted recovery and
48 host contracts. No agent native execution; source Prepared, release Blocked,
all 85 full acceptances Pending. See [procedure](s31_workers4_el.md).
<!-- /S31-WORKERS4-PROFILE -->'''
    path = docs / 'state.md'; text = path.read_text()
    if '<!-- S31-WORKERS4-PROFILE -->' in text:
        need(block in text, 'Preserve an independently changed profile note')
    else:
        marker = '<!-- /S31-RESULT -->'; need(text.count(marker) == 1, 'One S31 state marker required')
        pending[path] = text.replace(marker, marker + '\n\n' + block, 1)
    for filename in ('steps.csv', 'traceability.csv'):
        path = docs / filename
        with path.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        before = [dict(row) for row in rows]
        if filename == 'steps.csv':
            matches = [row for row in rows if row['step_id'] == 'S31']
            need(len(matches) == 1 and matches[0]['status'] == 'Prepared', 'Prepared S31 tracking required')
            row = matches[0]; allowed = {'code_reference_commit', 'evidence', 'next_step'}
            row['code_reference_commit'] = source
            row['next_step'] = 'Explicit workers4 full S31 retry; initial Failed retained; human R1/D05/G2 acceptance Pending'
        else:
            need(len(rows) == 85 and all(row['acceptance_status'] == 'Pending' for row in rows), '85 Pending acceptances required')
            matches = [row for row in rows if row['requirement_id'] == 'QR-05']; need(len(matches) == 1, 'One QR-05 row required')
            row = matches[0]; allowed = {'evidence', 'notes', 'last_reviewed'}
            note = ' S31 workers4: separate profile Prepared after operator comparison; full formal retry Pending, original Failed retained, release Blocked.'
            if note not in row['notes']:
                row['notes'] += note
            row['last_reviewed'] = '2026-11-19'
        for reference in references:
            if reference not in row['evidence'].split('; '):
                row['evidence'] += '; ' + reference
        for old, current in zip(before, rows):
            need(all(old[key] == current[key] for key in old.keys() - allowed), 'Protected tracking field changed')
            need(old == current or current is row, 'Unrelated tracking row changed')
        stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows); pending[path] = stream.getvalue()
    for path, text in pending.items():
        path.write_text(text)
