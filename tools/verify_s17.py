#!/usr/bin/env python3
"""S17 documentation/reference arithmetic gate; does not start Docker or touch a database.

Prepared is the expected outcome until the named accountant/office owner have
reviewed the exact policy/examples. --require-approved enforces that manual gate.
"""
import argparse
import ast
from collections import Counter
import copy
import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, FloatOperation, localcontext
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
RECORDS=ROOT/'docs/implementation'
BASE='e6fde507f634a0ccd2de80b197bfd883d0ab7ac9'
POLICY=RECORDS/'financial_policy.json'
EXAMPLES=RECORDS/'examples/S17-financial-examples.json'
DOCUMENTS=(RECORDS/'financial_policy.md',RECORDS/'financial_policy_review_el.md',RECORDS/'examples/S17-financial-examples_el.md')
EXPECTED_CONTEXT='sha256:5352ffd3433d3cd814886712010ad97313e7bb7331d2dda5530d3ee271ec822d'
REVIEW_IDS={f'D08-{i:02d}' for i in range(1,11)}


def digest(data):
    return 'sha256:'+hashlib.sha256(data).hexdigest()


def load(path):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate JSON field: '+key)
            result[key]=value
        return result
    def no_float(value):raise ValueError('Numeric values must use exact decimal strings, not floats')
    return json.loads(Path(path).read_text(),object_pairs_hook=unique,parse_float=no_float,parse_constant=no_float)


def current_bindings():
    docs={str(path.relative_to(ROOT)):digest(path.read_bytes()) for path in DOCUMENTS}
    return {'policy_sha256':digest(POLICY.read_bytes()),'examples_sha256':digest(EXAMPLES.read_bytes()),
            'documents_sha256':digest(json.dumps(docs,sort_keys=True,separators=(',',':')).encode())}


def decimal(value):
    if not isinstance(value,str) or len(value)>64 or not re.fullmatch(r'-?[0-9]+(?:\.[0-9]+)?',value):
        raise ValueError('A finite bounded decimal string is required')
    result=Decimal(value)
    if not result.is_finite() or len(result.as_tuple().digits)>30 or abs(result.as_tuple().exponent)>12:
        raise ValueError('Reference decimal outside the declared precision envelope')
    return result


def expression(formula,inputs):
    if not isinstance(formula,str) or len(formula)>300:raise ValueError('Invalid reference formula')
    if not isinstance(inputs,dict) or not inputs:raise ValueError('Reference inputs required')
    values={name:decimal(value) for name,value in inputs.items()}
    tree=ast.parse(formula,mode='eval')
    if len(list(ast.walk(tree)))>80:raise ValueError('Reference formula too large')
    used=set()
    def visit(node):
        if isinstance(node,ast.Expression):return visit(node.body)
        if isinstance(node,ast.Name) and node.id in values:
            used.add(node.id);return values[node.id]
        if isinstance(node,ast.BinOp) and isinstance(node.op,(ast.Add,ast.Sub,ast.Mult)):
            left,right=visit(node.left),visit(node.right)
            return left+right if isinstance(node.op,ast.Add) else left-right if isinstance(node.op,ast.Sub) else left*right
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            value=visit(node.operand);return value if isinstance(node.op,ast.UAdd) else -value
        raise ValueError('Only declared variables and decimal addition/subtraction/multiplication are allowed')
    with localcontext() as context:
        context.prec=72;context.traps[FloatOperation]=True
        result=visit(tree)
    if used!=set(values):raise ValueError('Unused or missing reference input')
    return result


