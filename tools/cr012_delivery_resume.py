"""Operator-only reuse of the exact1393/36 delivery supplied in the real console."""
import json
from pathlib import Path
import subprocess
import sys

from dev import ROOT
import image
from cr008_delivery_resume import context_at
from r1_gate import digest_bytes,digest_object,require

SOURCE='f4ce08871eae514d6d80fbf55c3d6b05c59bd227'  # pragma: allowlist secret -- actual public-source identity printed by the operator delivery
IMAGE='sha256:996ff3c2ff17afb8e8ac20f83f868cf0520f78eed1b0d972314edfefc94cd42f'
CONTEXT='sha256:8f8341cba921c7eac3c100abb8bb20fbd5d8dada82087c3be4573c3293df34ad'
CANONICAL='sha256:0edbc23a740c12be55a640103eab778d2a16cabead81258148a9594ed17979f1'


def load_retained_delivery(policy):
    require(not subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip(),
        'Commit the reviewed tools correction first; local changes were retained')
    directory=ROOT/'private/cr012'/IMAGE.removeprefix('sha256:')
    current=ROOT
    for part in directory.relative_to(ROOT).parts:
        current=current/part
        require(current.is_dir() and not current.is_symlink(),'Keep the original regular private delivery directory; otherwise run without --resume-delivery')
    matches=[]
    for path in sorted(directory.glob('delivery-'+SOURCE+'-*.json')):
        require(path.is_file() and not path.is_symlink() and path.stat().st_size<=2_000_000,
            'A retained native delivery must be a bounded regular file')
        raw=path.read_bytes();value=json.loads(raw)
        if digest_object(value)==CANONICAL:matches.append((path,raw,value))
    require(len(matches)==1,'The exact successful1393/36 report is missing or ambiguous; run the full gate without --resume-delivery')
    path,raw,delivery=matches[0];suite=delivery['suite'];selected=delivery['image'];context=selected['context']
    require(delivery['step']=='delivery' and delivery['status']=='Verified' and delivery['mode']=='docker-production-image'
        and delivery['docker_execution_this_step'] is True and delivery['production_image_built_verified'] is True,
        'Require the actual successful complete production-image delivery')
    require(suite['tests_run']==suite['tests_passed']==policy['expected_suite']==1393 and len(suite['cases'])==36
        and all(c['outcome']=='passed' for c in suite['cases'])
        and all(suite[k]==0 for k in ('known_failures_reproduced','unexpected_failures','unexpected_errors','unexpected_successes','skips')),
        'Require every1393 application contract and all36 financial cases')
    require(selected['image_id']==IMAGE and selected['revision']==selected['verification_revision']==delivery['source_reference_commit']=='git:'+SOURCE
        and context['digest']==policy['application_context_digest']==CONTEXT and context['file_count']==policy['application_inputs']==409
        and len([n for n in delivery['applied_migrations'] if n.startswith('accounting.')])==42,
        'Retain the exact passed image, source,409-input context and42 migrations')
    require(subprocess.run(['git','merge-base','--is-ancestor',SOURCE,'HEAD'],cwd=ROOT,capture_output=True).returncode==0,
        'The actual passed f4ce088 source must exist in native Git ancestry; never reconstruct it')
    require(context_at('HEAD')==context_at(SOURCE)==context==image.candidate_context()[1],
        'Application bytes changed after the successful suite; a new full delivery is required')
    proof={'report_path':path.relative_to(ROOT).as_posix(),'report_sha256':digest_bytes(raw),
        'canonical_report_sha256':CANONICAL,'source_commit':'git:'+SOURCE,'image_id':IMAGE,
        'application_context_digest':CONTEXT,'tests_passed':1393,'financial_cases':36}
    return delivery,proof


def scan_current_source(directory):
    """Fresh pinned source/history scan after the tools-only correction."""
    print('[CR012] Νέος έλεγχος τρέχουσας πηγής και ιστορίας με δεσμευμένα εργαλεία.',flush=True)
    environment=Path(directory)/'resume-tools'
    subprocess.run([sys.executable,'-m','venv',str(environment)],cwd=ROOT,capture_output=True,text=True,check=True)
    python=environment/'bin/python'
    subprocess.run([str(python),'-m','pip','--disable-pip-version-check','install','--timeout','120','--retries','5',
        '--require-hashes','--only-binary=:all:','--index-url','https://pypi.org/simple','-r',str(ROOT/'requirements-tools.txt')],
        cwd=ROOT,capture_output=True,text=True,check=True)
    result=subprocess.run([str(python),str(ROOT/'tools/scan_secrets.py')],cwd=ROOT,capture_output=True,text=True,check=True)
    value=json.loads(result.stdout)
    require(value.get('scanner')=='detect-secrets' and value.get('version')=='1.5.0' and value.get('unreviewed_findings')==0,
        'The fresh source/history secret-text scan must pass')
    return value
