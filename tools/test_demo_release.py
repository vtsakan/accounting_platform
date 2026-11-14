"""Denied cases for the narrow synthetic demo upgrade plan; no cloud execution."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import demo_release_common as policy


def fixture():
    return {'migrations':policy.S09_MIGRATIONS[:],'users':0,'business':{
        'entity':[{'id':7,'name':'ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S09','vat_number':'000000000','entity_type':'CUSTOMER',
            **{k:'' for k in ('tax_office','address','city','postal_code','phone_number','email')},
            'created_at':'2026-11-09T00:00:00+00:00','updated_at':'2026-11-09T00:00:00+00:00'}],
        'cashaccount':[{'id':9,'name':'ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S09','opening_balance':'0.00','is_active':True}],
        'category':[],'agreement':[],'transaction':[]}}


def deployments():
    source={'hostname':'totalaccounting.duckdns.org','external_ipv4':'207.175.136.231','db_user':'accounting_app',
        'db_name':'accounting_platform','acme_email':'synthetic@example.invalid','gcp':{'project_id':'accounting-514109','secret_versions':{'django':1,'postgres':1}},
        'published':{'image':policy.S09_IMAGE}}
    target=deepcopy(source);target['db_name']='accounting_demo_synthetic';target['published']['image']='synthetic-target'
    return source,target


class DemoPlanTests(unittest.TestCase):
    def plan(self):
        source,target=deployments()
        return policy.make_plan(source,target,fixture(),'sha256:synthetic','synthetic-operator','Δοκιμαστικό γραφείο')

    def test_exact_sample_plan_is_bound_to_source_target_ids_and_reviewer(self):
        p=self.plan();self.assertEqual(policy.validate_plan(p,policy.digest(p)),p)
        self.assertEqual({r['id'] for r in p['assignments']},{7,9})
        self.assertNotEqual(p['source']['db_name'],p['target']['db_name'])

    def test_existing_user_cannot_be_silently_assigned(self):
        d=fixture();d['users']=1
        with self.assertRaises(ValueError):policy.synthetic_only(d)

    def test_non_marker_or_extra_business_records_need_review(self):
        for table in policy.TABLES:
            d=fixture();d['business'][table].append({'id':55})
            with self.subTest(table=table),self.assertRaises(ValueError):policy.synthetic_only(d)

    def test_real_contact_data_in_marker_is_rejected(self):
        d=fixture();d['business']['entity'][0]['email']='contact@example.invalid'
        with self.assertRaises(ValueError):policy.synthetic_only(d)

    def test_nonzero_balance_or_disabled_cash_account_is_rejected(self):
        for field,value in (('opening_balance','1.00'),('is_active',False)):
            d=fixture();d['business']['cashaccount'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):policy.synthetic_only(d)

    def test_wrong_source_image_or_schema_is_rejected(self):
        source,target=deployments();source['published']['image']='unexpected'
        with self.assertRaises(ValueError):policy.make_plan(source,target,fixture(),'sha256:synthetic','operator','Δοκιμαστικό γραφείο')
        d=fixture();d['migrations'].append('0003_unexpected')
        with self.assertRaises(ValueError):policy.synthetic_only(d)

    def test_altered_plan_hash_or_unreviewed_assignment_is_rejected(self):
        p=self.plan();old=policy.digest(p);p['office_name']+=' άλλαξε'
        with self.assertRaises(ValueError):policy.validate_plan(p,old)
        p=self.plan();p['assignments'][0]['office_id']='00000000-0000-4000-8000-000000000001'
        with self.assertRaises(ValueError):policy.validate_plan(p,policy.digest(p))

    def test_original_database_is_not_an_allowed_migration_target(self):
        source,target=deployments();target['db_name']=source['db_name']
        with self.assertRaises(ValueError):policy.compare_identity(source,target)

    def test_changed_cloud_secret_domain_or_operator_is_rejected(self):
        for key,value in (('hostname','foreign.duckdns.org'),('external_ipv4','192.0.2.7'),('db_user','other_role')):
            source,target=deployments();target[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):policy.compare_identity(source,target)
        source,target=deployments();target['gcp']['secret_versions']['django']=2
        with self.assertRaises(ValueError):policy.compare_identity(source,target)
        source,target=deployments()
        with self.assertRaises(ValueError):policy.make_plan(source,target,fixture(),'sha256:synthetic','operator\n','Δοκιμαστικό γραφείο')

    def test_database_identifier_cannot_inject_sql(self):
        for value in ('x; DROP DATABASE x','"quoted"','../other','accounting-demo','postgres\n'):
            with self.subTest(value=value),self.assertRaises(ValueError):policy.identifier(value)

    def test_rollback_refuses_to_hide_new_demo_accounts_before_stopping_services(self):
        import demo_release_host as host
        source,target=deployments()
        state={'plan':{'source':source,'target':target},'cutover_started':True}
        with patch.object(host,'query',return_value='1'),patch.object(host.host,'compose') as compose,patch.object(host.common,'run') as command:
            with self.assertRaises(ValueError):host.rollback(state)
            compose.assert_not_called();command.assert_not_called()

    def test_diagnostics_only_expose_fixed_reviewed_reasons(self):
        import preview_events
        policy.register_diagnostics()
        self.assertIn('Reviewed demo plan hash differs',preview_events.REASONS)
        self.assertNotIn('provider-body-with-private-values',preview_events.REASONS)


if __name__=='__main__':unittest.main(verbosity=2)
