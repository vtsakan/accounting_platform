"""Operator-run stdlib release guards; no Docker, SSH, cloud or DB execution."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import vm_material_common as policy
import vm_material_host as vm


def configurations():
    source = {'hostname': policy.HOSTNAME, 'gcp': deepcopy(policy.BOOTSTRAP['gcp']),
              'db_name': 'accounting_s24_retained', 'db_user': 'accounting_app',
              'published': {'context_digest': policy.PREVIOUS_CONTEXT}, 'deployment_commit': 'a' * 40}
    source['gcp']['secret_versions'] = {'django': 1, 'postgres': 1}
    target = deepcopy(source)
    target['published'] = {'context_digest': policy.CONTEXT}
    target['deployment_commit'] = 'b' * 40
    return source, target


def proof_fixture():
    suite = {'tests_run': 661, 'tests_passed': 661, 'known_failures_reproduced': 0, 'unexpected_failures': 0,
             'unexpected_errors': 0, 'unexpected_successes': 0, 'skips': 0}
    cases = [{'case_id': str(number), 'outcome': 'passed'} for number in range(36)]
    proof = {'step': 'S24A', 'status': 'Verified', 'mode': 'operator-docker-production-image',
             'suite': suite, 'financial_cases': cases, 'source_commit': 'git:' + 'a' * 40,
             'production_image_id': 'sha256:' + 'b' * 64, 'application_context_digest': policy.CONTEXT}
    delivery = {'step': 'delivery', 'status': 'Verified', 'mode': 'docker-production-image', 'docker_execution_this_step': True,
                'production_image_built_verified': True, 'suite': {**suite, 'cases': deepcopy(cases)},
                'image': {'revision': proof['source_commit'], 'image_id': proof['production_image_id'],
                          'context': {'digest': policy.CONTEXT}},
                'secret_scan': {'unreviewed_findings': 0}, 'compiled_catalog_in_sync': True,
                'dependency_locks_reproduced': True, 'gunicorn_http_verified': True,
                'static_export_from_same_image_verified': True}
    return proof, delivery


class ReleaseContracts(unittest.TestCase):
    def test_image_and_operator_commit_may_change_with_identical_database(self):
        policy.same_database(*configurations())

    def test_different_database_is_rejected(self):
        source, target = configurations(); target['db_name'] = 'different_database'
        with self.assertRaisesRegex(ValueError, 'ui_database_or_identity_change'): policy.same_database(source, target)

    def test_signing_version_rotation_is_rejected(self):
        source, target = configurations(); target['gcp']['secret_versions']['django'] = 2
        with self.assertRaisesRegex(ValueError, 'ui_database_or_identity_change'): policy.same_database(source, target)

    def test_another_vm_even_when_source_and_target_agree_is_rejected(self):
        source, target = configurations()
        for value in (source, target): value['gcp']['vm_name'] = 'different-vm'
        with self.assertRaisesRegex(ValueError, 'ui_wrong_target'): policy.same_database(source, target)

    def test_completed_proof_can_be_reused_without_rebuilding_for_operator_files(self):
        policy.production_proof(*proof_fixture(), policy.CONTEXT)

    def test_incomplete_suite_is_rejected(self):
        proof, delivery = proof_fixture(); delivery['suite']['tests_passed'] = 660
        with self.assertRaisesRegex(ValueError, 'ui_incomplete_production_proof'):
            policy.production_proof(proof, delivery, policy.CONTEXT)

    def test_unexpected_financial_case_is_rejected(self):
        proof, delivery = proof_fixture(); delivery['suite']['cases'][0]['outcome'] = 'skipped'
        with self.assertRaisesRegex(ValueError, 'ui_incomplete_production_proof'):
            policy.production_proof(proof, delivery, policy.CONTEXT)

    def test_wrong_tested_image_is_rejected(self):
        proof, delivery = proof_fixture(); delivery['image']['image_id'] = 'sha256:' + 'c' * 64
        with self.assertRaisesRegex(ValueError, 'ui_receipt_binding_mismatch'):
            policy.production_proof(proof, delivery, policy.CONTEXT)

    def test_unreviewed_findings_are_rejected(self):
        proof, delivery = proof_fixture(); delivery['secret_scan']['unreviewed_findings'] = 1
        with self.assertRaisesRegex(ValueError, 'ui_incomplete_production_proof'):
            policy.production_proof(proof, delivery, policy.CONTEXT)

    def test_asset_path_cannot_escape_static_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'static'; root.mkdir()
            (root.parent / 'outside.txt').write_text('outside marker')
            with self.assertRaisesRegex(ValueError, 'ui_static_path_rejected'): policy.static_file(root, '../outside.txt')

    def test_asset_symlink_cannot_escape_static_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'static'; root.mkdir()
            outside = root.parent / 'outside.txt'; outside.write_text('outside marker')
            (root / 'link.txt').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'ui_static_path_rejected'): policy.static_file(root, 'link.txt')

    def test_cached_hashed_assets_are_retained_without_replacing_new_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'old'; source.mkdir()
            target = Path(directory) / 'new'; target.mkdir()
            (source / 'staticfiles.json').write_text(json.dumps({'paths': {'style.css': 'style.123.css'}}))
            (source / 'style.123.css').write_text('old hashed asset')
            manifest = '{"paths": {"new.css": "new.456.css"}}'
            (target / 'staticfiles.json').write_text(manifest)
            vm.merge_hashed_assets(source, target)
            self.assertEqual((target / 'style.123.css').read_text(), 'old hashed asset')
            self.assertEqual((target / 'staticfiles.json').read_text(), manifest)

    def test_asset_collision_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'old'; source.mkdir()
            target = Path(directory) / 'new'; target.mkdir()
            (source / 'staticfiles.json').write_text(json.dumps({'paths': {'style.css': 'style.123.css'}}))
            (source / 'style.123.css').write_text('old hashed asset')
            (target / 'style.123.css').write_text('different bytes')
            with self.assertRaisesRegex(ValueError, 'ui_static_collision'): vm.merge_hashed_assets(source, target)
            self.assertEqual((target / 'style.123.css').read_text(), 'different bytes')

    def test_wrong_restore_receipt_is_rejected_before_host_operations(self):
        state = {'phase': 'ui-awaiting-restore', 'after_backup': {'sha256': 'expected'}}
        with patch.object(vm.host, 'load') as load:
            with self.assertRaisesRegex(ValueError, 'ui_restore_binding_mismatch'): vm.activate(state, 'different')
            load.assert_not_called()

    def test_failed_attempt_is_not_silently_reapplied(self):
        source, target = configurations()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / 'attempt.json'
            state_path.write_text(json.dumps({'source': source, 'target': target, 'phase': 'ui-failed'}))
            with patch.object(vm, 'STATE', state_path), patch.object(vm.host, 'mounted') as mounted:
                with self.assertRaisesRegex(ValueError, 'ui_previous_attempt_needs_review'):
                    vm.prepare({'source': source, 'target': target}, Path('unused.tar'))
                mounted.assert_not_called()


if __name__ == '__main__': unittest.main()
