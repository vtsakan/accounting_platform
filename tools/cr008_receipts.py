"""Exclusive binding of the actual successful CR007 operator result, never recreated."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from cr007_receipts import EXPECTED as PRIOR,digest,verify_binding as verify_prior

BINDING='docs/implementation/evidence/CR008-operator-baseline.json'
REPORT='docs/implementation/evidence/CR007-verification.json'
PREVIOUS_BINDING='docs/implementation/evidence/CR007-operator-baseline.json'
CONTEXT='sha256:15e6f913692f72784d708e3b5e6c29caea5189004fc135158102c27f6b61092a'
PATHS=[*PRIOR,PREVIOUS_BINDING,REPORT]


def need(value,message):
    if not value:raise RuntimeError(message)


def git(root,*args):
    return subprocess.check_output(['git',*args],cwd=root,text=True).strip()


def validate(root):
    root=Path(root).resolve();verify_prior(root)
    report=json.loads((root/REPORT).read_text());suite=report.get('suite',{})
    need(report.get('change')=='CR-007' and report.get('status')=='Verified','Απαιτείται η πραγματική επιτυχής αναφορά CR007.')
    need(suite.get('tests_run')==suite.get('tests_passed')==1140
        and all(suite.get(k)==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips'))
        and len(suite.get('cases',[]))==36 and all(r.get('outcome')=='passed' for r in suite['cases']),
        'Απαιτούνται τα πραγματικά 1140/1140 και οι36 οικονομικές περιπτώσεις.')
    need(report.get('application_context_digest')==CONTEXT and report.get('new_test_methods')==55
        and report.get('retained_source_files_checked')==783,'Διαφέρει η επιτυχής διορθωμένη CR007.')
    need(all(report.get(k) is True for k in ('real_monthly_worker_and_commit_before_ack','revocation_blocks_execution',
        'second_scheduler_rejected','restricted_role_migrations','historical_receipts_unchanged','docker_execution_by_operator',
        'owned_resources_removed','vm_github_hold_by_user')),'Απουσιάζει πραγματική ολοκλήρωση worker/διατήρησης CR007.')
    need(all(report.get(k) is False for k in ('agent_native_execution','local_demo_or_vm_changed','github_updated','human_accounts_or_mfa_changed')),
        'Διαφέρει το πραγματικό πεδίο εκτέλεσης CR007.')
    need(report.get('actual_prior_receipt_files_sha256')==PRIOR and report.get('full_requirement_acceptances_pending')==85,
        'Διαφέρουν οι προηγούμενες αναφορές ή οι εκκρεμείς αποδοχές.')
    source=report.get('source_commit','')
    need(re.fullmatch(r'git:e1523b9[0-9a-f]{33}',source) is not None,'Απαιτείται η πραγματική επιτυχής πηγή e1523b9 του χειριστή.')
    completion=git(root,'rev-parse','02e3907^{commit}')
    need(subprocess.run(['git','merge-base','--is-ancestor',completion,'HEAD'],cwd=root,capture_output=True).returncode==0,
        'Απαιτείται το πραγματικό commit02e3907 που διατήρησε το αποτέλεσμα CR007.')
    need(git(root,'rev-parse',completion+'^')==source[4:],'Διαφέρει η πραγματική καταγραφή αποτελέσματος CR007.')
    need(set(git(root,'diff','--name-only',source[4:],completion).splitlines())=={REPORT,'docs/implementation/state.md'},
        'Το commit αποτελέσματος πρέπει να περιέχει μόνο τα δύο πραγματικά αρχεία.')
    need((root/REPORT).read_bytes()==subprocess.check_output(['git','show',completion+':'+REPORT],cwd=root),
        'Η πραγματική αναφορά CR007 άλλαξε μετά την καταγραφή της.')
    image=report.get('image',{});context=image.get('context',{})
    need(context.get('digest')==CONTEXT and context.get('file_count')==351
        and image.get('verification_revision')==source
        and re.fullmatch(r'sha256:[0-9a-f]{64}',image.get('image_id','')) is not None,
        'Απουσιάζει η ακριβής ταυτότητα της εικόνας που πέρασε τη CR007.')
    return {'change':'CR-008','schema':1,'cr007_source_commit':source,'cr007_record_commit':'git:'+completion,
        'cr007_tests_passed':1140,'cr007_financial_cases':36,'files':{name:digest(root,name) for name in PATHS}}


def verify_binding(root):
    root=Path(root).resolve();expected=validate(root);digest(root,BINDING)
    need(json.loads((root/BINDING).read_text())==expected,'Η δέσμευση CR008 άλλαξε. Δεν ανανεώθηκε.')
    return expected


def bind(root):
    root=Path(root).resolve();value=validate(root);path=root/BINDING
    if path.exists() or path.is_symlink():return verify_binding(root)
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return verify_binding(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['validate','bind','check']);parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    try:{'validate':validate,'bind':bind,'check':verify_binding}[args.action](args.root);print('Actual CR007 result and all14 prior files retained: '+args.action)
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as error:parser.exit(1,str(error)+'\n')
