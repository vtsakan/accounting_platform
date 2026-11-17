"""Source/tracking only. No application/test/build/migration execution."""
import csv,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];DOCS=ROOT/'docs/implementation'
EVIDENCE=['docs/implementation/evidence/S30-verification.json','docs/implementation/report_exports.md',
    'docs/implementation/evidence/S30-source.json','docs/implementation/evidence/S30-preserved-source.json',
    'accounting/export_selectors.py','accounting/tests_exports.py']


def record_result(report):
    status=report['status']
    if status not in {'Prepared','Verified'}:raise ValueError('Unexpected S30 status')
    day=report.get('verified_at',report.get('prepared_at'))[:10]
    (DOCS/'evidence/S30-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    state=DOCS/'state.md';text=state.read_text().replace('## Current selected work — S29','## Previous verified work — S29',1)
    if '<!-- S30-RESULT -->' not in text:
        at=text.index('\n## ');text=text[:at]+'\n\n## Current selected work — S30\n\n<!-- S30-RESULT -->\n<!-- /S30-RESULT -->\n'+text[at:]
    result=('Operator S30 production-image/PG17 gate Verified: full retained suite/36 finance cases, screen/PDF/CSV '
        'reconciliation, Greek Unicode font/text readback, complete pagination, formula-safe CSV, live download authority '
        'and concurrent snapshot/revocation contracts passed. Retained real S28 scheduler/Redis/ack-loss gate passed. '
        'PDF visual/browser/full acceptance, D05/G2 and VM rollout remain Pending.' if status=='Verified' else
        'Prepared source-only S30: authenticated in-memory PDF/CSV period reports, dated statements and annual overviews '
        'from unchanged S29 selectors and complete unpaged querysets. Greek/euro fonts, typed exact money, CSV text protection, '
        'private/no-store downloads, live authority after rendering and S59 provenance extension supplied. '
        '40 operator-run methods; 848/36 and retained real S28 broker gate are unobserved targets. '
        'No new migration. Agent tests/builds/Docker/migrations/native PDF/app verification unexecuted. '
        'PDF visual/browser/full acceptance, D05/G2 and VM rollout remain Pending.')
    text=re.sub(r'<!-- S30-RESULT -->.*?<!-- /S30-RESULT -->','<!-- S30-RESULT -->\n'+result+'\n<!-- /S30-RESULT -->',text,flags=re.S)
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+day+'. Current step: **S30 '+status+' — PDF and CSV report exports**. Next: **'+
        ('S31 when selected' if status=='Verified' else 'Operator S30 verification; S31 follows')+'**.\n',text,count=1);state.write_text(text)
    for name in ('steps.csv','traceability.csv'):
        path=DOCS/name
        with path.open(newline='') as stream:rows=list(csv.DictReader(stream))
        for row in rows:
            if row.get('step_id')=='S30':
                row.update(status=status,branch='step/s30-report-exports',code_reference_commit=report['source_commit'].removeprefix('git:'),
                    evidence='; '.join(EVIDENCE),blocker='' if status=='Verified' else 'Full operator 848/36 PDF/CSV and retained real fee-worker gate Pending; static agent work only',
                    manual_acceptance='Greek PDF visual/browser review, deployment and all full acceptances Pending',next_step='S31 finance release gate when selected')
            if row.get('requirement_id') in {'UR-REP-04','UR-LOC-01','QR-01','QR-03','QR-07','QR-14'}:
                row['last_reviewed']=day
                for item in EVIDENCE:
                    if item not in row['evidence']:row['evidence']+='; '+item
                if 'S30' not in row['implementation_steps'].split():row['implementation_steps']+=' S30'
                row['notes']=re.sub(r' S30 (Prepared|Verified):.*?full acceptance Pending\.','',row['notes'])+' S30 '+status+': authenticated scoped PDF/CSV exports with Greek text, exact totals, safe CSV and live authority; full acceptance Pending.'
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
