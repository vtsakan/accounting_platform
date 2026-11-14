#!/usr/bin/env python3
"""S15 isolated PostgreSQL client/supplier workspace gate; never touches the VM.

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

BASE = "ab9602592cb699684450bc4ee70438f80d30351f"
RECORDS = ROOT / "docs/implementation"
RUNNER = "accounting.regression_runner.FinancialRegressionRunner"


def source_checks():
    for step in ('S12','S14'):
        if json.loads((RECORDS/'evidence'/(step+'-verification.json')).read_text())['status']!='Verified':
            raise RuntimeError(step+' operator Docker gate required')
    def original(name):
        return subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT).decode()
    protected=['requirements.in','requirements.txt','requirements-tools.in','requirements-tools.txt','Dockerfile',
        'accounting/regression_runner.py','accounting/regression_cases.json','accounting/tests_regressions.py',
        'accounting/auth_models.py','accounting/auth_services.py','accounting/tests_authentication.py','core/auth_crypto.py',
        'core/tests/test_s04.py','core/tests/test_s07.py','core/tests/test_referrer.py','infrastructure/Caddyfile']
    protected += [str(p.relative_to(ROOT)) for p in (ROOT/'accounting/migrations').glob('000[12345678]_*.py')]
    protected += ['docs/implementation/evidence/'+step+'-verification.json' for step in ('S10','S11','S12','S13','S14')]
    for name in protected:
        if (ROOT/name).read_text()!=original(name):raise RuntimeError('Protected source changed: '+name)
    old=ast.parse(original('accounting/models.py'));new=ast.parse((ROOT/'accounting/models.py').read_text())
    for name in ('CashAccount','Category','Agreement','Transaction','Office','AccountantProfile'):
        get=lambda tree:next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==name)
        if ast.dump(get(old))!=ast.dump(get(new)):raise RuntimeError('Existing financial/membership model changed: '+name)
    old=ast.parse(original('accounting/views.py'));new=ast.parse((ROOT/'accounting/views.py').read_text())
    for name in ('dashboard_view','transaction_list_view','summary_report_view','agreement_list_view','agreement_detail_view','add_transfer_view'):
        get=lambda tree:next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
        if ast.dump(get(old))!=ast.dump(get(new)):raise RuntimeError('Existing financial calculation changed: '+name)
    # Exact fixture-only changes: new form contract, unchanged expected assertions.
    expected=original('accounting/tests_ownership.py')
    expected=expected.replace('"entity_type": "CUSTOMER", "vat_number":','"is_customer": True, "legal_kind": "BUSINESS", "version": 0, "vat_number":')
    expected=expected.replace('"entity_type": "CUSTOMER",\n            "vat_number":','"is_customer": True, "legal_kind": "BUSINESS", "version": 0,\n            "vat_number":')
    expected=expected.replace('        self.migrate_to("0004_office_ownership_nullable")', '        state = self.migrate_to("0004_office_ownership_nullable")\n        previous = MODELS.copy()\n        MODELS[\'entity\'] = state.get_model(\'accounting\', \'Entity\')\n        self.addCleanup(MODELS.update, previous)')
    if (ROOT/'accounting/tests_ownership.py').read_text()!=expected:raise RuntimeError('Unexpected ownership assertion/fixture change')
    expected=original('accounting/tests_staff.py').replace('{"entity_type": "CUSTOMER", "name": "ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S14"}', '{"is_customer": True, "legal_kind": "BUSINESS", "version": 0, "name": "ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S14"}')
    if (ROOT/'accounting/tests_staff.py').read_text()!=expected:raise RuntimeError('Unexpected staff assertion/fixture change')
    _,context=image.candidate_context()
    for name in ('accounting/counterparty_views.py','accounting/counterparty_services.py','accounting/counterparty_validation.py',
        'accounting/migrations/0009_counterparty_workspace.py','accounting/migrations/0010_counterparty_database_guards.py',
        'accounting/templates/accounting/includes/entity_fields.html'):
        if name not in context['paths']:raise RuntimeError('Production input missing: '+name)
    return {'original_eight_migrations_and_financial_models_preserved':True,
        'financial_assertions_registry_and_money_calculations_preserved':True,
        'existing_assertions_preserved_with_new_form_payloads':True,'s10_through_s14_evidence_preserved':True,
        'authentication_office_policy_referrer_and_dependency_locks_preserved':True,
        'workspace_and_migrations_in_production_context':True,'application_context_digest':context['digest']}


def verification(manage,read_suite):
    manage('shell','--no-imports','-c',"import subprocess,sys;subprocess.run([sys.executable,'-m','pip','check'],check=True,stdout=subprocess.DEVNULL)")
    packages=json.loads(manage('shell','--no-imports','-c',"import importlib.metadata,json;print(json.dumps({name:importlib.metadata.version(name) for name in ['Django','django-otp','cryptography','qrcode','psycopg']}))").stdout.strip())
    manage('migrate','--noinput')
    manage('makemigrations','--check','--dry-run')
    manage('check','--fail-level=WARNING')
    print('[S15] Testing dual roles, validation/search, archive/history, migration preservation, office denials and independent PG races.',flush=True)
    manage('test','--settings=core.settings.test','--testrunner='+RUNNER,'--noinput','--verbosity=1')
    suite=read_suite()
    count=sum(isinstance(node,ast.FunctionDef) and node.name.startswith('test_') for node in ast.walk(ast.parse((ROOT/'accounting/tests_counterparties.py').read_text())))
    if suite['tests_run']!=287+count or suite['known_failures_reproduced']!=26 or any(suite[key] for key in ('unexpected_failures','unexpected_errors','unexpected_successes','skips')):
        raise RuntimeError('Unexpected S15 or existing regression outcome')
    version=int(manage('shell','--no-imports','-c','from django.db import connection;print(connection.pg_version)').stdout.strip())
    if version//10000!=17:raise RuntimeError('PostgreSQL 17 required')
    return {'postgresql_version_num':version,'runtime_packages':packages,'runtime_pip_check':True,'s15_tests':count,
        'suite':{k:v for k,v in suite.items() if k!='cases'},'independent_customer_supplier_roles':True,
        'explicit_person_business_and_legacy_unreviewed_classification':True,'normalised_afm_office_uniqueness_and_concurrency':True,
        'greek_validated_search_and_paginated_consolidated_detail':True,'archive_restore_keeps_financial_history_and_identifiers':True,
        'archived_new_work_denied_through_forms_models_and_sql':True,'both_archive_post_lock_orders_verified':True,
        'new_form_stale_updates_and_office_revocation_rechecked':True,'lifecycle_events_atomic_append_only_and_scoped':True,
        'original_legacy_columns_users_and_foreign_keys_preserved_in_migration':True,
        'invalid_or_duplicate_legacy_identity_migration_stops_without_merge':True,'unsafe_downgrade_denied':True,'migration_drift':False}


def native(args, directory):
    with native_database(args.native_bin, directory) as (environment, version):
        setup = '''import os, psycopg
with psycopg.connect(dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
                     host=os.environ["DB_HOST"], port=os.environ["DB_PORT"], autocommit=True) as conn:
    conn.execute("CREATE ROLE accounting_s15_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
    conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO accounting_s15_migrator")
'''
        run([args.python, "-c", setup], environment=environment)
        restricted = {**environment, "PGOPTIONS": "-c role=accounting_s15_migrator"}
        run([args.python, ROOT / "manage.py", "migrate", "--noinput"], environment=restricted)
        probe = run([args.python, ROOT / "manage.py", "shell", "--no-imports", "-c",
            "from django.db import connection; c=connection.cursor(); c.execute('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user'); print(c.fetchone())"], environment=restricted)
        if probe.stdout.strip() != "(False, False, False)":
            raise RuntimeError("Restricted migration role unexpectedly elevated")
        def manage(*arguments):
            return run([args.python, ROOT / "manage.py", *arguments], environment=environment)
        result = verification(manage, lambda: json.loads(Path(environment["ACCOUNTING_REGRESSION_REPORT"]).read_text()))
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
    project = "accounting-s15-check-" + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()
    def compose(*arguments):
        return run(command + list(arguments), environment=environment)
    if compose("ps", "--all", "--quiet").stdout.strip() or run(
            ["docker", "volume", "ls", "--filter", "label=com.docker.compose.project=" + project, "--quiet"],
            environment=environment).stdout.strip():
        raise RuntimeError("Refusing to adopt an existing Docker project")
    try:
        print("[S15] Disposable local Docker project: " + project, flush=True)
        compose("build", "web")
        compose("up", "--detach", "--wait", "--wait-timeout", "180", "db")
        def manage(*arguments):
            return compose("run", "--rm", "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s15-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        # The report is copied via stdout from the test container, whose lifetime
        # ends on completion. Keep a one-shot container until its report is read.
        name = project + "-suite"
        def stable_manage(*arguments):
            if arguments[0] != "test":
                return manage(*arguments)
            return compose("run", "--name", name, "--no-deps", "--env", "ACCOUNTING_REGRESSION_REPORT=/tmp/s15-suite.json",
                           "--entrypoint", "python", "web", "manage.py", *arguments)
        def read_suite():
            copied = directory / "suite.json"
            run(["docker", "cp", name + ":/tmp/s15-suite.json", copied], environment=environment)
            return json.loads(copied.read_text())
        result = verification(stable_manage, read_suite)
        return {"mode": "docker-compose-postgresql17", "status": "Verified", "docker_execution": True, **result}
    finally:
        compose("down", "--volumes", "--remove-orphans")


def record(report):
    path=RECORDS/'evidence/S15-verification.json'
    if path.exists():
        previous=json.loads(path.read_text())
        if previous.get('application_context_digest')==report['application_context_digest'] and 'native_restricted_role_ddl' in previous and 'native_restricted_role_ddl' not in report:
            report['native_restricted_role_ddl']=previous['native_restricted_role_ddl']
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    with (RECORDS/'steps.csv').open(newline='') as stream:rows=list(csv.DictReader(stream))
    row=next(r for r in rows if r['step_id']=='S15')
    row.update(status=report['status'],branch='step/s15-client-workspace',code_reference_commit=report['source_commit'].removeprefix('git:'),
        evidence='docs/implementation/evidence/S15-verification.json; docs/implementation/client_supplier_workspace.md; accounting/tests_counterparties.py',
        blocker='' if report['status']=='Verified' else 'Reproduce with python3 tools/verify_s15.py --record on laptop Docker',
        manual_acceptance='Greek browser/keyboard review and full requirement acceptance Pending; VM deployment is separate',
        next_step='S16' if report['status']=='Verified' else 'Complete S15 local Docker gate')
    with (RECORDS/'steps.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=rows[0],lineterminator='\n');writer.writeheader();writer.writerows(rows)
    path=RECORDS/'state.md';text=path.read_text()
    text=re.sub(r'Updated .*?Current step:.*?\n','Updated '+report['verified_at'][:10]+'. Current step: **S15 '+report['status']+' — client and supplier workspace**. Next step: **'+row['next_step']+'**.\n',text,count=1)
    result='<!-- S15-RESULT -->\n'+report['status']+': '+str(report['s15_tests'])+' workspace/migration/archival/concurrency checks; '+str(report['suite']['tests_run'])+' total tests with 26 known financial failures and no unexpected outcomes. Docker execution: '+str(report['docker_execution'])+'. Greek browser and full requirement acceptance remain Pending.\n<!-- /S15-RESULT -->'
    if '<!-- S15-RESULT -->' in text:text=re.sub(r'<!-- S15-RESULT -->.*?<!-- /S15-RESULT -->',result,text,flags=re.S)
    else:text+='\n'+result+'\n'
    path.write_text(text)
    path=RECORDS/'traceability.csv'
    with path.open(newline='') as stream:requirements=list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement['requirement_id'] not in {'UR-CRM-01','UR-CRM-02','UR-CRM-03','UR-CRM-06','UR-CRM-07','QR-07','UR-LOC-01'}:continue
        note=' S15: '+report['status']+' on '+report['mode']+'; dual roles, explicit classification, Greek validation/search/detail, office AFM uniqueness, archive/history, migration and concurrency tests pass. Full staged acceptance and VM deployment remain Pending.'
        requirement['notes']=re.sub(r' S15:.*$','',requirement['notes'])+note
        for evidence in ('docs/implementation/evidence/S15-verification.json','docs/implementation/client_supplier_workspace.md','accounting/tests_counterparties.py'):
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
        with tempfile.TemporaryDirectory(prefix="accounting-s15-") as temp:
            directory = Path(temp)
            tooling = args.tools_python
            if tooling is None:
                print("[S15] Installing hashed maintenance tools; reproducing locks/catalog and scanning Git history.", flush=True)
                run([sys.executable, "-m", "venv", directory / "tools"])
                tooling = directory / "tools/bin/python"
                run([tooling, "-m", "pip", "--disable-pip-version-check", "install", "--timeout", "120", "--retries", "5",
                     "--require-hashes", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "-r", ROOT / "requirements-tools.txt"])
            run([tooling, ROOT / "tools/lock_dependencies.py", "--check"])
            run([tooling, ROOT / "tools/compile_translations.py", "--check"])
            scan = json.loads(run([tooling, ROOT / "tools/scan_secrets.py"]).stdout)
            result = native(args, directory) if args.native_bin else docker(directory)
            result.update(secret_scan=scan, runtime_and_tools_locks_reproduced=True, greek_catalog_verified=True)
        result.update(step="S15", verified_at=datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            source_commit="git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            source_dirty=bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
            source_reference_commit="git:" + BASE, cloud_or_vm_changed=False,
            human_application_accounts_created=False, real_client_data_imported=False,
            live_mail_sent=False, browser_visual_accessibility_acceptance="Pending",
            full_requirement_acceptance="Pending", full_requirement_acceptances_pending=85, **protected)
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, "S15 stopped: " + str(error) + "\n")


if __name__ == "__main__":
    main()
