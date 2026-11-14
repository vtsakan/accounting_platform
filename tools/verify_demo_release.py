#!/usr/bin/env python3
"""Rehearse S09→S14 on an isolated native PG17 database clone; no VM changes."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from dev import ROOT
from verify_s05 import run
from verify_s06 import native_database
import demo_release_common as policy
import image


def verify(args):
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip())
    unit=run([args.python,ROOT/'tools/test_demo_release.py'])
    count=int(re.search(r'Ran (\d+) tests',unit.stderr)[1])
    with tempfile.TemporaryDirectory(prefix='demo-clone-check-') as temporary:
        with native_database(args.native_bin,Path(temporary)) as (environment,version):
            import psycopg
            params={k:environment[v] for k,v in {'dbname':'DB_NAME','user':'DB_USER','password':'DB_PASSWORD','host':'DB_HOST','port':'DB_PORT'}.items()}
            with psycopg.connect(**params,autocommit=True) as connection:
                connection.execute('CREATE ROLE demo_migrator NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE')
                connection.execute('GRANT USAGE,CREATE ON SCHEMA public TO demo_migrator')
            restricted={**environment,'PGOPTIONS':'-c role=demo_migrator'}
            def manage(*values):return run([args.python,ROOT/'manage.py',*values],environment=restricted)
            for app in ('contenttypes','auth','admin','sessions'):manage('migrate',app,'--noinput')
            manage('migrate','accounting','0002','--noinput')
            seed="""from django.db import connection
