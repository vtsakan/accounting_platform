#!/usr/bin/env python3
"""S10 laptop setup, deployment, observation and isolated recovery commands."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile

from cloud import require
import image
import operations_common as common
import operations_cloud as cloud
import preview_common as preview


def gcloud(config, *arguments, json_output=False):
    command = ['gcloud', *arguments, '--project=' + config['preview']['gcp']['project_id'], '--quiet']
    output = common.run(command, environment={**os.environ, 'CLOUDSDK_CORE_LOG_HTTP': 'false'}, timeout=900)
    return json.loads(output) if json_output else output


def ssh(config, action):
    require(action in {'backup', 'monitor', 'status', 'alert-test'}, 'Unsupported VM operations action')
    p = config['preview']['gcp']
    command = shlex.join(['sudo', '-n', '/usr/local/sbin/accounting-operations', action])
    if action == 'backup':
        command = shlex.join(['sudo', '-n', 'systemctl', 'start', 'accounting-backup.service']) + ' && ' + shlex.join(['sudo', '-n', '/usr/local/sbin/accounting-operations', 'status'])
    return gcloud(config, 'compute', 'ssh', p['ssh_user'] + '@' + p['vm_name'], '--zone=' + p['zone'],
                  '--tunnel-through-iap', '--command=' + command, json_output=True)


def question(label, default=None):
    value = input(label + (f' [{default}]' if default is not None else '') + ': ').strip()
    return value or default or ''


def configure(path):
    require(not path.exists(), 'S10 configuration already exists; inspect it instead of replacing keys/policy')
    gate = json.loads((common.ROOT / 'docs/implementation/evidence/S09-verification.json').read_text())
    require(gate['status'] == 'Verified' and gate['reboot_persistence_verified'], 'Complete the real S09 public/reboot gate first')
    p = preview.validate(json.loads(preview.PRIVATE.read_text()), published=True)
    require(gate['image']['image'] == p['published']['image'], 'S09 proof refers to another image')
    require(shutil.which('age') and shutil.which('age-keygen'), 'Run tools/install_age.py on your laptop and add its directory to PATH')
    common.check_age()
    default_identity = Path.home() / '.config/totalaccounting/backup-age.key'
    identity = Path(question('Primary decryption identity path, outside Git', str(default_identity))).expanduser().resolve()
    require(not identity.is_relative_to(common.ROOT.resolve()), 'Keep recovery keys outside the repository')
    if not identity.exists():
        identity.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Reserve the path atomically. Concurrent setup must never replace a key.
        with open(identity, 'x', opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
            try:
                common.run(['age-keygen'], output=output)
            except Exception:
                identity.unlink(missing_ok=True)
                raise
    common.identity_file(identity)
    recipient = common.run(['age-keygen', '-y', identity]).decode().strip()
    print('The VM receives only the public recipient. The identity file above stays on your laptop.')
    print('Save an independent recovery copy in your password manager or offline storage before continuing.')
    require(question('Independent recovery copy saved outside this VM/laptop? Type yes') == 'yes', 'Save a recovery copy before configuring S10; the primary key was retained')
    incident = question('Incident owner (person responsible for alerts)')
    restore = question('Restore owner', incident)
    custodian = question('Recovery key custodian', incident)
    email = question('Operational alert email (Monitoring will use this destination)')
    print('Preview backup objects are deleted by a prefix-scoped lifecycle rule. Seven-day soft deletion is additional.')
    days = int(question('Synthetic backup retention in days, 7 to 90', '30'))
    require(question('Accept these synthetic-preview retention and operator assignments? Type yes') == 'yes', 'Preview policy was not confirmed')
    inventory = json.loads((common.ROOT / 'docs/implementation/cloud_inventory.json').read_text())
    config = {'schema': 1, 'preview': p, 'bucket': p['gcp']['backup_bucket'], 'prefix': common.PREFIX,
              'recipient': recipient, 'recipient_id': common.recipient_id(recipient), 'local_identity': str(identity),
              'instance_id': inventory['vm']['instance_id'], 'retention_days': days, 'max_dump_bytes': common.MAX_DUMP,
              'synthetic_only': True, 'policy_confirmed': True, 'separate_key_copy_confirmed': True,
              'incident_owner': incident, 'restore_owner': restore, 'key_custodian': custodian, 'alert_email': email,
              'policy_confirmed_at': common.now()}
    common.validate(config, local=True)
    preview.private_json(path, config, exclusive=True)
    return {'status': 'Configured', 'private_config': str(path), 'recipient_id': config['recipient_id'],
            'retention_days': days, 'cloud_or_vm_changed': False}


def install(config, path):
    require(config.get('cloud'), 'Run operations.py cloud before VM installation')
    revision, _, context = image.committed_context()
    require(context['digest'] == config['preview']['published']['context_digest'], 'Application context changed; S10 must reuse the verified S09 image')
    config['code_commit'] = revision
    preview.private_json(path, config)
    p = config['preview']['gcp']
    with tempfile.TemporaryDirectory(prefix='accounting-s10-source-') as temporary:
        stage = Path(temporary) / 'accounting-s10-stage'
        (stage / 'tools').mkdir(parents=True)
        (stage / 'docs/implementation').mkdir(parents=True)
        bundle = stage / 'source.tar'
        bundle.write_bytes(common.run(['git', '-C', common.ROOT, 'archive', '--format=tar', revision]))
        for name in ('operations_host.py', 'operations_common.py', 'operations_pg.py', 'preview_host.py',
                     'preview_common.py', 'preview_events.py', 'cloud.py'):
            (stage / 'tools' / name).write_bytes(common.run(['git', '-C', common.ROOT, 'show', revision + ':tools/' + name]))
        inventory = 'docs/implementation/cloud_inventory.json'
        (stage / inventory).write_bytes(common.run(['git', '-C', common.ROOT, 'show', revision + ':' + inventory]))
        preview.private_json(stage / 'operations.json', common.host_config(config))
        # Stable staging is removed only after installation; interrupted transfers
        # can be inspected and retried. No private identity enters this directory.
        remote = p['ssh_user'] + '@' + p['vm_name']
        gcloud(config, 'compute', 'scp', '--recurse', stage, remote + ':~/', '--zone=' + p['zone'], '--tunnel-through-iap')
        args = ['sudo', '-n', 'python3', 'accounting-s10-stage/tools/operations_host.py', 'install',
                '--config', 'accounting-s10-stage/operations.json', '--bundle', 'accounting-s10-stage/source.tar', '--sha256', common.sha(bundle)]
        result = gcloud(config, 'compute', 'ssh', remote, '--zone=' + p['zone'], '--tunnel-through-iap',
                        '--command=' + shlex.join(args), json_output=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('configure', 'cloud-plan', 'cloud', 'install', 'backup', 'monitor', 'status', 'latest', 'restore', 'alert-test'))
    parser.add_argument('--config', type=Path, default=common.PRIVATE)
    parser.add_argument('--identity', type=Path, help='Separately recovered age identity, outside Git (restore only)')
    parser.add_argument('--receipt', type=Path, help='Saved object receipt; restore can run without source-VM access')
    args = parser.parse_args()
    try:
        if args.action == 'configure':
            result = configure(args.config)
        else:
            config = common.validate(json.loads(args.config.read_text()), local=True)
            if args.action == 'cloud-plan':
                result = {'lifecycle': cloud.lifecycle(config), 'uptime': cloud.uptime(config),
                    'metrics': cloud.descriptors(), 'policies': cloud.policies(config, 'CHANNEL_ID', 'UPTIME_CHECK_ID'),
                    'new_vm_project_role': 'roles/monitoring.metricWriter', 'backup_bucket_vm_role': 'roles/storage.objectCreator'}
                target = common.ROOT / 'private/s10-cloud-plan.json'
                preview.private_json(target, result)
                result = {'status': 'Rendered', 'private_plan': str(target), 'cloud_changed': False}
            elif args.action == 'cloud':
                config['cloud'] = cloud.apply(config)
                preview.private_json(args.config, config)
                result = {'status': 'Configured', 'monitoring': config['cloud'], 'alert_receipt': 'Pending explicit alert-test and operator observation'}
            elif args.action == 'install':
                result = install(config, args.config)
            elif args.action == 'restore':
                from operations_recovery import restore
                require(args.identity is not None, 'Pass --identity with your independently recovered key file')
                receipt = json.loads(args.receipt.read_text()) if args.receipt else cloud.latest_receipt(config)
                result = restore(config, receipt, args.identity)
                preview.private_json(common.ROOT / 'private/s10-restore.json', result)
            elif args.action == 'latest':
                result = cloud.latest_receipt(config)
                preview.private_json(common.ROOT / 'private/s10-backup-receipt.json', result)
            else:
                result = ssh(config, args.action)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        # Internal literal errors are useful; arbitrary provider/SSH output is not.
        message = str(error) if type(error) in (ValueError, RuntimeError) or isinstance(error, (common.APIError, common.CommandFailure)) else 'Operation failed; payload omitted'
        parser.exit(1, f'S10 stopped ({type(error).__name__}): {message}\n')


if __name__ == '__main__':
    main()
