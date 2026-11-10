"""S10 denied-access, retry, tamper, cleanup and operational failure contracts."""

import copy
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import operations_common as common
import operations_cloud as cloud
import operations_host as host
import operations_pg as pg
import operations_recovery as recovery
import verify_s10
import install_age
from test_s09 import configuration as preview_configuration


def configuration():
    inventory = json.loads((common.ROOT / 'docs/implementation/cloud_inventory.json').read_text())
    p = preview_configuration()
    p['gcp'].update(project_id=inventory['project_id'], vm_name=inventory['vm']['name'], zone=inventory['zone'], region=inventory['region'],
                    backup_bucket=inventory['storage']['backup_bucket'], document_bucket=inventory['storage']['document_bucket'])
    p['published']['image'] = 'europe-west1-docker.pkg.dev/accounting-514109/accounting-platform/web@sha256:' + '1' * 64
    recipient = 'age1' + 'q' * 58  # Encoding-shaped public fixture; never a private key.
    return {'schema': 1, 'preview': p, 'bucket': inventory['storage']['backup_bucket'], 'prefix': common.PREFIX,
            'recipient': recipient, 'recipient_id': common.recipient_id(recipient), 'retention_days': 30,
            'max_dump_bytes': common.MAX_DUMP, 'synthetic_only': True, 'policy_confirmed': True,
            'separate_key_copy_confirmed': True, 'incident_owner': 'Synthetic operator', 'restore_owner': 'Synthetic operator',
            'key_custodian': 'Synthetic operator', 'alert_email': 'operator@example.invalid',
            'instance_id': inventory['vm']['instance_id'], 'code_commit': 'b' * 40}


def receipt(config):
    return {'bucket': config['bucket'], 'object': common.PREFIX + '20261110T000000Z-' + 'a' * 32 + '.tar.age',
            'generation': '123456', 'size': 1024, 'sha256': 'sha256:' + '1' * 64, 'crc32c': 'AAAAAA==',
            'recipient_id': config['recipient_id'], 'snapshot_started_at': common.now(), 'project_id': config['preview']['gcp']['project_id']}


