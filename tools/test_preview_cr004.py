"""Operator-only guard contracts; all provider/app execution is mocked."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import preview_cr004_policy as p
import preview_cr004_host as h
import preview_cr004_release as release
from preview_cr004_migrate import clone_guard


def pair():
    source = {'hostname':p.HOSTNAME,'gcp':{**p.BOOTSTRAP['gcp'],
        'data_uuid':'22415b2c-1e1b-4e39-9ce5-5fb0c19dd663','secret_versions':{'app':1,'database':1}},
        'db_name':'accounting_s31_000000000001','db_user':'app_role',
        'published':{'commit':p.OLD_APP_REVISION,'image':p.OLD_IMAGE,
            'context_digest':p.OLD_CONTEXT}, 'deployment_commit':'1'*40}
    target = deepcopy(source); target['db_name']='accounting_cr004_000000000002'
    target['deployment_commit']='2'*40
    target['published']={'commit':p.APP_REVISION,'image_id':p.IMAGE_ID,'context_digest':p.CONTEXT,
        'image':'europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:'+'a'*64}
    return source,target


def proofs():
    state={'phase':'awaiting_off_vm_restore','public_cutover_started':False,
        'before_backup':{'fixture':'before'},'after_backup':{'fixture':'after'}}
    recovered={name:{'status':'Restored','all_public_tables_match':True,'separate_recovery_key_used':True,
        'receipt':state[name+'_backup'],'plaintext_removed':True,'recovery_container_removed':True,
        'preview_database_modified':False} for name in ('before','after')}
    return state,recovered


def synthetic_report():
    return {'fixture':'synthetic guard contract only, not an operator receipt',
        'change':'CR-004','status':'Verified','source_commit':'git:'+p.APP_REVISION,
        'image':{'image_id':p.IMAGE_ID,'revision':'git:'+p.APP_REVISION,'context':{'file_count':308}},
        'application_context_digest':p.CONTEXT,'suite':{'tests_run':965,'tests_passed':965,
            'cases':[{'case_id':str(i),'outcome':'passed'} for i in range(36)]},
        'real_monthly_worker_and_commit_before_ack':True,
        'actual_cr003_receipt_sha256':p.digest_bytes(b'{"fixture":"synthetic history"}')}


class TransitionContracts(unittest.TestCase):
    def test_current_source_and_distinct_target_are_accepted(self):
        p.transition(*pair())

    def test_source_database_cannot_be_reused(self):
        source,target=pair();target['db_name']=source['db_name']
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_stale_s24_context_is_rejected(self):
        source,target=pair();source['published']['context_digest']='sha256:'+'0'*64
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_different_current_image_is_not_overwritten(self):
        source,target=pair();source['published']['image']='unexpected-image'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_new_database_role_is_rejected(self):
        source,target=pair();target['db_user']='replacement_role'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_key_version_change_is_rejected(self):
        source,target=pair();target['gcp']['secret_versions']['app']=2
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_foreign_vm_and_disk_are_rejected(self):
        for key,value in (('project_id','different-project'),('vm_name','other-vm'),('data_uuid','other-disk')):
            source,target=pair();target['gcp'][key]=value
            with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_unverified_target_context_is_rejected(self):
        source,target=pair();target['published']['context_digest']='sha256:'+'0'*64
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_unverified_application_commit_is_rejected(self):
        source,target=pair();target['published']['commit']='0'*40
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_existing_backup_policy_is_only_rebound_to_target(self):
        source,target=pair();original={'preview':source,'recipient':'synthetic-public-recipient','retention_days':7}
        result=p.rebound_operations(original,target)
        self.assertEqual(result['preview'],target)
        self.assertEqual(original['preview'],source)
        self.assertEqual({k:v for k,v in result.items() if k!='preview'},
                         {k:v for k,v in original.items() if k!='preview'})


class RecoveryContracts(unittest.TestCase):
    def test_exact_both_off_vm_proofs_are_required(self):
        state,recovered=proofs();p.ready_for_activation(state,recovered)
        del recovered['before']
        with self.assertRaises(RuntimeError):p.ready_for_activation(state,recovered)

    def test_wrong_backup_generation_proof_is_rejected(self):
        state,recovered=proofs();recovered['after']['receipt']={'fixture':'different'}
        with self.assertRaises(RuntimeError):p.ready_for_activation(state,recovered)

    def test_primary_key_or_remaining_plaintext_is_rejected(self):
        for field in ('separate_recovery_key_used','plaintext_removed','recovery_container_removed'):
            state,recovered=proofs();recovered['before'][field]=False
            with self.assertRaises(RuntimeError):p.ready_for_activation(state,recovered)

    def test_failed_all_table_comparison_is_rejected(self):
        state,recovered=proofs();recovered['after']['all_public_tables_match']=False
        with self.assertRaises(RuntimeError):p.ready_for_activation(state,recovered)

    def test_recovery_must_not_change_preview_database(self):
        state,recovered=proofs();recovered['after']['preview_database_modified']=True
        with self.assertRaises(RuntimeError):p.ready_for_activation(state,recovered)

    def test_rollback_is_refused_after_jobs_or_http_may_write(self):
        with self.assertRaises(RuntimeError):p.before_public({'public_cutover_started':True})
        p.before_public({'public_cutover_started':False})

    def test_unknown_cutover_flag_cannot_authorise_rollback(self):
        with self.assertRaises(RuntimeError):p.before_public({})

    def test_insufficient_current_vm_capacity_is_rejected(self):
        for values in ((3_000_000,1_100_000,9*1024**3,1000),(4_000_000,500_000,9*1024**3,1000),
                       (4_000_000,1_100_000,1000,1000)):
            with self.assertRaises(RuntimeError):p.same_capacity(*values)


class CloneContracts(unittest.TestCase):
    def test_only_distinct_restricted_clone_name_is_accepted(self):
        clone_guard('accounting_s31_000000000001','accounting_cr004_000000000002',
            'accounting_cr004_000000000002','db','postgresql',170011)

    def test_source_or_unknown_database_is_rejected(self):
        for source,target,database in (('accounting_cr004_000000000002',)*3,
            ('current','accounting_cr004_000000000002','current')):
            with self.assertRaises(RuntimeError):clone_guard(source,target,database,'db','postgresql',170011)

    def test_remote_database_host_or_server_change_is_rejected(self):
        for host,version in (('external.example.invalid',170011),('db',170012)):
            with self.assertRaises(RuntimeError):clone_guard('source','accounting_cr004_000000000002',
                'accounting_cr004_000000000002',host,'postgresql',version)


class QueueAndWritersContracts(unittest.TestCase):
    def test_every_writer_stops_before_source_freeze(self):
        source,_=pair()
        with patch.object(h,'compose') as command,patch.object(h,'container',return_value={'State':{'Running':False}}),\
             patch.object(h,'query',return_value='0'):
            h.stop_writers(source)
        self.assertEqual([c.args[-1] for c in command.call_args_list[:2]],['scheduler','worker'])
        self.assertEqual(command.call_args_list[2].args[-2:],('caddy','web'))
        self.assertFalse(any('db' in call.args[1:] for call in command.call_args_list))

    def test_running_worker_prevents_freezing_or_cloning(self):
        source,_=pair()
        with patch.object(h,'compose'),patch.object(h,'container',return_value={'State':{'Running':True}}),\
             patch.object(h,'query',return_value='0'):
            with self.assertRaises(RuntimeError):h.stop_writers(source)

    def test_running_job_lease_prevents_freezing(self):
        source,_=pair()
        with patch.object(h,'compose'),patch.object(h,'container',return_value={'State':{'Running':False}}),\
             patch.object(h,'query',return_value='1'):
            with self.assertRaises(RuntimeError):h.stop_writers(source)

    def test_existing_durable_queue_and_scheduler_volumes_are_reused(self):
        def value(config,service):
            return {'Mounts':[{'Type':'volume','Destination':'/data' if service=='redis' else '/app/run/beat',
                'Name':'accounting-preview_'+('redis_jobs' if service=='redis' else 'scheduler_state')}]}
        with patch.object(h,'container',side_effect=value),patch.object(h.common,'run') as run:
            result=h.queue_storage(pair()[0])
        self.assertEqual(set(result),{'redis','scheduler'});run.assert_not_called()

    def test_new_or_bind_mounted_queue_storage_is_rejected(self):
        for mount in ({'Type':'volume','Name':'unreviewed','Destination':'/data'},
                      {'Type':'bind','Name':'accounting-preview_redis_jobs','Destination':'/data'}):
            with patch.object(h,'container',return_value={'Mounts':[mount]}):
                with self.assertRaises(RuntimeError):h.queue_storage(pair()[0])


class ImageAndRecordContracts(unittest.TestCase):
    def test_missing_previously_verified_image_does_not_trigger_rebuild(self):
        with patch.object(release.image,'inspect',return_value=None),patch.object(release.image,'build') as build:
            with self.assertRaises(RuntimeError):release.cached_image()
        build.assert_not_called()

    def test_wrong_cached_image_label_is_rejected(self):
        built={'image_id':p.IMAGE_ID,'revision':'git:'+p.APP_REVISION,'context':{'digest':p.CONTEXT}}
        with patch.object(release.image,'inspect',return_value={'Config':{'Labels':{'org.opencontainers.image.revision':'0'*40}}}),\
             patch.object(release.image,'reuse_for_verification',return_value=built):
            with self.assertRaises(RuntimeError):release.cached_image()

    def test_report_mutation_is_not_recaptured(self):
        report=synthetic_report()
        with patch.object(p,'REPORT_SHA',p.digest_object(report)):
            p.verified_report(report)
            altered=deepcopy(report);altered['suite']['tests_passed']=964
            with self.assertRaises(RuntimeError):p.verified_report(altered)

    def test_recorded_state_changes_only_its_cr004_marker(self):
        before='before\n<!-- CR004-RESULT -->\nPrepared\n<!-- /CR004-RESULT -->\nafter\n'
        after=p.recorded_state(before)
        self.assertTrue(after.startswith('before\n'));self.assertTrue(after.endswith('\nafter\n'))
        self.assertIn('965 tests',after)

    def test_receipt_binding_cannot_refresh_changed_historical_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);report=synthetic_report()
            for name in p.RETAINED_REPORTS:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(report) if name==p.RECEIPT else '{"fixture":"synthetic history"}')
            with patch.object(p,'REPORT_SHA',p.digest_object(report)),patch('cr004_receipts.verify_binding',return_value={}):
                p.bind_reports(root);before=(root/p.BASELINE).read_bytes()
                (root/p.RETAINED_REPORTS[1]).write_text('{"fixture":"changed synthetic history"}')
                with self.assertRaises(RuntimeError):p.bind_reports(root)
                with self.assertRaises(RuntimeError):p.verify_reports(root)
                self.assertEqual((root/p.BASELINE).read_bytes(),before)

    def test_preview_tracking_preserves_all_requirement_acceptances(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);docs=root/'docs/implementation';docs.mkdir(parents=True)
            (docs/'state.md').write_text('# Implementation state\n\nfixture\n')
            with (docs/'traceability.csv').open('w',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=['acceptance_status']);writer.writeheader()
                writer.writerows({'acceptance_status':'Pending'} for _ in range(85))
            before=(docs/'traceability.csv').read_bytes()
            p.track(root,'Prepared','git:'+'0'*40)
            self.assertEqual((docs/'traceability.csv').read_bytes(),before)


if __name__ == '__main__':
    unittest.main()
