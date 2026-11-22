"""Operator-only same-current-database profile contracts; no provider/app calls."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import preview_cr008_profile_policy as p
import preview_cr008_profile_release as release


def pair():
    source={'hostname':p.prior.HOSTNAME,'gcp':{**p.prior.BOOTSTRAP['gcp'],
        'data_uuid':'22415b2c-1e1b-4e39-9ce5-5fb0c19dd663','secret_versions':{'app':1,'database':1}},
        'db_name':'accounting_cr008_000000000001','db_user':'retained_app',
        'published':{'commit':p.prior.APP_REVISION,'image':p.VM_IMAGE,'image_id':p.prior.IMAGE_ID,
            'context_digest':p.prior.CONTEXT},'deployment_commit':p.VM_DEPLOYMENT}
    target=deepcopy(source);target['deployment_commit']='1'*40
    return source,target


def proofs():
    state={'phase':'awaiting_off_vm_restore','public_cutover_started':False,
        'before_backup':{'synthetic':'before'},'after_backup':{'synthetic':'after'}}
    restored={name:{'status':'Restored','receipt':state[name+'_backup'],'tables_checked':61,
        'all_public_tables_match':True,'separate_recovery_key_used':True,'plaintext_removed':True,
        'recovery_container_removed':True,'preview_database_modified':False} for name in ('before','after')}
    return state,restored


def tracking_root(directory,content):
    root=Path(directory);docs=root/'docs/implementation';docs.mkdir(parents=True)
    (docs/'state.md').write_bytes(content)
    with (docs/'traceability.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['acceptance_status']);writer.writeheader()
        writer.writerows({'acceptance_status':'Pending'} for _ in range(85))
    return root,docs/'state.md'


class CurrentDatabaseContracts(unittest.TestCase):
    def test_same_current_database_and_published_image_are_accepted(self):p.transition(*pair())

    def test_retained_old_schema30_database_cannot_be_reactivated(self):
        source,target=pair();target['db_name']='accounting_cr005_000000000001'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_a_new_clone_is_not_a_profile_change(self):
        source,target=pair();target['db_name']='accounting_cr008_000000000002'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_pinned_signing_material_cannot_change(self):
        source,target=pair();target['gcp']['secret_versions']['app']=2
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_rebuilt_or_different_published_image_is_rejected(self):
        source,target=pair();target['published']['image']='unreviewed-image'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_an_unobserved_current_application_is_rejected(self):
        source,target=pair();source['published']['image']=target['published']['image']='other-current-image'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_completed_legacy_journal_on_current_database_is_accepted(self):
        source,_=pair();p.completed_journal({'phase':'deployed_and_restored','public_cutover_started':True,
            'target':source,'migration':{'target_migrations':36},'runtime':{'attachment_uploads_enabled':False}},source)

    def test_unfinished_previous_cutover_cannot_be_reused(self):
        source,_=pair()
        with self.assertRaises(RuntimeError):p.completed_journal({'phase':'preparing','public_cutover_started':False},source)

    def test_previous_journal_for_another_database_is_rejected(self):
        source,_=pair();wrong=deepcopy(source);wrong['db_name']='another_database'
        with self.assertRaises(RuntimeError):p.completed_journal({'phase':'deployed_and_restored','public_cutover_started':True,
            'target':wrong,'migration':{'target_migrations':36},'runtime':{'attachment_uploads_enabled':False}},source)

    def test_configuration_rollback_keeps_the_current_database(self):
        source,target=pair();self.assertEqual(p.rollback_database(source,target),source['db_name'])

    def test_previous_private_config_has_a_separate_namespace(self):
        self.assertNotEqual(release.CONFIG,release.previous.CONFIG)
        self.assertEqual(release.CONFIG.name,'vm-cr008-4gb-profile.json')


class RecoveryContracts(unittest.TestCase):
    def test_both_current61_table_restores_are_required(self):
        state,restored=proofs();p.ready(state,restored);del restored['before']
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_old53_table_restore_cannot_approve_this_profile(self):
        state,restored=proofs();restored['before']['tables_checked']=53
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_retained_plaintext_cannot_approve_activation(self):
        state,restored=proofs();restored['after']['plaintext_removed']=False
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_another_backup_generation_is_rejected(self):
        state,restored=proofs();restored['before']['receipt']={'synthetic':'another generation'}
        with self.assertRaises(RuntimeError):p.ready(state,restored)


class TrackingAndBindingContracts(unittest.TestCase):
    def test_unrelated_native_state_and_crlf_bytes_are_preserved(self):
        original='# Arbitrary native state\r\nΠραγματικό παλιό ιστορικό\r\n'.encode()
        with tempfile.TemporaryDirectory() as d:
            root,path=tracking_root(d,original);p.track(root,'Prepared')
            self.assertTrue(path.read_bytes().startswith(original))

    def test_only_own_block_is_replaced(self):
        prefix=b'actual previous state\n';suffix=b'\nretained original result\n'
        original=prefix+b'<!-- CR008-4GB-PROFILE -->\nold own block\n<!-- /CR008-4GB-PROFILE -->'+suffix
        with tempfile.TemporaryDirectory() as d:
            root,path=tracking_root(d,original);p.track(root,'Verified');current=path.read_bytes()
            self.assertTrue(current.startswith(prefix));self.assertTrue(current.endswith(suffix))

    def test_duplicate_markers_are_rejected_without_writes(self):
        original=b'<!-- CR008-4GB-PROFILE --><!-- /CR008-4GB-PROFILE -->'*2
        with tempfile.TemporaryDirectory() as d:
            root,path=tracking_root(d,original)
            with self.assertRaises(RuntimeError):p.track(root,'Prepared')
            self.assertEqual(path.read_bytes(),original)

    def test_missing_end_marker_is_rejected_without_writes(self):
        original=b'unchanged\n<!-- CR008-4GB-PROFILE -->'
        with tempfile.TemporaryDirectory() as d:
            root,path=tracking_root(d,original)
            with self.assertRaises(RuntimeError):p.track(root,'Prepared')
            self.assertEqual(path.read_bytes(),original)

    def test_exclusive_binding_is_not_refreshed(self):
        # Explicit synthetic guard fixture; no actual report or native Git history.
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/p.BASELINE).parent.mkdir(parents=True)
            original={'scope':p.PROFILE,'files':{'synthetic-only':'sha256:'+'0'*64}}
            with patch.object(p,'native_reports',return_value=original):p.bind(root)
            before=(root/p.BASELINE).read_bytes()
            changed=deepcopy(original);changed['files']['synthetic-only']='sha256:'+'1'*64
            with patch.object(p,'native_reports',return_value=changed):
                with self.assertRaises(RuntimeError):p.bind(root)
            self.assertEqual((root/p.BASELINE).read_bytes(),before)

    def test_all18_actual_report_paths_are_distinct(self):
        self.assertEqual(len(set(p.REPORTS)),18)


if __name__=='__main__':unittest.main()
