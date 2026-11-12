#!/usr/bin/env python3
"""S18 isolated PostgreSQL integrated office-boundary gate; never touches the VM.

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

BASE = "0870a08e9ff43b5380957084c511d0679b9825c3"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


from verify_s16 import check_boundary
from verify_s17 import current_bindings, reference_checks, review_result, load, digest

FIXED={f'AMT-{n:03d}' for n in range(1,9)}|{'SET-001','SET-002','STA-001','STA-002','CAN-001'}

def old_bytes(name):
    return subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT)

def source_checks():
    for step in ('S06','S10','S12','S13','S14','S15','S16','S17'):
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
    protected=[n for n in names if n.startswith(('accounting/migrations/','core/','locale/','templates/','docker/','infrastructure/','docs/baselines/')) or
        (n.startswith('accounting/tests') and n.endswith('.py') and n not in {'accounting/tests_regressions.py','accounting/tests_counterparties.py','accounting/tests_boundary.py','accounting/tests_ownership.py'}) or
        (n.startswith('docs/implementation/evidence/') and not n.rsplit('/',1)[-1].startswith('S17-')) or
        n in {'requirements.in','requirements.txt','requirements-tools.in','requirements-tools.txt','Dockerfile','docker-compose.yml',
          'accounting/auth_models.py','accounting/auth_services.py','accounting/auth_policy.py','accounting/auth_middleware.py',
          'accounting/auth_views.py','accounting/auth_forms.py','accounting/office_services.py','accounting/regression_runner.py',
          'accounting/office_boundary_matrix.json','docs/implementation/financial_policy.json','docs/implementation/financial_policy.md',
          'docs/implementation/financial_policy_review_el.md','docs/implementation/examples/S17-financial-examples.json',
          'docs/implementation/examples/S17-financial-examples_el.md'}]
    for name in protected:
        if (ROOT/name).read_bytes()!=old_bytes(name):raise RuntimeError('Protected baseline changed: '+name)
    for name in ('accounting/tests_regressions.py','accounting/tests_counterparties.py','accounting/tests_boundary.py','accounting/tests_ownership.py'):
        previous=ast.parse(old_bytes(name));candidate=ast.parse((ROOT/name).read_text())
        prior_names={n.name for n in ast.walk(previous) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
        current_names={n.name for n in ast.walk(candidate) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
        if not prior_names<=current_names:raise RuntimeError('Prior test removed: '+name)
        if name.endswith('tests_regressions.py'):
            calls=lambda tree:[ast.dump(n,include_attributes=False) for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='assert_financial_equal']
            if calls(previous)!=calls(candidate):raise RuntimeError('Correct financial assertions changed')
    previous=json.loads(old_bytes('accounting/regression_cases.json'))['cases']
    current=load(ROOT/'accounting/regression_cases.json')['cases']
    if len(previous)!=len(current):raise RuntimeError('Regression inventory changed')
    for before,after in zip(previous,current):
        compare={k:after[k] for k in before}
        if before['case_id'] in FIXED:compare['expected_outcome']='known_failure'
        if before!=compare:raise RuntimeError('Regression mapping/assertions changed outside S18 fixes')
    _,context=image.candidate_context()
    for name in ('accounting/finance_services.py','accounting/finance_models.py','accounting/finance_money.py',
       'accounting/tests_finance_posting.py','accounting/migrations/0012_financial_database_guards.py'):
        if name not in context['paths']:raise RuntimeError('Missing production context: '+name)
    return {'original_ten_migrations_preserved':True,'historical_evidence_through_s16_preserved':True,
        's17_approved_bound_review_preserved':True,'financial_expected_value_assertions_preserved':True,
        'all_existing_test_names_retained':True,'dependency_locks_authentication_mfa_referrer_preserved':True,
        'application_context_digest':context['digest']}


def verification(manage,read_suite,read_boundary):
    manage('shell','--no-imports','-c',"import subprocess,sys;subprocess.run([sys.executable,'-m','pip','check'],check=True,stdout=subprocess.DEVNULL)")
    packages=json.loads(manage('shell','--no-imports','-c',"import importlib.metadata,json;print(json.dumps({name:importlib.metadata.version(name) for name in ['Django','django-otp','cryptography','qrcode','psycopg']}))").stdout.strip())
    manage('migrate','--noinput');manage('makemigrations','--check','--dry-run');manage('check','--fail-level=WARNING')
    print('[S18] Testing exact money, immutable originals, atomic audit/retries/corrections, migration preservation and independent PostgreSQL races.',flush=True)
    manage('test','--settings=core.settings.test','--testrunner='+RUNNER,'--noinput','--verbosity=1')
    suite=read_suite();count=sum(isinstance(n,ast.FunctionDef) and n.name.startswith('test_') for n in ast.walk(ast.parse((ROOT/'accounting/tests_finance_posting.py').read_text())))
    if suite['tests_run']!=382+count or suite['known_failures_reproduced']!=13 or any(suite[k] for k in ('unexpected_failures','unexpected_errors','unexpected_successes','skips')):
        raise RuntimeError('Unexpected financial/existing suite outcome')
    rows=read_boundary();boundary=check_boundary(rows)
    case_results={row['case_id']:row for row in suite['cases']}
    if any(case_results[key]['outcome']!='passed' for key in FIXED):raise RuntimeError('An S18 corrected case did not pass')
    version=int(manage('shell','--no-imports','-c','from django.db import connection;print(connection.pg_version)').stdout.strip())
    if version//10000!=17:raise RuntimeError('PostgreSQL 17 required')
    return {'postgresql_version_num':version,'runtime_packages':packages,'runtime_pip_check':True,'s18_tests':count,
        'suite':{k:v for k,v in suite.items() if k!='cases'},'financial_cases':suite['cases'],
        'fixed_known_financial_cases':sorted(FIXED),'remaining_known_financial_failures':13,
        'boundary_matrix':boundary,'exact_money_rejects_raw_sql_overprecision':True,
        'immutable_originals_and_database_written_append_only_audit':True,
        'same_key_retry_conflict_and_independent_connection_races':True,
        'owner_password_recent_mfa_linked_reversal_replacement':True,
        'deferred_incomplete_unbalanced_group_commit_denied':True,
        'legacy_columns_and_ids_preserved_invalid_legacy_stops':True,
        'rollback_includes_command_cash_and_audit':True,
        'migration_drift':False}


def native(args, directory):
    with native_database(args.native_bin, directory) as (environment, version):
        environment['ACCOUNTING_BOUNDARY_REPORT']=str(directory/'boundary.jsonl')
        setup = '''import os, psycopg
with psycopg.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                     host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], autocommit=True) as conn:
    conn.execute("CREATE ROLE accounting_s18_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
    conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO accounting_s18_migrator")
'''
        run([args.python, "-c", setup], environment=environment)
        restricted = {**environment, "PGOPTIONS": "-c role=accounting_s18_migrator"}
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
    project = "accounting-s18-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S18] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s18-suite.json",
                           "--env", "ACCOUNTING_BOUNDARY_REPORT=/tmp/s18-boundary.jsonl",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s18-suite.json",
                           "--env", "ACCOUNTING_BOUNDARY_REPORT=/tmp/s18-boundary.jsonl",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s18-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        def read_boundary():
            copied=directory/'boundary.jsonl'
            run(['docker','cp',name+':/tmp/s18-boundary.jsonl',copied],environment=environment)
            return [json.loads(line) for line in copied.read_text().splitlines()]
        result = verification(stable_manage, read_suite, read_boundary)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report):
    path=RECORDS/'evidence/S18-verification.json'
    if path.exists():
        before=json.loads(path.read_text())
        if before.get('application_context_digest')==report['application_context_digest'] and 'native_restricted_role_ddl' in before:
            report.setdefault('native_restricted_role_ddl',before['native_restricted_role_ddl'])
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (RECORDS/'steps.csv').open(newline='') as stream:steps=list(csv.DictReader(stream))
    row=next(r for r in steps if r['step_id']=='S18')
    row.update(status=report['status'],branch='step/s18-financial-foundation',code_reference_commit=report['source_commit'].removeprefix('git:'),
        evidence='docs/implementation/evidence/S18-verification.json; docs/implementation/financial_posting.md; accounting/tests_finance_posting.py',
        blocker='' if report['status']=='Verified' else 'Run python3 tools/verify_s18.py --record on laptop Docker',
        manual_acceptance='Synthetic technical scope; browser/client, live VM upgrade and all full acceptances Pending',
        next_step='S19 dated cash accounts and balances' if report['status']=='Verified' else 'Complete S18 Docker gate')
    with (RECORDS/'steps.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=steps[0],lineterminator='\n');writer.writeheader();writer.writerows(steps)
    path=RECORDS/'state.md';text=path.read_text()
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+report['verified_at'][:10]+'. Current step: **S18 '+report['status']+' — financial posting foundation**. Next step: **'+row['next_step']+'**.\n',text,count=1)
    summary='<!-- S18-RESULT -->\n'+report['status']+': '+str(report['s18_tests'])+' S18 tests; '+str(report['suite']['tests_run'])+' total; 13 corrected known cases, 13 still reproduced, no unexpected outcomes. The 652-case office boundary is retained. Docker execution: '+str(report['docker_execution'])+'. Core correction uses owner/password/recent MFA; correction UI, dated opening/balance/report/allocation work remain later steps. No existing demo/VM migration performed.\n<!-- /S18-RESULT -->'
    if '<!-- S18-RESULT -->' in text:text=re.sub(r'<!-- S18-RESULT -->.*?<!-- /S18-RESULT -->',summary,text,flags=re.S)
    else:text+='\n'+summary+'\n'
    path.write_text(text)
    path=RECORDS/'traceability.csv'
    with path.open(newline='') as stream:requirements=list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement['requirement_id'] not in {'QR-03','QR-04','UR-CSH-02','UR-CSH-07','UR-LOC-01'}:continue
        note=' S18: '+report['status']+' on '+report['mode']+'; exact cents, atomic commands/audit, immutable originals and owner-MFA reversal service. Full workflows/acceptances remain Pending.'
        requirement['notes']=re.sub(r' S18:.*$','',requirement['notes'])+note
        for evidence in ('docs/implementation/evidence/S18-verification.json','docs/implementation/financial_posting.md','accounting/tests_finance_posting.py'):
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
        with tempfile.TemporaryDirectory(prefix="accounting-s18-") as temp:
            directory = Path(temp)
            tooling = args.tools_python
            if tooling is None:
                print("[S18] Installing hashed maintenance tools; reproducing locks/catalog and scanning Git history.", flush=True)
                run([sys.executable, "-m", "venv", directory / "tools"])
                tooling = directory / "tools/bin/python"
                run([tooling, "-m", "pip", "--disable-pip-version-check", "install", "--timeout", "120", "--retries", "5",
                     "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "-r", ROOT / "requirements-tools.txt"])
            run([tooling, ROOT / "tools/lock_dependencies.py", "--check"])
            run([tooling, ROOT / "tools/compile_translations.py", "--check"])
            scan = json.loads(run([tooling, ROOT / "tools/scan_secrets.py"]).stdout)
            result = native(args, directory) if args.native_bin else docker(directory)
            result.update(secret_scan=scan, runtime_and_tools_locks_reproduced=True, greek_catalog_verified=True)
        result.update(step="S18", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            live_mail_sent=False, browser_visual_accessibility_acceptance="Pending",
            local_demo_migrated=False, live_vm_upgraded=False, correction_http_ui="Deferred to S24",
            dated_openings_balances="Deferred to S19", allocations_credit_charges="Deferred to S22-S24",
            full_requirement_acceptance="Pending", full_requirement_acceptances_pending=85, **protected)
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S18 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
