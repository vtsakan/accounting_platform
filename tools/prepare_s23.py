#!/usr/bin/env python3
"""Merge S23 delivery metadata only; no application/test/build/DB invocation."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/implementation'
EVIDENCE = ('docs/implementation/evidence/S23-verification.json', 'docs/implementation/settlements_credit.md',
            'accounting/tests_settlements.py')
REQUIREMENTS = {'UR-AGR-02', 'UR-AGR-03', 'UR-BIL-04', 'QR-03', 'UR-LOC-01'}


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def prepare():
    path = DOCS / 'evidence/S23-verification.json'
    report = json.loads(path.read_text())
    if report.get('status') == 'Verified':
        return
    day = datetime.now(ZoneInfo('Europe/Athens')).date().isoformat()
    reference = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    report.update(source_commit='git:' + reference, prepared_at=day)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    path = DOCS / 'state.md'
    text = path.read_text()
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + day + '. Current step: **S23 Prepared — partial settlements and separate credit**. Next step: **Operator testing; S24 source follows**.\n', text, count=1)
    summary = '''<!-- S23-RESULT -->
Prepared: code-only delivery. S23 adds migrations 0017/0018, explicit atomic
cash-to-charge batches, immutable dated allocations/releases, separate customer
credit/supplier advances, complete request groups and owner password/recent-MFA
release. SQL bounds source/charge use at every affected historical change point.
Greek counterparty/agreement/report projections derive outstanding debt from
effective allocations, independent of legacy flags and cash references. No
automatic offset/refund, legacy allocation or account creation. Retain every
previous migration/assertion/receipt and lock. Supplied: 45 new methods; targets
605 passes, 36 financial cases and 838 boundary cases. These are not observed
results. No agent tests/builds/Docker/migrations/demo/VM/account/MFA/key operations
ran. Optional: python3 tools/verify_s23.py --record. S22's operator proof remains
560 passes/36 finance/799 boundary cases. Greek browser, restricted-role DDL,
explicit demo migration/restart and all 85 full acceptances remain Pending.
Grouped corrections/refund screens remain S24, legacy review S25.
<!-- /S23-RESULT -->'''
    if '<!-- S23-RESULT -->' in text:
        text = re.sub(r'<!-- S23-RESULT -->.*?<!-- /S23-RESULT -->', summary, text, flags=re.S)
    else:
        text = text.replace('## Current selected work', '## Historical selected work', 1)
        position = text.find('\n## ')
        text = (text[:position] + '\n\n## Current selected work — S23\n\n' + summary + '\n' + text[position:]) if position >= 0 else text + '\n' + summary + '\n'
    path.write_text(text)
    path = DOCS / 'steps.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S23')
    row.update(status='Prepared', branch='step/s23-settlements-credit', code_reference_commit=reference,
               evidence='; '.join(EVIDENCE), blocker='Tests/builds/migrations unexecuted: code-only delivery requested',
               manual_acceptance='Operator PG17 suite, restricted-role DDL and Greek browser/client review Pending',
               next_step='S24 linked corrections and cancellation')
    write_csv(path, rows)
    path = DOCS / 'traceability.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] not in REQUIREMENTS:
            continue
        if ' S23: Prepared code-only delivery;' not in row['notes']:
            row['notes'] += ' S23: Prepared code-only delivery; atomic explicit partial settlements, same-office/direction dated capacity, separate customer credit/supplier advance, owner MFA/password release, immutable history and Greek workspace. No agent tests/builds/migrations run; full acceptance Pending.'
        for item in EVIDENCE:
            if item not in row['evidence'].split('; '):
                row['evidence'] += ('; ' if row['evidence'] else '') + item
        row['last_reviewed'] = day
    write_csv(path, rows)


if __name__ == '__main__':
    prepare()
