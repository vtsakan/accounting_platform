"""Native operator contracts for the same-database CR012-LABEL image transition."""
from copy import deepcopy
import json
import unittest

import preview_cr012_label_policy as p
import preview_cr012_label_host as host
import preview_cr012_label_release as release
import cr012_label_transfer as correction
import preview_cr012_host as previous_host
import preview_cr012_release as previous_release
from test_preview_cr008_profile import pair,proofs


def transition_pair():
    source,_=pair();source['deployment_commit']=p.VM_DEPLOYMENT;source['db_name']='accounting_cr012_000000000001'
    source['published']={'commit':p.OLD_APP,'image':p.OLD_IMAGE,'image_id':p.OLD_IMAGE_ID,'context_digest':p.OLD_CONTEXT}
    target=deepcopy(source);target['deployment_commit']='2'*40
    target['published']={'commit':p.app_revision(),'image_id':p.image_id(),
        'context_digest':p.CONTEXT,'delivery_evidence':p.report_sha(),
        'image':'europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:'+'3'*64}
    return source,target


class CurrentDatabaseImageContracts(unittest.TestCase):
    def test_exact_same_database_new_verified_image_is_accepted(self):p.transition(*transition_pair())

    def test_new_database_clone_is_rejected(self):
        source,target=transition_pair();target['db_name']='accounting_cr008_000000000099'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_old_schema30_database_cannot_be_reselected(self):
        source,target=transition_pair();source['db_name']=target['db_name']='accounting_cr005_000000000001'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_database_role_cannot_change(self):
        source,target=transition_pair();target['db_user']='synthetic_other_role'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_pinned_secret_versions_cannot_change(self):
        source,target=transition_pair();target['gcp']['secret_versions']['app']=2
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_hostname_cannot_change(self):
        source,target=transition_pair();target['hostname']='synthetic.duckdns.org'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_selected_vm_zone_cannot_change(self):
        source,target=transition_pair();target['gcp']['zone']='europe-west1-c'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_another_source_deployment_is_rejected(self):
        source,target=transition_pair();source['deployment_commit']='4'*40
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_former_uploads_disabled_deployment_cannot_be_source(self):
        source,target=transition_pair();source['deployment_commit']=p.previous.VM_DEPLOYMENT
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_target_with_old_application_context_is_rejected(self):
        source,target=transition_pair();target['published']['context_digest']=p.OLD_CONTEXT
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_unverified_target_application_revision_is_rejected(self):
        source,target=transition_pair();target['published']['commit']='5'*40
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_unverified_target_image_id_is_rejected(self):
        source,target=transition_pair();target['published']['image_id']='sha256:'+'6'*64
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_another_registry_is_rejected(self):
        source,target=transition_pair();target['published']['image']='registry.example.invalid/web@sha256:'+'3'*64
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_missing_exact_operator_receipt_binding_is_rejected(self):
        source,target=transition_pair();target['published'].pop('delivery_evidence')
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_truncated_deployment_revision_is_rejected(self):
        source,target=transition_pair();target['deployment_commit']='abcdef0'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_configuration_rollback_keeps_the_current_database(self):
        source,target=transition_pair();self.assertEqual(p.rollback_database(source,target),source['db_name'])


class RecoveryAndIsolationContracts(unittest.TestCase):
    def test_both_fresh65_table_proofs_are_accepted(self):
        state,restored=proofs();restored['before']['tables_checked']=65;restored['after']['tables_checked']=65;p.ready(state,restored)

    def test_previous64_table_proof_cannot_approve_current_database(self):
        state,restored=proofs();restored['before']['tables_checked']=65;restored['after']['tables_checked']=65;restored['before']['tables_checked']=64
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_another_backup_generation_is_rejected(self):
        state,restored=proofs();restored['before']['tables_checked']=65;restored['after']['tables_checked']=65;restored['after']['receipt']={'synthetic':'different generation'}
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_recovery_requires_the_separate_key(self):
        state,restored=proofs();restored['before']['tables_checked']=65;restored['after']['tables_checked']=65;restored['before']['separate_recovery_key_used']=False
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_new_vm_state_plan_and_hold_do_not_reuse_previous_attempt(self):
        self.assertTrue({host.STATE,host.PLAN,host.HOLD}.isdisjoint(
            {previous_host.STATE,previous_host.PLAN,previous_host.HOLD}))
        self.assertEqual(host.LEGACY_STATE,previous_host.STATE)

    def test_new_local_config_result_and_report_are_separate(self):
        self.assertNotEqual(release.CONFIG,previous_release.CONFIG)
        self.assertNotEqual(release.RESULT,previous_release.RESULT)
        self.assertNotEqual(release.PUBLIC,previous_release.PUBLIC)

    def test_real_compose_decimal_byte_strings_are_accepted(self):
        value=json.loads('{"mem_limit":"201326592","memswap_limit":"402653184"}')
        self.assertEqual(host.scheduler_memory_limits(value),{'mem_limit':201326592,'memswap_limit':402653184})

    def test_old128mib_scheduler_memory_is_rejected(self):
        with self.assertRaises(RuntimeError):host.scheduler_memory_limits({'mem_limit':'134217728','memswap_limit':'134217728'})

    def test_private_provider_error_text_cannot_be_public(self):
        detail='synthetic private provider text'
        self.assertNotIn(detail,json.dumps(host.public_failure(RuntimeError(detail))))


