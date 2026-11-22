"""Operator-only contracts for retargeting the unstarted duration correction."""
from copy import deepcopy
import unittest

import preview_cr008_profile_retry as retry
from test_preview_cr008_profile import pair


def configuration():
    source,target=pair()
    return {'profile':retry.policy.PROFILE,'source':source,'target':target,
        'legacy_local_config_sha256':'synthetic retained binding'}


def plan():
    return {'status':'Planned','schema_before':36,'schema_after':36,
        'same_current_database':True,'database_cloned_or_migrated':False,
        'services_restarted':False,'plan_sha256':'sha256:'+'0'*64}


class RetryContracts(unittest.TestCase):
    def test_pending_config_is_not_mutated_in_place(self):
        value=configuration();before=deepcopy(value)
        result=retry.corrected_config(value,'2'*40)
        self.assertEqual(value,before)
        self.assertEqual(result['target']['deployment_commit'],'2'*40)
        result['target']['deployment_commit']=before['target']['deployment_commit']
        self.assertEqual(result,before)

    def test_another_database_cannot_be_retargeted(self):
        value=configuration();value['target']['db_name']='accounting_cr008_000000000099'
        with self.assertRaises(RuntimeError):retry.corrected_config(value,'2'*40)

    def test_changed_signing_material_cannot_be_retargeted(self):
        value=configuration();value['target']['gcp']['secret_versions']['app']=2
        with self.assertRaises(RuntimeError):retry.corrected_config(value,'2'*40)

    def test_another_image_cannot_be_retargeted(self):
        value=configuration();value['target']['published']['image']='synthetic unreviewed image'
        with self.assertRaises(RuntimeError):retry.corrected_config(value,'2'*40)

    def test_started_or_failed_plan_cannot_authorise_retarget(self):
        value=plan();value['status']='Stopped'
        with self.assertRaises(RuntimeError):retry.planned_only(value)

    def test_schema_change_cannot_authorise_retarget(self):
        value=plan();value['schema_after']=37
        with self.assertRaises(RuntimeError):retry.planned_only(value)

    def test_service_restart_cannot_authorise_retarget(self):
        value=plan();value['services_restarted']=True
        with self.assertRaises(RuntimeError):retry.planned_only(value)

    def test_database_clone_cannot_authorise_retarget(self):
        value=plan();value['database_cloned_or_migrated']=True
        with self.assertRaises(RuntimeError):retry.planned_only(value)


if __name__=='__main__':unittest.main()
