#!/usr/bin/env python3
"""Operator-only S29 full production/PG17 and real-worker generation gate."""
import argparse,ast,hashlib,json,re,subprocess,sys,tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dev import ROOT,require_local_docker
import image
from s28_broker_gate import broker_gate
DOCS=ROOT/'docs/implementation'


def preserved():
    entries=json.loads((DOCS/'evidence/S29-preserved-source.json').read_text()).get('sha256')
    if not isinstance(entries,dict) or not entries:raise RuntimeError('Invalid nonempty retained source manifest')
    for name,digest in entries.items():
        if (not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts or
                not isinstance(digest,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',digest)):
            raise RuntimeError('Invalid canonical retained source binding')
        path=ROOT/name
        if not path.is_file() or 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Retained source changed: '+name)
    return len(entries)


def preservation_contracts():
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tools'),'-p','test_s29_preservation.py'],
        cwd=ROOT,text=True,capture_output=True)
    count=re.search(r'Ran (\d+) tests?',result.stdout+result.stderr)
    if result.returncode or not count or int(count.group(1))!=4:raise RuntimeError('Four source contracts required:\n'+result.stderr[-3000:])
    return 4


def receipts():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (DOCS/'evidence').iterdir()
        if p.is_file() and not p.name.startswith('S29')}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--record',action='store_true')
    choice=parser.add_mutually_exclusive_group();choice.add_argument('--image');choice.add_argument('--host-dns',action='store_true')
    args=parser.parse_args();stage='source-preflight'
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise RuntimeError('Commit source before S29 verification')
        retained=preserved();contracts=preservation_contracts();historical=receipts();before=image.candidate_context()[1]['digest']
        count=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse((ROOT/'accounting/tests_reports.py').read_text())))
        if count!=36:raise RuntimeError('Every supplied S29 contract must be retained')
        require_local_docker();stage='production-image'
        if args.image:selected=image.reuse_for_verification(args.image)
        elif args.host_dns:
            from build_host_dns import build
            selected=build()
        else:selected=image.build()
        with tempfile.TemporaryDirectory(prefix='accounting-s29-') as directory:
            stage='full-production-delivery';destination=Path(directory)/'delivery.json'
            subprocess.run([sys.executable,str(ROOT/'tools/verify_delivery.py'),'--report',str(destination),'--image',selected['image_id']],cwd=ROOT,check=True)
            delivery=json.loads(destination.read_text());suite=delivery['suite']
            if suite['tests_run']!=772+count or suite['tests_passed']!=772+count or any(suite[k] for k in
                ['known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips']):
                raise RuntimeError('All retained 772 and 36 new reporting contracts must pass')
            if len(suite['cases'])!=36 or any(c['outcome']!='passed' for c in suite['cases']):raise RuntimeError('All 36 finance cases must pass')
            stage='real-redis-scheduler-generation-and-commit-before-ack';proof=broker_gate(Path(directory),selected['image_id'])
        preserved()
        if historical!=receipts():raise RuntimeError('A historical receipt changed')
        if before!=image.candidate_context()[1]['digest'] or subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
            raise RuntimeError('Source changed during S29 verification')
        report={'step':'S29','status':'Verified','scope':'production-pg17-reconciled-financial-reports-and-retained-real-fee-worker',
            'verified_at':datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit':'git:'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'suite':suite,'s29_test_methods':count,'image':delivery['image'],'application_context_digest':before,
            'retained_source_files_checked':retained,'source_preservation_contracts_passed':contracts,
            'historical_receipts_unchanged':True,'owned_resources_removed':True,'agent_tests_builds_docker_migrations_run':False,
            'docker_execution_by_operator':True,'local_demo_or_vm_changed':False,'human_accounts_or_mfa_changed':False,
            'full_requirement_acceptance':'Pending','full_requirement_acceptances_pending':85,
            'd05_real_migration_review':'Pending','g2_release_acceptance':'Pending',**proof}
        if args.record:
            from prepare_s29 import record_result
            record_result(report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,subprocess.SubprocessError,AssertionError) as error:
        print('S29-DIAG '+json.dumps({'stage':stage,'error':type(error).__name__}),file=sys.stderr)
        parser.exit(1,'S29 stopped: '+str(error)+'\n')


if __name__=='__main__':main()
