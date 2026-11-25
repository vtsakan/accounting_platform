#!/usr/bin/env python3
"""Operator-only GSIS copy gate: new source/image, full PG17 suite/files/worker."""
import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from dev import ROOT, require_local_docker
import image
from cr009_receipts import BASELINE, verify_binding
from cr009_static_inputs import inspect
from r1_gate import digest_bytes, require
from verify_cr008 import retained_assertion_dump

LOCK=ROOT/'docs/implementation/evidence/CR009-source-lock.json'
MANIFEST=ROOT/'docs/implementation/evidence/CR009-source.json'
REPORT='docs/implementation/evidence/CR009-verification.json'
STATE='docs/implementation/state.md'


def source_check():
    static=inspect(ROOT); policy=json.loads(LOCK.read_text()); expected={}
    manifest=json.loads(MANIFEST.read_text())
    require(not LOCK.is_symlink() and not MANIFEST.is_symlink()
        and manifest['change']==policy['change']=='CR-009' and manifest['status']==policy['status']=='Prepared'
        and manifest['source_lock_sha256']==digest_bytes(LOCK.read_bytes()), 'The prepared GSIS source-lock identity differs')
    require(policy['retained_test_count']==1186 and policy['new_test_methods']==24 and policy['expected_suite']==1210
        and policy['application_inputs']==377 and policy['retained_migrations']==36 and policy['new_migrations']==0,
        'Keep the exact selected GSIS source, retained suite and migration scope')
    require(policy.get('retained_deployment_guard_methods')==115
        and policy.get('actual_prior_reports_bound_exclusively')==21,
        'Retain the current4GiB deployment corrections and actual21-file history')
    for section in ('unchanged_files','changed_files','added_files'):
        entries=policy[section]
        require(isinstance(entries,dict) and bool(entries),'Missing source binding section')
        for name,value in entries.items():
            path=Path(name)
            require(name not in expected and not path.is_absolute() and '..' not in path.parts,
                'Invalid prepared source binding path')
            expected[name]=value
    for name,value in expected.items():
        path=ROOT/name
        require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(ROOT.resolve())
            and digest_bytes(path.read_bytes())==value, 'Prepared CR009 source changed: '+name)
    from preview_cr008_policy import unchanged_acceptances
    unchanged_acceptances(ROOT)
    for name,value in policy['retained_test_methods'].items():
        methods=[retained_assertion_dump(n) for n in ast.walk(ast.parse((ROOT/name).read_text()))
            if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
        require(digest_bytes(json.dumps(methods,separators=(',',':')).encode())==value,
            'An original test method changed: '+name)
    for name,value in policy['retained_deployment_guard_files'].items():
        require(digest_bytes((ROOT/name).read_bytes())==value,
            'A retained current4GiB deployment guard changed: '+name)
    tools_methods=sum(isinstance(node,ast.FunctionDef) and node.name.startswith('test_')
        for name in policy['retained_deployment_guard_files']
        for node in ast.walk(ast.parse((ROOT/name).read_text())))
    require(tools_methods==115,'Retain all115 deployed CR008 tool guard methods')
    context=image.candidate_context()[1]
    require(context['digest']==policy['application_context_digest'] and context['file_count']==policy['application_inputs'],
        'The prepared GSIS image inputs changed')
    methods=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_')
        for n in ast.walk(ast.parse((ROOT/'accounting/tests_gsis.py').read_text())))
    require(methods==policy['new_test_methods'],'GSIS operator test methods changed')
    return policy,len(expected),static


def clean_source():
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip(),
        'Commit source first; unrelated changes were retained without automatic storage')


