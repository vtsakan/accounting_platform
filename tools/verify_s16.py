#!/usr/bin/env python3
"""S16 isolated PostgreSQL integrated office-boundary gate; never touches the VM.

Default: disposable Docker Compose project. Native PG17 proof is Prepared until
the operator reproduces the same checks in the local Docker environment.
"""

import argparse
import ast
import csv
from datetime import datetime
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

from dev import ROOT, compose_command, compose_environment, require_local_docker
from init_local_env import create_local_env
from verify_s05 import HIDDEN_VALUES, run
from verify_s06 import native_database
import image

BASE = "5fc66cb6161c76482501b31499e8745f79181a93"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


def source_checks():
    for step in ('S06','S10','S12','S13','S14','S15'):
        if json.loads((RECORDS/'evidence'/(step+'-verification.json')).read_text())['status']!='Verified':
            raise RuntimeError(step+' operator verification required')
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE],cwd=ROOT,text=True).splitlines()
    protected=[name for name in names if name.startswith('accounting/migrations/') or
        (name.startswith(('accounting/tests','core/tests/')) and name.endswith('.py')) or
        name in {'requirements.in','requirements.txt','requirements-tools.in','requirements-tools.txt',
            'Dockerfile','docker-compose.yml','docker/development.Dockerfile','accounting/models.py',
            'accounting/views.py','accounting/forms.py','accounting/office_models.py','accounting/membership.py',
            'accounting/counterparty_services.py','accounting/counterparty_views.py','accounting/office_services.py',
            'accounting/auth_models.py','accounting/auth_services.py','accounting/auth_policy.py',
            'accounting/auth_middleware.py','accounting/auth_views.py','accounting/auth_forms.py',
            'accounting/regression_runner.py','accounting/regression_cases.json','core/auth_crypto.py',
            'core/referrer.py','infrastructure/Caddyfile'} or name.startswith('docs/implementation/evidence/')]
    for name in protected:
        if (ROOT/name).read_bytes()!=subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT):
            raise RuntimeError('Protected S15 baseline changed: '+name)
    _,context=image.candidate_context()
    for name in ('accounting/office_boundary_matrix.json','accounting/capabilities.py','accounting/office_access.py','accounting/tests_boundary.py'):
        if name not in context['paths']:raise RuntimeError('Production verification input missing: '+name)
    return {'original_ten_migrations_business_models_and_calculations_preserved':True,
        'all_344_existing_tests_and_exact_26_failure_registry_preserved':True,
        's10_through_s15_evidence_preserved':True,'dependency_locks_authentication_mfa_referrer_policy_preserved':True,
        'boundary_manifest_and_fixes_in_production_context':True,'application_context_digest':context['digest']}


def check_boundary(rows):
    from collections import Counter
    manifest=json.loads((ROOT/'accounting/office_boundary_matrix.json').read_text())
    expected_counts={'http-get':200,'http-post':90,'foreign-id':36,'foreign-choice':24,'filter':20,'role':8,
        'guessed-id':8,'workflow':1,'admin':110,'admin-entry':25,'autocomplete':9,'autocomplete-source':16,
        'admin-post':5,'admin-history':1,'global-auth':2,'database':28,'execution-adapter':9,'inventory':39,
        'operator':10,'concurrency':5,'gap':6}
    required_keys={'case_id','area','route','persona','scenario','observed','result'}
    if any(set(row)!=required_keys or row['result']!='Passed' for row in rows):
        raise RuntimeError('Invalid or failing boundary evidence')
    cases={row['case_id'] for row in rows}
    if len(cases)!=len(rows) or dict(Counter(row['area'] for row in rows))!=expected_counts:
        raise RuntimeError('Incomplete/duplicate boundary matrix; update the reviewed matrix for new entry points')
    required=set()
    for row in manifest['routes']:
        if row['realm']!='office-business':continue
        for persona in manifest['business_personas']:
            required.add(':'.join(('http-get',row['route'],persona,'own-office')))
            if 'POST' in row['methods'] and persona not in {'owner','accountant'}:
                required.add(':'.join(('http-post',row['route'],persona,'invalid-membership')))
    for name in manifest['business_admin_models']:
        for persona in ('limited-staff','platform-with-profile'):
            for action in ('change','history','delete'):
                for method in ('get','post'):required.add(':'.join(('admin',name,persona,'foreign-'+action+'-'+method)))
    required.update('concurrency:helper:accountant:revoked-'+kind+'-before-write' for kind in ('profile','office','user'))
    required.update({'concurrency:helper:accountant:write-before-later-revocation',
        'concurrency:transfer:accountant:revoked-profile-before-write',
        'workflow:client-finance-archive-restore:accountant:two-office-demonstration'})
    if not required<=cases:raise RuntimeError('Required route or concurrent boundary case missing')
    if {r['route'] for r in rows if r['area']=='operator'}!=set(manifest['operator_commands']):
        raise RuntimeError('Operator command inventory not exercised')
    return {'cases':len(rows),'by_area':expected_counts,'all_passed':True,
        'business_routes':sum(r['realm']=='office-business' for r in manifest['routes']),
        'identity_or_recipient_routes':sum(r['realm']!='office-business' for r in manifest['routes']),
        'business_personas':manifest['business_personas'],'business_admin_models':manifest['business_admin_models'],
        'operator_commands':manifest['operator_commands'],'future_pending':manifest['future_pending']}


