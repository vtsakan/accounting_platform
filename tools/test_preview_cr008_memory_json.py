"""Operator regression contracts for real Compose byte strings and guarded retry."""
from copy import deepcopy
import json
import unittest

import preview_cr008_memory_host as host
import preview_cr008_memory_json_retry as retry
from test_preview_cr008_profile import pair


class ComposeMemoryJSONContracts(unittest.TestCase):
    def test_compose_go_decimal_json_strings_are_valid_exact_limits(self):
        service=json.loads('{"mem_limit":"201326592","memswap_limit":"402653184"}')
        self.assertEqual(host.scheduler_memory_limits(service),
            {'mem_limit':201326592,'memswap_limit':402653184})

    def test_integer_json_limits_are_valid(self):
        service=json.loads('{"mem_limit":201326592,"memswap_limit":402653184}')
        self.assertEqual(host.scheduler_memory_limits(service),service)

    def test_mixed_exact_representations_are_valid(self):
        self.assertEqual(host.scheduler_memory_limits({'mem_limit':'201326592','memswap_limit':402653184}),
            {'mem_limit':201326592,'memswap_limit':402653184})

    def test_old128mib_scheduler_budget_is_rejected(self):
        with self.assertRaises(RuntimeError):
            host.scheduler_memory_limits({'mem_limit':'134217728','memswap_limit':'134217728'})

    def test_correct_ram_with_wrong_swap_limit_is_rejected(self):
        with self.assertRaises(RuntimeError):
            host.scheduler_memory_limits({'mem_limit':'201326592','memswap_limit':'201326592'})

    def test_missing_either_limit_blocks_planning(self):
        for key in ('mem_limit','memswap_limit'):
            with self.subTest(key=key):
                service={'mem_limit':'201326592','memswap_limit':'402653184'};del service[key]
                with self.assertRaises(RuntimeError):host.scheduler_memory_limits(service)

    def test_boolean_and_fractional_numbers_cannot_impersonate_limits(self):
        for value in (True,False,201326592.0,201326592.9,None):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    host.scheduler_memory_limits({'mem_limit':value,'memswap_limit':402653184})

    def test_noncanonical_unit_exponent_or_private_text_is_rejected(self):
        for value in ('192m','2.01326592e8','201326592.0',' 201326592','２０１３２６５９２','9'*100,'synthetic private text'):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    host.scheduler_memory_limits({'mem_limit':value,'memswap_limit':'402653184'})

    def test_missing_or_malformed_service_is_rejected(self):
        for service in (None,[],192,True,'synthetic service'):
            with self.subTest(service=service):
                with self.assertRaises(RuntimeError):host.scheduler_memory_limits(service)

    def test_zero_negative_or_unlimited_limits_are_rejected(self):
        for value in (0,-1,'0','-1'):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    host.scheduler_memory_limits({'mem_limit':value,'memswap_limit':'402653184'})


class UnstartedMemoryRetryContracts(unittest.TestCase):
    def test_retarget_preserves_every_field_except_deployment_revision(self):
        source,target=pair();config={'profile':retry.release.policy.PROFILE,'source':source,'target':target,
            'failed_attempt_sha256':'sha256:'+'0'*64,'legacy_local_config_sha256':'sha256:'+'1'*64}
        original=deepcopy(config);result=retry.corrected_config(config,'3'*40)
        expected=deepcopy(config);expected['target']['deployment_commit']='3'*40
        self.assertEqual(result,expected);self.assertEqual(config,original)

    def test_missing_or_partial_correction_revision_is_rejected(self):
        source,target=pair();config={'profile':retry.release.policy.PROFILE,'source':source,'target':target}
        for revision in ('',None,'3'*7,'git:'+'3'*40):
            with self.subTest(revision=revision):
                with self.assertRaises(RuntimeError):retry.corrected_config(config,revision)

    def test_only_exact_guarded_unstarted_plan_shape_is_accepted(self):
        retry.planned_only({'status':'Planned','schema_before':36,'schema_after':36,
            'same_current_database':True,'database_cloned_or_migrated':False,
            'services_restarted':False,'plan_sha256':'sha256:'+'0'*64})

    def test_started_partial_or_wrong_database_plan_cannot_retarget(self):
        valid={'status':'Planned','schema_before':36,'schema_after':36,
            'same_current_database':True,'database_cloned_or_migrated':False,
            'services_restarted':False,'plan_sha256':'sha256:'+'0'*64}
        for key,value in (('status','profile_verified'),('schema_before',30),('schema_after',36.0),
                ('same_current_database',1),('database_cloned_or_migrated',True),
                ('services_restarted',True),('plan_sha256','synthetic unbound plan')):
            with self.subTest(key=key):
                candidate={**valid,key:value}
                with self.assertRaises(RuntimeError):retry.planned_only(candidate)


if __name__=='__main__':unittest.main()
