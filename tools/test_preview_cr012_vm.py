"""Operator deployment contracts; no application, provider, Docker or database calls."""
from copy import deepcopy
import json
import unittest

import preview_cr012_policy as p
import preview_cr012_host as host
import preview_cr011_host as old_host
import preview_cr012_release as release
import preview_cr012_migrate as migrate
import preview_cr011_release as old_release
from test_preview_cr008_profile import pair,proofs


def transition_pair():
    source,_=pair();source['deployment_commit']=p.VM_DEPLOYMENT;source['db_name']='accounting_cr011_000000000001'
    source['published']={'commit':p.OLD_APP,'image_id':p.OLD_IMAGE_ID,'image':p.OLD_IMAGE,'context_digest':p.OLD_CONTEXT}
    target=deepcopy(source);target['db_name']='accounting_cr012_000000000002';target['deployment_commit']='2'*40
    target['published']={'commit':p.APP_REVISION,'image_id':p.IMAGE_ID,'context_digest':p.CONTEXT,
        'delivery_evidence':p.report_sha(),'image':'europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:'+'3'*64}
    return source,target


def recovery_pair():
    state,restored=proofs();restored['before']['tables_checked']=64;restored['after']['tables_checked']=65
    state['migration']={'source_migrations':40,'target_migrations':42,'old_tables_checked':64,
        'new_business_tables_empty':True,'restricted_role_migrations':True,
        'original_columns_rows_passwords_mfa_sessions_preserved':True,'original_database_migrated':False}
    return state,restored


class CloneIdentityContracts(unittest.TestCase):
    def test_exact_current40_to_new42_clone_is_accepted(self):p.transition(*transition_pair())

    def test_same_database_cannot_be_migration_target(self):
        source,target=transition_pair();target['db_name']=source['db_name']
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_old_retained_database_cannot_be_source(self):
        source,target=transition_pair();source['db_name']='accounting_cr005_000000000001'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_another_source_deployment_is_rejected(self):
        source,target=transition_pair();source['deployment_commit']='4'*40
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_another_source_image_is_rejected(self):
        source,target=transition_pair();source['published']['image_id']='sha256:'+'5'*64
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_previous_source_context_is_rejected(self):
        source,target=transition_pair();source['published']['context_digest']=p.CONTEXT
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_different_target_image_is_rejected(self):
        source,target=transition_pair();target['published']['image_id']=p.OLD_IMAGE_ID
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_different_target_source_is_rejected(self):
        source,target=transition_pair();target['published']['commit']=p.OLD_APP
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_missing_target_report_binding_is_rejected(self):
        source,target=transition_pair();target['published']['delivery_evidence']='sha256:'+'6'*64
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_foreign_registry_is_rejected(self):
        source,target=transition_pair();target['published']['image']='registry.example.invalid/web@sha256:'+'3'*64
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_cloud_resize_or_identity_change_is_rejected(self):
        source,target=transition_pair();target['gcp']['vm_name']='another-preview'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_secret_version_change_is_rejected(self):
        source,target=transition_pair();target['gcp']['secret_versions']['app']=2
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_role_change_is_rejected(self):
        source,target=transition_pair();target['db_user']='other_role'
        with self.assertRaises(RuntimeError):p.transition(source,target)

    def test_truncated_deployment_commit_is_rejected(self):
        source,target=transition_pair();target['deployment_commit']='abcdef0'
        with self.assertRaises(RuntimeError):p.transition(source,target)


class RecoveryContracts(unittest.TestCase):
    def test_both64_and65_table_proofs_are_accepted(self):p.ready(*recovery_pair())

    def test_previous64_table_target_proof_cannot_approve42(self):
        state,restored=recovery_pair();restored['after']['tables_checked']=64
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_wrong_backup_generation_is_rejected(self):
        state,restored=recovery_pair();restored['before']['receipt']={'synthetic':'different generation'}
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_independent_recovery_key_is_required(self):
        state,restored=recovery_pair();restored['after']['separate_recovery_key_used']=False
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_plaintext_cleanup_is_required(self):
        state,restored=recovery_pair();restored['after']['plaintext_removed']=False
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_preview_restore_over_live_database_is_rejected(self):
        state,restored=recovery_pair();restored['after']['preview_database_modified']=True
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_source_migration_is_rejected(self):
        state,restored=recovery_pair();state['migration']['original_database_migrated']=True
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_superuser_migration_proof_is_rejected(self):
        state,restored=recovery_pair();state['migration']['restricted_role_migrations']=False
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_unreviewed_business_writes_during_migration_are_rejected(self):
        state,restored=recovery_pair();state['migration']['new_business_tables_empty']=False
        with self.assertRaises(RuntimeError):p.ready(state,restored)

    def test_prepublic_abort_guard_is_allowed(self):p.before_public({'public_cutover_started':False})

    def test_old_database_reselection_after_public_writes_is_forbidden(self):
        with self.assertRaises(RuntimeError):p.before_public({'public_cutover_started':True})

    def test_completed_proof_validation_does_not_rewrite_state(self):
        state,restored=recovery_pair();state.update(phase='deployed_and_restored',public_cutover_started=True)
        before=deepcopy(state);p.recovery_proofs(state,restored);self.assertEqual(state,before)


