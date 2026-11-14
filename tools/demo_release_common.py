"""S14A synthetic VM demo: immutable plan and narrowly bounded legacy inventory."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re
import uuid

from cloud import require

TABLES = ('entity', 'cashaccount', 'category', 'agreement', 'transaction')
S09_MIGRATIONS = ['0001_initial', '0002_transaction_agreement_alter_agreement_status_and_more']
S14_MIGRATION = '0008_office_workflow_guards'
S09_IMAGE = 'europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:' + '9a8a2910370affb88ea64e56a3015906df06b8d126da815698e3a012073c36fb'


def register_diagnostics():
    # Only fixed validation messages may cross captured SSH stderr.
    import preview_events
    preview_events.REASONS.update({
        'This demo upgrade requires the exact S09 accounting migration state',
        'Existing VM users need a separately reviewed membership migration',
        'Only the two known S09 synthetic markers may enter this demo upgrade; stop for real-data review',
        'The marker contains contact data; stop for review',
        'Unknown legacy entity', 'Unknown/nonzero legacy cash account',
        'Private media needs separate document recovery before upgrade',
        'The installed deployment changed; create a new plan',
        'Legacy rows changed; create and review a new plan',
        'Recovery binding differs from the source',
        'Reviewed demo plan hash differs',
        'Target database exists; it will not be overwritten',
        'A prior attempt exists; inspect status/rollback rather than repeat migrations',
        'Demo accounts already exist; preserve them and review rollback separately',
        'Upgrade stopped; original database and journal retained. Inspect before recovery',
    })


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def identifier(value):
    require(isinstance(value,str) and re.fullmatch(r'[a-z][a-z0-9_]{2,40}',value), 'Invalid database identifier')
    return '"'+value+'"'


def snapshot_sql():
    business = ','.join("'"+name+"',coalesce((SELECT json_agg(to_jsonb(t)-'office_id' ORDER BY id) FROM accounting_"+name+" t),'[]'::json)" for name in TABLES)
    return "SET TIME ZONE 'UTC';\nSELECT json_build_object('migrations',(SELECT json_agg(name ORDER BY name) FROM django_migrations WHERE app='accounting'),'users',(SELECT count(*) FROM auth_user),'business',json_build_object("+business+"));\n"


def synthetic_only(snapshot):
    require(set(snapshot)=={'migrations','users','business'} and snapshot['migrations']==S09_MIGRATIONS,
            'This demo upgrade requires the exact S09 accounting migration state')
    require(type(snapshot['users']) is int and snapshot['users']==0, 'Existing VM users need a separately reviewed membership migration')
    rows=snapshot['business']; require(set(rows)==set(TABLES), 'Unexpected legacy inventory tables')
    require(all(isinstance(rows[k],list) for k in TABLES), 'Invalid inventory rows')
    require(len(rows['entity'])==len(rows['cashaccount'])==1 and not any(rows[k] for k in ('category','agreement','transaction')),
            'Only the two known S09 synthetic markers may enter this demo upgrade; stop for real-data review')
    entity,account=rows['entity'][0],rows['cashaccount'][0]
    require(set(entity)=={'id','entity_type','name','vat_number','tax_office','address','city','postal_code','phone_number','email','created_at','updated_at'},'Unexpected entity schema')
    require(entity['name']=='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S09' and entity['vat_number']=='000000000' and entity['entity_type']=='CUSTOMER', 'Unknown legacy entity')
    require(all(entity[k] in ('',None) for k in ('tax_office','address','city','postal_code','phone_number','email')), 'The marker contains contact data; stop for review')
    require(set(account)=={'id','name','opening_balance','is_active'} and account['name']=='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S09'
            and Decimal(str(account['opening_balance']))==Decimal('0.00') and account['is_active'] is True, 'Unknown/nonzero legacy cash account')
    require(all(type(row['id']) is int and row['id']>0 for row in (entity,account)), 'Invalid marker identity')
    return [{'model':name,'id':rows[name][0]['id']} for name in ('entity','cashaccount')]


def compare_identity(source,target):
    for key in ('hostname','external_ipv4','db_user','acme_email'):
        require(source[key]==target[key], 'Deployment identity changed: '+key)
    require(source['gcp']==target['gcp'], 'Cloud/disk/secret identity changed')
    require(source['db_name']!=target['db_name'] and target['db_name'].startswith('accounting_demo_'), 'Use a separate demo database')
    identifier(source['db_name']);identifier(target['db_name']);identifier(target['db_user'])


def make_plan(source,target,snapshot,bundle_hash,operator,office_name):
    require(isinstance(operator,str) and 1<=len(operator.strip())<=100 and not any(ord(c)<32 for c in operator), 'Name the responsible operator')
    require(isinstance(office_name,str) and office_name.startswith('Δοκιμαστικό ') and len(office_name)<=255, 'Use an explicitly named sample office')
    require(source['published']['image']==S09_IMAGE, 'Unexpected source image; inspect before planning an upgrade')
    compare_identity(source,target)
    assignments=synthetic_only(snapshot)
    office=str(uuid.uuid4())
    return {'schema':1,'source':source,'target':target,'source_snapshot':snapshot,'source_snapshot_sha256':digest(snapshot),
        'bundle_sha256':bundle_hash,'operator':operator.strip(),'office_name':office_name,'office_id':office,
        'assignments':[{**r,'office_id':office} for r in assignments], 'created_at':datetime.now(timezone.utc).isoformat(),
        'scope':'Synthetic S09 markers only; clone original database, migrate clone, preserve source for rollback'}


def validate_plan(plan,expected):
    require(digest(plan)==expected, 'Reviewed demo plan hash differs')
    compare_identity(plan['source'],plan['target'])
    expected_assignments=synthetic_only(plan['source_snapshot'])
    require(plan['source_snapshot_sha256']==digest(plan['source_snapshot']), 'Snapshot hash differs')
    require(str(uuid.UUID(plan['office_id']))==plan['office_id'], 'Invalid demo office identity')
    require(plan['assignments']==[{**r,'office_id':plan['office_id']} for r in expected_assignments], 'Only reviewed marker assignments are allowed')
    require(plan['source']['published']['image']==S09_IMAGE, 'Unexpected source image')
    return plan
