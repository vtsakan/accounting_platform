#!/usr/bin/env python3
"""Operator S24A VM image-only release using the existing 661-test production image."""
import argparse
from copy import deepcopy
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import urllib.request

from cloud import require
from dev import require_local_docker
import image
import preview_common as common
import preview_events as events
import operations_common as oc
import vm_material_common as policy

ROOT = common.ROOT
CONFIG = ROOT / 'private/vm-s24a-release.json'
STAGE = 'accounting-s24a-ui-stage'


def gcloud(config, *arguments, json_output=False):
    result = subprocess.run(['gcloud', *map(str, arguments), '--project=' + config['gcp']['project_id'], '--quiet'],
        stdin=subprocess.DEVNULL, capture_output=True, env={**os.environ, 'CLOUDSDK_CORE_LOG_HTTP': 'false'})
    if result.returncode: raise common.CommandFailure(['gcloud'], result)
    return json.loads(result.stdout) if json_output else result.stdout


def ssh(config, command, json_output=True):
    gcp = config['gcp']
    return gcloud(config, 'compute', 'ssh', gcp['ssh_user'] + '@' + gcp['vm_name'], '--zone=' + gcp['zone'],
                  '--tunnel-through-iap', '--command=' + command, json_output=json_output)


def gate():
    events.checkpoint('ui-source')
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(),
            'Commit reviewed code/evidence first; keep private files outside Git')
    revision, _, context = image.committed_context()
    proof = json.loads((ROOT / 'docs/implementation/evidence/S24A-verification.json').read_text())
    path = (ROOT / proof['delivery_receipt']).resolve()
    require(path.is_relative_to((ROOT / 'private').resolve()), 'ui_receipt_binding_mismatch')
    require(common.file_sha(path) == proof['delivery_receipt_sha256'], 'ui_receipt_binding_mismatch')
    delivery = json.loads(path.read_text())
    policy.production_proof(proof, delivery, context['digest'])
    return revision, proof, delivery, path


def publish():
    revision, proof, delivery, path = gate()
    if CONFIG.exists():
        config = json.loads(CONFIG.read_text())
        policy.same_database(config['source'], config['target'])
        require(config['target']['published']['delivery_evidence'] == common.file_sha(path), 'ui_receipt_binding_mismatch')
        return {'status': 'Already published', **config['target']['published']}
    require_local_docker()
    built = delivery['image']
    metadata = image.inspect(built['image_id'])
    require(metadata is not None, 'ui_verified_image_missing')
    labels = metadata['Config'].get('Labels', {})
    tested_commit = built['revision'].removeprefix('git:')
    require(metadata['Id'] == built['image_id'] and metadata['Architecture'] == 'amd64'
            and metadata['Os'] == 'linux' and metadata['Config']['User'] == '10001:10001'
            and labels.get('org.opencontainers.image.revision') == tested_commit
            and labels.get('gr.accounting.source-context') == policy.CONTEXT, 'ui_image_identity_mismatch')
    source = common.validate(ssh(policy.BOOTSTRAP, 'sudo -n cat /etc/accounting/preview.json'), published=True)
    target = deepcopy(source)
    target['deployment_commit'] = revision
    gcp = source['gcp']
    require(source['hostname'] == policy.HOSTNAME and source['published']['context_digest'] == policy.PREVIOUS_CONTEXT
            and all(gcp[key] == value for key, value in policy.BOOTSTRAP['gcp'].items()), 'ui_wrong_target')
    events.checkpoint('ui-publication')
    tag = f"{gcp['region']}-docker.pkg.dev/{gcp['project_id']}/{gcp['repository']}/web:{tested_commit}"
    token = gcloud(source, 'auth', 'print-access-token').strip()
    require(token and b'\n' not in token, 'ui_image_identity_mismatch')
    endpoint = os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
    if not endpoint: endpoint = json.loads(common.run(['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}']))
    environment = {key: value for key, value in os.environ.items() if key != 'DOCKER_CONTEXT'}
    environment['DOCKER_HOST'] = endpoint
    with tempfile.TemporaryDirectory(prefix='accounting-s24a-publish-') as temporary:
        cli = ['docker', '--config', temporary]
        common.run(cli + ['login', tag.split('/')[0], '--username', 'oauth2accesstoken', '--password-stdin'], payload=token, environment=environment)
        common.run(cli + ['tag', built['image_id'], tag], environment=environment)
        pushed = common.run(cli + ['push', tag], environment=environment).decode()
    data = image.inspect(tag)
    repository = tag.rsplit(':', 1)[0]
    digests = [ref for ref in data.get('RepoDigests', []) if ref.startswith(repository + '@sha256:')]
    if not digests:
        matches = set(re.findall(r'\bdigest: (sha256:[0-9a-f]{64})\b', pushed))
        require(len(matches) == 1, 'ui_image_identity_mismatch')
        digests = [repository + '@' + matches.pop()]
    require(len(digests) == 1, 'ui_image_identity_mismatch')
    target['published'] = {'commit': tested_commit, 'image': digests[0], 'image_id': built['image_id'],
                           'context_digest': policy.CONTEXT, 'delivery_evidence': common.file_sha(path)}
    common.validate(target, published=True)
    policy.same_database(source, target)
    require(gate()[0] == revision, 'ui_source_changed')
    common.private_json(CONFIG, {'source': source, 'target': target}, exclusive=True)
    return {'status': 'Published verified image without rebuilding', **target['published'], 'database_or_vm_changed': False}


