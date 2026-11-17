"""Source/tracking only. Never import Django, run a build or migrate."""
import csv
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT/'docs/implementation'
EVIDENCE = ['docs/implementation/evidence/S27-verification.json','docs/implementation/recurring_fees.md',
    'docs/implementation/evidence/S27-source.json','docs/implementation/evidence/S27-preserved-source.json',
    'accounting/tests_fees.py']


def record_result(report):
    status=report['status']
    if status not in {'Prepared','Verified'}:raise ValueError('Unexpected S27 status')
    day=report.get('verified_at',report.get('prepared_at'))[:10]
    (DOCS/'evidence/S27-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    text=(DOCS/'state.md').read_text()
    text=text.replace('## Current selected work — S26','## Previous verified work — S26',1)
    if '<!-- S27-RESULT -->' not in text:
        at=text.index('\n## ')
        text=text[:at]+'\n\n## Current selected work — S27\n\n<!-- S27-RESULT -->\n<!-- /S27-RESULT -->\n'+text[at:]
    result=('Operator S27 production-image/PG17 gate Verified: retained suite and all finance cases, catalogue/schedule scope, future-rate preview, concurrency and real Redis background regression passed. S28 generation, VM rollout and all full acceptances remain Pending.' if status=='Verified' else
        'Prepared source-only S27: owner-managed versioned service prices, scoped monthly schedules, prospective owner/MFA configuration changes and read-only period/price preview. Existing charge snapshots and canonical agreement/month sources are retained. New tests/builds/Docker/migrations were not run by the agent. Operator full PG17/production-image and real Redis regression gate Pending. S28 automatic generation, VM rollout and all full acceptances remain Pending.')
    text=re.sub(r'<!-- S27-RESULT -->.*?<!-- /S27-RESULT -->','<!-- S27-RESULT -->\n'+result+'\n<!-- /S27-RESULT -->',text,flags=re.S)
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+day+'. Current step: **S27 '+status+' — price lists and monthly fee schedules**. Next: **'+('S28 when selected' if status=='Verified' else 'Operator S27 verification; S28 follows')+'**.\n',text,count=1)
    (DOCS/'state.md').write_text(text)
    for filename in ['steps.csv','traceability.csv']:
        path=DOCS/filename;rows=list(csv.DictReader(path.open(newline='')))
        for row in rows:
            if row.get('step_id')=='S27':
                row.update(status=status,branch='step/s27-price-lists-fees',code_reference_commit=report['source_commit'].removeprefix('git:'),
                    evidence='; '.join(EVIDENCE),blocker='' if status=='Verified' else 'Full operator PG17/image/regression gate Pending; agent static checks only',
                    manual_acceptance='Greek browser review, VM rollout and all full acceptances Pending',next_step='S28 charge generation when selected')
            if row.get('requirement_id') in {'UR-BIL-01','UR-BIL-02','UR-LOC-01','QR-01','QR-06','QR-14'}:
                row['last_reviewed']=day
                for item in EVIDENCE:
                    if item not in row['evidence']:row['evidence']+='; '+item
                if 'S27' not in row['implementation_steps'].split():row['implementation_steps']+=' S27'
                row['notes']=re.sub(r' S27 (Prepared|Verified):.*?full acceptance Pending\.','',row['notes'])+' S27 '+status+': versioned catalogue/monthly plans, effective terms preview and immutable source identities; generation S28, full acceptance Pending.'
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
