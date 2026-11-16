#!/usr/bin/env python3
"""Tracking/source metadata only: never import Django or invoke runtime tools."""
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/implementation'
EVIDENCE = ('docs/implementation/evidence/S26-verification.json', 'docs/implementation/background_jobs.md',
    'accounting/tests_background_jobs.py', 'docs/implementation/evidence/S26-preserved-source.json')


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator='\n')
        writer.writeheader();writer.writerows(rows)


def record_result(report):
    status=report['status']
    if status not in {'Prepared','Verified'}:raise ValueError('Unexpected S26 state')
    verified=status=='Verified'
    day=report.get('verified_at',report.get('prepared_at'))[:10]
    reference=report['source_commit'].removeprefix('git:')
    (DOCS/'evidence/S26-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    path=DOCS/'state.md';text=path.read_text()
    result=('Operator S26 production-image and real Redis gate Verified. The retained suite, scoped job effects, dispatch recovery, cancellation/revocation, singleton scheduler and restart checks passed. Full acceptance, VM deployment and feature-specific jobs remain Pending.' if verified else
        'Prepared source-only S26: same-image Redis/Celery worker and exactly-one scheduler definitions, durable DB outbox, fenced atomic client probe, retry/cancellation/fresh authority guards and private queue health. 35 new test methods supplied; expected 696 total is a target, not an observed result. Agent execution: static source checks only. Operator command: python3 tools/verify_s26.py --record. VM/deployment, future fee/mail/task adapters and all 85 full acceptances remain Pending.')
    block='<!-- S26-RESULT -->\n'+result+'\n<!-- /S26-RESULT -->'
    if '<!-- S26-RESULT -->' in text:
        text=re.sub(r'<!-- S26-RESULT -->.*?<!-- /S26-RESULT -->',block,text,flags=re.S)
    else:
        text=text.replace('## Current selected work — S25','## Previous verified work — S25',1)
        at=text.index('\n## ')
        text=text[:at]+'\n\n## Current selected work — S26\n\n'+block+'\n'+text[at:]
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+day+'. Current step: **S26 '+status+' — reliable background execution**. Next: **'+('S27 recurring fee schedules when selected' if verified else 'Operator S26 verification; S27 follows')+'**.\n',text,count=1)
    # Record the actual supplied S25 log without replacing its local --record output.
    s25='Operator S25 synthetic rehearsal Verified on 2026-11-16: 61 planner tests, 184 financial checks, concurrency, atomic rollback and encrypted native15/target17 recovery passed. Source git:456f7db74a7dfbf8599d588fedf6cc0f16483d32. See evidence/S25-operator-completion.json; actual local S25-verification.json is preserved. D05/G2 and all 85 full acceptances remain Pending.'
    text=re.sub(r'<!-- S25-RESULT -->.*?<!-- /S25-RESULT -->','<!-- S25-RESULT -->\n'+s25+'\n<!-- /S25-RESULT -->',text,flags=re.S)
    path.write_text(text)
    path=DOCS/'steps.csv';rows=list(csv.DictReader(path.open(newline='')))
    row=next(r for r in rows if r['step_id']=='S26')
    row.update(status=status,branch='step/s26-background-execution',code_reference_commit=reference,
        evidence='; '.join(EVIDENCE),blocker='' if verified else 'Tests/builds/Docker/migrations unexecuted by agent; operator gate Pending',
        manual_acceptance='VM rollout, workload targets, future feature adapters and all full acceptances Pending',next_step='S27 recurring fee schedules when selected')
    previous=next(r for r in rows if r['step_id']=='S25')
    previous['status']='Verified';previous['code_reference_commit']='456f7db74a7dfbf8599d588fedf6cc0f16483d32'
    previous['blocker']='Synthetic technical gate passed; D05/G2/accepted workload recovery/full acceptance Pending'
    item='docs/implementation/evidence/S25-operator-completion.json'
    if item not in previous['evidence']:previous['evidence']+='; '+item
    write_csv(path,rows)
    path=DOCS/'traceability.csv';rows=list(csv.DictReader(path.open(newline='')))
    for row in rows:
        if row['requirement_id'] in {'QR-01','QR-06','QR-12','UR-LOC-01'}:
            row['last_reviewed']=day
            for name in EVIDENCE:
                if name not in row['evidence']:row['evidence']+='; '+name
            note=' S26 '+status+': common scoped DB-only probe/jobs, bounded retry, durable dispatch recovery and singleton scheduler; future adapters and full acceptance Pending.'
            row['notes']=re.sub(r' S26 (Prepared|Verified):.*?full acceptance Pending\.','',row['notes'])+note
            if row['requirement_id']=='UR-LOC-01' and 'S26' not in row['implementation_steps'].split():
                row['implementation_steps']+=' S26'
        if row['requirement_id'] in {'QR-03','QR-04','QR-09','QR-14'}:
            item='docs/implementation/evidence/S25-operator-completion.json'
            if item not in row['evidence']:row['evidence']+='; '+item
            note=' S25 operator synthetic technical rehearsal passed; D05/G2/full acceptance remain Pending.'
            if note not in row['notes']:row['notes']+=note
        # Full acceptance is independent of technical source/operator completion.
    write_csv(path,rows)


def main():
    report=json.loads((DOCS/'evidence/S26-verification.json').read_text())
    if report['status']=='Verified':raise SystemExit('Do not replace a Verified S26 receipt with preparation')
    report['source_commit']='git:'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    record_result(report)


if __name__=='__main__':main()
