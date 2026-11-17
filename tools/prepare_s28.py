"""Source/tracking only; no Django, builds, tests or migrations."""
import csv,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'docs/implementation'
EVIDENCE=['docs/implementation/evidence/S28-verification.json','docs/implementation/fee_generation.md',
    'docs/implementation/evidence/S28-source.json','docs/implementation/evidence/S28-preserved-source.json',
    'accounting/tests_fee_generation.py','tools/s28_broker_gate.py']


def record_result(report):
    status=report['status']
    if status not in {'Prepared','Verified'}:raise ValueError('Unexpected S28 status')
    day=report.get('verified_at',report.get('prepared_at'))[:10]
    (DOCS/'evidence/S28-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    state=DOCS/'state.md';text=state.read_text().replace('## Current selected work — S27','## Previous verified work — S27',1)
    if '<!-- S28-RESULT -->' not in text:
        at=text.index('\n## ');text=text[:at]+'\n\n## Current selected work — S28\n\n<!-- S28-RESULT -->\n<!-- /S28-RESULT -->\n'+text[at:]
    result=('Operator S28 production-image/PG17 gate Verified: retained suite and finance cases, scoped generation, retries/concurrency, '
        'actual scheduler-discovered charges, commit-before-ack worker loss/redelivery and zero-cash reconciliation passed. '
        'VM rollout, D05/G2 and all full acceptances remain Pending.' if status=='Verified' else
        'Prepared source-only S28: explicit owner/MFA opt-in, default-off monthly discovery, canonical-source charge generation through the '
        'fenced S26 worker, scoped reviewed catch-up CLI and Greek office/month reconciliation. 34 PG contracts supplied; 772/36 and the '
        'actual scheduler/commit-before-ack real Redis gate are unobserved targets. Agent tests/builds/Docker/migrations unexecuted. '
        'VM rollout, D05/G2 and all full acceptances remain Pending.')
    text=re.sub(r'<!-- S28-RESULT -->.*?<!-- /S28-RESULT -->','<!-- S28-RESULT -->\n'+result+'\n<!-- /S28-RESULT -->',text,flags=re.S)
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+day+'. Current step: **S28 '+status+' — recurring fee generation**. Next: **'+
        ('S29 when selected' if status=='Verified' else 'Operator S28 verification; S29 follows')+'**.\n',text,count=1)
    state.write_text(text)
    for name in ('steps.csv','traceability.csv'):
        path=DOCS/name
        with path.open(newline='') as stream:rows=list(csv.DictReader(stream))
        for row in rows:
            if row.get('step_id')=='S28':
                row.update(status=status,branch='step/s28-recurring-generation',code_reference_commit=report['source_commit'].removeprefix('git:'),
                    evidence='; '.join(EVIDENCE),blocker='' if status=='Verified' else 'Full operator 772/36 and real Redis fee gate Pending; static agent work only',
                    manual_acceptance='Greek/browser review, real deployment and all full acceptances Pending',next_step='S29 when selected')
            if row.get('requirement_id') in {'UR-BIL-03','UR-LOC-01','QR-01','QR-03','QR-06','QR-14'}:
                row['last_reviewed']=day
                for item in EVIDENCE:
                    if item not in row['evidence']:row['evidence']+='; '+item
                if 'S28' not in row['implementation_steps'].split():row['implementation_steps']+=' S28'
                row['notes']=re.sub(r' S28 (Prepared|Verified):.*?full acceptance Pending\.','',row['notes'])+' S28 '+status+': canonical monthly obligations, scoped worker/explicit catch-up and no cash effect; full acceptance Pending.'
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