def reference_checks(policy,examples):
    if policy.get('document_id')!='ACC-FIN-001' or policy.get('version')!='0.1':raise ValueError('Unknown policy document/version')
    decisions=policy.get('decisions',[])
    if len(decisions)!=10 or {d['id'] for d in decisions}!=REVIEW_IDS:raise ValueError('Missing/duplicate D08 decision')
    for decision in decisions:
        if not decision.get('proposed_option') or not decision.get('proposed_rule') or not decision.get('blocks_steps'):
            raise ValueError('Each proposed choice needs a rule and named blocked steps')
        if decision.get('selected_option') is not None:raise ValueError('Candidate snapshot must not invent a human selection')
    invariants={row['id'] for row in policy['constraints']}
    if len(policy['constraints'])!=12 or invariants!={f'FIN-{i:03d}' for i in range(1,13)}:
        raise ValueError('Incomplete invariant inventory')
    operations=policy.get('operations',[])
    expected_ops={'OPEN','ADJUST_OPENING','REVERSE_REFUND','AGREEMENT','CHARGE','RECEIPT','PAYMENT','ALLOCATE','RELEASE','REFUND','TRANSFER',
                  'REVERSE_CASH','REVERSE_CHARGE','AMEND','CANCEL','RECURRING','TASK_CHARGE'}
    if len(operations)!=17 or {o['id'] for o in operations}!={'OP-'+n for n in expected_ops}:
        raise ValueError('Incomplete operation inventory')
    for operation in operations:
        for key in ('inputs','balance_effect','preconditions','correction','invariants','decisions','implementation_steps'):
            if not operation.get(key):raise ValueError('Incomplete operation: '+operation['id']+' '+key)
        if not set(operation['invariants'])<=invariants or not set(operation['decisions'])<=REVIEW_IDS:
            raise ValueError('Unknown operation decision/invariant')
    machines=policy['state_machines']
    if set(machines)!={'terms','charge','cash','allocation','settlement_projection'}:raise ValueError('Incomplete state machines')
    for name,machine in machines.items():
        states=machine['states']
        if len(states)!=len(set(states)):raise ValueError('Duplicate state')
        for start,end in machine.get('transitions',[]):
            if start not in states or end not in states or start==end:raise ValueError('Invalid state transition')
    if ['CANCELLED','ACTIVE'] in machines['terms']['transitions']:raise ValueError('Silent reactivation is not proposed')
    if examples.get('policy_document_id')!=policy['document_id']:raise ValueError('Example policy mismatch')
    scenarios=examples.get('examples',[]);denied=examples.get('denied_cases',[])
    if len(scenarios)!=20 or {r['id'] for r in scenarios}!={f'EX-{i:03d}' for i in range(1,21)}:
        raise ValueError('Missing/duplicate expected example')
    if len(denied)!=16 or {r['id'] for r in denied}!={f'DEN-{i:02d}' for i in range(1,17)}:
        raise ValueError('Missing/duplicate denied specification')
    rows=[]
    for scenario in scenarios:
        if not scenario.get('decision_ids') or not set(scenario['decision_ids'])<=REVIEW_IDS:
            raise ValueError('Every example needs its unresolved decision references')
        if not scenario.get('checks') or not scenario.get('implementation_steps'):raise ValueError('Incomplete example')
        labels=set()
        for check in scenario['checks']:
            if check['label'] in labels:raise ValueError('Duplicate example check')
            labels.add(check['label'])
            observed=expression(check['formula'],check['inputs'])
            if check.get('rounding'):
                if check['rounding']!='ROUND_HALF_UP' or 'D08-06' not in scenario['decision_ids']:
                    raise ValueError('Unknown/unbound candidate rounding convention')
                with localcontext() as context:
                    context.prec=72;observed=observed.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
            expected=decimal(check['expected'])
            if observed!=expected:raise ValueError('Reference arithmetic mismatch: '+scenario['id']+'/'+check['label'])
            if expected!=expected.quantize(Decimal('0.01')):raise ValueError('Expected posted result must be exact cents')
            rows.append({'example':scenario['id'],'check':check['label'],'formula':check['formula'],
                'expected':format(expected,'.2f'),'observed':format(observed,'.2f'),'result':'Arithmetic matched',
                'business_approval':'Pending bound accountant review','application_execution':'Not run by S17'})
    for row in denied:
        if not row.get('condition') or not row.get('expected') or not row.get('implementation_steps'):
            raise ValueError('Incomplete denied-case specification')
    for document in DOCUMENTS:
        text=document.read_text()
        required=REVIEW_IDS if document.name!='S17-financial-examples_el.md' else {e['id'] for e in scenarios}
        if any(token not in text for token in required):raise ValueError('Review document omits a required ID: '+document.name)
    return rows


