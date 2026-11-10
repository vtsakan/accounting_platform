#!/usr/bin/env python3
"""S10 local safeguards or actual scheduled/upload/restore/alert evidence."""

import argparse
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import time
import unittest
from zoneinfo import ZoneInfo

from cloud import require
import image
import operations_common as common
import operations_cloud as cloud
import operations
import preview_common as preview
import preview_http

BASE = 'eced8ea70e26f410ce2d234e41169d3fc05f529b'
RECORDS = common.ROOT / 'docs/implementation'


def offline():
    gate = json.loads((RECORDS / 'evidence/S09-verification.json').read_text())
    require(gate['status'] == 'Verified' and gate['reboot_persistence_verified'], 'Actual S09 public/reboot proof is required')
    with (RECORDS / 'traceability.csv').open(newline='') as stream:
        requirements = list(csv.DictReader(stream))
    require(len(requirements) == 85 and all(r['acceptance_status'] == 'Pending' for r in requirements), 'Full release acceptance must remain Pending')
    names = common.run(['git', '-C', common.ROOT, 'ls-files', '--cached', '--others', '--exclude-standard', '-z']).decode().split('\0')
    files = {name: (common.ROOT / name).read_bytes() for name in names if name and image.allowed(name)}
    _, context = image.archive(files)
    require(context['digest'] == gate['image']['context_digest'], 'S10 changes the verified application image context')
    for name in ('requirements.txt', 'requirements-tools.txt', 'compose.production.yml'):
        require((common.ROOT / name).read_bytes() == common.run(['git', '-C', common.ROOT, 'show', BASE + ':' + name]), 'Application locks or production Compose changed')
    suite = unittest.defaultTestLoader.discover(str(common.ROOT / 'tools'), pattern='test_s10.py')
    output = io.StringIO(); result = unittest.TextTestRunner(stream=output).run(suite)
    require(result.wasSuccessful() and result.testsRun > 0, 'S10 safeguard tests failed:\n' + output.getvalue())
    return {'mode': 'offline', 'status': 'Prepared', 'safeguard_tests': result.testsRun,
            'application_context_digest': context['digest'], 'application_migrations_locks_unchanged': True,
            'actual_cloud_execution': False, 'actual_docker_execution': False, 'full_acceptances_pending': 85}


def live(config, confirmed):
    require(confirmed, 'Run the explicit alert-test and pass --confirm-alert-received only after receiving its notification')
    status = operations.ssh(config, 'status')
    require(status['operations_commit'] == config['code_commit'], 'VM operations source differs')
    require(all(status['timers_enabled'].get(unit) == 'enabled' and status['timers_active'].get(unit) == 'active' for unit in common.UNITS), 'Backup/monitor timers are not enabled and active')
    require(status['scheduled_backup_trigger_observed'], 'The first backup timer has not fired yet; retry after the initial one-minute window')
    require(status['backup_service_result'] == 'success' and status['backup_service_state'] == 'inactive', 'The scheduled backup service is still running or failed')
    require(status['backup']['last_attempt_ok'], 'The latest backup attempt failed')
    common.validate_receipt(status['backup']['last_success'], config)
    require(status['effective_backup_permissions'] == ['storage.objects.create'] and status['backup_read_and_list_denied'], 'VM backup read/delete authority differs')
    monitor = status['monitor']
    require(monitor and monitor['metrics_published'] and 0 <= time.time() - common.timestamp(monitor['observed_at']) <= 900, 'Host observations are missing/stale')
    require(monitor['values']['readiness'] == 1 and monitor['values']['certificate_seconds'] > 86400, 'Readiness/certificate observation failed')
    restored = json.loads((common.ROOT / 'private/s10-restore.json').read_text())
    check_restore(config, restored)
    configured = cloud.inspect(config)
    samples = cloud.observed(config)
    certificate = preview_http.certificate(config['preview']['hostname'])
    require(preview_http.ssl.cert_time_to_seconds(certificate['not_after']) > time.time() + 86400, 'Public certificate expires within one day')
    return {'step': 'S10', 'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
            'status': 'Verified', 'mode': 'operator-gcs-docker-restore-monitoring', 'operations_commit': 'git:' + config['code_commit'],
            'source_reference_commit': 'git:' + BASE, 'image': config['preview']['published']['image'],
            'scheduled_backup_trigger_observed': True, 'latest_backup': status['backup']['last_success'],
            'vm_create_only_backup_access': True, 'monitoring': {**configured, **samples}, 'restore': restored,
            'alert_delivery': {'operator_confirmed_received': True, 'confirmed_at': common.now()},
            'named_operators_and_preview_retention_recorded_privately': True, 'public_certificate': certificate,
            'application_accounts_created': False, 'real_client_data_imported': False,
            'document_recovery': 'Deferred to S38; current private media must be empty',
            'accepted_dataset_rpo_rto': 'Pending', 'full_requirement_acceptance': 'Pending'}


