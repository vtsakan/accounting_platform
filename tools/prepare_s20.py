#!/usr/bin/env python3
"""Render S20 code-delivery metadata only; no Django, tests, builds or DB access."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/implementation'


def prepare():
    day = datetime.now(ZoneInfo('Europe/Athens')).date().isoformat()
    reference = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report = json.loads((DOCS / 'evidence/S20-verification.json').read_text())
    if report.get('status') == 'Verified':
        return
    report['source_commit'] = 'git:' + reference
    report['prepared_at'] = day
    (DOCS / 'evidence/S20-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    path = DOCS / 'state.md'
    text = path.read_text()
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + day + '. Current step: **S20 Prepared — ordinary cash and validated filters**. Next step: **Operator testing; S21 source follows**.\n', text, count=1)
    summary = '''<!-- S20-RESULT -->
Prepared: code-only delivery at the user's request. Greek ordinary cash forms
include remarks/optional references and stable operation identities. Shared typed
historical filters, pagination and full matching-scope cash totals are supplied.
The nine FLT cases are expected-pass targets, not observed passes. No S20 tests,
builds, Docker, database or cloud actions were executed by the implementation
agent. Original migrations 0001–0014 and all previous receipts remain intact.
Operator command, when desired: python3 tools/verify_s20.py --record.
Full requirement acceptance remains Pending.
<!-- /S20-RESULT -->'''
    if '<!-- S20-RESULT -->' in text:
        text = re.sub(r'<!-- S20-RESULT -->.*?<!-- /S20-RESULT -->', summary, text, flags=re.S)
    else:
        text = text.replace('## Current selected work', '## Historical selected work', 1)
        position = text.find('\n## ')
        if position >= 0:
            text = text[:position] + '\n\n## Current selected work — S20\n\n' + summary + '\n' + text[position:]
        else:
            text += '\n' + summary + '\n'
    path.write_text(text)
    path = DOCS / 'steps.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S20')
    row.update(status='Prepared', branch='step/s20-cash-movements', code_reference_commit=reference,
               evidence='docs/implementation/evidence/S20-verification.json; docs/implementation/cash_movements.md; accounting/tests_cash_movements.py',
               blocker='Tests/builds not executed: user requested code-only delivery',
               manual_acceptance='Operator testing and Greek client/browser acceptance Pending', next_step='S21 atomic internal transfers')
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
    path = DOCS / 'traceability.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] not in {'UR-CSH-02', 'UR-CSH-06', 'UR-LOC-01'}:
            continue
        if ' S20: Prepared code-only delivery;' not in row['notes']:
            row['notes'] += ' S20: Prepared code-only delivery; ordinary posting/remarks, typed combined filters and pagination. No tests/builds executed by agent per user request; full acceptance Pending.'
        for evidence in ('docs/implementation/evidence/S20-verification.json', 'docs/implementation/cash_movements.md', 'accounting/tests_cash_movements.py'):
            if evidence not in row['evidence'].split('; '):
                row['evidence'] += '; ' + evidence
        row['last_reviewed'] = day
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n'); writer.writeheader(); writer.writerows(rows)


if __name__ == '__main__':
    prepare()
