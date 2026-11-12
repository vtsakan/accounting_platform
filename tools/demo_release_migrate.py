"""Executed inside the pinned application image against the NEW demo database only."""
import json
import sys
from datetime import datetime,timezone

import django
django.setup()
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.contrib.auth import get_user_model
from accounting.legacy_ownership import template, backfill


def migrate_clone(plan):
    if connection.settings_dict['NAME']!=plan['target']['db_name'] or connection.settings_dict['NAME']==plan['source']['db_name']:
        raise RuntimeError('Refusing to migrate the original database')
    if get_user_model().objects.exists():
        raise RuntimeError('Existing identities require a separately reviewed migration')
    call_command('migrate','accounting','0004_office_ownership_nullable',interactive=False,verbosity=0)
    state=MigrationExecutor(connection).loader.project_state([('accounting','0004_office_ownership_nullable')])
    Office=state.apps.get_model('accounting','Office')
    if Office.objects.exists():
        raise RuntimeError('Unexpected existing office in demo clone')
    Office.objects.create(id=plan['office_id'],name=plan['office_name'])
    document=template()
    actual=[{'model':r['model'],'id':r['id']} for r in document['assignments']]
    expected=[{'model':r['model'],'id':r['id']} for r in plan['assignments']]
    if sorted(actual,key=lambda x:(x['model'],x['id']))!=sorted(expected,key=lambda x:(x['model'],x['id'])):
        raise RuntimeError('Clone record identities differ from the reviewed plan')
    document.update(reviewed_by=plan['operator'],reviewed_at=datetime.now(timezone.utc).isoformat(),assignments=plan['assignments'])
    dry=backfill(document,apply=False)
    applied=backfill(document,apply=True)
    if dry['mapping_sha256']!=applied['mapping_sha256']:
        raise RuntimeError('Ownership mapping changed while applying')
    call_command('migrate',interactive=False,verbosity=0)
    call_command('makemigrations',check=True,dry_run=True,verbosity=0)
    return {'status':'Migrated clone','office_id':plan['office_id'],'mapping':document,'mapping_sha256':applied['mapping_sha256'],
        'records':applied['records'],'human_accounts_created':False,'original_database_modified':False}


if __name__=='__main__':
    print(json.dumps(migrate_clone(json.loads(sys.argv[1])),ensure_ascii=False))