def track(report):
    path=ROOT/STATE;before=path.read_bytes();start=b'<!-- CR009-RESULT -->';end=b'<!-- /CR009-RESULT -->'
    require(before.count(start)==before.count(end) and before.count(start)<=1,'Ambiguous CR009 tracking markers')
    block=(start.decode()+'\nVerified: '+str(report['suite']['tests_passed'])+' isolated PG17 tests,36 financial cases, '
        'real file antivirus/recovery and retained monthly worker. GSIS opens with explicit selected-person copy; '
        'no extension or cross-origin autofill. Native GSIS/browser/clipboard acceptance Pending. '
        'Current4GiB deployment115 guards retained and passed; rollout authorised after this gate, '
        'VM upgrade Pending; all85 full acceptances Pending.\n'+end.decode()).encode()
    if start in before:
        a=before.index(start);b=before.index(end)+len(end);require(a<b,'Unordered CR009 tracking markers')
        after=before[:a]+block+before[b:]
    else:after=before+b'\n\n'+block+b'\n'
    path.write_bytes(after)


def record(report, policy):
    clean_source(); bound=verify_binding(ROOT); source_check()
    require(report['source_commit']=='git:'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        and report['status']=='Verified'
        and report['suite']['tests_run']==report['suite']['tests_passed']==policy['expected_suite']
        and report['application_context_digest']==policy['application_context_digest']
        and report['actual_prior_receipt_files_sha256']==bound['files']
        and all(report[k] is True for k in ('real_monthly_worker_and_commit_before_ack','revocation_blocks_execution',
            'second_scheduler_rejected','restricted_role_migrations','historical_receipts_unchanged',
            'deployment_guard_suite_passed','vm_github_upgrade_authorized_after_verification'))
        and report.get('deployment_guard_tests_passed')==115
        and report.get('prior_completed_vm_record')==bound['previous_completed_vm_record']
        and all(report[k] is False for k in ('local_demo_or_vm_changed','github_updated','human_accounts_or_mfa_changed',
            'agent_native_execution','vm_github_hold_by_user')),
        'Record only the exact current successful operator result')
    destination=ROOT/REPORT
    require(not destination.exists() and not destination.is_symlink(),'A prior CR009 result exists; retain it for review')
    with destination.open('x') as stream:stream.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    track(report)
    allowed={REPORT,STATE}
    changed=set(subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=ROOT,text=True).splitlines())
    extra=set(subprocess.check_output(['git','ls-files','--others','--exclude-standard'],cwd=ROOT,text=True).splitlines())
    require(changed|extra==allowed,'Only the exact result/tracking may be recorded')
    subprocess.run(['git','-c','core.hooksPath=/dev/null','add','--',*sorted(allowed)],cwd=ROOT,check=True)
    subprocess.run(['git','-c','core.hooksPath=/dev/null','commit','-m','docs: record actual successful CR009 GSIS copy gate',
        '--',*sorted(allowed)],cwd=ROOT,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only',action='store_true');parser.add_argument('--record',action='store_true')
    choice=parser.add_mutually_exclusive_group();choice.add_argument('--host-dns',action='store_true');choice.add_argument('--image')
    args=parser.parse_args()
    if args.source_only and (args.record or args.host_dns or args.image):parser.error('--source-only accepts no runtime options')
    stage='source-preflight'
    try:
        policy,count,static=source_check();bound=verify_binding(ROOT) if (ROOT/BASELINE).exists() else None
        if args.source_only:
            print(json.dumps({'change':'CR-009','status':'Prepared','source_files_checked':count,
                'application_inputs':policy['application_inputs'],'runtime_executed':False,
                'actual21_prior_reports_bound':bound is not None,'static':static},ensure_ascii=False));return
        clean_source();bound=verify_binding(ROOT);require_local_docker()
        revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        stage='retained115-current4gib-tool-guards'
        subprocess.run([sys.executable,'-m','unittest','discover','-s','tools','-p','test_preview_cr008*.py'],
            cwd=ROOT,check=True)
        stage='new-production-image'
        if args.image:selected=image.reuse_for_verification(args.image)
        elif args.host_dns:
            from build_host_dns import build
            selected=build()
        else:selected=image.build()
        with tempfile.TemporaryDirectory(prefix='accounting-cr009-') as directory:
            folder=Path(directory);delivery_path=folder/'delivery.json';stage='full-production-pg17-delivery'
            subprocess.run([sys.executable,str(ROOT/'tools/verify_delivery.py'),'--report',str(delivery_path),
                '--image',selected['image_id']],cwd=ROOT,check=True)
            delivery=json.loads(delivery_path.read_text());suite=delivery['suite']
            # Preserve actual native delivery even if a later file/worker gate stops.
            retained=ROOT/'private/cr009'/selected['image_id'].removeprefix('sha256:')
            retained.mkdir(parents=True,exist_ok=True,mode=0o700)
            with tempfile.NamedTemporaryFile(mode='w',prefix='delivery-'+revision+'-',suffix='.json',
                    dir=retained,delete=False) as stream:
                json.dump(delivery,stream,ensure_ascii=False,indent=2);stream.write('\n')
            print('[CR009] Η πραγματική αναφορά της σουίτας διατηρήθηκε: '+stream.name,flush=True)
            require(suite['tests_run']==suite['tests_passed']==policy['expected_suite'] and all(suite[k]==0
                for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips')),
                'Every retained/new test must pass in the production image')
            require(len(suite['cases'])==36 and all(c['outcome']=='passed' for c in suite['cases']),
                'All36 financial cases must pass')
            require(len([n for n in delivery['applied_migrations'] if n.startswith('accounting.')])==36,
                'Keep the same36 migrations; GSIS adds no database migration')
            require(delivery['image']['context']['digest']==policy['application_context_digest']
                and delivery['image']['context']['file_count']==policy['application_inputs'], 'Verify this exact new source image')
            stage='retained-real-antivirus-files-and-recovery'
            from cr008_files_gate import files_gate
            files=files_gate(folder,selected['image_id'],host_dns=args.host_dns)
            stage='retained-real-monthly-worker'
            from s28_broker_gate import broker_gate
            broker=broker_gate(folder,selected['image_id'])
        source_check();verify_binding(ROOT);clean_source()
        require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==revision,'Source moved during verification')
        report={'change':'CR-009','status':'Verified','source_status':'Prepared',
            'scope':'isolated-production-pg17-explicit-scoped-gsis-copy-and-retained-files-worker',
            'verified_at':datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit':'git:'+revision,'image':delivery['image'],'application_context_digest':policy['application_context_digest'],
            'suite':suite,'new_test_methods':policy['new_test_methods'],'retained_source_files_checked':count,
            'static':static,'secret_scan':delivery['secret_scan'],'private_files':files,
            'real_monthly_worker_and_commit_before_ack':True,'revocation_blocks_execution':broker['revocation_blocks_execution'],
            'second_scheduler_rejected':broker['second_scheduler_rejected'],'restricted_role_migrations':broker['restricted_role_migrations'],
            'original_36_migrations_unchanged':True,'new_migrations':0,'historical_receipts_unchanged':True,
            'actual_prior_receipt_files_sha256':bound['files'],'docker_execution_by_operator':True,'agent_native_execution':False,
            'prior_completed_vm_record':bound['previous_completed_vm_record'],
            'deployment_guard_suite_passed':True,'deployment_guard_tests_passed':115,
            'local_demo_or_vm_changed':False,'github_updated':False,'human_accounts_or_mfa_changed':False,
            'vm_github_hold_by_user':False,'vm_github_upgrade_authorized_after_verification':True,
            'vm_rollout_status':'Pending this new image verification and separate deployment binding',
            'owned_resources_removed':True,'full_requirement_acceptances_pending':85,
            'gsis_browser_extension_required':False,'gsis_cross_origin_autofill':False,'gsis_login_automatically_submitted':False,
            'actual_gsis_browser_clipboard_acceptance':'Pending operator test; no real GSIS credentials used by verifier',
            'accountant_browser_acceptance':'Pending','g2_release_acceptance':'Pending'}
        if args.record:record(report,policy)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,KeyError,TypeError,AssertionError,subprocess.SubprocessError) as error:
        print('CR009-DIAG '+json.dumps({'stage':stage,'error':type(error).__name__}),file=sys.stderr)
        parser.exit(1,'CR-009 stopped: '+str(error)+'\n')


if __name__=='__main__':main()
