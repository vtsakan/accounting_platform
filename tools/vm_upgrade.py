#!/usr/bin/env python3
"""Laptop-operated S14 -> S24 VM upgrade; no agent or startup execution."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import tempfile

from cloud import require
import image
import preview as publisher
import preview_common as common
import operations_common as oc

CONFIG = common.ROOT / 'private/vm-s24-upgrade.json'
STAGE = 'accounting-s24-upgrade-stage'
BOOTSTRAP = {'gcp': {'project_id': 'accounting-514109', 'vm_name': 'accounting-preview',
                      'zone': 'europe-west1-b', 'ssh_user': 'vasilistsakanikas'}}


def gate():
    revision, _, context = image.committed_context()
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=common.ROOT).strip(), 'Commit reviewed source/evidence first; keep private files outside Git')
    proof = json.loads((common.ROOT / 'docs/implementation/evidence/S24-verification.json').read_text())
    suite = proof.get('suite', {})
    require(proof['status'] == 'Verified' and proof['docker_execution'] is True and suite.get('tests_passed') == 656 and suite.get('tests_run') == 656,
            'The operator S24 656-test receipt must be recorded first')
    require(all(suite.get(key, 1) == 0 for key in ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')),
            'S24 proof contains an incomplete or failed outcome')
    require(len(proof.get('financial_cases', [])) == 36 and all(row['outcome'] == 'passed' for row in proof['financial_cases']) and proof.get('boundary_cases') == 922,
            'S24 financial/boundary evidence differs')
    require(proof['application_context_digest'] == context['digest'], 'Application bytes differ from the operator-verified S24 source')
    return revision, context


def ssh(config, command, *, json_output=True):
    gcp = config['gcp']
    return publisher.gcloud(config, 'compute', 'ssh', gcp['ssh_user'] + '@' + gcp['vm_name'], '--zone=' + gcp['zone'],
                            '--tunnel-through-iap', '--command=' + command, json_output=json_output)


def load(): return json.loads(CONFIG.read_text())


def host_action(config, action, *arguments):
    command = shlex.join(['sudo', '-n', 'python3', STAGE + '/tools/vm_upgrade_host.py', action, *arguments])
    value = ssh(config['source'], command)
    require(value.get('status') != 'Stopped', 'VM upgrade stopped at ' + value.get('phase', 'unknown') + ': ' + value.get('reason', 'Inspect status'))
    return value


def configure():
    gate(); require(not CONFIG.exists(), 'S24 VM configuration exists; reuse publish/plan/status rather than replace it')
    source = common.validate(ssh(BOOTSTRAP, 'sudo -n cat /etc/accounting/preview.json'), published=True)
    require(source['gcp']['project_id'] == BOOTSTRAP['gcp']['project_id'] and source['gcp']['vm_name'] == BOOTSTRAP['gcp']['vm_name']
            and source['gcp']['zone'] == BOOTSTRAP['gcp']['zone'] and source['hostname'] == 'totalaccounting.duckdns.org', 'Unexpected VM/hostname')
    target = deepcopy(source); target['db_name'] = 'accounting_s24_' + secrets.token_hex(6)
    target['published'] = None; target.pop('deployment_commit', None)
    common.private_json(CONFIG, {'source': source, 'target': target}, exclusive=True)
    return {'status': 'Configured', 'source_database': source['db_name'], 'clone_database': target['db_name'], 'vm_changed': False}


def publish(config):
    gate()
    path = common.ROOT / 'private/vm-s24-preview.json'; common.private_json(path, config['target'])
    result = publisher.publish(config['target'], path, common.ROOT / 'private/vm-s24-delivery.json')
    config['target'] = json.loads(path.read_text()); common.private_json(CONFIG, config)
    return result


def published_proof(config, context):
    published = common.validate(config['target'], published=True)['published']
    require(published['context_digest'] == context['digest'], 'Application bytes differ from the published image; a new delivery check is required')
    proof_path = common.ROOT / 'private/vm-s24-delivery.json'
    require(common.file_sha(proof_path) == published['delivery_evidence'], 'Production delivery receipt differs from publication')
    publisher.verified_delivery({'revision': 'git:' + published['commit'], 'image_id': published['image_id'], 'context': context},
                               json.loads(proof_path.read_text()))


def sync_host_helper(config, revision):
    # Refresh operator tooling only. No application image/DB/key is changed.
    with tempfile.TemporaryDirectory(prefix='accounting-s24-retry-helper-') as temporary:
        file = Path(temporary) / 'vm_upgrade_host.py'
        file.write_bytes(common.run(['git', 'show', revision + ':tools/vm_upgrade_host.py']))
        gcp = config['source']['gcp']
        publisher.gcloud(config['source'], 'compute', 'scp', file,
                         gcp['ssh_user'] + '@' + gcp['vm_name'] + ':~/' + STAGE + '/tools/vm_upgrade_host.py',
                         '--zone=' + gcp['zone'], '--tunnel-through-iap')


def retry(config):
    revision, context = gate(); published_proof(config, context)
    previous = deepcopy(config)
    attempt = config['target']['db_name']
    require(re.fullmatch(r'accounting_s24_[0-9a-f]{12}', attempt), 'Unexpected previous attempt identifier')
    directory = common.ROOT / 'private/vm-s24-attempts'; directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    local_archive = directory / (attempt + '.json')
    if local_archive.exists():
        require(json.loads(local_archive.read_text()) == previous, 'Previous local attempt archive differs; it was not overwritten')
    else: common.private_json(local_archive, previous, exclusive=True)
    sync_host_helper(config, revision)
    archived = host_action(config, 'archive-attempt', '--attempt-id', attempt)
    source = common.validate(ssh(config['source'], 'sudo -n cat /etc/accounting/preview.json'), published=True)
    require(source == config['source'], 'Installed source changed after rollback; inspect before preparing a retry')
    target = deepcopy(source); target['db_name'] = 'accounting_s24_' + secrets.token_hex(6)
    target['published'] = deepcopy(config['target']['published']); target.pop('deployment_commit', None)
    require(target['db_name'] != attempt, 'Retry identifier collision; no previous database will be overwritten')
    updated = {'source': source, 'target': target,
               'archived_attempts': config.get('archived_attempts', []) + [{'attempt': attempt, 'host_archive': archived['archive']} ]}
    common.private_json(CONFIG, updated)
    return {'status': 'Retry prepared', 'source_database': source['db_name'], 'previous_clone_retained': attempt,
            'new_clone_database': target['db_name'], 'published_image_reused': target['published']['image'],
            'application_data_changed': False, 'local_archive': str(local_archive), 'next_command': 'python3 tools/vm_upgrade.py plan --current-tools'}


def plan(config, *, current_tools=False):
    revision, context = gate(); target = common.validate(config['target'], published=True)
    if current_tools:
        published_proof(config, context)
        target['deployment_commit'] = revision
    else:
        require(target['published']['commit'] == revision and target['published']['context_digest'] == context['digest'], 'Publish this exact commit, or use --current-tools for unchanged verified application bytes')
    config['target'] = target
    with tempfile.TemporaryDirectory(prefix='accounting-s24-stage-') as temporary:
        directory = Path(temporary) / STAGE; (directory / 'tools').mkdir(parents=True)
        (directory / 'docs/implementation').mkdir(parents=True)
        bundle = directory / 'source.tar'; bundle.write_bytes(common.run(['git', 'archive', '--format=tar', revision]))
        names = ('vm_upgrade_host', 'vm_upgrade_migrate', 'preview_common', 'preview_host', 'preview_events', 'operations_common',
                 'operations_host', 'operations_pg', 'cloud', 'image', 'static_export', 'dev', 'verify_s05', 'init_local_env')
        for name in names: (directory / 'tools' / (name + '.py')).write_bytes(common.run(['git', 'show', revision + ':tools/' + name + '.py']))
        inventory = 'docs/implementation/cloud_inventory.json'
        (directory / inventory).write_bytes(common.run(['git', 'show', revision + ':' + inventory]))
        common.private_json(directory / 'input.json', {'source': config['source'], 'target': target, 'bundle_sha256': common.file_sha(bundle)})
        ssh(config['source'], 'umask 077; mkdir -p ' + STAGE, json_output=False)
        gcp = config['source']['gcp']
        publisher.gcloud(config['source'], 'compute', 'scp', '--recurse', directory,
                         gcp['ssh_user'] + '@' + gcp['vm_name'] + ':~/', '--zone=' + gcp['zone'], '--tunnel-through-iap')
    result = host_action(config, 'plan', '--input', STAGE + '/input.json', '--bundle', STAGE + '/source.tar')
    config['plan'] = result; common.private_json(CONFIG, config)
    return result


def recovery_config(state):
    rebound = deepcopy(state['operations'])
    require(rebound is not None and rebound['preview'] == state['target'], 'New backup binding is missing')
    primary = None
    for name in ('demo-operations.json', 'operations.json'):
        path = common.ROOT / 'private' / name
        if path.exists():
            old = json.loads(path.read_text())
            if old.get('recipient_id') == rebound['recipient_id'] and old.get('local_identity'):
                primary = old['local_identity']; break
    require(primary, 'Matching local recovery-key configuration not found; keep the VM hold and inspect key custody')
    rebound['local_identity'] = primary; oc.validate(rebound, local=True)
    common.private_json(common.ROOT / 'private/vm-s24-operations.json', rebound)
    return rebound


def deploy(config, identity):
    revision, _ = gate(); require('plan' in config, 'Run plan first')
    require(common.deployment_commit(config['target']) == revision, 'Operator source changed after planning; run plan --current-tools again')
    # Validate the separate recovery copy BEFORE stopping any VM service.
    path = oc.identity_file(identity)
    old = ssh(config['source'], 'sudo -n cat /etc/accounting/operations.json')
    require(old['preview'] == config['source'], 'The source backup binding changed')
    local = recovery_config({'operations': {**old, 'preview': config['target']}, 'target': config['target']})
    require(path != Path(local['local_identity']).expanduser().resolve(), 'Use the independent recovered identity copy, not the primary file')
    oc.check_age()
    require(common.run(['age-keygen', '-y', path]).decode().strip() == old['recipient'], 'Recovered identity belongs to another backup recipient')
    from dev import require_local_docker
    require_local_docker()
    prepared = host_action(config, 'prepare', '--plan-sha256', config['plan']['plan_sha256'])
    require(prepared['status'] == 'awaiting_off_vm_restore', 'Unexpected prepared deployment state')
    try:
        result = restore_and_activate(config, path, prepared)
    except Exception:
        state = host_action(config, 'status')
        if not state.get('public_cutover_started'):
            host_action(config, 'abort')
        raise
    return result


def restore_and_activate(config, identity, state=None):
    state = state or host_action(config, 'status')
    require(state['status'] in {'awaiting_off_vm_restore', 'needs_public_check', 'public_cutover_started'}, 'VM is not awaiting restore/activation')
    from operations_recovery import restore
    recovery = restore(recovery_config(state), state['after_backup'], identity)
    common.private_json(common.ROOT / 'private/vm-s24-restore.json', recovery)
    result = host_action(config, 'activate', '--restored-sha256', state['after_backup']['sha256'])
    from demo_release import public_checks
    checks = public_checks(config['target']['hostname'])
    result.update(off_vm_restore=recovery, public_checks=checks)
    common.private_json(common.ROOT / 'private/vm-s24-result.json', result)
    return {'status': 'Deployed and restored', 'hostname': config['target']['hostname'], 'image': config['target']['published']['image'],
            'source_database_retained': config['source']['db_name'], 'active_database': config['target']['db_name'],
            'original_columns_rows_and_people_preserved': result['migration']['original_columns_rows_and_people_preserved'],
            'restricted_role_migrations': result['migration']['restricted_role_migration'],
            'off_vm_restore_tables_match': recovery['all_public_tables_match'], 'public_checks': checks,
            'existing_owner_login': 'Preserved; operator browser login Pending', 'private_result': str(common.ROOT / 'private/vm-s24-result.json')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('configure', 'publish', 'plan', 'deploy', 'status', 'resume', 'abort', 'retry'))
    parser.add_argument('--identity', type=Path)
    parser.add_argument('--current-tools', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'configure': result = configure()
        else:
            config = load()
            if args.action == 'publish': result = publish(config)
            elif args.action == 'plan': result = plan(config, current_tools=args.current_tools)
            elif args.action == 'retry': result = retry(config)
            elif args.action == 'deploy':
                require(args.identity is not None, 'Supply the separate recovered age identity path')
                result = deploy(config, args.identity)
            elif args.action == 'resume':
                require(args.identity is not None, 'Supply the separate recovered age identity path')
                result = restore_and_activate(config, args.identity)
            else: result = host_action(config, args.action)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, 'S24 VM stopped: ' + str(error) + '\n')


if __name__ == '__main__': main()