class EvidenceTransferRetryContracts(unittest.TestCase):
    def pending(self):
        source,target=transition_pair();target['deployment_commit']=correction.FAILED_COMMIT
        return {'profile':p.PROFILE,'source':source,'target':target,
            'deployment_manifest_sha256':correction.OLD_MANIFEST,
            'prior_journal_sha256':{'synthetic_retained_journal':'sha256:'+'8'*64}}

    def unstarted(self):
        return {'status':'Unstarted','state_exists':False,'hold_active':False,
            'plan_exists':False,'installed_binding':'source'}

    def plan(self):
        return {'status':'Planned','schema_before':42,'schema_after':42,'same_current_database':True,
            'database_cloned_or_migrated':False,'services_restarted':False,'plan_sha256':'sha256:'+'9'*64}

    def test_entire_native_evidence_closure_includes_previous_binding(self):
        names=correction.evidence_names(p.identity())
        self.assertEqual(len(names),len(set(names)));self.assertEqual(len(names),38)
        self.assertIn(p.previous.BASELINE,names);self.assertIn(p.RECEIPT,names);self.assertIn(p.BASELINE,names)

    def test_incomplete_old_deployment_binding_cannot_be_transferred(self):
        binding=deepcopy(p.identity());binding['files'].pop(p.previous.BASELINE)
        binding['files']['docs/implementation/evidence/synthetic-unrelated.json']='sha256:'+'9'*64
        with self.assertRaises(RuntimeError):correction.evidence_names(binding)

    def test_retarget_changes_only_pending_revision_and_manifest(self):
        before=self.pending();original=deepcopy(before);expected=deepcopy(before)
        expected['target']['deployment_commit']='7'*40;expected['deployment_manifest_sha256']='sha256:'+'9'*64
        self.assertEqual(correction.candidate(before,'7'*40,'sha256:'+'9'*64),expected)
        self.assertEqual(before,original)

    def test_retarget_rejects_another_prepared_manifest(self):
        value=self.pending();value['deployment_manifest_sha256']='sha256:'+'6'*64
        with self.assertRaises(RuntimeError):correction.candidate(value,'7'*40,'sha256:'+'9'*64)

    def test_retarget_rejects_another_pending_deployment(self):
        value=self.pending();value['target']['deployment_commit']='6'*40
        with self.assertRaises(RuntimeError):correction.candidate(value,'7'*40,'sha256:'+'9'*64)

    def test_retarget_rejects_a_journal_hold_plan_or_changed_live_source(self):
        for key,value in (('state_exists',True),('hold_active',True),('plan_exists',True),('installed_binding','other')):
            with self.subTest(key=key):
                status=self.unstarted();status[key]=value
                with self.assertRaises(RuntimeError):correction.unstarted(status)

    def test_unstarted_same_database_plan_is_accepted(self):
        correction.guarded_plan(self.unstarted(),self.plan())

    def test_plan_cannot_restart_services_or_change_the_database(self):
        for key,value in (('schema_before',40),('schema_after',43),('same_current_database',False),
                ('database_cloned_or_migrated',True),('services_restarted',True),('plan_sha256','invalid')):
            with self.subTest(key=key):
                plan=self.plan();plan[key]=value
                with self.assertRaises(RuntimeError):correction.guarded_plan(self.unstarted(),plan)


if __name__=='__main__':unittest.main()
