"""Operator-only stdlib guard contracts; no app/Docker/cloud execution."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import subprocess
from contextlib import contextmanager
import unittest
from unittest.mock import patch

import preview_s31_policy as p
from preview_s31_migrate import clone_guard

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def pending_report_source():
    """A real private Git fixture; no application, Docker or cloud execution."""
    import image
    import preview_s31_release as release
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        names = sorted(image.EXACT)
        names += ['accounting/fixture_input_' + str(i) + '.py' for i in range(284 - len(names))]
        for name in names:
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'# synthetic source fixture\n')
        report = root / 'docs/implementation/evidence/S31-verification.json'
        report.parent.mkdir(parents=True); report.write_text('{"fixture":"prepared"}\n')
        def git(*args):
            return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
                '-c', 'user.name=Source fixture', '-c', 'user.email=fixture@example.invalid', '-C', str(root), *args],
                env=image.git_environment(), capture_output=True, check=True).stdout
        git('init', '--quiet'); git('add', '.'); git('commit', '--quiet', '-m', 'synthetic source fixture')
        with patch.object(image, 'ROOT', root):
            revision, _, context = image.committed_context()
            report.write_text('{"fixture":"verified"}\n')
            with patch.object(p, 'CONTEXT', context['digest']):
                yield root, report, git, revision, release


def pair():
    source = {'hostname': p.HOSTNAME, 'gcp': {**p.BOOTSTRAP['gcp'],
               'data_uuid': '22415b2c-1e1b-4e39-9ce5-5fb0c19dd663', 'secret_versions': {'django': 1, 'postgres': 1}},
              'db_name': 'accounting_previous', 'db_user': 'accounting_app',
              'published': {'image': p.OLD_IMAGE, 'context_digest': p.OLD_CONTEXT}}
    target = deepcopy(source); target['db_name'] = 'accounting_s31_0123456789ab'
    target['published'] = {'context_digest': p.CONTEXT, 'image_id': p.IMAGE_ID, 'commit': p.APP_REVISION}
    return source, target


def recovery():
    state = {'phase': 'awaiting_off_vm_restore', 'public_cutover_started': False,
             'before_backup': {'object': 'before', 'sha256': 'a'}, 'after_backup': {'object': 'after', 'sha256': 'b'}}
    proofs = {name: {'status': 'Restored', 'all_public_tables_match': True, 'separate_recovery_key_used': True,
                    'plaintext_removed': True, 'recovery_container_removed': True, 'preview_database_modified': False,
                    'receipt': state[field]}
              for name, field in (('before', 'before_backup'), ('after', 'after_backup'))}
    return state, proofs


class PreviewGuards(unittest.TestCase):
    def test_pending_receipt_audited_before_commit_then_clean_identity_required(self):
        with pending_report_source() as (root, report, git, revision, release):
            import image
            with self.assertRaises(RuntimeError):
                image.committed_context()
            source, _ = release.source_context(clean=False)
            self.assertIsNone(source)
            self.assertEqual(git('rev-parse', 'HEAD').decode().strip(), revision)
            self.assertTrue(git('diff', '--name-only', 'HEAD').strip())
            git('add', '--', str(report.relative_to(root))); git('commit', '--quiet', '-m', 'record synthetic result')
            source, _ = release.source_context()
            self.assertEqual(source, git('rev-parse', 'HEAD').decode().strip())

    def test_dirty_application_is_denied_even_with_a_pending_receipt(self):
        with pending_report_source() as (root, report, git, revision, release):
            (root / 'manage.py').write_bytes(b'# independently changed application\n')
            with self.assertRaises(RuntimeError):
                release.source_context(clean=False)
            self.assertEqual(git('rev-parse', 'HEAD').decode().strip(), revision)

    def test_actual_operator_report(self):
        p.verified_report(json.loads((ROOT / p.RECEIPT).read_text()))

    def test_altered_success_cannot_authorize_image(self):
        value = json.loads((ROOT / p.RECEIPT).read_text()); value['suite']['tests_passed'] = 847
        with self.assertRaises(RuntimeError):
            p.verified_report(value)

    def test_same_selected_target(self):
        p.transition(*pair())

    def test_other_project_denied(self):
        source, target = pair(); target['gcp']['project_id'] = 'somewhere-else'
        with self.assertRaises(RuntimeError):
            p.transition(source, target)

    def test_secret_version_change_denied(self):
        source, target = pair(); target['gcp']['secret_versions']['django'] = 2
        with self.assertRaises(RuntimeError):
            p.transition(source, target)

    def test_original_database_cannot_be_target(self):
        source, target = pair(); target['db_name'] = source['db_name']
        with self.assertRaises(RuntimeError):
            p.transition(source, target)

    def test_different_cached_image_denied(self):
        source, target = pair(); target['published']['image_id'] = 'sha256:' + '0' * 64
        with self.assertRaises(RuntimeError):
            p.transition(source, target)

    def test_new_clone_migration_identity(self):
        name = 'accounting_s31_0123456789ab'
        clone_guard('previous', name, name, 'db', 'postgresql', 170011)

    def test_migration_of_original_denied(self):
        name = 'accounting_s31_0123456789ab'
        with self.assertRaises(RuntimeError):
            clone_guard(name, name, name, 'db', 'postgresql', 170011)

    def test_remote_database_migration_denied(self):
        name = 'accounting_s31_0123456789ab'
        with self.assertRaises(RuntimeError):
            clone_guard('previous', name, name, 'public.example.invalid', 'postgresql', 170011)

    def test_low_memory_denied(self):
        with self.assertRaises(RuntimeError):
            p.same_capacity(2_000_000, 1_500_000, 10 * 1024**3, 1024)

    def test_low_disk_denied(self):
        with self.assertRaises(RuntimeError):
            p.same_capacity(4_000_000, 2_000_000, 1024**3, 1024)

    def test_both_exact_restores_required(self):
        state, proofs = recovery(); p.ready_for_activation(state, proofs)
        del proofs['before']
        with self.assertRaises(RuntimeError):
            p.ready_for_activation(state, proofs)

    def test_wrong_backup_generation_denied(self):
        state, proofs = recovery(); proofs['after']['receipt'] = {'object': 'different'}
        with self.assertRaises(RuntimeError):
            p.ready_for_activation(state, proofs)

    def test_missing_recovered_key_proof_denied(self):
        state, proofs = recovery(); proofs['before']['separate_recovery_key_used'] = False
        with self.assertRaises(RuntimeError):
            p.ready_for_activation(state, proofs)

    def test_failed_table_comparison_denied(self):
        state, proofs = recovery(); proofs['after']['all_public_tables_match'] = False
        with self.assertRaises(RuntimeError):
            p.ready_for_activation(state, proofs)

    def test_no_rollback_after_possible_new_writes(self):
        import preview_s31_host as host
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'state.json'; file.write_text(json.dumps({'public_cutover_started': True}))
            with patch.object(host, 'STATE', file), patch.object(host, 'hold') as hold:
                with self.assertRaises(RuntimeError):
                    host.abort()
                hold.assert_not_called()

    def test_hold_stops_boot_before_docker(self):
        import preview_s31_host as host
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'hold'; file.write_text('hold')
            with patch.object(host, 'HOLD', file), patch.object(host, 'compose') as compose:
                with self.assertRaises(RuntimeError):
                    host.boot()
                compose.assert_not_called()

    def test_recovery_owners_and_code_unchanged(self):
        old = {'preview': {'old': True}, 'code_commit': 'old-operations', 'recipient': 'existing', 'retention_days': 7}
        value = p.rebound_operations(old, {'new': True})
        self.assertEqual({k: v for k, v in value.items() if k != 'preview'}, {k: v for k, v in old.items() if k != 'preview'})
        self.assertEqual(old['preview'], {'old': True})

    def test_tracking_retains_old_steps_and_all_acceptances(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); docs = root / 'docs/implementation'; docs.mkdir(parents=True)
            for name in ('state.md', 'steps.csv', 'traceability.csv'):
                (docs / name).write_bytes((ROOT / 'docs/implementation' / name).read_bytes())
            original_trace = (docs / 'traceability.csv').read_bytes()
            before = list(csv.DictReader((docs / 'steps.csv').open()))
            p.track(root, 'Prepared', 'git:' + p.VERIFIED_SOURCE)
            p.track(root, 'Verified', 'git:' + p.VERIFIED_SOURCE)
            after = list(csv.DictReader((docs / 'steps.csv').open()))
            self.assertEqual([r for r in before if r['step_id'] != 'S31A'], [r for r in after if r['step_id'] != 'S31A'])
            self.assertEqual((docs / 'traceability.csv').read_bytes(), original_trace)
            self.assertEqual(sum(r['step_id'] == 'S31A' for r in after), 1)


if __name__ == '__main__':
    unittest.main()