def check_restore(config, restored):
    require(restored['mode'] == 'off-vm-gcs-download-local-docker' and restored['status'] == 'Restored'
            and all(restored[k] is True for k in ('all_public_tables_match', 'separate_recovery_key_used', 'recovery_container_removed', 'plaintext_removed'))
            and restored['restore_seconds'] <= 8 * 3600 and restored['preview_database_modified'] is False,
            'A complete isolated off-VM restore is required')
    require(restored['isolation']['network'] == 'none' and restored['isolation']['published_ports'] == []
            and restored['isolation']['persistent_mounts'] == [], 'Restore was not isolated from persistent/networked data')
    common.validate_receipt(restored['receipt'], config)
    require(restored['receipt']['image'] == config['preview']['published']['image'], 'Restore proof belongs to another application image')


def record(report):
    path = RECORDS / 'evidence/S10-verification.json'
    old = json.loads(path.read_text()) if path.exists() else {}
    if report.get('mode') == 'offline':
        old.update(step='S10', status=old.get('status', 'Prepared'), repository_checks=report)
        report = old
    else:
        for key in ('repository_checks', 'native_recovery_checks', 'secret_scan'):
            report[key] = old.get(key, {})
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with (RECORDS / 'steps.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    row = next(r for r in rows if r['step_id'] == 'S10')
    status = report['status']
    row.update(status=status, branch='step/s10-backup-restore', code_reference_commit=report.get('operations_commit', '').removeprefix('git:'),
               evidence='docs/implementation/evidence/S10-verification.json; docs/implementation/backup_restore.md',
               blocker='' if status == 'Verified' else 'Execute selected cloud/timers, scheduled encrypted upload, off-VM Docker restore with recovered key and observed alert',
               manual_acceptance='Synthetic recovery only; business retention and full release acceptance remain Pending',
               next_step='S11' if status == 'Verified' else 'Complete S10 operator recovery/observation gate')
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
    (RECORDS / 'steps.csv').write_text(stream.getvalue())
    trace = RECORDS / 'traceability.csv'
    with trace.open(newline='') as stream:
        requirements = list(csv.DictReader(stream))
    for requirement in requirements:
        if requirement['requirement_id'] not in {'QR-09', 'QR-12'}:
            continue
        evidence = 'docs/implementation/evidence/S10-verification.json; docs/implementation/backup_restore.md'
        if 'docs/implementation/evidence/S10-verification.json' not in requirement['evidence']:
            requirement['evidence'] = (requirement['evidence'] + '; ' + evidence).lstrip('; ')
        note = ('S10 operator-Verified: scheduled encrypted GCS backup, recovered-key isolated laptop restore, external observations and confirmed alert receipt; accepted dataset/full release acceptance remain Pending.'
                if status == 'Verified' else 'S10 Prepared: encrypted backup/receipt, create-only upload, recovered-key isolated restore, timers and Monitoring are implemented; native PG17/age proof is separate from pending operator cloud/Docker/alert execution.')
        if note not in requirement['notes']:
            requirement['notes'] += ' ' + note
        requirement['last_reviewed'] = str(datetime.now(ZoneInfo('Europe/Athens')).date())
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=requirements[0], lineterminator='\n'); writer.writeheader(); writer.writerows(requirements)
    trace.write_text(stream.getvalue())
    state = RECORDS / 'state.md'
    import re
    content = state.read_text()
    headline = f"Updated {datetime.now(ZoneInfo('Europe/Athens')).date()}. Current step: **S10 {status} — backup and operating checks**. Next step: **{'S11 — offices and accountant profiles' if status == 'Verified' else 'complete S10 operator recovery and alert proof'}**."
    content = re.sub(r'Updated .*?\n', headline + '\n', content, count=1)
    state.write_text(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--confirm-alert-received', action='store_true')
    parser.add_argument('--record', action='store_true')
    parser.add_argument('--config', type=Path, default=common.PRIVATE)
    args = parser.parse_args()
    try:
        report = live(common.validate(json.loads(args.config.read_text()), local=True), args.confirm_alert_received) if args.live else offline()
        if args.record:
            record(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except Exception as error:
        detail = str(error) if type(error) in (ValueError, RuntimeError) or isinstance(error, (common.APIError, common.CommandFailure)) else 'Details omitted; inspect the named operation'
        parser.exit(1, f'S10 verification stopped ({type(error).__name__}): {detail}\n')


if __name__ == '__main__':
    main()
