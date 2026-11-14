#!/usr/bin/env python3
"""Merge S24 metadata only. No Django, Docker, build, test or database invocation."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/implementation'
REQUIREMENTS = {'UR-CSH-07', 'UR-AGR-04', 'UR-AGR-05', 'QR-04', 'UR-LOC-01'}
EVIDENCE = ('docs/implementation/evidence/S24-verification.json',
            'docs/implementation/financial_corrections.md', 'accounting/tests_corrections.py')


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def record_result(report):
    verified = report['status'] == 'Verified'
    day = report.get('verified_at', report.get('prepared_at', ''))[:10]
    reference = report['source_commit'].removeprefix('git:')
    (DOCS / 'evidence/S24-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    path = DOCS / 'state.md'
    text = path.read_text()
    title = 'S24 ' + report['status'] + ' — linked corrections, refunds and agreement lifecycle'
    text = re.sub(r'Updated .*?Current step:.*?\n',
                  'Updated ' + day + '. Current step: **' + title + '**. Next step: **' +
                  ('S25 legacy migration and reconciliation' if verified else 'Operator testing; S25 source follows') + '**.\n', text, count=1)
    summary = ('''<!-- S24-RESULT -->
Verified by the operator's disposable Docker/PostgreSQL 17 execution; see
S24-verification.json for actual suite, financial and boundary results. Prior
S23 operator evidence is unchanged. This does not deploy or migrate the retained
local demo/VM, accept the Greek browser flow or satisfy all 85 acceptances.
<!-- /S24-RESULT -->''' if verified else '''<!-- S24-RESULT -->
Prepared: code-only delivery. Migrations 0019/0020 add retained correction
links, source-bound credit/advance refunds, owner/password/recent-MFA atomic
cash/charge corrections, both transfer legs, prospective agreement amendments
and cancellation, and a forward-only declared closed-period cutoff. Originals
and allocations remain; replacement cash needs separate allocation confirmation.
Separate cash balances and signed operating totals retain dated refund/reversal
effects. New source/command/audit/event counts must commit as a complete group.
No old receipt, assertion, migration or dependency lock is replaced. Supplied:
51 new test methods; targets 656 passes, all 36 financial cases, 922 boundary
cases. Targets are NOT observed results. No agent test/build/Docker/database/
local demo/VM/account/MFA/key operation ran. Optional operator command:
python3 tools/verify_s24.py --record. Historical S23 operator proof: 605 passes,
36 financial cases, 838 boundary cases. Browser/client acceptance, restricted-role
DDL, retained-demo migration and all 85 full acceptances remain Pending. S25
legacy review/import/reconciliation remains separate; stop after S24.
<!-- /S24-RESULT -->''')
    if '<!-- S24-RESULT -->' in text:
        text = re.sub(r'<!-- S24-RESULT -->.*?<!-- /S24-RESULT -->', summary, text, flags=re.S)
    else:
        text = text.replace('## Current selected work', '## Historical selected work', 1)
        position = text.find('\n## ')
        text = text[:position] + '\n\n## Current selected work — S24\n\n' + summary + '\n' + text[position:] if position >= 0 else text + '\n' + summary + '\n'
    path.write_text(text)
    path = DOCS / 'steps.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S24')
    row.update(status=report['status'], branch='step/s24-financial-corrections', code_reference_commit=reference,
               evidence='; '.join(EVIDENCE), blocker='' if verified else 'Tests/builds/migrations unexecuted: user code-only delivery preference',
               manual_acceptance='Greek browser/client acceptance, restricted-role DDL and all full acceptances Pending',
               next_step='S25 legacy migration and reconciliation')
    write_csv(path, rows)
    path = DOCS / 'traceability.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] not in REQUIREMENTS: continue
        note = (' S24 operator Docker verification recorded; full acceptance remains Pending.' if verified else
                ' S24: Prepared code-only delivery; linked atomic corrections, original-bound refunds, dated history, prospective lifecycle and period cutoff. No agent execution; full acceptance Pending.')
        if note not in row['notes']: row['notes'] += note
        for item in EVIDENCE:
            if item not in row['evidence'].split('; '): row['evidence'] += ('; ' if row['evidence'] else '') + item
        row['last_reviewed'] = day
    write_csv(path, rows)


def prepare():
    report = json.loads((DOCS / 'evidence/S24-verification.json').read_text())
    if report.get('status') == 'Verified': return
    report.update(prepared_at=datetime.now(ZoneInfo('Europe/Athens')).date().isoformat(),
                  source_commit='git:' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    record_result(report)


if __name__ == '__main__':
    prepare()
