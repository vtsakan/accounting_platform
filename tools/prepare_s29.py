"""Source/tracking only. No application/test/build/migration execution."""
import csv,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DOCS=ROOT/'docs/implementation'
EVIDENCE=['docs/implementation/evidence/S29-verification.json','docs/implementation/financial_reports.md',
    'docs/implementation/evidence/S29-source.json','docs/implementation/evidence/S29-preserved-source.json',
    'accounting/report_selectors.py','accounting/tests_reports.py']


def record_result(report):
    status=report['status']
    if status not in {'Prepared','Verified'}:raise ValueError('Unexpected S29 status')
    day=report.get('verified_at',report.get('prepared_at'))[:10]
    (DOCS/'evidence/S29-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    state=DOCS/'state.md';text=state.read_text().replace('## Current selected work — S28','## Previous verified work — S28',1)
    if '<!-- S29-RESULT -->' not in text:
        at=text.index('\n## ');text=text[:at]+'\n\n## Current selected work — S29\n\n<!-- S29-RESULT -->\n<!-- /S29-RESULT -->\n'+text[at:]
    result=('Operator S29 production-image/PG17 gate Verified: retained suite/financial cases, scoped read-only reports, '
        'cash bridges, dated statements, annual cohorts/pagination and concurrent report snapshots passed; retained S28 '
        'real scheduler/Redis/ack-loss regression passed. Browser/full acceptance, D05/G2 and VM rollout remain Pending.' if status=='Verified' else
        'Prepared source-only S29: real unpaid-obligation dashboard, filtered operating cash report, full selected-account '
        'opening/flows/transfers/adjustments/closing bridge, dated statements and annual fee/settlement/credit cohorts. '
        '36 PG reporting/snapshot methods supplied; 808/36 and the retained S28 real-broker gate are unobserved targets. '
        'Agent tests/builds/Docker/migrations/native application verification unexecuted. No new migration. '
        'Browser/full acceptance, D05/G2 and VM rollout remain Pending.')
    text=re.sub(r'<!-- S29-RESULT -->.*?<!-- /S29-RESULT -->','<!-- S29-RESULT -->\n'+result+'\n<!-- /S29-RESULT -->',text,flags=re.S)
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+day+'. Current step: **S29 '+status+' — dashboards and financial reports**. Next: **'+
        ('S30 when selected' if status=='Verified' else 'Operator S29 verification; S30 follows')+'**.\n',text,count=1);state.write_text(text)
    for name in ('steps.csv','traceability.csv'):
        path=DOCS/name
        with path.open(newline='') as stream:rows=list(csv.DictReader(stream))
        for row in rows:
            if row.get('step_id')=='S29':
                row.update(status=status,branch='step/s29-financial-overviews',code_reference_commit=report['source_commit'].removeprefix('git:'),
                    evidence='; '.join(EVIDENCE),blocker='' if status=='Verified' else 'Full operator 808/36 and retained real fee-worker gate Pending; static agent work only',
                    manual_acceptance='Greek/browser review, deployment and all full acceptances Pending',next_step='S30 PDF/CSV when selected')
            if row.get('requirement_id') in {'UR-REP-01','UR-REP-02','UR-REP-03','UR-LOC-01','QR-01','QR-03','QR-07','QR-14'}:
                row['last_reviewed']=day
                for item in EVIDENCE:
                    if item not in row['evidence']:row['evidence']+='; '+item
                if 'S29' not in row['implementation_steps'].split():row['implementation_steps']+=' S29'
                row['notes']=re.sub(r' S29 (Prepared|Verified):.*?full acceptance Pending\.','',row['notes'])+' S29 '+status+': dated office cash/debt/credit reports, client statements and annual cohort reconciliation; full acceptance Pending.'
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