def review_result(review,policy,bindings):
    if review is None:return {'status':'Pending','blocked_decisions':sorted(REVIEW_IDS),'reason':'Named accountant/office-owner review not recorded'}
    if type(review.get('schema_version')) is not int or review['schema_version']!=1 or review.get('document_id')!=policy['document_id']:raise ValueError('Unknown review schema/document')
    if any(review.get(k)!=v for k,v in bindings.items()):raise ValueError('Review is stale or bound to different policy/examples/documents')
    rows=review.get('decisions',[])
    if len(rows)!=10 or {r.get('id') for r in rows}!=REVIEW_IDS:raise ValueError('Missing/duplicate review decision')
    proposed={r['id']:r['proposed_option'] for r in policy['decisions']}
    blocked=sorted(r['id'] for r in rows if r.get('selected_option')!=proposed[r['id']])
    if not isinstance(review.get('conditions'),list):raise ValueError('Review conditions must be explicit')
    if review.get('status')!='Approved' or blocked or review['conditions'] or review.get('examples_reviewed') is not True:
        return {'status':'Pending','blocked_decisions':blocked or sorted(REVIEW_IDS),
                'reason':'Review pending or requests changes/conditions; revise and re-review the exact contract'}
    for key,role in (('accountant_reviewer','accountant'),('office_owner','office_owner')):
        person=review.get(key)
        if not isinstance(person,dict) or person.get('role')!=role or not isinstance(person.get('name'),str) or not 2<=len(person['name'].strip())<=200:
            raise ValueError('Approved review requires named accountant and office owner with their declared roles')
    try:
        reviewed=datetime.fromisoformat(review['reviewed_at'])
        if reviewed.tzinfo is None:raise ValueError('Timezone is required')
    except (KeyError,ValueError,TypeError):raise ValueError('Approved review requires a timezone-aware timestamp') from None
    ref=review.get('evidence_reference')
    if not isinstance(ref,str) or not 3<=len(ref.strip())<=500:raise ValueError('Approved review requires an actual review reference')
    return {'status':'Approved','blocked_decisions':[],'reviewed_at':reviewed.isoformat(),
        'accountant_and_owner_named':True,'examples_reviewed':True,'choices':proposed,
        'attestation':'Operator-supplied human-review record; not identity verification or a digital signature'}


def negative_controls(policy,examples,bindings):
    controls=[]
    wrong=copy.deepcopy(examples);wrong['examples'][0]['checks'][0]['expected']='999.00'
    missing=copy.deepcopy(examples);missing['examples'].pop()
    duplicate=copy.deepcopy(examples);duplicate['examples'][-1]=copy.deepcopy(duplicate['examples'][0])
    float_input=copy.deepcopy(examples);float_input['examples'][0]['checks'][0]['inputs']['opening']=0.1
    unsafe=copy.deepcopy(examples);unsafe['examples'][0]['checks'][0]['formula']='opening.__class__'
    for label,candidate in (('wrong-total',wrong),('missing-example',missing),('duplicate-example',duplicate),('float-input',float_input),('unsafe-expression',unsafe)):
        try:reference_checks(policy,candidate)
        except (ValueError,InvalidOperation,SyntaxError):controls.append(label);continue
        raise ValueError('Negative reference control was accepted: '+label)
    synthetic={'schema_version':1,'document_id':policy['document_id'],**bindings,'status':'Approved',
        'accountant_reviewer':{'name':'Synthetic reviewer','role':'accountant'},'office_owner':{'name':'Synthetic owner','role':'office_owner'},
        'reviewed_at':datetime.now(timezone.utc).isoformat(),'evidence_reference':'Synthetic parser fixture only',
        'decisions':[{'id':r['id'],'selected_option':r['proposed_option']} for r in policy['decisions']],
        'examples_reviewed':True,'conditions':[]}
    if review_result(synthetic,policy,bindings)['status']!='Approved':raise ValueError('Synthetic complete review parser control failed')
    stale=copy.deepcopy(synthetic);stale['policy_sha256']='sha256:'+'0'*64
    unnamed=copy.deepcopy(synthetic);unnamed['accountant_reviewer']=None
    duplicate_review=copy.deepcopy(synthetic);duplicate_review['decisions'][-1]=copy.deepcopy(duplicate_review['decisions'][0])
    for label,candidate in (('stale-review',stale),('unnamed-accountant',unnamed),('duplicate-review-decision',duplicate_review)):
        try:review_result(candidate,policy,bindings)
        except ValueError:controls.append(label);continue
        raise ValueError('Invalid review accepted: '+label)
    for label,field,value in (('unreviewed-examples','examples_reviewed',False),('conditional-review','conditions',['Synthetic unresolved condition'])):
        candidate=copy.deepcopy(synthetic);candidate[field]=value
        if review_result(candidate,policy,bindings)['status']=='Approved':raise ValueError('Incomplete review accepted: '+label)
        controls.append(label)
    changed=copy.deepcopy(synthetic);changed['decisions'][0]['selected_option']='different-unreviewed-option'
    if review_result(changed,policy,bindings)['status']=='Approved':raise ValueError('Alternative choice automatically accepted')
    controls.append('changed-policy-choice')
    return controls


