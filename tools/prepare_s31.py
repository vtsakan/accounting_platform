"""S31 tracking writes only. Technical proof never marks a release accepted."""
import csv
import json
from pathlib import Path
import re
from r1_gate import require

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/implementation'
EVIDENCE = ['docs/implementation/evidence/S31-verification.json', 'docs/implementation/evidence/S31-source.json',
            'docs/implementation/evidence/S31-preserved-source.json', 'docs/implementation/finance_release_gate.md',
            'docs/implementation/r1_acceptance_matrix.json', 'docs/implementation/r1_review_el.md',
            'docs/implementation/r1_workload.json', 'docs/implementation/r1_cutover_el.md']


def record_result(report):
    require(report['step'] == 'S31' and report['status'] == 'Prepared' and report['release_decision'] == 'Blocked',
            'Source/technical tracking cannot accept S31 or a live release')
    day = report.get('checked_at', report.get('prepared_at'))[:10]
    (DOCS / 'evidence/S31-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    state = DOCS / 'state.md'
    text = state.read_text().replace('## Current selected work — S30', '## Previous verified work — S30', 1)
    if '<!-- S31-RESULT -->' not in text:
        at = text.index('\n## ')
        text = text[:at] + '\n\n## Current selected work — S31\n\n<!-- S31-RESULT -->\n<!-- /S31-RESULT -->\n' + text[at:]
    technical = report.get('technical_status', 'Pending')
    summary = ('S31 source Prepared; actual release Blocked. Technical rehearsal: ' + technical + '. '
               'Effective R1 matrix includes 33 Must user requirements (32 baseline plus Greek frontend) and nine quality requirements. '
               'Operator-only retained 848/36 and real S28 broker gate, current synthetic billing/collection/correction/reporting cycle, '
               '50 distinct HTTP sessions and encrypted PG17 baseline20/current26 recovery supplied. '
               'Human accountant/product-owner application acceptance, agreed workload/recovery/operational owners, '
               'D05 real dataset mapping/reconciliation, Greek visual/HTTPS review, authorised first-office cutover and G2 remain Pending. '
               'All 85 full acceptance statuses remain Pending. No application/image/migration/dependency/demo/VM/account/MFA change. '
               'S32 independent source work requires separate selection; live use remains blocked.')
    text = re.sub(r'<!-- S31-RESULT -->.*?<!-- /S31-RESULT -->', '<!-- S31-RESULT -->\n' + summary + '\n<!-- /S31-RESULT -->', text, flags=re.S)
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + day + '. Current step: **S31 Prepared — finance release gate; release Blocked**. '
                  'Next: **operator S31 rehearsal and named R1 acceptance; S32 source work when selected**.\n', text, count=1)
    state.write_text(text)
    for name in ('steps.csv', 'traceability.csv'):
        path = DOCS / name
        with path.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        before = {r['requirement_id']: r['acceptance_status'] for r in rows if 'requirement_id' in r}
        for row in rows:
            if row.get('step_id') == 'S31':
                row.update(status='Prepared', branch='step/s31-finance-release-gate',
                    code_reference_commit=report['source_commit'].removeprefix('git:'), evidence='; '.join(EVIDENCE),
                    blocker='Release Blocked: actual R1 acceptance, D05/G2, approved workload/recovery and authorised cutover Pending; technical ' + technical,
                    manual_acceptance='Named accountant/product-owner 42-row R1 review; real recovery, Greek visual/HTTPS/MFA and first-office/G2 decision',
                    next_step='Complete release approvals/execution; S32 independent source work only when separately selected')
            if row.get('release') == 'R1' and row.get('priority') == 'Must':
                row['last_reviewed'] = day
                for item in EVIDENCE:
                    if item not in row['evidence']:
                        row['evidence'] += '; ' + item
                if 'S31' not in row['implementation_steps'].split():
                    row['implementation_steps'] += ' S31'
                row['notes'] = re.sub(r' S31 gate:.*?full acceptance Pending\.', '', row['notes']) + \
                    ' S31 gate: technical ' + technical + '; proposed synthetic rehearsal and 42-row review; actual release Blocked, full acceptance Pending.'
        require(before == {r['requirement_id']: r['acceptance_status'] for r in rows if 'requirement_id' in r}, 'Acceptance status preservation failed')
        with path.open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