def host_action(config, action, *arguments):
    command = shlex.join(['sudo', '-n', 'python3', STAGE + '/tools/vm_material_host.py', action, *map(str, arguments)])
    return ssh(config['source'], command)


def transfer(config):
    revision, _, _, _ = gate()
    target = config['target']
    require(revision == common.deployment_commit(target), 'ui_source_changed')
    events.checkpoint('ui-transfer')
    names = ('vm_material_host', 'vm_material_common', 'preview_common', 'preview_host', 'preview_events',
             'operations_common', 'operations_host', 'operations_pg', 'cloud', 'image', 'static_export', 'dev', 'verify_s05', 'init_local_env')
    with tempfile.TemporaryDirectory(prefix='accounting-s24a-transfer-') as temporary:
        directory = Path(temporary) / STAGE
        (directory / 'tools').mkdir(parents=True)
        (directory / 'docs/implementation').mkdir(parents=True)
        bundle = directory / 'source.tar'
        bundle.write_bytes(common.run(['git', 'archive', '--format=tar', revision]))
        for name in names:
            (directory / 'tools' / (name + '.py')).write_bytes(common.run(['git', 'show', revision + ':tools/' + name + '.py']))
        inventory = 'docs/implementation/cloud_inventory.json'
        (directory / inventory).write_bytes(common.run(['git', 'show', revision + ':' + inventory]))
        common.private_json(directory / 'input.json', {**config, 'bundle_sha256': common.file_sha(bundle)})
        ssh(config['source'], 'umask 077; mkdir -p ' + STAGE, json_output=False)
        gcp = config['source']['gcp']
        gcloud(config['source'], 'compute', 'scp', '--recurse', directory, gcp['ssh_user'] + '@' + gcp['vm_name'] + ':~/',
               '--zone=' + gcp['zone'], '--tunnel-through-iap')


def recovery_config(state, identity):
    config = deepcopy(state['target_operations'])
    primary = None
    for name in ('vm-s24-operations.json', 'demo-operations.json', 'operations.json'):
        path = ROOT / 'private' / name
        if path.exists():
            candidate = json.loads(path.read_text())
            if candidate.get('recipient_id') == config['recipient_id'] and candidate.get('local_identity'):
                primary = Path(candidate['local_identity']).expanduser().resolve(); break
    require(primary is not None, 'ui_recovery_key_mismatch')
    recovered = oc.identity_file(identity)
    require(recovered != primary, 'ui_recovery_key_mismatch')
    config['local_identity'] = str(primary)
    oc.validate(config, local=True)
    oc.check_age()
    require(common.run(['age-keygen', '-y', recovered]).decode().strip() == config['recipient'], 'ui_recovery_key_mismatch')
    return config


def public_assets(state):
    base = 'https://' + state['target']['hostname']
    with urllib.request.urlopen(base + '/login/', timeout=25) as response:
        body = response.read().decode()
        require('auth-layout' in body and 'Σύνδεση στην εφαρμογή' in body, 'ui_public_verification_failed')
    for asset in state['static_assets']:
        require(asset['path'].startswith('/static/accounting/workspace/'), 'ui_static_path_rejected')
        with urllib.request.urlopen(base + asset['path'], timeout=25) as response:
            require(response.status == 200 and 'sha256:' + hashlib.sha256(response.read()).hexdigest() == asset['sha256'],
                    'ui_public_verification_failed')
    return {'material_login': True, 'immutable_image_static_assets_verified': len(state['static_assets'])}