def source_checks():
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE],cwd=ROOT,text=True).splitlines()
    protected=[n for n in names if n.startswith(('accounting/','core/','locale/','templates/','docker/','infrastructure/','docs/baselines/'))
        or n in {'requirements.in','requirements.txt','requirements-tools.in','requirements-tools.txt','Dockerfile',
            'docker-compose.yml','compose.production.yml','manage.py','gunicorn.conf.py','tools/image.py',
            'tools/verify_s16.py','accounting/regression_cases.json','docs/implementation/effective_baseline.json'}
        or n.startswith('docs/implementation/evidence/')]
    for name in protected:
        if (ROOT/name).read_bytes()!=subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT):
            raise ValueError('S17 must preserve application/baseline/evidence source: '+name)
    import image
    _,context=image.candidate_context()
    if context['digest']!=EXPECTED_CONTEXT:raise ValueError('S17 changed the S16 application context')
    s16=load(RECORDS/'evidence/S16-verification.json');g1=load(RECORDS/'evidence/G1-foundation.json')
    csv_path=RECORDS/'evidence/S16-office-boundary.csv'
    if (s16['status']!='Verified' or not s16['docker_execution'] or s16['suite']['tests_run']!=382
            or s16['suite']['known_failures_reproduced']!=26 or s16['boundary_matrix']['cases']!=652
            or not s16['boundary_matrix']['all_passed'] or g1['status']!='Verified'
            or s16['boundary_matrix']['sha256']!=digest(csv_path.read_bytes())):
        raise ValueError('Actual S16 Docker/G1 verification is required')
    if any(s16['suite'][k] for k in ('unexpected_failures','unexpected_errors','unexpected_successes','skips')):
        raise ValueError('S16 verification has unresolved outcomes')
    registry=load(ROOT/'accounting/regression_cases.json')
    if sum(r['expected_outcome']=='known_failure' for r in registry['cases'])!=26:raise ValueError('Financial failure registry changed')
    return {'source_reference_commit':'git:'+BASE,'s16_status':'Verified','g1_technical_status':'Verified',
        'previous_application_suite':s16['suite'],'application_context_digest':context['digest'],
        'protected_files':len(protected),'original_ten_migrations_all_application_code_and_tests_preserved':True,
        'dependency_locks_and_all_historical_evidence_preserved':True,'known_financial_failures_preserved':26}


def private_review_path(path):
    path=path.resolve()
    if path.is_relative_to(ROOT) and not path.is_relative_to(ROOT/'private'):
        raise ValueError('Keep named review records in ignored private/ or outside Git')
    return path