class RestrictedTargetContracts(unittest.TestCase):
    def test_only_the_new_restricted_clone_can_be_migrated(self):
        migrate.clone_guard('accounting_cr011_000000000001','accounting_cr012_000000000002',
            'accounting_cr012_000000000002','db','postgresql',170011)

    def test_current40_database_is_never_a_migration_target(self):
        with self.assertRaises(RuntimeError):migrate.clone_guard('accounting_cr011_000000000001',
            'accounting_cr011_000000000001','accounting_cr011_000000000001','db','postgresql',170011)

    def test_incorrect_database_environment_is_rejected(self):
        with self.assertRaises(RuntimeError):migrate.clone_guard('accounting_cr011_000000000001',
            'accounting_cr012_000000000002','other','db','postgresql',170011)

    def test_nonprivate_database_host_is_rejected(self):
        with self.assertRaises(RuntimeError):migrate.clone_guard('accounting_cr011_000000000001',
            'accounting_cr012_000000000002','accounting_cr012_000000000002','external','postgresql',170011)


class RetainedDeploymentContracts(unittest.TestCase):
    def test_old_journal_is_retained_in_its_namespace(self):
        self.assertEqual(host.LEGACY_STATE,old_host.STATE)
        self.assertTrue({host.STATE,host.PLAN,host.HOLD}.isdisjoint({old_host.STATE,old_host.PLAN,old_host.HOLD}))

    def test_local_configuration_and_report_are_new_paths(self):
        self.assertNotEqual(release.CONFIG,old_release.CONFIG);self.assertNotEqual(release.PUBLIC,old_release.PUBLIC)

    def test_compose_decimal_memory_strings_are_accepted(self):
        self.assertEqual(host.scheduler_memory_limits({'mem_limit':'201326592','memswap_limit':'402653184'}),
            {'mem_limit':201326592,'memswap_limit':402653184})

    def test_old128mib_scheduler_is_rejected(self):
        with self.assertRaises(RuntimeError):host.scheduler_memory_limits({'mem_limit':134217728,'memswap_limit':134217728})

    def test_unknown_provider_text_is_private(self):
        detail='synthetic private provider text';self.assertNotIn(detail,json.dumps(host.public_failure(RuntimeError(detail))))

    def test_exactly_five_preceding_journals_are_retained(self):
        self.assertEqual(len(p.PRIOR_STATES),5);self.assertIn(old_host.STATE,p.PRIOR_STATES)


class ActualReportContracts(unittest.TestCase):
    def report(self):
        from dev import ROOT
        return json.loads((ROOT/p.RECEIPT).read_text())

    def test_genuine_full_native_result_is_accepted(self):p.operator_report(self.report())

    def test_partial_delivery_is_rejected(self):
        value=self.report();value['status']='Prepared'
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_old1307_suite_is_rejected(self):
        value=self.report();value['suite']['tests_run']=value['suite']['tests_passed']=1307
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_missing_selected_charge_recovery_is_rejected(self):
        value=self.report();value['private_files']['cash_charge_selection_recovered']=False
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_overpayment_credit_proof_is_required(self):
        value=self.report();value['private_files']['charge_workflow']['excess_kept_as_credit']=False
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_only_selected_charge_proof_is_required(self):
        value=self.report();value['private_files']['charge_workflow']['only_selected_charge_settled']=False
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_missing_worker_revocation_proof_is_rejected(self):
        value=self.report();value['revocation_blocks_execution']=False
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_unreviewed_secret_findings_are_rejected(self):
        value=self.report();value['secret_scan']['unreviewed_findings']=1
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_original_delivery_binding_is_required(self):
        value=self.report();value['retained_successful_delivery']['canonical_report_sha256']='sha256:'+'0'*64
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_changed_image_revision_is_rejected(self):
        value=self.report();value['image']['revision']='git:'+'0'*40
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_full_business_acceptance_is_not_inferred(self):
        value=self.report();value['full_requirement_acceptances_pending']=0
        with self.assertRaises(RuntimeError):p.operator_report(value)

    def test_a_restore_of_only64_tables_is_rejected(self):
        value=self.report();value['private_files']['all_public_tables_restored']=64
        with self.assertRaises(RuntimeError):p.operator_report(value)


if __name__=='__main__':unittest.main()