def verification(manage,read_suite,read_boundary):
    manage('shell','--no-imports','-c',"import subprocess,sys;subprocess.run([sys.executable,'-m','pip','check'],check=True,stdout=subprocess.DEVNULL)")
    packages=json.loads(manage('shell','--no-imports','-c',"import importlib.metadata,json;print(json.dumps({name:importlib.metadata.version(name) for name in ['Django','django-otp','cryptography','qrcode','psycopg']}))").stdout.strip())
    manage('migrate','--noinput')
    manage('makemigrations','--check','--dry-run')
    manage('check','--fail-level=WARNING')
    print('[S16] Testing the route/admin/SQL/operator matrix and independent PostgreSQL revocation lock waits.',flush=True)
    manage('test','--settings=core.settings.test','--testrunner='+RUNNER,'--noinput','--verbosity=1')
    suite=read_suite()
    count=sum(isinstance(node,ast.FunctionDef) and node.name.startswith('test_') for node in ast.walk(ast.parse((ROOT/'accounting/tests_boundary.py').read_text())))
    if suite['tests_run']!=344+count or suite['known_failures_reproduced']!=26 or any(suite[key] for key in ('unexpected_failures','unexpected_errors','unexpected_successes','skips')):
        raise RuntimeError('Unexpected S16 or existing regression outcome')
    version=int(manage('shell','--no-imports','-c','from django.db import connection;print(connection.pg_version)').stdout.strip())
    if version//10000!=17:raise RuntimeError('PostgreSQL 17 required')
    rows=read_boundary()
    boundary=check_boundary(rows)
    invalid_reports={'missing-case':rows[1:],'duplicate-case':rows+[rows[0]],
        'failed-case':[{**rows[0],'result':'Failed'},*rows[1:]],
        'unexpected-payload':[{**rows[0],'raw_response':'forbidden'},*rows[1:]]}
    for label,invalid in invalid_reports.items():
        try:
            check_boundary(invalid)
        except RuntimeError:
            continue
        raise RuntimeError('Boundary evidence incorrectly accepted '+label)
    return {'postgresql_version_num':version,'runtime_packages':packages,'runtime_pip_check':True,'s16_tests':count,
        'suite':{k:v for k,v in suite.items() if k!='cases'},'boundary_matrix':boundary,'_boundary_rows':rows,
        'boundary_report_negative_controls':list(invalid_reports),
        'undeclared_business_routes_fail_closed':True,'admin_autocomplete_source_and_remote_office_checked':True,
        'archived_new_work_choices_excluded_with_stored_history_retained':True,
        'write_authority_rechecked_after_office_user_lock_wait':True,
        'both_revocation_posting_lock_orders_proven':True,'operator_process_trust_boundary_explicit':True,
        'synthetic_client_finance_archive_restore_demonstrated':True,
        'actual_worker_file_export_proofs':'Pending: these modules are not implemented',
        'migration_drift':False}