from django.db.migrations.executor import MigrationExecutor
state=MigrationExecutor(connection).loader.project_state([('accounting','0002_transaction_agreement_alter_agreement_status_and_more')])
E=state.apps.get_model('accounting','Entity');C=state.apps.get_model('accounting','CashAccount')
E.objects.create(name='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S09',vat_number='000000000',entity_type='CUSTOMER')
C.objects.create(name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S09',opening_balance='0.00')
"""
            manage('shell','--no-imports','-c',seed)
            def read(db):
                with psycopg.connect(**{**params,'dbname':db},autocommit=True) as c:
                    c.execute("SET TIME ZONE 'UTC'")
                    sql=policy.snapshot_sql().split('\n',1)[1]
                    raw=c.execute('SELECT ('+sql.removeprefix('SELECT ').rstrip(';\n')+')::text').fetchone()[0]
                    return json.loads(raw,parse_float=str)
            original=read(environment['DB_NAME']);policy.synthetic_only(original)
            source={'hostname':'totalaccounting.duckdns.org','external_ipv4':'207.175.136.231','db_user':'demo_migrator',
                'db_name':environment['DB_NAME'],'acme_email':'synthetic@example.invalid','gcp':{},'published':{'image':policy.S09_IMAGE}}
            target={**source,'db_name':'accounting_demo_rehearsal','published':{'image':'synthetic-new-image'}}
            plan=policy.make_plan(source,target,original,'sha256:synthetic','synthetic-reviewer','Δοκιμαστικό γραφείο επαναφοράς')
            # Close all source connections, then clone with an operator role.
            with psycopg.connect(**{**params,'dbname':'postgres'},autocommit=True) as c:
                c.execute('CREATE DATABASE accounting_demo_rehearsal WITH TEMPLATE '+policy.identifier(environment['DB_NAME'])+' OWNER demo_migrator')
            assert read(target['db_name'])==original
            updated={**restricted,'DB_NAME':target['db_name']}
            program=(ROOT/'tools/demo_release_migrate.py').read_text()
            result=run([args.python,'-c',program,json.dumps(plan,ensure_ascii=False)],environment=updated)
            migration=json.loads(result.stdout[result.stdout.index('{'):])
            after=read(target['db_name']);assert after['business']==original['business'] and after['users']==0
            assert policy.S14_MIGRATION in after['migrations'] and read(environment['DB_NAME'])==original
            role=run([args.python,ROOT/'manage.py','shell','--no-imports','-c',"from django.db import connection;c=connection.cursor();c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user');print(c.fetchone())"],environment=updated).stdout.strip()
            assert role=='(False, False, False)'
            # A plan pointed at the original database must stop BEFORE migrating.
            forbidden=run([args.python,'-c',"exec("+repr(program.split("if __name__",1)[0])+" );\ntry:migrate_clone(__import__('json').loads(__import__('sys').argv[1]))\nexcept RuntimeError:print('original-target-denied')",json.dumps(plan)],environment=restricted)
            assert 'original-target-denied' in forbidden.stdout and read(environment['DB_NAME'])==original
            invitation_test="""import io,runpy,secrets,sys
from contextlib import redirect_stdout
from unittest.mock import patch
import django;django.setup()
from django.contrib.auth import get_user_model
from django.utils import timezone
from django_otp.oath import totp
from core.auth_crypto import cipher
from accounting.membership import create_accountant_profile
from accounting.auth_models import AuthenticatorDevice
from accounting.auth_policy import state_for
from accounting.office_models import StaffInvitation
from accounting.models import AccountantProfile
password=secrets.token_urlsafe(32)
user=get_user_model().objects.create_user('demo-operator-fixture','operator@example.invalid',password)
create_accountant_profile(user_id=user.pk,office_id=sys.argv[2],role='owner')
device=AuthenticatorDevice(user=user,name='ΔΟΚΙΜΑΣΤΙΚΗ ΣΥΣΚΕΥΗ',confirmed=True,setup_expires_at=timezone.now())
device.encrypted_secret=cipher(user.pk,device.secret_salt).encrypt(secrets.token_bytes(20)).decode();device.save()
state=state_for(user);state.enrolled_at=timezone.now();state.save()
script=sys.argv[1];sys.argv=[script,user.username,'recruit@example.invalid',sys.argv[2]]
with patch('getpass.getpass',side_effect=[password,f'{totp(device.bin_key):06d}']), patch('core.auth_mail.get_connection') as backend,redirect_stdout(io.StringIO()) as output:
    runpy.run_path(script,run_name='__main__')
    backend.assert_not_called()
assert '/join/' in output.getvalue()
assert StaffInvitation.objects.get().status=='pending' and StaffInvitation.objects.get().mail_status=='captured'
assert AccountantProfile.objects.count()==1 and get_user_model().objects.count()==1
before=StaffInvitation.objects.count()
with patch('getpass.getpass',return_value=secrets.token_urlsafe(32)),redirect_stdout(io.StringIO()):
    try:runpy.run_path(script,run_name='__main__')
    except SystemExit as error:assert error.code==1
    else:raise AssertionError('Wrong owner password accepted')
assert StaffInvitation.objects.count()==before
print('operator-invitation-proof-passed')
"""
            captured=run([args.python,'-c',invitation_test,ROOT/'tools/demo_invitation.py',plan['office_id']],environment=updated)
            assert 'operator-invitation-proof-passed' in captured.stdout and read(environment['DB_NAME'])==original
    from verify_s07 import native_verification
    with tempfile.TemporaryDirectory(prefix='demo-production-check-') as temporary:
        delivery=native_verification(args.native_bin,Path(temporary),args.python,current_source=True)
    smoke={k:delivery[k] for k in ('status','mode','postgresql_version_num','gunicorn_http_verified','readiness_outage_recovery_verified',
        'greek_login_verified','admin_manifest_references_verified','query_string_excluded_from_access_log','deployment_checks','static_assets')}
    smoke['suite']={k:v for k,v in delivery['suite'].items() if k!='cases'}
    return {'step':'S14A','status':'Prepared','mode':'native-postgresql17-database-clone','postgresql':version,
        'source_commit':'git:'+revision,'source_dirty':dirty,
        'unit_tests':count,'two_marker_clone_and_reviewed_backfill':True,'all_eight_migrations_applied':True,
        'restricted_migration_role':True,'legacy_record_values_and_ids_preserved':True,'original_database_unchanged':True,
        'original_database_migration_denied':True,'captured_invitation_password_otp_and_pending_approval':True,
        'human_accounts_created':False,'docker_execution':False,'cloud_execution':False,
        'application_context_digest':image.candidate_context()[1]['digest'],'clone_mapping_sha256':migration['mapping_sha256'],
        'native_production_smoke':smoke}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-bin',type=Path,required=True);parser.add_argument('--python',type=Path,default=Path(sys.executable));parser.add_argument('--report',type=Path)
    args=parser.parse_args();result=verify(args)
    if args.report:args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
