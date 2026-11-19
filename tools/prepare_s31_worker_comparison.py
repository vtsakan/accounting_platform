"""File-only follow-up tracking; preserve the actual formal S31 Failed report."""
import csv
import io
from pathlib import Path
import re


EVIDENCE = ('docs/implementation/evidence/S31-performance-observed.json',
            'docs/implementation/evidence/S31-worker-comparison.json',
            'docs/implementation/s31_workers_el.md')
BLOCK = '''<!-- S31-WORKER-COMPARISON -->
### S31 performance follow-up

Operator diagnosis Observed at 2026-11-19T11:02:52+02:00: 450 HTTP requests,
zero errors; concurrent list/detail p95 2.904/3.038 s versus Gunicorn logged
0.062/0.074 s; no cgroup CPU throttling. This supports a worker-queue hypothesis,
not a measured queue duration or accepted VM capacity. Formal S31 remains
technical Failed, source Prepared and release Blocked; all 85 acceptances Pending.

Prepared operator-only 2 → 4 → 2 sync-worker comparison: same immutable image,
financial dataset, 50 sessions, CPU/memory caps and p95 targets. Candidate four
is exploratory only. Original two-worker workload/receipt stays unchanged.
See [procedure](s31_workers_el.md); run `python3 tools/compare_s31_workers.py`.
Agent runtime not executed; comparison results and formal retry Pending.
<!-- /S31-WORKER-COMPARISON -->'''


def record_prepared(root, source):
    root = Path(root); docs = root / 'docs/implementation'
    if not re.fullmatch(r'[0-9a-f]{40}', source):
        raise RuntimeError('Actual applied source commit required')
    state = docs / 'state.md'; text = state.read_text()
    pending = {}
    if '<!-- S31-WORKER-COMPARISON -->' in text:
        if BLOCK not in text:
            raise RuntimeError('Preserve an independently changed worker-comparison note')
    else:
        marker = '<!-- /S31-RESULT -->'
        if text.count(marker) != 1:
            raise RuntimeError('One original S31 state marker required')
        pending[state] = text.replace(marker, marker + '\n\n' + BLOCK, 1)
    for name in ('traceability.csv', 'steps.csv'):
        path = docs / name
        with path.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        before = [dict(row) for row in rows]
        if name == 'traceability.csv':
            if len(rows) != 85 or any(row['acceptance_status'] != 'Pending' for row in rows):
                raise RuntimeError('All original 85 acceptance statuses must remain Pending')
            matches = [row for row in rows if row['requirement_id'] == 'QR-05']
            if len(matches) != 1:
                raise RuntimeError('One original QR-05 row required')
            row = matches[0]
            note = ' S31 worker comparison: operator diagnosis Observed; separate 2/4/2 experiment Prepared, formal technical Failed and release Blocked preserved.'
            if note not in row['notes']:
                row['notes'] += note
            row['last_reviewed'] = '2026-11-19'
            allowed = {'notes', 'evidence', 'last_reviewed'}
        else:
            matches = [row for row in rows if row['step_id'] == 'S31']
            if len(matches) != 1 or matches[0]['status'] != 'Prepared':
                raise RuntimeError('Prepared S31 source tracking required')
            row = matches[0]
            row['code_reference_commit'] = source
            row['next_step'] = 'Operator-only 2/4/2 worker comparison; preserve official Failed; formal runtime-profile review/retry and R1 acceptance Pending'
            allowed = {'evidence', 'code_reference_commit', 'next_step'}
        for reference in EVIDENCE:
            if reference not in row['evidence'].split('; '):
                row['evidence'] += '; ' + reference
        for old, current in zip(before, rows):
            if any(old[key] != current[key] for key in old.keys() - allowed):
                raise RuntimeError('Protected tracking field changed')
            if old != current and current is not row:
                raise RuntimeError('Unrelated tracking row changed')
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
        pending[path] = stream.getvalue()
    # Validate every target before writing any tracking file. These reversible
    # file writes are committed together by the source-only installer.
    for path, contents in pending.items():
        path.write_text(contents)
