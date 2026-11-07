#!/usr/bin/env python3
"""Verify the S01 handoff without importing Django or accessing a database.

Run from any directory with Python 3.12 or newer. This checks the S01 snapshot;
later implementation steps are expected to change its source files and records.
"""
from pathlib import Path
from collections import Counter
from zipfile import ZipFile
import argparse, ast, csv, hashlib, json, re, subprocess

ROOT=Path(__file__).resolve().parents[1]
RECORDS=ROOT/'docs/implementation'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

def rows(name):
    with (RECORDS/name).open(encoding='utf-8',newline='') as f:return list(csv.DictReader(f))

def verify(archive=None):
    checks=[]
    def check(name,condition,detail):
        if not condition:raise AssertionError(name+': '+str(detail))
        checks.append({'check':name,'result':'PASS','detail':detail})
    reqs=rows('traceability.csv');users=[x for x in reqs if x['requirement_id'].startswith('UR-')];quality=[x for x in reqs if x['requirement_id'].startswith('QR-')]
    check('requirement counts',len(users)==70 and len(quality)==14 and len({x['requirement_id'] for x in reqs})==84,'70 UR and 14 QR; 84 unique identifiers')
    check('requirements remain pending',all(x['acceptance_status']=='Pending' and x['evidence']=='' for x in reqs),'S01 does not pass any application requirement')
    check('acceptance identifiers',all(x['acceptance_test_id']==('AT-'+x['requirement_id'][3:] if x['requirement_id'].startswith('UR-') else 'QT-'+x['requirement_id'][3:]) for x in reqs),'AT and QT identifiers follow the requirements baseline')
    steps=rows('steps.csv');ids=[x['step_id'] for x in steps]
    check('step registry',ids==[f'S{x:02}' for x in range(1,65)],'S01 through S64, in order')
    check('step status',steps[0]['status']=='Verified' and all(x['status']=='Not started' for x in steps[1:]),'S01 Verified; S02 through S64 Not started')
    for s in steps:
        deps=[d for d in s['dependencies'].split() if d]
        check(s['step_id']+' dependencies',all(d in ids and int(d[1:])<int(s['step_id'][1:]) for d in deps),'all dependencies refer to earlier steps')
    check('requirement allocation',all(x['implementation_steps'] and all(s in ids for s in x['implementation_steps'].split()) for x in reqs),'every requirement maps to valid numbered steps')
    manifest=rows('source_manifest.csv');included=[x for x in manifest if x['working_path']]
    for row in included:
        p=ROOT/row['working_path']
        check('source '+row['working_path'],p.is_file() and sha(p)==row['working_sha256'],'working export matches its manifest')
        if row['disposition']=='Preserved':
            check('unchanged '+row['working_path'],row['working_sha256']==row['source_sha256'],'byte-identical to the original archive entry')
    protected=['accounting/models.py','accounting/migrations/0001_initial.py','accounting/migrations/0002_transaction_agreement_alter_agreement_status_and_more.py']
    check('business models and migration identities',all(next(r for r in included if r['working_path']==p)['disposition']=='Preserved' for p in protected),'models.py and both migration files are unchanged')
    baseline=json.loads((RECORDS/'baseline_sources.json').read_text())
    for item in baseline['documents']:
        p=ROOT/item['repository_path'];check('baseline '+item['identifier'],p.is_file() and sha(p)==item['sha256'],'saved baseline bytes preserved')
    python_files=[p for folder in ['accounting','core','tools'] for p in (ROOT/folder).rglob('*.py')]+[ROOT/'manage.py']
    for p in python_files:ast.parse(p.read_text(encoding='utf-8'),filename=str(p))
    check('Python syntax',True,f'{len(python_files)} Python files parsed without importing the application')
    tree=ast.parse((ROOT/'core/settings.py').read_text());secret=None;passwords=[]
    for n in tree.body:
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='SECRET_KEY' for t in n.targets):secret=ast.literal_eval(n.value)
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='DATABASES' for t in n.targets):
            for child in ast.walk(n.value):
                if isinstance(child,ast.Dict):
                    passwords += [ast.literal_eval(v) for k,v in zip(child.keys,child.values) if isinstance(k,ast.Constant) and k.value=='PASSWORD']
    check('working configuration redaction',secret=='' and passwords==[''],'legacy SECRET_KEY and database password values are absent')
    compose=(ROOT/'docker-compose.yml').read_text();assignments=re.findall(r'^\s*-\s*POSTGRES_PASSWORD=(.*)$',compose,re.M)
    check('Compose credential redaction',assignments==[''],'legacy Compose password is absent')
    forbidden=[p for p in ROOT.rglob('*') if '.git' not in p.parts and (p.name=='backup.sql' or p.suffix=='.pyc' or 'venv' in p.relative_to(ROOT).parts)]
    check('runtime payload exclusion',not forbidden,'no database dump, bundled venv or Python bytecode in the working package')
    inventory=json.loads((RECORDS/'source_inventory.json').read_text())
    check('inventory shape',len(inventory['models'])==5 and len(inventory['migrations'])==2 and len(inventory['views'])==15 and len(inventory['templates'])==17,'5 models, 2 migrations, 15 views and 17 templates')
    view_names={x['name'] for x in inventory['views']}
    check('route targets',all(x['view'].split('.',1)[1] in view_names for x in inventory['routes'] if x['view'].startswith('views.')),'all accounting view references resolve in the source inventory')
    check('source baseline commit',bool(re.fullmatch(r'[0-9a-f]{40}',baseline['source_baseline_commit'])),'actual Git source baseline identity recorded')
    result=subprocess.run(['git','rev-parse','--verify',baseline['source_baseline_commit']+'^{commit}'],cwd=ROOT,capture_output=True,text=True)
    check('source baseline recoverable',result.returncode==0,'source baseline commit exists in this repository')
    if archive:
        check('original archive checksum',sha(archive)==baseline['source_archive']['sha256'],'untouched archive matches the recorded original')
        with ZipFile(archive) as z:
            for row in manifest:
                check('archive '+row['source_path'],hashlib.sha256(z.read(row['source_path'])).hexdigest()==row['source_sha256'],'archive member checksum matches')
    return {'step':'S01','status':'Verified','checks_passed':len(checks),'requirements':{'user':len(users),'quality':len(quality),'acceptance':'Pending'},'steps':len(steps),'source_baseline_commit':baseline['source_baseline_commit'],'source_files_in_package':len(included),'application_tests_run':False,'database_or_migration_execution':False,'google_cloud_resources_created':False,'checks':checks}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--archive',type=Path);parser.add_argument('--report',type=Path)
    args=parser.parse_args();report=verify(args.archive)
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='checks'},indent=2))
