#!/usr/bin/env python3
"""Laptop-operated GitHub checkpoint and existing synthetic VM upgrade."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
import tempfile

from dev import ROOT, require_local_docker
import image
import operations_common as oc
import preview as publisher
import preview_common as common
import preview_cr004_policy as policy
from r1_gate import digest_bytes, digest_object, require

CONFIG = ROOT / 'private/vm-cr004-preview.json'
RESULT = ROOT / 'private/vm-cr004-result.json'
RESTORED = ROOT / 'private/vm-cr004-restored.json'
STAGE = 'accounting-cr004-preview-stage'
PUBLIC = 'docs/implementation/evidence/CR004-VM-verification.json'
SOURCE = ROOT / 'docs/implementation/evidence/CR004-VM-source.json'
TOOLS_TEMP = None
TOOLS_PYTHON = None


def git(*args, capture=True):
    command = ['git', *args]
    if capture:
        return common.run(command, environment=image.git_environment()).decode().strip()
    result = subprocess.run(command, cwd=ROOT, env=image.git_environment())
    require(result.returncode == 0, 'Git operation stopped; no force update or history repair was attempted')


def source_context(*, clean=True):
    # Pending operator reports are audited without claiming a committed image.
    # Only the second, clean pass can return a production source identity.
    revision = None
    if clean:
        revision, _, context = image.committed_context()
    else:
        _, context = image.candidate_context()
    require(context['digest'] == policy.CONTEXT and context['file_count'] == 308,
            'The operator-verified application source changed; no substitute build is accepted')
    return revision, context


def source_gate(*, clean=True):
    from verify_cr004 import source_check
    _, count = source_check()
    require(count == 695, 'Retain every695 verified CR004 source binding')
    report = policy.verify_reports(ROOT)
    policy.unchanged_acceptances(ROOT)
    require(subprocess.run(['git','merge-base','--is-ancestor',policy.APP_REVISION,'HEAD'],cwd=ROOT,
        env=image.git_environment(),capture_output=True).returncode == 0,
        'Keep the actual successful CR004 source commit in the operator history')
    revision, _ = source_context(clean=clean)
    manifest = json.loads(SOURCE.read_text())
    require(manifest.get('step') == 'CR004-VM' and manifest.get('status') == 'Prepared'
        and manifest.get('application_context_digest') == policy.CONTEXT
        and manifest.get('application_inputs') == 308
        and manifest.get('operator_source') == 'git:' + policy.APP_REVISION
        and manifest.get('operator_report_canonical_sha256') == policy.REPORT_SHA,
        'The prepared preview manifest must bind the actual successful CR004 gate')
    for name, expected in manifest['sha256'].items():
        path = ROOT/name
        require(path.is_file() and not path.is_symlink() and digest_bytes(path.read_bytes()) == expected,
            'Prepared CR004 preview tooling changed: '+name)
    require(not git('ls-files','--','private/'), 'Private operational files must remain outside Git')
    if clean:
        require(not git('status','--porcelain'), 'Retain reviewed operator records before clean source publication')
    return revision, report


def checkpoint():
    source_gate(clean=False)
    changed = set(filter(None,git('diff','--name-only','HEAD').splitlines()))
    untracked = set(filter(None,git('ls-files','--others','--exclude-standard').splitlines()))
    require(changed | untracked <= set(policy.RECORDED),
        'Unrelated local changes were retained; only the known CR004 record outputs can be saved automatically')
    if 'docs/implementation/state.md' in changed:
        previous = subprocess.check_output(['git','show','HEAD:docs/implementation/state.md'],
            cwd=ROOT,env=image.git_environment(),text=True)
        require((ROOT/'docs/implementation/state.md').read_text() == policy.recorded_state(previous),
            'State changes are not the exact known successful CR004 recorder output')
    if changed or untracked:
        git('diff','--check','HEAD')
        git('add','--',*sorted(changed | untracked),capture=False)
        git('commit','-m','docs: retain actual successful CR004 operator receipt',capture=False)
    return source_gate()[0]


def secret_scan():
    global TOOLS_TEMP, TOOLS_PYTHON
    if TOOLS_PYTHON is None:
        supplied = os.environ.get('ACCOUNTING_TOOLS_PYTHON')
        if supplied:
            TOOLS_PYTHON = Path(supplied).expanduser().resolve(strict=True)
        else:
            TOOLS_TEMP = tempfile.TemporaryDirectory(prefix='accounting-s31-scan-')
            directory = Path(TOOLS_TEMP.name)
            common.run([sys.executable, '-m', 'venv', directory / 'tools'])
            TOOLS_PYTHON = directory / 'tools/bin/python'
            common.run([TOOLS_PYTHON, '-m', 'pip', 'install', '--timeout', '30', '--retries', '2',
                        '--require-hashes', '--only-binary=:all:', '--index-url', 'https://pypi.org/simple',
                        '-r', ROOT / 'requirements-tools.txt'])
    result = subprocess.run([str(TOOLS_PYTHON), str(ROOT / 'tools/scan_secrets.py')], cwd=ROOT,
                            capture_output=True)
    require(result.returncode in (0, 1) and result.stdout.strip().startswith(b'{'),
            'Pinned source/history scanner could not run; raw provider output omitted')
    value = json.loads(result.stdout)
    require(value.get('scanner') == 'detect-secrets' and value.get('version') == '1.5.0', 'Unexpected scanner identity')
    return value


def github():
    revision = checkpoint()
    remote = git('remote', 'get-url', 'origin')
    require(remote in (policy.REPOSITORY, 'git@github.com:vtsakan/accounting_platform.git'), 'Unexpected GitHub origin')
    git('fetch', 'origin', 'main', capture=False)
    old = git('rev-parse', 'FETCH_HEAD')
    require(re.fullmatch(r'[0-9a-f]{40}', old) is not None, 'Invalid observed GitHub head')
    require(subprocess.run(['git', 'merge-base', '--is-ancestor', old, revision], cwd=ROOT,
                           env=image.git_environment(), capture_output=True).returncode == 0,
            'GitHub main has independent work; nothing was overwritten. Integrate it before deploying')
    # Scan the actual local history, including the operator-only bindings, before any push.
    result = secret_scan()
    common.private_json(ROOT / 'private/vm-cr004-github-scan.json', result)
    require(result['unreviewed_findings'] == 0, 'Source/history secret scan has unreviewed findings; publication stopped')
    git('push', '-u', 'origin', 'HEAD:refs/heads/' + policy.BRANCH, capture=False)
    # Ordinary fast-forward push rejects both divergent work and branch protection.
    git('push', 'origin', 'HEAD:refs/heads/main', capture=False)
    observed = git('ls-remote', '--heads', 'origin', 'main').split()
    require(observed and observed[0] == revision, 'GitHub main moved concurrently; inspect it before VM deployment')
    return {'status': 'GitHub updated', 'commit': 'git:' + revision, 'previous_main': 'git:' + old,
            'repository': policy.REPOSITORY, 'force_push': False}


def ssh(config, command, *, json_output=True):
    gcp = config['gcp']
    return publisher.gcloud(config, 'compute', 'ssh', gcp['ssh_user'] + '@' + gcp['vm_name'],
                            '--zone=' + gcp['zone'], '--tunnel-through-iap', '--command=' + command,
                            json_output=json_output)


def host_action(config, action, *arguments):
    command = shlex.join(['sudo', '-n', 'python3', STAGE + '/tools/preview_cr004_host.py', action, *map(str, arguments)])
    value = ssh(config['source'], command)
    require(value.get('status') != 'Stopped', 'VM stopped at ' + value.get('phase', 'unknown') + ': ' + value.get('reason', 'Inspect status'))
    return value


def load():
    value = json.loads(CONFIG.read_text())
    policy.transition(value['source'], value['target'])
    common.validate(value['source'], published=True); common.validate(value['target'], published=True)
    return value


def recovery_config(operations, identity):
    primary = None
    for name in ('vm-s24-operations.json', 'demo-operations.json', 'operations.json'):
        path = ROOT / 'private' / name
        if path.is_file():
            candidate = json.loads(path.read_text())
            if candidate.get('recipient_id') == operations['recipient_id'] and candidate.get('local_identity'):
                primary = oc.identity_file(candidate['local_identity']); break
    require(primary is not None, 'The matching existing primary recovery-key configuration is required; no key was generated')
    recovered = oc.identity_file(identity)
    require(recovered != primary, 'Use the existing independent recovered key copy, outside Git')
    oc.check_age()
    require(common.run(['age-keygen', '-y', recovered]).decode().strip() == operations['recipient'],
            'The existing independent key does not match the installed backup recipient')
    result = deepcopy(operations); result['local_identity'] = str(primary)
    oc.validate(result, local=True)
    return result


def cached_image():
    existing = image.inspect(policy.IMAGE_ID)
    require(existing is not None, 'The exact previously verified CR004 image is missing locally; no rebuild was attempted')
    built = image.reuse_for_verification(policy.IMAGE_ID)
    require(built['image_id'] == policy.IMAGE_ID and built['revision'] == 'git:' + policy.APP_REVISION
            and built['context']['digest'] == policy.CONTEXT, 'Cached image identity differs')
    labels = existing['Config'].get('Labels', {})
    require(labels.get('org.opencontainers.image.revision') == policy.APP_REVISION
            and labels.get('gr.accounting.source-context') == policy.CONTEXT, 'Cached image labels differ')
    return built


def publish(identity):
    revision, report = source_gate(); require_local_docker()
    if CONFIG.exists():
        return load()
    source = common.validate(ssh(policy.BOOTSTRAP, 'sudo -n cat /etc/accounting/preview.json'), published=True)
    policy.target_identity(source)
    require(source['published']['image'] == policy.OLD_IMAGE, 'VM differs from the observed current S31A release; retain it and inspect before updating')
    operations = ssh(source, 'sudo -n cat /etc/accounting/operations.json')
    oc.validate(operations)
    require(operations['preview'] == source, 'The existing backup binding differs')
    recovery_config(operations, identity)  # Before any VM service is stopped.
    cached_image()  # Reuse the exact965-test image; never build a substitute.
    gcp = source['gcp']
    repository = f"{gcp['region']}-docker.pkg.dev/{gcp['project_id']}/{gcp['repository']}/web"
    tag = repository + ':' + policy.APP_REVISION
    token = publisher.gcloud(source, 'auth', 'print-access-token').strip()
    require(token and b'\n' not in token, 'Unexpected operator access-token response')
    endpoint = os.environ.get('DOCKER_HOST') if not os.environ.get('DOCKER_CONTEXT') else None
    if not endpoint:
        endpoint = json.loads(common.run(['docker', 'context', 'inspect', '--format', '{{json .Endpoints.docker.Host}}']))
    environment = {k: v for k, v in os.environ.items() if k != 'DOCKER_CONTEXT'}
    environment['DOCKER_HOST'] = endpoint
    with tempfile.TemporaryDirectory(prefix='accounting-s31-publish-') as temporary:
        cli = ['docker', '--config', temporary]
        common.run(cli + ['login', tag.split('/')[0], '--username', 'oauth2accesstoken', '--password-stdin'], payload=token, environment=environment)
        common.run(cli + ['tag', policy.IMAGE_ID, tag], environment=environment)
        pushed = common.run(cli + ['push', tag], environment=environment).decode()
    metadata = image.inspect(tag)
    digests = [ref for ref in metadata.get('RepoDigests', []) if ref.startswith(repository + '@sha256:')]
    if not digests:
        matches = set(re.findall(r'\bdigest: (sha256:[0-9a-f]{64})\b', pushed))
        require(len(matches) == 1, 'An unambiguous immutable registry digest is required')
        digests = [repository + '@' + matches.pop()]
    require(len(digests) == 1, 'Ambiguous published registry digest')
    target = deepcopy(source); target['db_name'] = 'accounting_cr004_' + secrets.token_hex(6)
    target['deployment_commit'] = revision
    target['published'] = {'commit': policy.APP_REVISION, 'image': digests[0], 'image_id': policy.IMAGE_ID,
                           'context_digest': policy.CONTEXT, 'delivery_evidence': digest_object(report)}
    policy.transition(source, target); common.validate(target, published=True)
    value = {'source': source, 'target': target, 'operator_report_sha256': digest_object(report)}
    common.private_json(CONFIG, value, exclusive=True)
    return value


def transfer(config):
    revision = common.deployment_commit(config['target'])
    source_gate()
    require(subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'HEAD'], cwd=ROOT,
                           env=image.git_environment(), capture_output=True).returncode == 0, 'Deployment source is not in this history')
    with tempfile.TemporaryDirectory(prefix='accounting-s31-transfer-') as temporary:
        directory = Path(temporary) / STAGE
        (directory / 'tools').mkdir(parents=True)
        (directory / 'docs/implementation').mkdir(parents=True)
        bundle = directory / 'source.tar'
        bundle.write_bytes(common.run(['git', 'archive', '--format=tar', revision], environment=image.git_environment()))
        names = git('ls-tree', '-r', '--name-only', revision, '--', 'tools').splitlines()
        for name in names:
            if name.endswith('.py'):
                path = directory / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(common.run(['git', 'show', revision + ':' + name], environment=image.git_environment()))
        name = 'docs/implementation/cloud_inventory.json'
        (directory / name).write_bytes(common.run(['git', 'show', revision + ':' + name], environment=image.git_environment()))
        common.private_json(directory / 'input.json', {**config, 'bundle_sha256': common.file_sha(bundle)})
        ssh(config['source'], 'umask 077; mkdir -p ' + STAGE, json_output=False)
        gcp = config['source']['gcp']
        publisher.gcloud(config['source'], 'compute', 'scp', '--recurse', directory,
                         gcp['ssh_user'] + '@' + gcp['vm_name'] + ':~/', '--zone=' + gcp['zone'], '--tunnel-through-iap')


def proof_file(config, name, value):
    require(name in ('restored.json', 'public.json'), 'Fixed private proof path required')
    command = shlex.join(['python3', '-c', 'import json,os,pathlib,sys; p=pathlib.Path(sys.argv[1]); p.write_bytes(sys.stdin.buffer.read()); p.chmod(0o600)', STAGE + '/' + name])
    # gcloud SSH accepts stdin; the private attestation contains no decryption key.
    gcp = config['source']['gcp']
    common.run(['gcloud', 'compute', 'ssh', gcp['ssh_user'] + '@' + gcp['vm_name'], '--project=' + gcp['project_id'],
                '--zone=' + gcp['zone'], '--tunnel-through-iap', '--quiet', '--command=' + command],
               payload=json.dumps(value).encode(), environment={**os.environ, 'CLOUDSDK_CORE_LOG_HTTP': 'false'})
    return STAGE + '/' + name


def deploy(config, identity):
    source_gate(); require_local_docker()
    transfer(config)
    current = host_action(config, 'status')
    if current['status'] == 'Not applied':
        planned = host_action(config, 'plan', '--input', STAGE + '/input.json', '--bundle', STAGE + '/source.tar')
        config['plan'] = planned; common.private_json(CONFIG, config)
        # Recheck the independent key before beginning maintenance.
        original = ssh(config['source'], 'sudo -n cat /etc/accounting/operations.json')
        recovery_config(original, identity)
        print('[CR004-VM] Κρυπτογραφημένο backup, clone και migrations 26 → 28 στο υπάρχον preview.', flush=True)
        state = host_action(config, 'prepare', '--plan-sha256', planned['plan_sha256'])
    else:
        state = host_action(config, 'state')
    require(state['phase'] in ('awaiting_off_vm_restore', 'public_cutover_started', 'needs_public_check', 'deployed_and_restored'),
            'The retained attempt needs review: ' + state['phase'] + '; no journal/database was deleted')
    if state['phase'] != 'deployed_and_restored':
        try:
            if state['public_cutover_started']:
                restored = state['off_vm_restored']
            else:
                from operations_recovery import restore
                restored = {}
                for label, operations, receipt in (('before', state['source_operations'], state['before_backup']),
                                                    ('after', state['target_operations'], state['after_backup'])):
                    print('[CR004-VM] Επαναφορά εκτός VM: ' + label + '.', flush=True)
                    restored[label] = restore(recovery_config(operations, identity), receipt, identity)
                policy.ready_for_activation(state, restored)
                common.private_json(RESTORED, restored)
            path = proof_file(config, 'restored.json', restored)
            print('[CR004-VM] Ενεργοποίηση preview, Redis, worker και ενός scheduler.', flush=True)
            state = host_action(config, 'activate', '--proof', path)
            from demo_release import public_checks
            from vm_material_release import public_assets
            checks = public_checks(config['target']['hostname'])
            checks.update(public_assets(state))
            path = proof_file(config, 'public.json', checks)
            state = host_action(config, 'complete', '--proof', path)
        except Exception:
            latest = host_action(config, 'state')
            if latest.get('public_cutover_started') is False:
                host_action(config, 'abort')
            raise
    common.private_json(RESULT, state)
    return record(state)


def record(state):
    require(state['phase'] == 'deployed_and_restored' and state['public_cutover_started'], 'No successful preview deployment to record')
    migration = state['migration']
    require(migration['source_migrations'] == 26 and migration['target_migrations'] == 28
            and migration['original_columns_rows_passwords_mfa_sessions_preserved'] is True
            and migration['new_business_tables_empty'] is True and migration['restricted_role_migrations'] is True
            and migration['original_database_migrated'] is False, 'The actual clone preservation receipt is incomplete')
    for name, receipt in (('before', state['before_backup']), ('after', state['after_backup'])):
        recovered = state['off_vm_restored'][name]
        require(recovered['receipt'] == receipt and recovered['all_public_tables_match'] is True
                and recovered['plaintext_removed'] is True and recovered['separate_recovery_key_used'] is True,
                'The actual encrypted recovery result differs')
    require(state['off_vm_restored']['before']['tables_checked'] == migration['old_tables_checked']
            and state['off_vm_restored']['after']['tables_checked'] == migration['old_tables_checked'] + 1,
            'The actual source/clone restored table coverage is incomplete')
    report = {'step': 'CR004-VM', 'status': 'Verified', 'verified_at': state['completed_at'],
              'scope': 'existing-preview-only', 'hostname': policy.HOSTNAME,
              'application_commit': 'git:' + policy.APP_REVISION,
              'deployment_commit': 'git:' + common.deployment_commit(state['target']),
              'image': state['target']['published']['image'], 'application_context_digest': policy.CONTEXT,
              'cr004_operator_report_sha256': policy.REPORT_SHA,
              'production_suite_previously_passed': 965, 'financial_cases_previously_passed': 36,
              'production_suite_rerun': False, 'source_migrations': 26, 'target_migrations': 28,
              'original_database_retained_unmigrated': True, 'original_columns_rows_passwords_mfa_sessions_preserved': True,
              'database_container_restarted': False, 'accounts_mfa_or_keys_reset': False, 'existing_durable_queue_retained': True,
              'automatic_financial_posting_during_migration': False, 'runtime': state['runtime'],
              'off_vm_source_restore_tables': state['off_vm_restored']['before']['tables_checked'],
              'off_vm_target_restore_tables': state['off_vm_restored']['after']['tables_checked'],
              'off_vm_source_restore_seconds': state['off_vm_restored']['before']['restore_seconds'],
              'off_vm_target_restore_seconds': state['off_vm_restored']['after']['restore_seconds'],
              'off_vm_all_public_tables_match': True, 'separate_recovered_key_used': True,
              'plaintext_removed': True, 'public_checks': state['public_checks'],
              'actual_browser_login_mfa': 'Pending operator login with the existing account',
              'real_client_release': 'Blocked; R1/D05/D06/D07/G2 Pending',
              'full_requirement_acceptances_pending': 85, 'document_recovery': 'Pending S38; media verified empty',
              'agent_native_execution': False}
    path = ROOT / PUBLIC
    if path.exists():
        require(json.loads(path.read_text()) == report, 'Existing public deployment evidence differs; it was not replaced')
    else:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    policy.track(ROOT, 'Verified', 'git:' + common.deployment_commit(state['target']), receipt=PUBLIC)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def push_result():
    changed = set(filter(None, git('diff', '--name-only', 'HEAD').splitlines()))
    untracked = set(filter(None, git('ls-files', '--others', '--exclude-standard').splitlines()))
    allowed = {PUBLIC, 'docs/implementation/state.md'}
    require(changed | untracked <= allowed, 'Unrelated changes were preserved; only this preview result/tracking may be committed')
    if changed or untracked:
        git('add', '--', *sorted(allowed), capture=False)
        git('commit', '-m', 'docs: record CR004 preview upgrade and both off-VM restores', capture=False)
    return github()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('source', 'all', 'github', 'publish', 'deploy', 'resume', 'status', 'abort', 'record'))
    parser.add_argument('--identity', type=Path,
                        default=Path.home() / '.config/totalaccounting/recovered-backup-age.key')
    args = parser.parse_args()
    os.chdir(ROOT)
    try:
        if args.action == 'source':
            revision, report = source_gate()
            result = {'status':'Prepared','application_context_digest':policy.CONTEXT,'application_inputs':308,
                'operator_gate':'Verified965/36','deployment_commit':'git:'+revision,'runtime_executed':False}
        elif args.action == 'github':
            result = github()
        elif args.action == 'status':
            result = host_action(load(), 'status') if CONFIG.exists() else {'status': 'Not configured; no VM change'}
        elif args.action == 'abort':
            result = host_action(load(), 'abort')
        elif args.action == 'publish':
            config = publish(args.identity)
            result = {'status': 'Published the same965-test verified image without rebuilding', 'image': config['target']['published']['image']}
        elif args.action == 'record':
            state = host_action(load(), 'state'); record(state); result = push_result()
        else:
            if args.action == 'all':
                print('[CR004-VM] Έλεγχος πραγματικού CR004965/36 και ενημέρωση GitHub.', flush=True)
                print(json.dumps(github(), ensure_ascii=False))
                config = publish(args.identity)
            else:
                config = load()
            deploy(config, args.identity)
            result = push_result()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, TypeError):
        # A traceback/provider response can contain private paths, auth or SQL.
        error = sys.exc_info()[1]
        reason = str(error) if isinstance(error, RuntimeError) else 'Local input/tooling could not be read; raw provider output omitted'
        parser.exit(1, 'CR004-VM stopped: ' + reason + '\n')
    finally:
        if TOOLS_TEMP is not None:
            TOOLS_TEMP.cleanup()


if __name__ == '__main__':
    main()
