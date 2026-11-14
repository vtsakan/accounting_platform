#!/usr/bin/env python3
"""Merge S22 delivery metadata only. No Django/test/build/database invocation."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/implementation'
EVIDENCE = ('docs/implementation/evidence/S22-verification.json', 'docs/implementation/agreement_charges.md',
            'accounting/tests_agreement_charges.py')


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def prepare():
    path = DOCS / 'evidence/S22-verification.json'
    report = json.loads(path.read_text())
    if report.get('status') == 'Verified':
        return
    day = datetime.now(ZoneInfo('Europe/Athens')).date().isoformat()
    reference = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report.update(source_commit='git:' + reference, prepared_at=day)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    path = DOCS / 'state.md'
    text = path.read_text()
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + day + '. Current step: **S22 Prepared — agreement terms and explicit charges**. Next step: **Operator testing; S23 source follows**.\n', text, count=1)
    summary = '''<!-- S22-RESULT -->
Prepared: code-only delivery. Additive migrations 0015/0016 retain all original
agreement/cash/user IDs and fourteen migrations. Database-written immutable
terms snapshots and explicit source-bound charges separate terms, obligations
and cash. Legacy records are UNREVIEWED without automatic charges/paid flags.
Greek forms/detail/report panes, canonical one-off/month sources, atomic retries,
same-office SQL guards and 27 new test methods are supplied. All 533 previous
test names/assertions and 784 boundary cases remain; migration-test teardown
restores the latest schema. Targets are 560 passes, 36 finance cases and 799
boundary cases, not observed results. No S22 tests/builds/containers/migrations
or cloud actions were executed by the agent. S21's actual successful receipt
remains unchanged. Optional: python3 tools/verify_s22.py --record. Explicit demo
migration/restart, Greek browser review and full acceptance remain Pending.
<!-- /S22-RESULT -->'''
    if '<!-- S22-RESULT -->' in text:
        text = re.sub(r'<!-- S22-RESULT -->.*?<!-- /S22-RESULT -->', summary, text, flags=re.S)
    else:
        text = text.replace('## Current selected work', '## Historical selected work', 1)
        position = text.find('\n## ')
        if position >= 0:
            text = text[:position] + '\n\n## Current selected work — S22\n\n' + summary + '\n' + text[position:]
        else:
            text += '\n' + summary + '\n'
    path.write_text(text)
    path = DOCS / 'steps.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S22')
    row.update(status='Prepared', branch='step/s22-agreement-charges', code_reference_commit=reference,
               evidence='; '.join(EVIDENCE), blocker='Tests/builds/migrations unexecuted: code-only delivery requested',
               manual_acceptance='Operator PG17 suite, restricted-role DDL and Greek browser/client review Pending',
               next_step='S23 partial settlements and allocations')
    write_csv(path, rows)
    path = DOCS / 'traceability.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] not in {'UR-AGR-01', 'UR-LOC-01', 'QR-03'}:
            continue
        if ' S22: Prepared code-only delivery;' not in row['notes']:
            row['notes'] += ' S22: Prepared code-only delivery; separate retained terms and explicit obligations, source uniqueness independent of schedule/version, Greek screens and same-office immutable SQL guards. No agent tests/builds/migrations run; full acceptance Pending.'
        for item in EVIDENCE:
            if item not in row['evidence'].split('; '):
                row['evidence'] += ('; ' if row['evidence'] else '') + item
        row['last_reviewed'] = day
    write_csv(path, rows)


if __name__ == '__main__':
    prepare()
