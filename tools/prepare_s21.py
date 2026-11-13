#!/usr/bin/env python3
"""Merge S21 delivery metadata only; no Django, tests, builds or database access."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/implementation'
EVIDENCE = ('docs/implementation/evidence/S21-verification.json',
            'docs/implementation/internal_transfers.md', 'accounting/tests_internal_transfers.py')


def prepare():
    path = DOCS / 'evidence/S21-verification.json'
    report = json.loads(path.read_text())
    if report.get('status') == 'Verified':
        return
    day = datetime.now(ZoneInfo('Europe/Athens')).date().isoformat()
    reference = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report.update(source_commit='git:' + reference, prepared_at=day)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    path = DOCS / 'state.md'
    text = path.read_text()
    text = re.sub(r'Updated .*?Current step:.*?\n',
                  'Updated ' + day + '. Current step: **S21 Prepared — atomic internal transfers**. Next step: **Operator testing; S22 source follows**.\n', text, count=1)
    summary = '''<!-- S21-RESULT -->
Prepared: code-only delivery. Explicit paired transfers retain one command,
atomic writes, stable retries and shared Greek audit references. Dated cash
balances/history include the legs; operating/category totals exclude explicit
transfers. Legacy UUIDs remain unclassified for S25. S20's actual 511-test
operator receipt remains unchanged. The 22 new test sources are unexecuted;
all 533 tests, 36 financial cases and 784 boundary cases are expected to pass,
not observed passes. No S21 tests/builds/containers/database/cloud actions were
executed by the implementation agent. Fourteen migrations, existing test
assertions, accounts/MFA/keys and dependency locks remain intact. Optional
operator command: python3 tools/verify_s21.py --record. Full acceptance Pending.
<!-- /S21-RESULT -->'''
    if '<!-- S21-RESULT -->' in text:
        text = re.sub(r'<!-- S21-RESULT -->.*?<!-- /S21-RESULT -->', summary, text, flags=re.S)
    else:
        text = text.replace('## Current selected work', '## Historical selected work', 1)
        position = text.find('\n## ')
        if position >= 0:
            text = text[:position] + '\n\n## Current selected work — S21\n\n' + summary + '\n' + text[position:]
        else:
            text += '\n' + summary + '\n'
    path.write_text(text)

    path = DOCS / 'steps.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    selected = next(row for row in rows if row['step_id'] == 'S21')
    selected.update(status='Prepared', branch='step/s21-internal-transfers', code_reference_commit=reference,
                    evidence='; '.join(EVIDENCE), blocker='Tests/builds not executed: user requested code-only delivery',
                    manual_acceptance='Operator PostgreSQL tests and Greek browser/client review Pending',
                    next_step='S22 agreement terms and charge obligations')
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)

    path = DOCS / 'traceability.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] not in {'UR-CSH-04', 'QR-03', 'UR-LOC-01', 'UR-REP-02'}:
            continue
        if ' S21: Prepared code-only delivery;' not in row['notes']:
            row['notes'] += ' S21: Prepared code-only delivery; atomic explicit transfers, stable retries and shared references; operating/category totals exclude transfers while dated cash balances retain them. New tests supplied but not run; legacy pairing S25 and full acceptance Pending.'
        for item in EVIDENCE:
            if item not in row['evidence'].split('; '):
                row['evidence'] += '; ' + item
        row['last_reviewed'] = day
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


if __name__ == '__main__':
    prepare()
