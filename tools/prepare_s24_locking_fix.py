#!/usr/bin/env python3
"""Record S24 operator failure and source-fix metadata only; never run the app."""
import csv
from datetime import datetime
import json
import subprocess
from zoneinfo import ZoneInfo
from prepare_s24 import DOCS, REQUIREMENTS, record_result, write_csv

EVIDENCE = 'docs/implementation/evidence/S24-locking-csrf-fix.json'


def prepare():
    report = json.loads((DOCS / 'evidence/S24-verification.json').read_text())
    if report.get('status') == 'Verified':
        print('Existing Verified receipt retained; no historical result replaced.')
        return
    reference = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=DOCS.parents[1], text=True).strip()
    day = datetime.now(ZoneInfo('Europe/Athens')).date().isoformat()
    report.update(status='Prepared', source_commit='git:' + reference, prepared_at=day,
                  source_fix={'name': 'locking-and-csrf-fixture', 'status': 'Prepared',
                              'operator_rerun': 'Pending', 'evidence': EVIDENCE},
                  reported_failed_operator_attempt={'tests_run': 656, 'failures': 1, 'errors': 20,
                      'source_commit': None, 'date': '2026-11-14', 'elapsed_seconds': 163.919,
                      'scope': 'Uploaded tail only; no full strict suite/financial/boundary receipt supplied'})
    record_result(report)
    path = DOCS / 'state.md'
    text = path.read_text()
    note = '''\n<!-- S24-LOCKING-FIX -->
Operator reported 656 tests with 20 errors and one failure on 2026-11-14.
The supplied tail identifies an unrestricted FOR UPDATE across a nullable
release join and a CSRF-enforced client passed into the tokenless MFA fixture.
Source fix restricts row locks to CashAllocation and reuses a real MFA-verified
synthetic session for the CSRF request, including a successful GET assertion.
No security check or financial assertion is removed. No migrations/locks change.
Source remains Prepared: the corrected full PostgreSQL run is Pending. No agent
test/build/database/VM/demo execution. See evidence/S24-locking-csrf-fix.json.
<!-- /S24-LOCKING-FIX -->\n'''
    if '<!-- S24-LOCKING-FIX -->' not in text:
        # Keep this pending note inside the replaceable S24 result block so
        # a successful future operator receipt replaces it with Verified.
        text = text.replace('<!-- /S24-RESULT -->', note + '\n<!-- /S24-RESULT -->', 1)
    path.write_text(text)
    path = DOCS / 'steps.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S24')
    row['blocker'] = 'Operator reported 20 errors/1 failure; locking/CSRF source fix Prepared; corrected PG17 rerun Pending'
    if EVIDENCE not in row['evidence'].split('; '): row['evidence'] += '; ' + EVIDENCE
    write_csv(path, rows)
    path = DOCS / 'traceability.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    note = ' S24 locking/CSRF source fix Prepared after operator failure; fresh full PostgreSQL run Pending; no assertions waived.'
    for row in rows:
        if row['requirement_id'] not in REQUIREMENTS: continue
        if note not in row['notes']: row['notes'] += note
        if EVIDENCE not in row['evidence'].split('; '): row['evidence'] += ('; ' if row['evidence'] else '') + EVIDENCE
        row['last_reviewed'] = day
    write_csv(path, rows)


if __name__ == '__main__':
    prepare()