def native(args, directory):
    with native_database(args.native_bin, directory) as (environment, version):
        environment['ACCOUNTING_BOUNDARY_REPORT']=str(directory/'boundary.jsonl')
        setup = '''import os, psycopg
with psycopg.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                     host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], autocommit=True) as conn:
    conn.execute("CREATE ROLE accounting_s16_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
    conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO accounting_s16_migrator")
'''
        run([args.python, "-c", setup], environment=environment)
        restricted = {**environment, "PGOPTIONS": "-c role=accounting_s16_migrator"}
        run([args.python, ROOT / "manage.py", "migrate", "--noinput"], environment=restricted)
        probe = run([args.python, ROOT / "manage.py", "shell", "--no-imports", "-c",
            "from django.db import connection; c=connection.cursor(); c.execute('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user'); print(c.fetchone())"], environment=restricted)
        if probe.stdout.strip() != "(False, False, False)":
            raise RuntimeError("Restricted migration role unexpectedly elevated")
        def manage(*arguments):
            return run([args.python, ROOT / "manage.py", *arguments], environment=environment)
        result = verification(manage, lambda: json.loads(Path(environment["ACCOUNTING_REGRESSION_REPORT"]).read_text()),
            lambda: [json.loads(line) for line in Path(environment["ACCOUNTING_BOUNDARY_REPORT"]).read_text().splitlines()])
    return {"mode": "native-postgresql17", "status": "Prepared", "docker_execution": False,
            "postgresql_binary_version": version, "native_restricted_role_ddl": {
                "all_migrations_passed": True, "superuser": False, "createdb": False, "createrole": False}, **result}


