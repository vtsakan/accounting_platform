"""Native operator contracts; synthetic dictionaries only, no cloud/app calls."""
from copy import deepcopy
import json
import unittest

import preview_cr008_memory_policy as policy
import preview_cr008_memory_host as host
import preview_cr008_memory_release as release
import preview_cr008_memory_runtime as runtime
import preview_cr008_profile_host as previous_host
import preview_cr008_profile_release as previous_release
from test_preview_cr008_profile import pair,proofs


def failed():
    source,target=pair();target['deployment_commit']=policy.FAILED_DEPLOYMENT
    value,restored=proofs()
    value.update(profile=policy.previous_profile.PROFILE,source=source,target=target,
        phase='configuration_rolled_back_current_database_retained',public_cutover_started=True,
        off_vm_restored=restored)
    return value,source


class PredecessorContracts(unittest.TestCase):
    def test_exact_retained_rollback_with_actual_proof_shape_is_accepted(self):
        value,source=failed();self.assertIs(policy.failed_attempt(value,source),value)

    def test_unfinished_rollback_cannot_start_a_retry(self):
        value,source=failed();value['phase']='needs_profile_recovery'
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)

    def test_unobserved_failed_revision_is_rejected(self):
        value,source=failed();value['target']['deployment_commit']='2'*40
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)

    def test_another_source_database_is_rejected(self):
        value,source=failed();different=deepcopy(source);different['db_name']='accounting_cr008_000000000099'
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,different)

    def test_old_schema30_database_cannot_be_reactivated(self):
        value,source=failed();value['target']['db_name']='accounting_cr005_000000000099'
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)

    def test_changed_published_image_is_rejected(self):
        value,source=failed();value['target']['published']['image']='synthetic unreviewed image'
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)

    def test_missing_independent_recovery_key_proof_is_rejected(self):
        value,source=failed();value['off_vm_restored']['before']['separate_recovery_key_used']=False
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)

    def test_different_encrypted_backup_receipt_is_rejected(self):
        value,source=failed();value['off_vm_restored']['after']['receipt']={'synthetic':'other generation'}
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)

    def test_predecessor_requires_both_restores(self):
        value,source=failed();del value['off_vm_restored']['before']
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)

    def test_previous53_table_restore_cannot_approve_current_database(self):
        value,source=failed();value['off_vm_restored']['before']['tables_checked']=53
        with self.assertRaises(RuntimeError):policy.failed_attempt(value,source)


class MemoryEvidenceContracts(unittest.TestCase):
    def test_zero_observed_oom_counters_are_accepted(self):
        runtime.clean_oom_counters({'oom':0,'oom_kill':0,'oom_group_kill':0})

    def test_killed_health_probe_blocks_acceptance_even_without_pid1_death(self):
        with self.assertRaises(RuntimeError):runtime.clean_oom_counters({'oom':1,'oom_kill':1})

    def test_oom_pressure_blocks_acceptance_even_without_a_kill(self):
        with self.assertRaises(RuntimeError):runtime.clean_oom_counters({'oom':1,'oom_kill':0})

    def test_missing_memory_evidence_is_rejected(self):
        with self.assertRaises(RuntimeError):runtime.clean_oom_counters({})

    def test_boolean_cannot_impersonate_observed_zero_counter(self):
        with self.assertRaises(RuntimeError):runtime.clean_oom_counters({'oom':False,'oom_kill':0})

    def test_group_oom_kill_blocks_acceptance(self):
        with self.assertRaises(RuntimeError):runtime.clean_oom_counters({'oom':0,'oom_kill':0,'oom_group_kill':1})


class IsolationAndDiagnosticContracts(unittest.TestCase):
    def test_failed_journal_plan_and_hold_namespaces_are_not_reused(self):
        old={previous_host.STATE,previous_host.PLAN,previous_host.HOLD}
        new={host.STATE,host.PLAN,host.HOLD}
        self.assertTrue(old.isdisjoint(new))
        self.assertEqual(policy.FAILED_STATE,previous_host.STATE)

    def test_local_configuration_and_result_paths_are_separate(self):
        self.assertNotEqual(release.CONFIG,previous_release.CONFIG)
        self.assertNotEqual(release.RESULT,previous_release.RESULT)
        self.assertNotEqual(release.PUBLIC,previous_release.PUBLIC)

    def test_unreviewed_provider_text_is_not_a_public_failure_message(self):
        detail='synthetic private provider detail'
        self.assertNotIn(detail,json.dumps(host.public_failure(RuntimeError(detail))))

    def test_specific_oom_service_can_be_reported_without_private_output(self):
        message='A new service cgroup recorded an OOM event: scheduler'
        self.assertEqual(host.public_failure(RuntimeError(message))['reason'],message)


if __name__=='__main__':unittest.main()
