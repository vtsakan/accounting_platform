#!/usr/bin/env python3
"""S19 isolated PostgreSQL integrated office-boundary gate; never touches the VM.

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

BASE = "22dbd3a12816cfaceb62958ad45e19231669f3be"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


from verify_s17 import current_bindings, reference_checks, review_result, load, digest

FIXED={'BAL-001','BAL-002','BAL-003'}
ADAPTED_TESTS={'accounting/tests_regressions.py','accounting/tests_counterparties.py','accounting/tests_boundary.py',
    'accounting/tests_ownership.py','accounting/tests_finance_posting.py','accounting/tests_staff.py','accounting/tests_integration.py'}

def old_bytes(name):
    return subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT)

def source_checks():
    for step in ('S06','S10','S12','S13','S14','S15','S16','S17','S18'):
        if json.loads((RECORDS/'evidence'/(step+'-verification.json')).read_text())['status']!='Verified':
            raise RuntimeError(step+' completion gate required')
    review=load(RECORDS/'evidence/S17-verification.json');bindings=current_bindings()
    if review['bindings']!=bindings or review['review']['status']!='Approved' or review['review']['blocked_decisions']:
        raise RuntimeError('S17 approved review must bind the current policy/examples/documents')
    proposed={r['id']:r['proposed_option'] for r in load(RECORDS/'financial_policy.json')['decisions']}
    if review['review']['choices']!=proposed or not review['review']['accountant_and_owner_named']:
        raise RuntimeError('Named S17 review or policy choices are incomplete')
    private=ROOT/'private/S17-financial-review.json'
    if private.exists():
        if review_result(load(private),load(RECORDS/'financial_policy.json'),bindings)['status']!='Approved' or digest(private.read_bytes())!=review['review']['sha256']:
            raise RuntimeError('Private review does not match its public receipt')
    reference_checks(load(RECORDS/'financial_policy.json'),load(RECORDS/'examples/S17-financial-examples.json'))
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE],cwd=ROOT,text=True).splitlines()
    protected=[n for n in names if n.startswith(('accounting/migrations/','core/','locale/','templates/','docker/','infrastructure/','docs/baselines/','tools/')) or
        (n.startswith('accounting/tests') and n.endswith('.py') and n not in ADAPTED_TESTS) or n.startswith('docs/implementation/evidence/') or
        n in {'requirements.in','requirements.txt','requirements-tools.in','requirements-tools.txt','Dockerfile','docker-compose.yml',
          'accounting/auth_models.py','accounting/auth_services.py','accounting/auth_policy.py','accounting/auth_middleware.py',
          'accounting/auth_views.py','accounting/auth_forms.py','accounting/office_services.py','accounting/office_access.py','accounting/membership.py',
          'accounting/finance_models.py','accounting/finance_money.py','accounting/regression_runner.py','docs/implementation/office_role_policy.json',
          'docs/implementation/financial_policy.json','docs/implementation/financial_policy.md','docs/implementation/financial_policy_review_el.md',
          'docs/implementation/examples/S17-financial-examples.json','docs/implementation/examples/S17-financial-examples_el.md'}]
    for name in protected:
        if (ROOT/name).read_bytes()!=old_bytes(name):raise RuntimeError('Protected S18 baseline changed: '+name)
    for name in sorted(ADAPTED_TESTS):
        previous=ast.parse(old_bytes(name));candidate=ast.parse((ROOT/name).read_text())
        tests=lambda tree:{(cls.name,n.name) for cls in ast.walk(tree) if isinstance(cls,ast.ClassDef)
            for n in cls.body if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
        if not tests(previous)<=tests(candidate):raise RuntimeError('Prior test removed: '+name)
        if name.endswith('tests_regressions.py'):
            calls=lambda tree:[ast.dump(n,include_attributes=False) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='assert_financial_equal']
            if calls(previous)!=calls(candidate):raise RuntimeError('Correct financial assertions changed')
    previous=json.loads(old_bytes('accounting/regression_cases.json'))['cases'];current=load(ROOT/'accounting/regression_cases.json')['cases']
    if len(previous)!=len(current):raise RuntimeError('Regression inventory changed')
    for before,after in zip(previous,current):
        compare={k:after[k] for k in before}
        if before['case_id'] in FIXED:
            compare['expected_outcome']='known_failure'
            if after.get('fixed_in')!='S19':raise RuntimeError('Missing S19 balance correction mapping')
        if before!=compare:raise RuntimeError('Regression mapping/assertions changed outside S19 balance fixes')
    baseline=json.loads(old_bytes('accounting/office_boundary_matrix.json'));manifest=load(ROOT/'accounting/office_boundary_matrix.json')
    if any(row not in manifest['routes'] for row in baseline['routes']):raise RuntimeError('Existing route boundary removed')
    for key in ('business_personas','business_admin_models','operator_commands','future_pending'):
        if baseline[key]!=manifest[key]:raise RuntimeError('Unrelated boundary scope changed: '+key)
    _,context=image.candidate_context()
    for name in ('accounting/account_services.py','accounting/account_models.py','accounting/cash_selectors.py',
        'accounting/account_views.py','accounting/account_forms.py','accounting/templates/accounting/cash/detail.html',
        'accounting/tests_cash_workspace.py','accounting/migrations/0014_cash_workspace_guards.py'):
        if name not in context['paths']:raise RuntimeError('Missing production context: '+name)
    return {'original_twelve_migrations_and_exact_money_guards_preserved':True,'historical_evidence_through_verified_s18_preserved':True,
        's17_approved_bound_review_preserved':True,'financial_expected_value_assertions_preserved':True,
        'all_428_existing_test_names_retained':True,'dependency_locks_authentication_mfa_referrer_preserved':True,
        'application_context_digest':context['digest']}


def check_boundary(rows):
    import io
    from collections import Counter
    manifest=load(ROOT/'accounting/office_boundary_matrix.json')
    baseline=list(csv.DictReader(io.StringIO(old_bytes('docs/implementation/evidence/S16-office-boundary.csv').decode())))
    expected=Counter(row['area'] for row in baseline)
    expected.update({'http-get':80,'http-post':42,'inventory':10})
    keys={'case_id','area','route','persona','scenario','observed','result'}
    if any(set(row)!=keys or row['result']!='Passed' for row in rows):raise RuntimeError('Invalid or failing boundary evidence')
    ids={row['case_id'] for row in rows}
    if len(ids)!=len(rows) or Counter(row['area'] for row in rows)!=expected:raise RuntimeError('Incomplete/duplicate S19 boundary matrix')
    if not {row['case_id'] for row in baseline}<=ids:raise RuntimeError('Original 652 boundary cases must be retained')
    required=set()
    for row in manifest['routes']:
        if row['realm']!='office-business':continue
        for persona in manifest['business_personas']:
            required.add(':'.join(('http-get',row['route'],persona,'own-office')))
            if 'POST' in row['methods'] and persona not in {'owner','accountant'}:
                required.add(':'.join(('http-post',row['route'],persona,'invalid-membership')))
    if not required<=ids:raise RuntimeError('Required current route boundary case missing')
    if {r['route'] for r in rows if r['area']=='operator'}!=set(manifest['operator_commands']):raise RuntimeError('Operator command inventory not exercised')
    return {'cases':len(rows),'by_area':dict(sorted(expected.items())),'all_passed':True,'original_652_cases_retained':True,
        'business_routes':sum(r['realm']=='office-business' for r in manifest['routes']),
        'identity_or_recipient_routes':sum(r['realm']!='office-business' for r in manifest['routes']),
        'business_personas':manifest['business_personas'],'business_admin_models':manifest['business_admin_models'],
        'operator_commands':manifest['operator_commands'],'future_pending':manifest['future_pending']}


def verification(manage,read_suite,read_boundary):
    manage('shell','--no-imports','-c',"import subprocess,sys;subprocess.run([sys.executable,'-m','pip','check'],check=True,stdout=subprocess.DEVNULL)")
    packages=json.loads(manage('shell','--no-imports','-c',"import importlib.metadata,json;print(json.dumps({name:importlib.metadata.version(name) for name in ['Django','django-otp','cryptography','qrcode','psycopg']}))").stdout.strip())
    manage('migrate','--noinput');manage('makemigrations','--check','--dry-run');manage('check','--fail-level=WARNING')
    print('[S19] Testing dated balances, reviewed opening cutoffs, immutable adjustments, category hierarchy/retirement, migration and independent PostgreSQL races.',flush=True)
    manage('test','--settings=core.settings.test','--testrunner='+RUNNER,'--noinput','--verbosity=1')
    suite=read_suite();count=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse((ROOT/'accounting/tests_cash_workspace.py').read_text())))
    if suite['tests_run']!=428+count or suite['known_failures_reproduced']!=10 or any(suite[k] for k in ('unexpected_failures','unexpected_errors','unexpected_successes','skips')):
        raise RuntimeError('Unexpected financial/existing suite outcome')
    rows=read_boundary();boundary=check_boundary(rows)
    case_results={row['case_id']:row for row in suite['cases']}
    if any(case_results[key]['outcome']!='passed' for key in FIXED):raise RuntimeError('An S19 corrected case did not pass')
    version=int(manage('shell','--no-imports','-c','from django.db import connection;print(connection.pg_version)').stdout.strip())
    if version//10000!=17:raise RuntimeError('PostgreSQL 17 required')
    return {'postgresql_version_num':version,'runtime_packages':packages,'runtime_pip_check':True,'s19_tests':count,
        'suite':{k:v for k,v in suite.items() if k!='cases'},'financial_cases':suite['cases'],
        'fixed_known_financial_cases':sorted(FIXED),'remaining_known_financial_failures':10,
        'boundary_matrix':boundary,'_boundary_rows':rows,
        'exact_dated_balance_empty_income_expense_and_no_join_multiplication':True,
        'legacy_opening_amounts_preserved_without_inferred_dates':True,
        'owner_password_recent_mfa_bound_cutoff_review_and_exact_retries':True,
        'immutable_signed_adjustments_do_not_create_operating_cash':True,
        'retirement_preserves_history_and_blocks_new_work':True,
        'same_office_acyclic_category_hierarchy_in_service_and_sql':True,
        'independent_read_committed_and_repeatable_read_cycle_races':True,
        'revoked_owner_rechecked_after_real_postgresql_lock_wait':True,
        'deferred_adjustment_audit_commit_and_rollback_proven':True,
        'legacy_columns_ids_and_audit_preserved_invalid_hierarchy_stops':True,
        'migration_drift':False}



def native(args, directory):
    with native_database(args.native_bin, directory) as (environment, version):
        environment['ACCOUNTING_BOUNDARY_REPORT']=str(directory/'boundary.jsonl')
        if args.native_fast_io:
            # This newly created synthetic cluster is discarded after the run.
            # Logical commit/constraint/isolation tests remain PostgreSQL tests;
            # no power-loss or crash durability is claimed with this option.
            run([args.python,'-c','''import os,time,psycopg
def connect():
    return psycopg.connect(dbname=os.environ['DB_NAME'],user=os.environ['DB_USER'],password=os.environ['DB_PASSWORD'],host=os.environ['DB_HOST'],port=os.environ['DB_PORT'],autocommit=True)
with connect() as c:
    c.execute("ALTER SYSTEM SET fsync='off'")
    c.execute("ALTER SYSTEM SET synchronous_commit='off'")
    c.execute('SELECT pg_reload_conf()')
for attempt in range(30):
    with connect() as c:
        if c.execute('SHOW fsync').fetchone()[0]=='off' and c.execute('SHOW synchronous_commit').fetchone()[0]=='off':break
    time.sleep(.05)
else:raise RuntimeError('Disposable native I/O settings were not applied')
'''],environment=environment)
        setup = '''import os, psycopg
with psycopg.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                     host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], autocommit=True) as conn:
    conn.execute("CREATE ROLE accounting_s19_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
    conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO accounting_s19_migrator")
'''
        run([args.python, "-c", setup], environment=environment)
        restricted = {**environment, "PGOPTIONS": "-c role=accounting_s19_migrator"}
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
            "native_io": {"fsync": not args.native_fast_io, "synchronous_commit": not args.native_fast_io,
                "scope": "Disposable synthetic cluster; no power-loss/crash durability proof"},
            "postgresql_binary_version": version, "native_restricted_role_ddl": {
                "all_migrations_passed": True, "superuser": False, "createdb": False, "createrole": False}, **result}


def docker(directory):
    require_local_docker()
    env_file = directory / "env"; create_local_env(env_file)
    HIDDEN_VALUES.update(line.split("=", 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(("DJANGO_SECRET_KEY=", "DB_PASSWORD=")))
    with env_file.open("a") as stream:
        stream.write("WEB_PORT=0\n")
    project = "accounting-s19-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S19] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s19-suite.json",
                           "--env", "ACCOUNTING_BOUNDARY_REPORT=/tmp/s19-boundary.jsonl",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s19-suite.json",
                           "--env", "ACCOUNTING_BOUNDARY_REPORT=/tmp/s19-boundary.jsonl",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s19-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        def read_boundary():
            copied=directory/'boundary.jsonl'
            run(['docker','cp',name+':/tmp/s19-boundary.jsonl',copied],environment=environment)
            return [json.loads(line) for line in copied.read_text().splitlines()]
        result = verification(stable_manage, read_suite, read_boundary)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report,rows=None):
    path=RECORDS/'evidence/S19-verification.json'
    if path.exists():
        before=load(path)
        if before.get('application_context_digest')==report['application_context_digest'] and 'native_restricted_role_ddl' in before:
            report.setdefault('native_restricted_role_ddl',before['native_restricted_role_ddl'])
    boundary_path=RECORDS/'evidence/S19-office-boundary.csv'
    if rows is not None:
        with boundary_path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['case_id','area','route','persona','scenario','observed','result'],lineterminator='\n')
            writer.writeheader();writer.writerows(sorted(rows,key=lambda row:row['case_id']))
    bound=list(csv.DictReader(boundary_path.open(newline='')))
    check_boundary(bound)
    report['boundary_matrix'].update(evidence='docs/implementation/evidence/S19-office-boundary.csv',sha256=digest(boundary_path.read_bytes()))
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (RECORDS/'steps.csv').open(newline='') as stream:steps=list(csv.DictReader(stream))
    row=next(r for r in steps if r['step_id']=='S19')
    row.update(status=report['status'],branch='step/s19-cash-accounts',code_reference_commit=report['source_commit'].removeprefix('git:'),
        evidence='docs/implementation/evidence/S19-verification.json; docs/implementation/evidence/S19-office-boundary.csv; docs/implementation/cash_accounts_categories.md; accounting/tests_cash_workspace.py',
        blocker='' if report['status']=='Verified' else 'Run python3 tools/verify_s19.py --record on laptop Docker',
        manual_acceptance='Synthetic technical scope; browser/client, live VM upgrade and all full acceptances Pending',
        next_step='S20 ordinary cash movements and validated filters' if report['status']=='Verified' else 'Complete S19 Docker gate')
    with (RECORDS/'steps.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=steps[0],lineterminator='\n');writer.writeheader();writer.writerows(steps)
    path=RECORDS/'state.md';text=path.read_text()
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+report['verified_at'][:10]+'. Current step: **S19 '+report['status']+' — dated cash accounts and categories**. Next step: **'+row['next_step']+'**.\n',text,count=1)
    summary='<!-- S19-RESULT -->\n'+report['status']+': '+str(report['s19_tests'])+' S19 tests; '+str(report['suite']['tests_run'])+' total; BAL-001–003 corrected, 10 known failures still reproduced, no unexpected outcomes. All '+str(report['boundary_matrix']['cases'])+' current boundary cases passed, retaining the original 652. Docker execution: '+str(report['docker_execution'])+'. Legacy amounts and history remain; opening dates require explicit owner/password/recent-MFA review. Signed adjustments are immutable and do not create operating cash. No existing demo/VM migration performed by verification.\n<!-- /S19-RESULT -->'
    if '<!-- S19-RESULT -->' in text:text=re.sub(r'<!-- S19-RESULT -->.*?<!-- /S19-RESULT -->',summary,text,flags=re.S)
    else:text+='\n'+summary+'\n'
    path.write_text(text)
    path=RECORDS/'traceability.csv'
    with path.open(newline='') as stream:requirements=list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement['requirement_id'] not in {'UR-CSH-01','UR-CSH-03','UR-CSH-05','UR-LOC-01','QR-03','QR-04'}:continue
        note=' S19: '+report['status']+' on '+report['mode']+'; reviewed dated opening/balance selectors, immutable signed corrections, category hierarchy/retirement and history preservation. Full workflow/browser acceptances remain Pending.'
        requirement['notes']=re.sub(r' S19:.*$','',requirement['notes'])+note
        for evidence in ('docs/implementation/evidence/S19-verification.json','docs/implementation/evidence/S19-office-boundary.csv','docs/implementation/cash_accounts_categories.md','accounting/tests_cash_workspace.py'):
            if evidence not in requirement['evidence'].split('; '):requirement['evidence']='; '.join(filter(None,[requirement['evidence'],evidence]))
        requirement['last_reviewed']=report['verified_at'][:10]
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=requirements[0],lineterminator='\n');writer.writeheader();writer.writerows(requirements)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-bin", type=Path)
    parser.add_argument("--native-fast-io", action="store_true", help="Only for the disposable native cluster: no fsync/synchronous commit; no crash durability proof")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--tools-python", type=Path, help="Reuse an existing pinned maintenance environment")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()
    try:
        if args.native_fast_io and not args.native_bin:
            raise RuntimeError("--native-fast-io requires --native-bin; Docker and retained environments are never altered by this option")
        if args.record and subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT).strip():
            raise RuntimeError("Commit the candidate source before recording its verification")
        protected = source_checks()
        with tempfile.TemporaryDirectory(prefix="accounting-s19-") as temp:
            directory = Path(temp)
            tooling = args.tools_python
            if tooling is None:
                print("[S19] Installing hashed maintenance tools; reproducing locks/catalog and scanning Git history.", flush=True)
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
        result.update(step="S19", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            live_mail_sent=False, browser_visual_accessibility_acceptance="Pending",
            local_demo_migrated=False, live_vm_upgraded=False, correction_http_ui="Opening adjustments only; ordinary cash correction UI remains S24",
            dated_openings_balances="Implemented; legacy cutoffs require owner review", allocations_credit_charges="Deferred to S22-S24",
            full_requirement_acceptance="Pending", full_requirement_acceptances_pending=85, **protected)
        if args.record:
            record(result,rows)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S19 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
