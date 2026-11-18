"""Twelve operator-run stdlib contracts for local historical-result bindings."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from dev import ROOT
import s31_receipts as receipts


class ReceiptContracts(unittest.TestCase):
    def policy(self):
        return {'schema': 1, 'binding_file': receipts.BINDING, 'paths': list(receipts.RECEIPTS)}

    def fixture(self, directory):
        root = Path(directory)
        for name in receipts.RECEIPTS:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            if name.endswith('.csv'):
                path.write_text('case_id,area,route,persona,scenario,observed,result\nexample,read,detail,accountant,own,200,Passed\n')
            elif name.endswith('G1-foundation.json'):
                path.write_text(json.dumps({'gate': 'G1', 'status': 'Verified'}))
            elif name.endswith('S25-verification.json'):
                value = json.loads((ROOT / 'docs/implementation/evidence/S25-operator-completion.json').read_text())
                value['preserved_application_context'] = 'sha256:aa53c8f70d8ca11881457a7c80ee7e21684c8b4212a86fe9dbfe28ed95220ba0'
                path.write_text(json.dumps(value))
            elif name.endswith('S30-verification.json'):
                path.write_bytes((ROOT / name).read_bytes())
            else:
                path.write_text(json.dumps({'step': path.name.removesuffix('-verification.json'), 'status': 'Prepared'}))
        return root

    def snapshot(self, root):
        return {name: (root / name).read_bytes() for name in receipts.RECEIPTS}

    def capture(self, root):
        return receipts.capture(root, self.policy(), 'git:' + 'a' * 40)

    def alter(self, root, name, change):
        path = root / (receipts.PREFIX + name); value = json.loads(path.read_text()); change(value)
        path.write_text(json.dumps(value))

    def test_capture_preserves_all_actual_JSON_and_CSV_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); before = self.snapshot(root); record = self.capture(root)
            self.assertEqual(len(record['sha256']), 35); self.assertEqual(self.snapshot(root), before)
            self.assertFalse((root / receipts.BINDING).exists())

    def test_known_successful_S25_is_accepted_without_a_Prepared_file_hash(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); path = root / (receipts.PREFIX + 'S25-verification.json')
            old = path.read_bytes(); self.capture(root)
            self.assertEqual(json.loads(path.read_text())['status'], 'Verified'); self.assertEqual(path.read_bytes(), old)

    def test_Prepared_history_remains_Prepared_without_synthetic_promotion(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); path = root / (receipts.PREFIX + 'S25-verification.json')
            path.write_text(json.dumps({'step': 'S25', 'status': 'Prepared', 'operator_results': 'Pending'}))
            before = path.read_bytes(); record = self.capture(root)
            receipts.bind_once(root, self.policy(), record)
            self.assertEqual(path.read_bytes(), before); self.assertEqual(json.loads(path.read_text())['status'], 'Prepared')

    def test_conflicting_claimed_Verified_S25_plan_or_finance_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); path = root / (receipts.PREFIX + 'S25-verification.json'); original = path.read_bytes()
            for key, value in (('plan_sha256', 'sha256:' + '0' * 64), ('all_financial_checks_matched', False), ('planner_tests_passed', 58)):
                path.write_bytes(original); self.alter(root, path.name, lambda x: x.update({key: value})); before = path.read_bytes()
                with self.subTest(key=key), self.assertRaises(RuntimeError): self.capture(root)
                self.assertEqual(path.read_bytes(), before)

    def test_claimed_S30_Verified_requires_full_848_36_and_same_context(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); path = root / (receipts.PREFIX + 'S30-verification.json'); original = path.read_bytes()
            changes = [lambda x: x['suite'].update(tests_passed=847), lambda x: x['suite']['cases'][0].update(outcome='failed'),
                       lambda x: x.update(application_context_digest='sha256:' + '0' * 64)]
            for change in changes:
                path.write_bytes(original); self.alter(root, path.name, change)
                with self.assertRaises(RuntimeError): self.capture(root)

    def test_binding_is_exclusive_idempotent_and_does_not_rewrite_history(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); before = self.snapshot(root); record = self.capture(root)
            self.assertTrue(receipts.bind_once(root, self.policy(), record)); original = (root / receipts.BINDING).read_bytes()
            self.assertFalse(receipts.bind_once(root, self.policy(), record)); self.assertEqual(receipts.verify(root, self.policy()), 35)
            self.assertEqual((root / receipts.BINDING).read_bytes(), original); self.assertEqual(self.snapshot(root), before)

    def test_changed_bound_receipt_is_denied_without_rebinding(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); receipts.bind_once(root, self.policy(), self.capture(root))
            original = (root / receipts.BINDING).read_bytes()
            self.alter(root, 'S25-verification.json', lambda x: x.update(synthetic_restore_seconds=1.234))
            with self.assertRaises(RuntimeError): receipts.verify(root, self.policy())
            with self.assertRaises(RuntimeError): receipts.bind_once(root, self.policy(), self.capture(root))
            self.assertEqual((root / receipts.BINDING).read_bytes(), original)

    def test_missing_binding_is_denied_and_never_created_by_verification(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d)
            with self.assertRaises(RuntimeError): receipts.verify(root, self.policy())
            self.assertFalse((root / receipts.BINDING).exists())

    def test_missing_or_malformed_receipt_is_not_replaced_by_a_template(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); path = root / (receipts.PREFIX + 'S25-verification.json')
            for data in (b'{', b'{"step":"S25","step":"S26","status":"Verified"}', b'{"step":"S25","status":"Prepared","n":NaN}'):
                path.write_bytes(data)
                with self.assertRaises(RuntimeError): self.capture(root)
                self.assertEqual(path.read_bytes(), data)
            path.unlink()
            with self.assertRaises(RuntimeError): self.capture(root)
            self.assertFalse(path.exists())

    def test_unknown_duplicate_and_escaping_policy_paths_are_rejected(self):
        for addition in ('../outside.json', receipts.RECEIPTS[0], 'accounting/finance_services.py'):
            value = self.policy(); value['paths'].append(addition)
            with self.subTest(addition=addition), self.assertRaises(RuntimeError): receipts.validate_policy(value)
        value = self.policy(); value['binding_file'] = '../bindings.json'
        with self.assertRaises(RuntimeError): receipts.validate_policy(value)

    def test_missing_extra_malformed_or_stale_binding_entries_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); good = self.capture(root)
            for action in (lambda x: x['sha256'].pop(receipts.RECEIPTS[0]), lambda x: x['sha256'].update({'extra.json': 'sha256:' + '0' * 64}),
                           lambda x: x.update(policy_sha256='sha256:' + '0' * 64), lambda x: x['sha256'].update({receipts.RECEIPTS[0]: '0' * 64})):
                bad = copy.deepcopy(good); action(bad)
                with self.assertRaises(RuntimeError): receipts.check_snapshot(root, self.policy(), bad)

    def test_valid_local_format_variants_are_bound_exactly_and_symlinks_denied(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.fixture(d); path = root / (receipts.PREFIX + 'S25-verification.json')
            first = self.capture(root)['sha256'][str(path.relative_to(root))]
            path.write_text(json.dumps(json.loads(path.read_text()), ensure_ascii=False, indent=4) + '\n')
            record = self.capture(root); self.assertNotEqual(record['sha256'][str(path.relative_to(root))], first)
            receipts.bind_once(root, self.policy(), record)
            original = path.with_suffix('.original'); path.rename(original); path.symlink_to(original)
            with self.assertRaises(RuntimeError): receipts.verify(root, self.policy())


if __name__ == '__main__':
    unittest.main()