def wait_public(hostname):
    for attempt in range(30):
        try:
            with urllib.request.urlopen('https://' + hostname + '/health/ready/', timeout=10) as response:
                require(response.status == 200 and json.load(response) == {'status': 'ready'}, 'ui_public_verification_failed')
            return
        except Exception:
            if attempt == 29: raise RuntimeError('ui_public_verification_failed') from None
            time.sleep(2)


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def record(result, config):
    docs = ROOT / 'docs/implementation'
    public = {'step': 'S24A-VM', 'status': 'Verified', 'verified_at': result['completed_at'],
              'hostname': policy.HOSTNAME, 'application_commit': 'git:' + config['target']['published']['commit'],
              'deployment_commit': 'git:' + common.deployment_commit(config['target']),
              'image': config['target']['published']['image'], 'application_context_digest': policy.CONTEXT,
              'production_tests_previously_passed': 661, 'financial_cases_previously_passed': 36,
              'database_migrated_or_restored_on_vm': False, 'database_restarted_during_release': False,
              'accounts_mfa_or_keys_reset': False, 'all_original_rows_preserved_before_public_activation': True,
              'encrypted_prechange_and_new_binding_backups_created': True,
              'off_vm_restore_tables_match': result['off_vm_restore']['all_public_tables_match'],
              'restore_tables_checked': result['off_vm_restore']['tables_checked'],
              'public_checks': result['public_checks'], 'actual_browser_mfa_acceptance': 'Pending operator login',
              'full_requirement_acceptance': 'Pending', 'agent_vm_or_test_execution': False}
    (docs / 'evidence/S24A-VM-verification.json').write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\n')
    path = docs / 'state.md'
    text = path.read_text()
    current = '<!-- S24A-RESULT -->\nOperator production-image gate Verified: 661 passes and all 36 finance cases.\n'
    current += 'Local preview and VM Material image/static deployment are now operator-Verified;\n'
    current += 'the same VM database, original rows/accounts/MFA and pinned credentials were\n'
    current += 'retained before public activation. Encrypted backups, exact off-VM restore and\n'
    current += 'public HTTPS/CSRF/static checks passed. Browser/MFA/responsive/dark-theme/full\n'
    current += 'S47 acceptance remains Pending. S25 is separate.\n<!-- /S24A-RESULT -->'
    text = re.sub(r'<!-- S24A-RESULT -->.*?<!-- /S24A-RESULT -->', lambda _: current, text, flags=re.S)
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + public['verified_at'][:10] +
        '. Current step: **S24A Verified — local and VM Material workspace**. Next step: **Browser/client review; S25 remains separate**.\n', text, count=1)
    note = '<!-- S24A-VM-RESULT -->\nOperator S24A VM image-only deployment Verified: same 20-migration database,\n'
    note += 'all original rows/credentials/MFA retained before public activation, encrypted\nbackups and exact off-VM restore, Greek Material login, HTTPS/CSRF and same-image\nstatic assets. Browser/MFA/accessibility/full acceptance remains Pending.\n<!-- /S24A-VM-RESULT -->'
    text = re.sub(r'<!-- S24A-VM-RESULT -->.*?<!-- /S24A-VM-RESULT -->', lambda _: note, text, flags=re.S) if '<!-- S24A-VM-RESULT -->' in text else text.replace('## Current selected work — S24A', '## Current selected work — S24A\n\n' + note, 1)
    path.write_text(text)
    path = docs / 'steps.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S24A')
    row['manual_acceptance'] = 'Operator VM image/static release, unchanged DB and off-VM restore passed; browser MFA/responsive/accessibility acceptance Pending'
    write_csv(path, rows)
    path = docs / 'traceability.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] in {'QR-07', 'QR-08', 'UR-LOC-01'}:
            note = ' S24A VM operator image/static deployment, unchanged database, off-VM restore and HTTPS/CSRF passed; browser/full acceptance Pending.'
            if note not in row['notes']: row['notes'] += note
            row['evidence'] += '; docs/implementation/evidence/S24A-VM-verification.json' if 'S24A-VM-verification.json' not in row['evidence'] else ''
            row['last_reviewed'] = public['verified_at'][:10]
    write_csv(path, rows)
    # Only validated public image/Git provenance, never a discovered credential.
    path = ROOT / 'docs/security/secret_scan_allowlist.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream)); fields = list(rows[0])
    existing = {(row['detector'], row['fingerprint']) for row in rows}
    for value in (public['application_commit'][4:], public['deployment_commit'][4:], public['image'].rsplit(':', 1)[1]):
        fingerprint = hashlib.sha1(value.encode()).hexdigest()
        if ('Hex High Entropy String', fingerprint) not in existing:
            rows.append(dict(zip(fields, ['Hex High Entropy String', fingerprint,
                'Validated public Git/image provenance from operator S24A VM deployment; not a credential',
                'docs/implementation/evidence/S24A-VM-verification.json'])))
    write_csv(path, rows)
    return public


