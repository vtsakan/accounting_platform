"""Eight operator-run stdlib contracts for supplementary historical metadata."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from dev import ROOT
import r1_gate
import s31_evidence as evidence
import s31_receipts as receipts


class HistoricalEvidenceContracts(unittest.TestCase):
    def policy(self):
        return {'schema': 1, 'binding_file': evidence.BINDING, 'paths': list(evidence.PATHS)}

    def receipt_policy(self):
        return {'schema': 1, 'binding_file': receipts.BINDING, 'paths': list(receipts.RECEIPTS)}

    def fixture(self, directory):
        root = Path(directory)
        for name in (*evidence.PATHS, *receipts.RECEIPTS):
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())
        return root

    def capture(self, root):
        return evidence.capture(root, self.policy(), 'git:' + 'a' * 40)

    def test_preparation_fix_manifests_and_provenance_have_an_exact_disjoint_inventory(self):
        self.assertEqual(len(evidence.PATHS), 71); self.assertFalse(set(evidence.PATHS) & set(receipts.RECEIPTS))
        for name in ('S26-hash-fix.json', 'S26-hash-fix-source.json', 'S27-preserved-source.json', 'S25-operator-completion.json'):
            self.assertIn(receipts.PREFIX + name, evidence.PATHS)
        manifest = json.loads((ROOT / 'docs/implementation/evidence/S31-preserved-source.json').read_text())
        for path in ('accounting/models.py', 'accounting/tests_finance_posting.py', 'requirements.txt',
                     'tools/legacy_worker.py', 'docker/image-pins.json', 'docs/implementation/financial_policy.json'):
            self.assertIn(path, manifest['sha256']); self.assertNotIn(path, evidence.PATHS)

    def test_local_preparation_stamps_are_captured_exactly_without_overwrite_or_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); path = root / (receipts.PREFIX + 'S26-hash-fix.json')
            value = json.loads(path.read_text()); value.update(recorded_at='2026-11-17', applied_source_commit='git:' + 'b' * 40)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=4) + '\n')
            before = {n: (root / n).read_bytes() for n in evidence.PATHS}
            record = self.capture(root)
            self.assertEqual(record['sha256'][str(path.relative_to(root))], receipts.sha(path.read_bytes()))
            self.assertEqual({n: (root / n).read_bytes() for n in evidence.PATHS}, before)
            self.assertEqual(json.loads(path.read_text())['status'], value['status'])

    def test_exclusive_binding_is_idempotent_and_covers_every_supplementary_document(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); record = self.capture(root)
            self.assertTrue(evidence.bind_once(root, self.policy(), record)); before = (root / evidence.BINDING).read_bytes()
            self.assertFalse(evidence.bind_once(root, self.policy(), record)); self.assertEqual(evidence.verify(root, self.policy()), 71)
            self.assertEqual((root / evidence.BINDING).read_bytes(), before)

    def test_bound_metadata_change_is_rejected_without_rebinding(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); evidence.bind_once(root, self.policy(), self.capture(root))
            original = (root / evidence.BINDING).read_bytes(); path = root / (receipts.PREFIX + 'S26-hash-fix.json')
            value = json.loads(path.read_text()); value['recorded_at'] = '2026-11-18'; path.write_text(json.dumps(value))
            with self.assertRaises(RuntimeError): evidence.verify(root, self.policy())
            with self.assertRaises(RuntimeError): evidence.bind_once(root, self.policy(), self.capture(root))
            self.assertEqual((root / evidence.BINDING).read_bytes(), original)

    def test_missing_and_malformed_metadata_are_reported_together_without_templates(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); first = root / (receipts.PREFIX + 'S26-hash-fix.json'); second = root / (receipts.PREFIX + 'S26-hash-fix-source.json')
            first.write_bytes(b'{'); second.unlink()
            with self.assertRaises(RuntimeError) as error: self.capture(root)
            self.assertIn(first.name, str(error.exception)); self.assertIn(second.name, str(error.exception))
            self.assertEqual(first.read_bytes(), b'{'); self.assertFalse(second.exists())
            first.write_bytes(b'{"step":"S26","step":"S25"}')
            with self.assertRaises(RuntimeError): self.capture(root)

    def test_unknown_duplicate_escaping_or_code_paths_cannot_be_classified_as_history(self):
        for name in ('../outside.json', evidence.PATHS[0], 'accounting/models.py', 'docs/implementation/financial_policy.json'):
            policy = self.policy(); policy['paths'].append(name)
            with self.subTest(name=name), self.assertRaises(RuntimeError): evidence.validate_policy(policy)
        policy = self.policy(); policy['binding_file'] = receipts.BINDING
        with self.assertRaises(RuntimeError): evidence.validate_policy(policy)

    def test_missing_partial_stale_or_symlink_binding_is_never_repaired_by_verification(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            with self.assertRaises(RuntimeError): evidence.verify(root, self.policy())
            self.assertFalse((root / evidence.BINDING).exists())
            record = self.capture(root)
            for mutate in (lambda x: x['sha256'].pop(evidence.PATHS[0]), lambda x: x.update(policy_sha256='sha256:' + '0' * 64)):
                bad = copy.deepcopy(record); mutate(bad)
                with self.assertRaises(RuntimeError): evidence.check_snapshot(root, self.policy(), bad)
            path = root / evidence.PATHS[0]; original = path.with_suffix('.original'); path.rename(original); path.symlink_to(original)
            with self.assertRaises(RuntimeError): self.capture(root)

    def test_historical_manifest_values_never_replace_published_source_hashes(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); guarded = root / 'guarded.py'; guarded.write_text('assert True\n')
            expected = receipts.sha(guarded.read_bytes()); path = root / (receipts.PREFIX + 'S26-preserved-source.json')
            old = json.loads(path.read_text()); old['sha256'] = {'guarded.py': receipts.sha(b'assert False\n')}; path.write_text(json.dumps(old))
            policy = self.receipt_policy()
            receipts.bind_once(root, policy, receipts.capture(root, policy, 'git:' + 'a' * 40))
            evidence.bind_once(root, self.policy(), self.capture(root))
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'step':'S31','sha256':{'guarded.py':expected},
                'operator_receipts':policy,'historical_evidence':self.policy()}))
            self.assertEqual(r1_gate.preserved(root, manifest), 107)
            guarded.write_text('assert False\n')
            with self.assertRaises(RuntimeError): r1_gate.preserved(root, manifest)


if __name__ == '__main__':
    unittest.main()
