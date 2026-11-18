"""Twenty operator-run stdlib acceptance/provenance contracts, no app imports."""
import copy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from dev import ROOT
import r1_gate as gate

DOCS = ROOT / 'docs/implementation'


class ReleaseContracts(unittest.TestCase):
    def workload(self):
        return json.loads((DOCS / 'r1_workload.json').read_text())

    def review(self):
        return gate.pending_review('git:' + 'a' * 40, 'sha256:' + 'b' * 64, 'sha256:' + 'c' * 64,
                                   'sha256:' + 'd' * 64, 'sha256:' + 'e' * 64)

    def complete_review(self):
        value = self.review()
        for role, name in (('accountant', 'Declared accountant'), ('product_owner', 'Declared owner')):
            value[role].update(name=name, reference='Private declared application observation', reviewed_at='2026-11-18T12:00:00+02:00')
        for row in value['requirements'].values():
            row.update(status='Passed', observed_reference='Private observed artifact', observed_sha256='sha256:' + 'f' * 64,
                       reviewed_at='2026-11-18T12:00:00+02:00')
        for row in value['approvals'].values():
            row.update(status='Approved', reference='Private explicit decision', sha256='sha256:' + 'f' * 64)
        value['first_office'].update(environment='Selected private environment', office='Selected office', window='Approved window',
            freeze_owner='Declared freeze owner', rollback_owner='Declared restore owner', authorisation_reference='Private authorisation',
            authorisation_sha256='sha256:' + 'f' * 64, backup_reference='Private verified backup', backup_sha256='sha256:' + 'f' * 64)
        return value

    def manifest_fixture(self, directory):
        root = Path(directory); (root / 'old.py').write_text('assert True\n')
        file = root / 'manifest.json'
        file.write_text(json.dumps({'sha256': {'old.py': gate.digest_bytes((root / 'old.py').read_bytes())}}))
        return root, file

    def matrix_fixture(self, directory):
        root = Path(directory); docs = root / 'docs/implementation'; docs.mkdir(parents=True)
        value = json.loads((DOCS / 'r1_acceptance_matrix.json').read_text())
        for row in value['requirements']:
            row['candidate_evidence'] = ['candidate.py']
        (root / 'candidate.py').write_text('candidate evidence only\n')
        (docs / 'r1_acceptance_matrix.json').write_text(json.dumps(value))
        (docs / 'traceability.csv').write_bytes((DOCS / 'traceability.csv').read_bytes())
        return root, docs, value

    def technical(self):
        recovery = {k: True for k in ('all_public_tables_matched', 'required_synthetic_key_material_recovered', 'wrong_signing_key_denied',
            'restored_http_200', 'baseline_20_rollback_matched', 'source_original_unchanged', 'proposed_targets_met_in_this_rehearsal')}
        return {'step': 'S31', 'scope': 'synthetic-isolated-finance-release-rehearsal', 'status': 'Prepared', 'release_decision': 'Blocked',
            'technical_status': 'Verified', 'full_requirement_acceptance': 'Pending', 'full_requirement_acceptances_pending': 85,
            'suite': {'tests_run': 848, 'tests_passed': 848, 'cases': [{'outcome': 'passed'} for _ in range(36)],
                      **{k: 0 for k in ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')}},
            's28_generation': {'automatic': {'scheduler_discovered': True}, 'commit_before_ack': {'committed_receipt_survived_child_sigkill': True,
                'task_deliveries': 2, 'charge_count': 1}, 'reconciliation': {'cash_entries': 0}},
            'rehearsal': {'performance': {'thresholds_passed': True}, 'cycle': {'passed': True}, 'recovery': recovery, 'plaintext_removed': True},
            'owned_resources_removed': True}

    def test_real_retained_sources_match_published_bytes(self):
        self.assertGreater(gate.preserved(ROOT, DOCS / 'evidence/S31-preserved-source.json'), 381)

    def test_matching_manifest_is_read_without_rebinding(self):
        with tempfile.TemporaryDirectory() as d:
            root, file = self.manifest_fixture(d); before = file.read_bytes()
            self.assertEqual(gate.preserved(root, file), 1); self.assertEqual(file.read_bytes(), before)
            review = root / 'docs/security/secret_scan_allowlist.csv'; review.parent.mkdir(parents=True)
            prefix, suffix = b'old exact review\n', b'new exact review\n'; review.write_bytes(prefix + suffix)
            value = json.loads(file.read_text())
            value['append_only_files'] = {'docs/security/secret_scan_allowlist.csv': {
                'original_bytes': len(prefix), 'original_sha256': gate.digest_bytes(prefix),
                'suffix_sha256': gate.digest_bytes(suffix), 'after_sha256': gate.digest_bytes(prefix + suffix)}}
            file.write_text(json.dumps(value)); before = file.read_bytes()
            self.assertEqual(gate.preserved(root, file), 2); self.assertEqual(file.read_bytes(), before)
            for data in (b'changed old review\n' + suffix, prefix + b'different extra review\n'):
                review.write_bytes(data)
                with self.assertRaises(RuntimeError): gate.preserved(root, file)
                self.assertEqual(file.read_bytes(), before)

    def test_changed_retained_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root, file = self.manifest_fixture(d); before = file.read_bytes(); (root / 'old.py').write_text('assert False\n')
            with self.assertRaises(RuntimeError): gate.preserved(root, file)
            self.assertEqual(file.read_bytes(), before)

    def test_missing_malformed_escaping_and_symlink_sources_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root, file = self.manifest_fixture(d)
            for entries in ({}, None, {'old.py': '0' * 64}, {'../old.py': 'sha256:' + '0' * 64}, {'missing.py': 'sha256:' + '0' * 64}):
                file.write_text(json.dumps({'sha256': entries}))
                with self.subTest(entries=entries), self.assertRaises(RuntimeError): gate.preserved(root, file)
            (root / 'alias.py').symlink_to(root / 'old.py')
            file.write_text(json.dumps({'sha256': {'alias.py': gate.digest_bytes((root / 'old.py').read_bytes())}}))
            with self.assertRaises(RuntimeError): gate.preserved(root, file)

    def test_effective_R1_matrix_contains_33_UR_and_nine_QR(self):
        rows = gate.matrix(ROOT)
        self.assertEqual(len(rows), 42); self.assertEqual(sum(r['requirement_id'].startswith('UR-') for r in rows), 33)

    def test_original_32_count_cannot_drop_Greek_frontend(self):
        with tempfile.TemporaryDirectory() as d:
            root, docs, value = self.matrix_fixture(d)
            value['requirements'] = [r for r in value['requirements'] if r['requirement_id'] != 'UR-LOC-01']
            (docs / 'r1_acceptance_matrix.json').write_text(json.dumps(value))
            with self.assertRaises(RuntimeError): gate.matrix(root)

    def test_acceptance_criterion_cannot_be_replaced_by_a_test_claim(self):
        with tempfile.TemporaryDirectory() as d:
            root, docs, value = self.matrix_fixture(d)
            value['requirements'][0]['acceptance_check'] = 'A source check passed'
            (docs / 'r1_acceptance_matrix.json').write_text(json.dumps(value))
            with self.assertRaises(RuntimeError): gate.matrix(root)

    def test_supplied_workload_is_explicitly_unapproved(self):
        value = gate.profile(self.workload())
        self.assertEqual(value['approval'], 'Pending'); self.assertEqual(value['synthetic_envelope']['sessions'], 50)

    def test_reduced_load_or_weaker_p95_is_not_silently_accepted(self):
        for key in ('sessions', 'ordinary_movements', 'window_days'):
            value = self.workload(); value['synthetic_envelope'][key] -= 1
            with self.subTest(key=key), self.assertRaises(RuntimeError): gate.profile(value)
        value = self.workload(); value['proposed_p95_seconds']['list'] = 20
        with self.assertRaises(RuntimeError): gate.profile(value)

    def test_p95_uses_nearest_rank_including_tail(self):
        self.assertEqual(gate.percentile95(list(range(1, 101))), 95)
        self.assertEqual(gate.percentile95([7]), 7)
        self.assertEqual(gate.percentile95([100, 1, 1]), 100)

    def test_invalid_or_empty_timing_samples_are_rejected(self):
        for samples in ([], [True], [-1], [float('nan')], [float('inf')], ['1']):
            with self.subTest(samples=samples), self.assertRaises(RuntimeError): gate.percentile95(samples)

    def test_failed_requests_and_slow_tail_fail_measured_gate(self):
        samples = {k: [.1] * 150 for k in ('list', 'detail', 'annual_report')}
        samples['list'][-10:] = [45] * 10
        result = gate.performance_result(samples, [{'code': 'timeout'}], self.workload())
        self.assertFalse(result['thresholds_passed']); self.assertEqual(result['operations']['list']['p95_seconds'], 45)
        self.assertEqual(result['errors'], 1); self.assertFalse(result['production_capacity_accepted'])

    def test_missing_attempts_cannot_improve_percentile(self):
        samples = {k: [.1] * 150 for k in ('list', 'detail', 'annual_report')}; samples['detail'].pop()
        with self.assertRaises(RuntimeError): gate.performance_result(samples, [], self.workload())

    def test_pending_review_never_implies_acceptance(self):
        value = self.review(); blockers = gate.review_blockers(value, self.review())
        self.assertGreater(len(blockers), 42); self.assertTrue(all(r['status'] == 'Pending' for r in value['requirements'].values()))

    def test_stale_image_source_workload_or_report_binding_is_rejected(self):
        for key in self.review()['bindings']:
            value = self.review(); value['bindings'][key] = 'stale'
            with self.subTest(key=key), self.assertRaises(RuntimeError): gate.review_blockers(value, self.review())

    def test_missing_acceptance_or_approval_row_is_rejected(self):
        value = self.review(); del value['requirements']['UR-LOC-01']
        with self.assertRaises(RuntimeError): gate.review_blockers(value, self.review())
        value = self.review(); del value['approvals']['d05_ownership_and_reconciliation']
        with self.assertRaises(RuntimeError): gate.review_blockers(value, self.review())

    def test_complete_declared_review_cannot_fabricate_live_cutover(self):
        value = self.complete_review(); value['first_office']['cutover_executed'] = True
        blockers = gate.review_blockers(value, self.review())
        self.assertEqual(len(blockers), 1); self.assertIn('separately observed execution', blockers[0])

    def test_one_person_requires_explicit_dual_role_confirmation(self):
        value = self.complete_review(); value['product_owner']['name'] = value['accountant']['name']
        self.assertEqual(len(gate.review_blockers(value, self.review())), 2)
        value['same_person_for_both_roles_explicitly_confirmed'] = True
        self.assertEqual(len(gate.review_blockers(value, self.review())), 1)

    def test_technical_receipt_requires_full_suite_and_still_blocks_release(self):
        self.assertTrue(gate.technical_valid(self.technical()))
        for change in ({'release_decision': 'Approved'}, {'status': 'Verified'}, {'technical_status': 'Pending'}):
            with self.subTest(change=change), self.assertRaises(RuntimeError): gate.technical_valid(self.technical() | change)
        value = self.technical(); value['suite']['tests_passed'] = 847
        with self.assertRaises(RuntimeError): gate.technical_valid(value)

    def test_missing_key_rollback_broker_or_cleanup_cannot_complete_technical_gate(self):
        value = self.technical(); value['rehearsal']['recovery']['wrong_signing_key_denied'] = False
        with self.assertRaises(RuntimeError): gate.technical_valid(value)
        value = self.technical(); value['s28_generation']['commit_before_ack']['task_deliveries'] = 1
        with self.assertRaises(RuntimeError): gate.technical_valid(value)
        value = self.technical(); value['rehearsal']['plaintext_removed'] = False
        with self.assertRaises(RuntimeError): gate.technical_valid(value)


if __name__ == '__main__':
    unittest.main()