def deploy(config, identity, resume=False):
    from operations_recovery import restore
    from demo_release import public_checks
    policy.same_database(config['source'], config['target'])
    require_local_docker()
    # Validate the separate recovery copy before any service can be stopped.
    old_operations = ssh(config['source'], 'sudo -n cat /etc/accounting/operations.json')
    require(old_operations['preview'] in (config['source'], config['target']), 'ui_source_changed')
    provisional = deepcopy(old_operations); provisional['preview'] = config['target']
    recovery_config({'target_operations': provisional}, identity)
    result_path = ROOT / 'private/vm-s24a-result.json'
    if not resume and not result_path.exists(): transfer(config)
    state = host_action(config, 'state')
    if state.get('status') == 'Not applied':
        require(not resume, 'ui_wrong_release_state')
        state = host_action(config, 'prepare', '--input', STAGE + '/input.json', '--bundle', STAGE + '/source.tar')
    require(state['source'] == config['source'] and state['target'] == config['target'], 'ui_source_changed')
    if state['phase'] == 'ui-complete':
        require(result_path.exists(), 'ui_wrong_release_state')
        result = json.loads(result_path.read_text())
        require(result['off_vm_restore']['receipt']['sha256'] == state['after_backup']['sha256'], 'ui_restore_binding_mismatch')
        result['completed_at'] = state['completed_at']
        return record(result, config)
    require(state['phase'] in {'ui-awaiting-restore', 'ui-activate', 'ui-public-check'}, 'ui_wrong_release_state')
    if state['phase'] == 'ui-awaiting-restore':
        try:
            recovered = restore(recovery_config(state, identity), state['after_backup'], identity)
            require(recovered['all_public_tables_match'] is True and recovered['receipt']['image'] == config['target']['published']['image'],
                    'ui_restore_binding_mismatch')
            common.private_json(ROOT / 'private/vm-s24a-restore.json', recovered)
        except Exception:
            # Before public activation an image-only rollback restores service
            # availability while retaining this same live database and backups.
            try: host_action(config, 'rollback')
            except Exception: pass
            raise
    else:
        recovered = json.loads((ROOT / 'private/vm-s24a-restore.json').read_text())
        require(recovered['receipt']['sha256'] == state['after_backup']['sha256'], 'ui_restore_binding_mismatch')
    host_action(config, 'activate', '--restored-sha256', recovered['receipt']['sha256'])
    wait_public(config['target']['hostname'])
    checks = {**public_checks(config['target']['hostname']), **public_assets(state)}
    result = {'off_vm_restore': recovered, 'public_checks': checks}
    # Keep the local proof before marking the VM complete, so an SSH interruption
    # cannot orphan a successful deployment without its recovery/public receipt.
    common.private_json(result_path, result)
    finished = host_action(config, 'finish')
    require(finished['status'] == 'ui-complete' and not finished['hold_active'], 'ui_wrong_release_state')
    result['vm'] = finished
    result['completed_at'] = finished['completed_at']
    common.private_json(result_path, result)
    return record(result, config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('publish', 'deploy', 'resume', 'status', 'rollback', 'retry'))
    parser.add_argument('--identity', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'publish': result = publish()
        else:
            config = json.loads(CONFIG.read_text())
            if args.action in {'deploy', 'resume'}:
                require(args.identity is not None, 'Supply the independent recovered age identity path')
                result = deploy(config, args.identity.expanduser().resolve(), resume=args.action == 'resume')
            else: result = host_action(config, args.action)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, 'S24A VM stopped (' + type(error).__name__ + '): ' + str(error) + '\n')


if __name__ == '__main__': main()