def docker(directory):
    require_local_docker()
    env_file = directory / "env"; create_local_env(env_file)
    HIDDEN_VALUES.update(line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(("DJANGO_SECRET_KEY=", "DB_PASSWORD=")))
    with env_file.open("a") as stream:
        stream.write("WEB_PORT=0\n")
    project = "accounting-s16-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S16] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s16-suite.json",
                           "--env", "ACCOUNTING_BOUNDARY_REPORT=/tmp/s16-boundary.jsonl",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s16-suite.json",
                           "--env", "ACCOUNTING_BOUNDARY_REPORT=/tmp/s16-boundary.jsonl",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s16-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        def read_boundary():
            copied=directory/'boundary.jsonl'
            run(['docker','cp',name+':/tmp/s16-boundary.jsonl',copied],environment=environment)
            return [json.loads(line) for line in copied.read_text().splitlines()]
        result = verification(stable_manage, read_suite, read_boundary)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report,rows):
    import hashlib
    path=RECORDS/'evidence/S16-verification.json'
    if path.exists():
        previous=json.loads(path.read_text())
        if previous.get('application_context_digest')==report['application_context_digest'] and 'native_restricted_role_ddl' in previous and 'native_restricted_role_ddl' not in report:
            report['native_restricted_role_ddl']=previous['native_restricted_role_ddl']
    matrix_path=RECORDS/'evidence/S16-office-boundary.csv'
    with matrix_path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['case_id','area','route','persona','scenario','observed','result'],lineterminator='\n')
        writer.writeheader();writer.writerows(sorted(rows,key=lambda r:r['case_id']))
    report['boundary_matrix']['evidence']='docs/implementation/evidence/S16-office-boundary.csv'
    report['boundary_matrix']['sha256']='sha256:'+hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    manifest=json.loads((ROOT/'accounting/office_boundary_matrix.json').read_text())
    gate={'gate':'G1','status':report['status'],'verified_at':report['verified_at'],'mode':report['mode'],
        'scope':'Technical office foundation through S16; synthetic local PostgreSQL workflow',
        'source_commit':report['source_commit'],'source_reference_commit':report['source_reference_commit'],
        'technical_evidence':report['boundary_matrix'],
        'requirements':{key:{'technical_scope':report['status'],'full_acceptance':'Pending'} for key in manifest['requirements']},
        'full_requirement_acceptances_pending':85,'known_financial_failures_preserved':26,
        'operator_maintenance':'Privileged database process; not a staff API. See office_boundary.md.',
        'future_pending':manifest['future_pending'],'human_browser_client_acceptance':'Pending',
        'live_vm_rollout':'Not performed by S16','real_data_cutover':'Not authorised by this gate',
        'next_step':'S17: accountant review of D08 financial rules before posting changes'}
    (RECORDS/'evidence/G1-foundation.json').write_text(json.dumps(gate,ensure_ascii=False,indent=2)+'\n')
    with (RECORDS/'steps.csv').open(newline='') as stream:steps=list(csv.DictReader(stream))
    row=next(r for r in steps if r['step_id']=='S16')
    row.update(status=report['status'],branch='step/s16-office-boundary',code_reference_commit=report['source_commit'].removeprefix('git:'),
        evidence='docs/implementation/evidence/S16-verification.json; docs/implementation/evidence/S16-office-boundary.csv; docs/implementation/evidence/G1-foundation.json; docs/implementation/office_boundary.md',
        blocker='' if report['status']=='Verified' else 'Run python3 tools/verify_s16.py --record on laptop Docker',
        manual_acceptance='G1 technical scope only; browser/client and all full requirements Pending; live VM rollout separate',
        next_step='S17 financial policy review' if report['status']=='Verified' else 'Complete S16 local Docker gate')
    with (RECORDS/'steps.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=steps[0],lineterminator='\n');writer.writeheader();writer.writerows(steps)
    path=RECORDS/'state.md';text=path.read_text()
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+report['verified_at'][:10]+'. Current step: **S16 '+report['status']+' — complete office boundary**. Next step: **'+row['next_step']+'**.\n',text,count=1)
    summary='<!-- S16-RESULT -->\n'+report['status']+': '+str(report['s16_tests'])+' integrated tests; '+str(report['boundary_matrix']['cases'])+' explicit boundary cases; '+str(report['suite']['tests_run'])+' total tests with 26 exact known financial failures and no unexpected outcomes. Docker execution: '+str(report['docker_execution'])+'. G1 technical evidence is recorded; browser/client, future modules and full requirement acceptance remain Pending.\n<!-- /S16-RESULT -->'
    if '<!-- S16-RESULT -->' in text:text=re.sub(r'<!-- S16-RESULT -->.*?<!-- /S16-RESULT -->',summary,text,flags=re.S)
    else:text+='\n'+summary+'\n'
    path.write_text(text)
    path=RECORDS/'traceability.csv'
    with path.open(newline='') as stream:requirements=list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement['requirement_id'] not in set(manifest['requirements'])|{'UR-LOC-01'}:continue
        note=' S16: '+report['status']+' on '+report['mode']+'; reusable HTTP/admin/autocomplete/SQL/operator matrix, concurrent revocation proof and synthetic G1 client workflow. Future files/exports/workers/portal and full acceptance remain Pending.'
        requirement['notes']=re.sub(r' S16:.*$','',requirement['notes'])+note
        for evidence in ('docs/implementation/evidence/S16-verification.json','docs/implementation/evidence/S16-office-boundary.csv','docs/implementation/evidence/G1-foundation.json','docs/implementation/office_boundary.md','accounting/tests_boundary.py'):
            if evidence not in requirement['evidence'].split('; '):requirement['evidence']='; '.join(filter(None,[requirement['evidence'],evidence]))
        requirement['last_reviewed']=report['verified_at'][:10]
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=requirements[0],lineterminator='\n');writer.writeheader();writer.writerows(requirements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--tools-python", type=Path, help="Reuse an existing pinned maintenance environment")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    try:
        if args.record and subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
            raise RuntimeError("Commit the candidate source before recording its verification")
        protected = source_checks()
        with tempfile.TemporaryDirectory(prefix="accounting-s16-") as temp:
            directory = Path(temp)
            tooling = args.tools_python
            if tooling is None:
                print("[S16] Installing hashed maintenance tools; reproducing locks/catalog and scanning Git history.", flush=True)
                run([sys.executable, "-m", "venv", directory / "tools"])
                tooling = directory / "tools/bin/python"
                run([tooling, "-m", "pip", "--disable-pip-version-check", "install", "--timeout", "120", "--retries", "5",
                     "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "-r", ROOT / "requirements-tools.txt"])
            run([tooling, ROOT / "tools/lock_dependencies.py", "--check"])
            run([tooling, ROOT / "tools/compile_translations.py", "--check"])
            scan = json.loads(run([tooling, ROOT / "tools/scan_secrets.py"]).stdout)
            result = native(args, directory) if args.native_bin else docker(directory)
            result.update(secret_scan=scan, runtime_and_tools_locks_reproduced=True, greek_catalog_verified=True)
        rows=result.pop("_boundary_rows")
        result.update(step="S16", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            live_mail_sent=False, browser_visual_accessibility_acceptance="Pending",
            full_requirement_acceptance="Pending", full_requirement_acceptances_pending=85, **protected)
        if args.record:
            record(result,rows)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S16 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
