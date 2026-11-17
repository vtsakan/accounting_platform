#!/usr/bin/env python3
"""Operator-only full S27 production-image/PG17 and background regression gate."""
import argparse
import ast
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo
from dev import ROOT, require_local_docker
import image
from verify_s26 import broker_gate

DOCS=ROOT/'docs/implementation'


def test_method_count(path):
    # Count the supplied methods without serializing a version-dependent AST.
    return sum(isinstance(node,ast.FunctionDef) and node.name.startswith('test_')
        for node in ast.walk(ast.parse(path.read_text())))


def preserved():
    manifest=json.loads((DOCS/'evidence/S27-preserved-source.json').read_text())
    bindings=json.loads((DOCS/'evidence/S27-test-source-bindings.json').read_text()).get('sha256')
    retained=manifest.get('sha256');methods=manifest.get('test_methods')
    if not isinstance(retained,dict) or not retained or not isinstance(methods,dict) or not methods:
        raise RuntimeError('Invalid retained-source manifest')
    if not isinstance(bindings,dict) or set(bindings)!=set(methods):
        raise RuntimeError('Every retained test file must have an exact source binding')
    for name,digest in bindings.items():
        if name in retained and digest!=retained[name]:
            raise RuntimeError('Test binding differs from canonical retained digest: '+name)
        if name not in retained and name!='accounting/tests_boundary.py':
            raise RuntimeError('Unexpected retained test fixture binding: '+name)
    sources={**retained,**bindings}
    for name,digest in sources.items():
        if (not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts or
                not isinstance(digest,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',digest)):
            raise RuntimeError('Invalid canonical retained-source SHA-256 binding')
        path=ROOT/name
        if not path.is_file() or 'sha256:'+hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Retained source changed: '+name)
    return len(sources)


def preservation_contracts():
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/'tools'),
        '-p','test_s27_preservation.py'],cwd=ROOT,text=True,capture_output=True)
    count=re.search(r'Ran (\d+) tests?',result.stdout+result.stderr)
    if result.returncode or count is None or int(count.group(1))!=4:
        raise RuntimeError('Four portable source-preservation contracts must pass:\n'+result.stderr[-3000:])
    return 4


def receipts():
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (DOCS/'evidence').iterdir()
        if p.is_file() and not p.name.startswith('S27')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record',action='store_true')
    choice=parser.add_mutually_exclusive_group()
    choice.add_argument('--image',help='Exact existing image with identical committed application context')
    choice.add_argument('--host-dns',action='store_true',help='Build using a temporary host-network/DNS builder')
    args=parser.parse_args();stage='source-preflight'
    try:
        if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():raise RuntimeError('Commit source before S27 verification')
        retained=preserved();contracts=preservation_contracts();historical=receipts();before=image.candidate_context()[1]['digest']
        require_local_docker();stage='production-image'
        if args.image:selected=image.reuse_for_verification(args.image)
        elif args.host_dns:
            from build_host_dns import build
            selected=build()
        else:selected=image.build()
        with tempfile.TemporaryDirectory(prefix='accounting-s27-') as directory:
            destination=Path(directory)/'delivery.json';stage='full-production-delivery'
            subprocess.run([sys.executable,str(ROOT/'tools/verify_delivery.py'),'--report',str(destination),
                '--image',selected['image_id']],cwd=ROOT,check=True)
            delivery=json.loads(destination.read_text());suite=delivery['suite']
            count=test_method_count(ROOT/'accounting/tests_fees.py')
            if suite['tests_run']!=696+count or suite['tests_passed']!=696+count or any(suite[k] for k in
                ['known_failures_reproduced','unexpected_errors','unexpected_failures','unexpected_successes','skips']):
                raise RuntimeError('Every retained 696 test and all new S27 contracts must pass')
            if len(suite['cases'])!=36 or any(case['outcome']!='passed' for case in suite['cases']):
                raise RuntimeError('Every retained financial case must pass')
            stage='restricted-migrations-and-real-background-regression'
            proof=broker_gate(Path(directory),selected['image_id'])
        preserved()
        if historical!=receipts():raise RuntimeError('A historical operator receipt changed')
        if before!=image.candidate_context()[1]['digest'] or subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
            raise RuntimeError('Source changed during verification')
        report={'step':'S27','status':'Verified','scope':'production-image-pg17-catalogue-monthly-preview-and-real-background-regression',
            'verified_at':datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'source_commit':'git:'+subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'suite':suite,'s27_test_methods':count,'image':delivery['image'],'application_context_digest':before,
            'retained_source_files_checked':retained,'source_preservation_contracts_passed':contracts,
            'historical_receipts_unchanged':True,'owned_resources_removed':True,
            'agent_tests_builds_docker_migrations_run':False,'docker_execution_by_operator':True,
            'local_demo_or_vm_changed':False,'human_accounts_or_mfa_changed':False,'automatic_generation':'Pending S28',
            'full_requirement_acceptance':'Pending','full_requirement_acceptances_pending':85,
            'd05_real_migration_review':'Pending','g2_release_acceptance':'Pending',**proof}
        if args.record:
            from prepare_s27 import record_result
            record_result(report)
        print(json.dumps(report,ensure_ascii=False,indent=2))
    except (RuntimeError,OSError,ValueError,subprocess.SubprocessError,AssertionError) as error:
        print('S27-DIAG '+json.dumps({'stage':stage,'error':type(error).__name__}),file=sys.stderr)
        parser.exit(1,'S27 stopped: '+str(error)+'\n')


if __name__=='__main__':main()