class ConfigurationTests(unittest.TestCase):
    def test_duplicate_tmpfs_entries_are_valid_but_disk_or_missing_mounts_are_denied(self):
        with patch.object(common, 'run', return_value=b'tmpfs\ntmpfs\n'):
            common.require_tmpfs('/synthetic')
        for output in (b'', b'ext4\n', b'tmpfs\noverlay\n'):
            with self.subTest(output=output), patch.object(common, 'run', return_value=output), self.assertRaises(ValueError):
                common.require_tmpfs('/synthetic')

    def test_unreviewed_age_download_is_not_installed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive = root / 'wrong.tar.gz'; archive.write_bytes(b'synthetic incorrect release')
            with self.assertRaises(ValueError): install_age.install(root / 'bin', archive)
            self.assertFalse((root / 'bin').exists())

    def test_selected_preview_accepts_a_public_recipient_only(self):
        common.validate(configuration())

    def test_other_environment_identity_and_destination_are_rejected(self):
        cases = [('bucket', 'unrelated-bucket'), ('prefix', '../elsewhere/'), ('instance_id', '123'),
                 ('recipient_id', 'sha256:' + '0' * 64), ('synthetic_only', False), ('max_dump_bytes', 2 ** 40),
                 ('private_key_payload', 'synthetic forbidden field')]
        for key, value in cases:
            with self.subTest(key=key), self.assertRaises(ValueError):
                config = configuration(); config[key] = value; common.validate(config)

    def test_cross_project_and_wrong_data_disk_are_rejected(self):
        for key, value in [('project_id', 'unrelated-project'), ('data_uuid', '00000000-0000-0000-0000-000000000000')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                config = configuration(); config['preview']['gcp'][key] = value; common.validate(config)

    def test_retention_requires_explicit_preview_policy(self):
        for key, value in [('retention_days', 0), ('retention_days', 3650), ('policy_confirmed', False),
                           ('separate_key_copy_confirmed', False), ('incident_owner', ''), ('alert_email', 'missing')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                config = configuration(); config[key] = value; common.validate(config)

    def test_private_identity_path_is_never_shipped(self):
        config = configuration(); config['local_identity'] = '/tmp/synthetic.key'
        self.assertNotIn('local_identity', common.host_config(config))
        with self.assertRaises(ValueError):
            common.validate(config)

    def test_identity_in_git_or_readable_by_others_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / 'key'; key.write_text('synthetic fixture'); key.chmod(0o644)
            with self.assertRaises(ValueError): common.identity_file(key)
            key.chmod(0o600)
            self.assertEqual(common.identity_file(key), key.resolve())
        with self.assertRaises(ValueError): common.identity_file(common.ROOT / 'manage.py')


class ArchiveTests(unittest.TestCase):
    def test_fixed_archive_roundtrip_and_dump_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); dump = root / 'source'; dump.write_bytes(b'PGDMP' + b'x' * 100)
            manifest = {'format': 'accounting-s10-v1', 'dump_sha256': common.sha(dump)}
            archive = root / 'archive.tar'
            with archive.open('wb') as output: common.write_archive(output, dump, manifest, {'secret_versions': [1, 1]})
            dest = root / 'decoded'; dest.mkdir()
            self.assertEqual(common.unpack(archive, dest), (manifest, {'secret_versions': [1, 1]}))
            self.assertEqual((dest / 'database.dump').read_bytes(), dump.read_bytes())

    def test_traversal_links_duplicate_and_private_key_members_are_rejected(self):
        for bad_name, kind in [('../outside', tarfile.REGTYPE), ('database.dump', tarfile.SYMTYPE),
                                ('recovery.key', tarfile.REGTYPE), ('manifest.json', tarfile.REGTYPE)]:
            with self.subTest(name=bad_name, kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); archive = root / 'bad.tar'
                with tarfile.open(archive, 'w') as stream:
                    for name in ['database.dump', 'manifest.json', bad_name]:
                        item = tarfile.TarInfo(name); item.type = kind if name == bad_name else tarfile.REGTYPE
                        data = b'bad'; item.size = len(data)
                        stream.addfile(item, io.BytesIO(data))
                with self.assertRaises(ValueError): common.unpack(archive, root)
                self.assertFalse((root.parent / 'outside').exists())

    def test_dump_content_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); dump = root / 'source'; dump.write_bytes(b'PGDMP' + b'x' * 100)
            manifest = {'format': 'accounting-s10-v1', 'dump_sha256': 'sha256:' + '0' * 64}
            archive = root / 'archive.tar'
            with archive.open('wb') as output: common.write_archive(output, dump, manifest, {})
            with self.assertRaises(ValueError): common.unpack(archive, root)

    def test_crc32c_uses_standard_castagnoli_check_vector(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'vector'; path.write_bytes(b'123456789')
            self.assertEqual(common.crc32c_file(path), '4waSgw==')


class StorageTests(unittest.TestCase):
    def test_receipt_rejects_private_material_and_preserves_a_recoverable_old_backup(self):
        config = configuration(); item = receipt(config)
        item.update(uploaded_at=common.now(), operations_commit='b' * 40, image=config['preview']['published']['image'], manifest_sha256='sha256:' + '2' * 64)
        with patch.object(common, 'api') as api, self.assertRaises(ValueError):
            common.upload_receipt(config, {**item, 'local_identity': '/synthetic/private.key'})
        api.assert_not_called()
        item['snapshot_started_at'] = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        common.validate_receipt(item, config, max_age=None)
        with self.assertRaises(ValueError): common.validate_receipt(item, config)

    def test_failed_upload_keeps_previous_success_and_cleans_all_new_payloads(self):
        config = configuration()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = root / 'data'; data.mkdir(); (data / 'media').mkdir()
            runtime = root / 'runtime'; runtime.mkdir()
            previous = {'last_success': receipt(config), 'last_attempt_ok': True}
            state = data / 'state.json'; state.write_text(json.dumps(previous))
            def dump(psql, command, target, env):
                target.write_bytes(b'PGDMP' + b'x' * 100)
                return {'snapshot_started_at': common.now(), 'dump_sha256': common.sha(target), 'tables': []}
            def encrypted(dump, manifest, recovery, recipient, output): output.write_bytes(b'age-encryption.org/v1\n')
            def run(command, **kwargs): return b'v1.3.2' if command == ['age', '--version'] else b'170011\n'
            with patch.object(host, 'check'), patch.object(host, 'runtime'), patch.object(host, 'RUNTIME', runtime), \
                 patch.object(host, 'DATA', data), patch.object(common, 'STATE', state), patch.object(host.preview, 'HOST_DATA', data), \
                 patch.object(common, 'run', side_effect=run), patch.object(pg, 'dump', side_effect=dump), \
                 patch.object(host, 'encrypt', side_effect=encrypted), patch.object(common, 'upload', side_effect=common.APIError(403)), \
                 redirect_stderr(io.StringIO()), self.assertRaises(common.APIError):
                host.backup(config)
            current = json.loads(state.read_text())
            self.assertEqual(current['last_success'], previous['last_success'])
            self.assertFalse(current['last_attempt_ok'])
            self.assertFalse(list(runtime.glob('plaintext-*')))
            self.assertFalse(list(data.glob('pending-*')))

    def test_plaintext_never_reaches_upload(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(common, 'api') as api:
            path = Path(temporary) / 'database.dump'; path.write_bytes(b'PGDMP' + b'x' * 100)
            with self.assertRaises(ValueError): common.upload(configuration(), path, receipt(configuration())['object'])
            api.assert_not_called()

    def test_upload_is_create_only_and_requires_generation_size_and_crc(self):
        config = configuration(); name = receipt(config)['object']
        with tempfile.TemporaryDirectory() as temporary, patch.object(common.preview, 'access_token', return_value='synthetic-token'):
            path = Path(temporary) / 'cipher.age'; path.write_bytes(b'age-encryption.org/v1\n' + b'x' * 100)
            seen = []
            def api(method, url, token, stream, **kwargs):
                seen.append((method, url, stream.read(), kwargs['headers']))
                return {'bucket': config['bucket'], 'name': name, 'size': str(path.stat().st_size), 'generation': '123', 'crc32c': common.crc32c_file(path)}
            with patch.object(common, 'api', side_effect=api):
                result = common.upload(config, path, name)
            self.assertEqual(result['sha256'], common.sha(path))
            self.assertIn('ifGenerationMatch=0', seen[0][1])
            self.assertEqual(seen[0][2], path.read_bytes())
            self.assertEqual(seen[0][3]['Content-Length'], str(path.stat().st_size))
            for field, value in [('crc32c', 'AAAAAA=='), ('generation', '0'), ('name', 'elsewhere')]:
                response = {'bucket': config['bucket'], 'name': name, 'size': str(path.stat().st_size), 'generation': '123', 'crc32c': common.crc32c_file(path)}
                response[field] = value
                with self.subTest(field=field), patch.object(common, 'api', return_value=response), self.assertRaises(ValueError):
                    common.upload(config, path, name)

    def test_existing_object_conflict_is_not_retried_as_overwrite(self):
        config = configuration()
        with tempfile.TemporaryDirectory() as temporary, patch.object(common.preview, 'access_token', return_value='synthetic-token'):
            path = Path(temporary) / 'cipher.age'; path.write_bytes(b'age-encryption.org/v1\n' + b'x' * 100)
            with patch.object(common, 'api', side_effect=common.APIError(412)) as api, self.assertRaises(common.APIError):
                common.upload(config, path, receipt(config)['object'])
            self.assertEqual(api.call_count, 1)

    def test_stale_future_cross_key_and_cross_project_receipts_fail(self):
        config = configuration()
        for key, value in [('snapshot_started_at', (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()),
                           ('snapshot_started_at', (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
                           ('project_id', 'another-project'), ('recipient_id', 'sha256:' + '0' * 64), ('object', '../database.dump')]:
            value_receipt = receipt(config); value_receipt[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): common.validate_receipt(value_receipt, config)

    def test_provider_text_and_unreviewed_diagnostics_are_not_echoed(self):
        canary = 'S10-sensitive-output-canary'
        result = subprocess.CompletedProcess(['gcloud'], 1, b'', (canary + '\nS10-DIAG ' + json.dumps({
            'stage': 'backup-upload', 'error': 'APIError', 'reason': canary, 'http_status': 403})).encode())
        error = common.CommandFailure(['gcloud'], result)
        self.assertNotIn(canary, str(error)); self.assertIn('backup-upload', str(error)); self.assertIn('403', str(error))


class ObservationTests(unittest.TestCase):
    def test_missing_stale_failed_and_resource_pressure_are_visible(self):
        config = configuration(); clock = datetime.now(timezone.utc).timestamp()
        values = host.observe(config, {}, {'MemAvailable': 10, 'MemTotal': 100}, [0.1, 0.9], 86400, False, clock)
        self.assertGreater(values['backup_age_seconds'], 86400)
        self.assertEqual(values['backup_last_attempt_ok'], 0)
        self.assertEqual(values['disk_used_ratio'], 0.9)
        self.assertEqual(values['memory_used_ratio'], 0.9)
        self.assertEqual(values['readiness'], 0)

    def test_failed_attempt_does_not_reset_age_of_previous_success(self):
        config = configuration(); current = receipt(config)
        state = {'last_success': current, 'last_attempt_ok': False}
        clock = common.timestamp(current['snapshot_started_at']) + 23 * 3600
        values = host.observe(config, state, {'MemAvailable': 50, 'MemTotal': 100}, [0.1], 1e7, True, clock)
        self.assertEqual(values['backup_age_seconds'], 23 * 3600)
        self.assertEqual(values['backup_last_attempt_ok'], 0)

    def test_monitor_payload_is_bounded_to_selected_instance_and_numeric_values(self):
        config = configuration()
        payload = host.metric_payload(config, {name: 1 for name in common.METRIC_NAMES})
        self.assertEqual(len(payload['timeSeries']), 8)
        for series in payload['timeSeries']:
            self.assertEqual(series['resource']['labels']['instance_id'], config['instance_id'])
            self.assertEqual(series['valueType'], 'DOUBLE')
            self.assertNotIn('labels', series['metric'])
        self.assertNotIn(config['alert_email'], json.dumps(payload))

    def test_transient_alert_test_expires(self):
        values = host.observe(configuration(), {'alert_probe_until': 100}, {'MemAvailable': 1, 'MemTotal': 2}, [0], 1, True, at=101)
        self.assertEqual(values['alert_probe'], 0)


class CloudTests(unittest.TestCase):
    def test_receipt_discovery_needs_no_source_vm_and_ignores_partial_backups(self):
        config = configuration(); item = receipt(config)
        name = item['object'].removesuffix('.tar.age') + '.receipt.json'
        client = object.__new__(cloud.Client); client.token = 'synthetic-token'
        results = [{'items': [{'name': item['object'], 'generation': '100'}, {'name': name, 'generation': '101'}]}, item]
        with patch.object(cloud, 'Client', return_value=client), patch.object(common, 'api', side_effect=results) as api:
            self.assertEqual(cloud.latest_receipt(config), item)
        self.assertEqual(api.call_count, 2)
        self.assertIn('generation=101', api.call_args_list[1].args[1])

    def test_backup_lifecycle_cannot_delete_other_prefixes(self):
        rule = cloud.lifecycle(configuration())['rule'][0]
        self.assertEqual(rule['condition']['matchesPrefix'], ['s10/v1/'])
        self.assertEqual(rule['condition']['age'], 30)

    def test_external_check_and_missing_metrics_policy_survive_a_dead_vm(self):
        config = configuration(); check = cloud.uptime(config)
        self.assertTrue(check['httpCheck']['useSsl']); self.assertTrue(check['httpCheck']['validateSsl'])
        self.assertEqual(check['monitoredResource']['labels']['host'], 'totalaccounting.duckdns.org')
        policies = cloud.policies(config, 'projects/accounting-514109/notificationChannels/123', 'projects/accounting-514109/uptimeCheckConfigs/check')
        self.assertEqual(len(policies), 9)
        self.assertTrue(any('conditionAbsent' in p['conditions'][0] for p in policies))
        self.assertTrue(any('uptime_check/check_passed' in json.dumps(p) for p in policies))

    def test_cloud_retry_reuses_exact_configuration_and_rejects_conflicts(self):
        config = configuration(); client = object.__new__(cloud.Client)
        desired = cloud.uptime(config); existing = {**copy.deepcopy(desired), 'name': 'projects/example/uptimeCheckConfigs/1'}
        with patch.object(client, 'listing', return_value=[existing]), patch.object(client, 'call') as call:
            self.assertEqual(client.ensure('uptimeCheckConfigs', desired), existing)
            call.assert_not_called()
        existing['httpCheck']['validateSsl'] = False
        with patch.object(client, 'listing', return_value=[existing]), self.assertRaises(ValueError):
            client.ensure('uptimeCheckConfigs', desired)

    def test_duplicate_display_names_do_not_create_another_resource(self):
        client = object.__new__(cloud.Client); desired = cloud.uptime(configuration())
        with patch.object(client, 'listing', return_value=[desired, desired]), patch.object(client, 'call') as call, self.assertRaises(ValueError):
            client.ensure('uptimeCheckConfigs', desired)
        call.assert_not_called()


class RecoveryTests(unittest.TestCase):
    def test_native_incomplete_nonisolated_and_wrong_image_proof_cannot_complete_gate(self):
        config = configuration(); r = receipt(config); r['image'] = config['preview']['published']['image']
        valid = {'status': 'Restored', 'mode': 'off-vm-gcs-download-local-docker', 'all_public_tables_match': True,
                 'separate_recovery_key_used': True, 'recovery_container_removed': True, 'plaintext_removed': True,
                 'restore_seconds': 3, 'preview_database_modified': False, 'receipt': r,
                 'isolation': {'network': 'none', 'published_ports': [], 'persistent_mounts': []}}
        verify_s10.check_restore(config, valid)
        for key, value in [('mode', 'native-postgresql17-age'), ('separate_recovery_key_used', False),
                            ('restore_seconds', 8 * 3600 + 1), ('preview_database_modified', True)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                bad = copy.deepcopy(valid); bad[key] = value; verify_s10.check_restore(config, bad)
        bad = copy.deepcopy(valid); bad['isolation']['network'] = 'host'
        with self.assertRaises(ValueError): verify_s10.check_restore(config, bad)

    def test_record_updates_only_s10_and_preserves_verified_s09(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'evidence').mkdir()
            for name in ('steps.csv', 'state.md', 'traceability.csv'):
                (root / name).write_bytes((verify_s10.RECORDS / name).read_bytes())
            with patch.object(verify_s10, 'RECORDS', root):
                verify_s10.record({'mode': 'offline', 'status': 'Prepared', 'safeguard_tests': 1})
            import csv
            rows = list(csv.DictReader((root / 'steps.csv').open()))
            self.assertEqual(next(r for r in rows if r['step_id'] == 'S09')['status'], 'Verified')
            self.assertEqual(next(r for r in rows if r['step_id'] == 'S10')['status'], 'Prepared')

    def test_changed_recovered_table_is_denied(self):
        expected = [{'table': 'public.synthetic', 'rows': 1, 'checksum': '1' * 32}]
        actual = [{'table': 'public.synthetic', 'rows': 0, 'checksum': '2' * 32}]
        with patch.object(common, 'run', return_value=(json.dumps(actual[0]) + '\nS10-END\n').encode()), self.assertRaises(ValueError):
            pg.verify_tables(['psql'], expected)

    def test_restore_requires_separate_recovered_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / 'key'; key.write_text('synthetic'); key.chmod(0o600)
            config = configuration(); config['local_identity'] = str(key)
            with patch.object(common, 'check_age'), self.assertRaises(ValueError): recovery.restore(config, receipt(config), key)

    def test_wrong_recovered_key_does_not_download_or_start_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            key = Path(temporary) / 'key'; key.write_text('synthetic'); key.chmod(0o600)
            config = configuration(); config['local_identity'] = str(Path(temporary) / 'lost-primary')
            with patch.object(common, 'check_age'), patch.object(common, 'run', return_value=b'age1wrong'), patch.object(recovery, 'download') as download, self.assertRaises(ValueError):
                recovery.restore(config, receipt(config), key)
            download.assert_not_called()

    def test_backup_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(host, 'RUNTIME', Path(temporary)), patch.object(host, 'runtime'):
            with host.lock():
                with self.assertRaises(RuntimeError):
                    with host.lock(): pass

    def test_units_schedule_backups_and_bound_operator_logs(self):
        root = common.ROOT / 'infrastructure/operations'
        timer = (root / 'accounting-backup.timer').read_text()
        self.assertIn('Persistent=true', timer); self.assertIn('02,14:15:00 UTC', timer)
        self.assertIn('OnActiveSec=30s', timer)
        journal = (root / 'journald.conf').read_text()
        self.assertIn('SystemMaxUse=16M', journal); self.assertIn('MaxRetentionSec=14day', journal)
        for name in ('accounting-monitor.service', 'accounting-backup.service'):
            unit = (root / name).read_text()
            self.assertIn('RequiresMountsFor=/srv/accounting', unit)
            self.assertIn('UMask=0077', unit); self.assertIn('LogNamespace=accounting-ops', unit)


if __name__ == '__main__':
    unittest.main()
