"""Eight operator-run profile/lineage denial contracts; no app/Docker imports."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from dev import ROOT
import r1_gate as gate
import s31_profiles as policy


class ProfileContracts(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        path = root / policy.CURRENT; path.parent.mkdir(parents=True)
        # Actual original operator evidence, retained by APPLY; no report is
        # fabricated from the agent's source-only Prepared placeholder.
        path.write_bytes((ROOT / policy.ARCHIVE).read_bytes())
        return root

    def test_legacy_preserved_and_only_named_candidate_delta(self):
        _, old = policy.load_workload(ROOT, 'legacy')
        _, new = policy.load_workload(ROOT, 'workers4')
        self.assertEqual(gate.profile(old), old); self.assertEqual(gate.profile(new), new)
        self.assertEqual(new['synthetic_envelope']['web_workers'], 4)
        restored = copy.deepcopy(new)
        for key in ('profile_id', 'predecessor_profile_sha256', 'comparison_evidence_sha256'):
            restored.pop(key)
        restored['schema'] = 1; restored['synthetic_envelope']['web_workers'] = 2
        self.assertEqual(restored, old)
        self.assertEqual(policy.identify(new), 'workers4')

    def test_weaker_targets_load_or_larger_resources_rejected(self):
        _, original = policy.load_workload(ROOT, 'workers4')
        for key, value in (('sessions', 49), ('clients', 199), ('ordinary_movements', 1999), ('window_days', 364),
                           ('web_workers', 3), ('web_cpus', 4), ('web_memory_mib', 2048), ('database_cpus', 4)):
            changed = copy.deepcopy(original); changed['synthetic_envelope'][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): gate.profile(changed)
        changed = copy.deepcopy(original); changed['proposed_p95_seconds']['list'] = 3
        with self.assertRaises(RuntimeError): gate.profile(changed)

    def test_approval_or_provenance_changes_do_not_promote_candidate(self):
        _, original = policy.load_workload(ROOT, 'workers4')
        for key, value in (('approval', 'Approved'), ('scope', 'production'), ('comparison_evidence_sha256', 'stale')):
            changed = copy.deepcopy(original); changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError): gate.profile(changed)
        for name in ('../r1_workload.json', 'automatic', 'workers8'):
            with self.subTest(name=name), self.assertRaises(RuntimeError): policy.load_workload(ROOT, name)

    def test_exclusive_archive_retains_actual_bytes_and_survives_new_current_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory); before = (root / policy.CURRENT).read_bytes()
            snapshot = policy.capture_initial(root, 'git:' + 'a' * 40)
            binding = policy.bind_initial(root, snapshot)
            self.assertEqual((root / policy.ARCHIVE).read_bytes(), before)
            self.assertEqual(policy.bind_initial(root, snapshot), binding)
            current = b'{"new_operator_result":"retained independently"}\n'
            (root / policy.CURRENT).write_bytes(current)
            self.assertEqual(policy.verify_lineage(root), binding)
            self.assertEqual(policy.bind_initial(root, snapshot), binding)
            self.assertEqual((root / policy.CURRENT).read_bytes(), current)
            with self.assertRaises(RuntimeError): policy.capture_initial(root, 'git:' + 'b' * 40)

    def test_changed_initial_report_is_not_captured_or_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            value = json.loads((root / policy.CURRENT).read_text()); value['technical_status'] = 'Verified'
            (root / policy.CURRENT).write_text(json.dumps(value))
            with self.assertRaises(RuntimeError): policy.capture_initial(root, 'git:' + 'a' * 40)
            self.assertFalse((root / policy.ARCHIVE).exists()); self.assertFalse((root / policy.LINEAGE).exists())

    def test_missing_or_partial_lineage_is_never_created_by_runtime_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.fixture(directory)
            with self.assertRaises(RuntimeError): policy.verify_lineage(root)
            self.assertFalse((root / policy.ARCHIVE).exists()); self.assertFalse((root / policy.LINEAGE).exists())
            (root / policy.ARCHIVE).write_bytes((root / policy.CURRENT).read_bytes())
            with self.assertRaises(RuntimeError): policy.verify_lineage(root)
            with self.assertRaises(RuntimeError): policy.capture_initial(root, 'git:' + 'a' * 40)
            self.assertFalse((root / policy.LINEAGE).exists())

    def test_archive_binding_tamper_and_symlink_rejected_without_rebind(self):
        for target in (policy.ARCHIVE, policy.LINEAGE):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as directory:
                root = self.fixture(directory); snapshot = policy.capture_initial(root, 'git:' + 'a' * 40)
                policy.bind_initial(root, snapshot)
                path = root / target; original = path.read_bytes(); path.write_bytes(original + b'changed')
                with self.assertRaises(RuntimeError): policy.verify_lineage(root)
                with self.assertRaises(RuntimeError): policy.bind_initial(root, snapshot)
                path.unlink(); path.symlink_to(root / policy.CURRENT)
                with self.assertRaises(RuntimeError): policy.verify_lineage(root)

    def test_actual_worker_image_resource_or_recovery_mismatch_cannot_verify(self):
        image_id = 'sha256:' + 'a' * 64
        proof = {'service': 'web', 'image': image_id, 'configured_workers': 4, 'live_worker_children': 4,
                 'effective_cpu_limit': 2, 'memory_bytes': 1024 ** 3, 'worker_class': 'sync',
                 'entrypoint': ['gunicorn'], 'command': ['core.wsgi:application', '--config', 'gunicorn.conf.py']}
        self.assertEqual(policy.validate_runtime(proof, 4, image_id, 'web'), proof)
        for change in ({'live_worker_children': 2}, {'configured_workers': 2}, {'effective_cpu_limit': 4},
                       {'memory_bytes': 2 * 1024 ** 3}, {'image': 'other'}, {'service': 'restored_web'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                policy.validate_runtime(proof | change, 4, image_id, 'web')
        _, workload = policy.load_workload(ROOT, 'workers4')
        rehearsal = {'runtime': {'workload_profile': 'workers4', 'container_limits': workload['synthetic_envelope'],
                                'effective_web': proof, 'effective_restored_web': proof | {'service': 'restored_web'}}}
        self.assertTrue(policy.validate_rehearsal(rehearsal, workload, image_id))
        rehearsal['runtime']['effective_restored_web'] = proof
        with self.assertRaises(RuntimeError): policy.validate_rehearsal(rehearsal, workload, image_id)


if __name__ == '__main__':
    unittest.main()