def record(report,rows):
    evidence=RECORDS/'evidence/S17-reference-checks.csv'
    for row in rows:
        row['business_approval']='Approved in bound review' if report['review']['status']=='Approved' else 'Pending bound accountant review'
    with evidence.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    report['reference_arithmetic']['evidence']='docs/implementation/evidence/S17-reference-checks.csv'
    report['reference_arithmetic']['sha256']=digest(evidence.read_bytes())
    (RECORDS/'evidence/S17-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (RECORDS/'steps.csv').open(newline='') as stream:steps=list(csv.DictReader(stream))
    step=next(r for r in steps if r['step_id']=='S17')
    step.update(status=report['status'],branch='step/s17-financial-policy',code_reference_commit=report['source_commit'].removeprefix('git:'),
        evidence='docs/implementation/financial_policy.md; docs/implementation/financial_policy.json; docs/implementation/examples/S17-financial-examples.json; docs/implementation/evidence/S17-verification.json',
        manual_acceptance='Named accountant/office owner must review D08 choices and examples; full requirement acceptance remains Pending',
        blocker='Accountant decisions D08-01–D08-10 are Pending' if report['status']!='Verified' else '',
        next_step='Record D08 review before S18' if report['status']!='Verified' else 'S18 for approved operations only')
    with (RECORDS/'steps.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=steps[0],lineterminator='\n');writer.writeheader();writer.writerows(steps)
    path=RECORDS/'state.md';text=path.read_text()
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+report['verified_at'][:10]+'. Current step: **S17 '+report['status']+' — financial policy**. Next step: **'+step['next_step']+'**.\n',text,count=1)
    note='<!-- S17-RESULT -->\n'+report['status']+': 17 operation contracts, 10 explicit D08 decisions, 20 worked examples and '+str(len(rows))+' exact-decimal arithmetic checks; 16 denied specifications are for future application tests. Application/database/cloud execution this step: none. D08 review: '+report['review']['status']+'. All full requirement acceptances remain Pending.\n<!-- /S17-RESULT -->'
    if '<!-- S17-RESULT -->' in text:text=re.sub(r'<!-- S17-RESULT -->.*?<!-- /S17-RESULT -->',note,text,flags=re.S)
    else:text+='\n'+note+'\n'
    path.write_text(text)
    path=RECORDS/'traceability.csv'
    with path.open(newline='') as stream:requirements=list(csv.DictReader(stream))
    for r in requirements:
        if r['requirement_id'] not in {'QR-03','QR-04'}:continue
        r['notes']=re.sub(r' S17:.*$','',r['notes'])+' S17: '+report['status']+' policy/reference arithmetic; D08 review '+report['review']['status']+'. No financial fixes, application/database execution or full acceptance claimed.'
        for item in ('docs/implementation/financial_policy.md','docs/implementation/financial_policy.json','docs/implementation/evidence/S17-verification.json','docs/implementation/examples/S17-financial-examples.json'):
            if item not in r['evidence'].split('; '):r['evidence']='; '.join(filter(None,[r['evidence'],item]))
        r['last_reviewed']=report['verified_at'][:10]
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=requirements[0],lineterminator='\n');writer.writeheader();writer.writerows(requirements)
    if report['review']['status']=='Approved':
        path=RECORDS/'decision_register.json';register=load(path)
        d08=next(d for d in register['decisions'] if d['id']=='D08')
        d08['status']='Approved for reviewed ACC-FIN-001 v0.1 snapshot; implementation and release acceptance Pending'
        d08['approval_evidence']={'path':'docs/implementation/evidence/S17-verification.json','review_sha256':report['review']['sha256'],**report['bindings']}
        d08['confirmed']=[key+': '+value for key,value in sorted(report['review']['choices'].items())]
        d08['unresolved']=['Unimplemented/excluded operations remain outside the reviewed first scope; later changes require review.']
        path.write_text(json.dumps(register,ensure_ascii=False,indent=2)+'\n')
        path=RECORDS/'decisions.md';text=path.read_text()
        start=text.index('## D08 — Office financial posting policy');end=text.index('\n## D09',start)
        section=text[start:end]
        section=re.sub(r'(Status: )\*\*.*?\*\*',r'\1**Approved for the bound ACC-FIN-001 v0.1 scope; implementation/release acceptance Pending**',section,count=1)
        section=section.replace('Open inputs:','Review topics resolved for the bound first scope:')
        section=section.replace('Approval evidence: **not recorded**.','Approval evidence: bound S17 receipt in evidence/S17-verification.json; named review retained privately.')
        marker='### S17 D08 review packet'
        section=section[:section.index(marker)]+marker+' — Approved bound snapshot\n\n'
        section+='Declared accountant/office-owner review recorded at '+report['review']['reviewed_at']+'. The receipt binds the exact candidate policy, examples and documents. Names and source reference remain private. This records adoption of the reviewed contents, not application correctness or release acceptance.\n'
        text=text[:start]+section+text[end:]
        path.write_text(text)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',action='store_true')
    parser.add_argument('--review-file',type=Path)
    parser.add_argument('--make-review-template',type=Path)
    parser.add_argument('--require-approved',action='store_true')
    parser.add_argument('--tools-python',type=Path,help='Optional existing pinned maintenance Python for a fresh candidate/history secret scan')
    args=parser.parse_args()
    try:
        if args.record and subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
            raise ValueError('Commit the candidate source/evidence before recording another verification')
        source=source_checks();policy=load(POLICY);examples=load(EXAMPLES)
        rows=reference_checks(policy,examples);bindings=current_bindings()
        controls=negative_controls(policy,examples,bindings)
        if args.make_review_template:
            if args.record or args.review_file or args.require_approved:raise ValueError('Template creation is separate from recording/review validation')
            target=private_review_path(args.make_review_template)
            template=load(RECORDS/'financial_policy_review.template.json');template.update(bindings)
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            import os
            with open(target,'x',opener=lambda name,flags:os.open(name,flags,0o600)) as stream:
                stream.write(json.dumps(template,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'status':'Review template created','private_review_file':str(target),'approval':'Pending','application_changed':False},indent=2));return
        previous=RECORDS/'evidence/S17-verification.json'
        if args.record and previous.exists() and load(previous)['status']=='Verified' and args.review_file is None:
            raise ValueError('Supply the existing bound review file when refreshing an approved policy record')
        review=load(private_review_path(args.review_file)) if args.review_file else None
        outcome=review_result(review,policy,bindings)
        if args.review_file:outcome['sha256']=digest(args.review_file.read_bytes())
        report={'step':'S17','status':'Verified' if outcome['status']=='Approved' else 'Prepared',
            'mode':'policy-document-and-reference-arithmetic','verified_at':datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit':'git:'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),**source,'bindings':bindings,
            'reference_arithmetic':{'scenarios':20,'checks':len(rows),'all_matched':True,'rounding':'Proposed ROUND_HALF_UP per derived line; not an approved tax rule'},
            'operation_contracts':17,'pending_or_bound_decisions':10,'denied_application_case_specifications':16,
            'negative_controls':controls,'review':outcome,'application_tests_run_this_step':False,
            'database_or_migration_execution':False,'docker_execution_this_step':False,'cloud_or_vm_changed':False,
            'human_application_accounts_created':False,'known_financial_failures_fixed':0,
            'full_requirement_acceptance':'Pending','full_requirement_acceptances_pending':85,
            'next_step':'S18 for the reviewed scope' if outcome['status']=='Approved' else 'Accountant/office-owner decisions before S18'}
        if args.tools_python:
            scanned=subprocess.run([str(args.tools_python),str(ROOT/'tools/scan_secrets.py')],cwd=ROOT,capture_output=True,text=True)
            if scanned.returncode:raise ValueError('Fresh secret scan failed; inspect findings locally without pasting source lines')
            report['secret_scan']=json.loads(scanned.stdout)
        else:report['secret_scan_this_step']='Not rerun; supply --tools-python with the pinned maintenance environment to scan history/candidate'
        if args.record:record(report,rows)
        print(json.dumps(report,ensure_ascii=False,indent=2))
        if args.require_approved and outcome['status']!='Approved':
            parser.exit(2,'S17 policy approval remains Pending; no posting implementation has been changed.\n')
    except (ValueError,OSError,KeyError,InvalidOperation,SyntaxError,subprocess.SubprocessError) as error:
        parser.exit(1,'S17 stopped: '+str(error)+'\n')


if __name__=='__main__':main()
