"""S24A image-only release contracts; no network/runtime action on import."""
from pathlib import Path, PurePosixPath
import hashlib
import json

from cloud import require
import preview_events as events

CONTEXT = 'sha256:aa53c8f70d8ca11881457a7c80ee7e21684c8b4212a86fe9dbfe28ed95220ba0'
PREVIOUS_CONTEXT = 'sha256:8308c42a4eb01a114c7439c78adb54659ed5468cdec73921435d3512c023daed'
BOOTSTRAP = {'gcp': {'project_id': 'accounting-514109', 'vm_name': 'accounting-preview',
                     'zone': 'europe-west1-b', 'ssh_user': 'vasilistsakanikas'}}
HOSTNAME = 'totalaccounting.duckdns.org'
ASSETS = ('accounting/workspace/workspace.css', 'accounting/workspace/workspace.js', 'accounting/workspace/mark.svg')
STAGES = {'ui-source', 'ui-publication', 'ui-transfer', 'ui-preflight', 'ui-image-pull', 'ui-static',
          'ui-maintenance', 'ui-backup-before', 'ui-rebind', 'ui-web', 'ui-preservation',
          'ui-backup-after', 'ui-awaiting-restore', 'ui-activate', 'ui-public-check',
          'ui-complete', 'ui-rollback', 'ui-status', 'ui-failed'}
REASONS = {
    'ui_wrong_target', 'ui_database_or_identity_change', 'ui_wrong_application_context',
    'ui_incomplete_production_proof', 'ui_receipt_binding_mismatch', 'ui_verified_image_missing',
    'ui_image_identity_mismatch', 'ui_source_changed', 'ui_schema_mismatch',
    'ui_infrastructure_changed', 'ui_container_identity_mismatch', 'ui_private_port_exposed',
    'ui_database_restarted', 'ui_runtime_secret_changed', 'ui_retained_rows_changed',
    'ui_static_path_rejected', 'ui_static_collision', 'ui_static_missing', 'ui_web_not_healthy',
    'ui_existing_maintenance_hold', 'ui_operations_busy', 'ui_previous_attempt_needs_review',
    'ui_restore_binding_mismatch', 'ui_recovery_key_mismatch', 'ui_wrong_release_state',
    'ui_public_verification_failed', 'ui_insufficient_data_space', 'ui_missing_source_file',
}


def register():
    events.STAGES.update(STAGES)
    events.REASONS.update(REASONS)


def same_database(source, target):
    """Every installed identity/policy field stays equal, including pinned keys."""
    remove = {'published', 'deployment_commit'}
    require({key: value for key, value in source.items() if key not in remove}
            == {key: value for key, value in target.items() if key not in remove}, 'ui_database_or_identity_change')
    require(source['hostname'] == target['hostname'] == HOSTNAME
            and all(source['gcp'][key] == value for key, value in BOOTSTRAP['gcp'].items()), 'ui_wrong_target')
    require(source['published']['context_digest'] == PREVIOUS_CONTEXT
            and target['published']['context_digest'] == CONTEXT, 'ui_wrong_application_context')


def production_proof(proof, delivery, context):
    require(proof['step'] == 'S24A' and proof['status'] == 'Verified'
            and proof['mode'] == 'operator-docker-production-image'
            and delivery['step'] == 'delivery' and delivery['status'] == 'Verified'
            and delivery['mode'] == 'docker-production-image'
            and delivery['docker_execution_this_step'] is True and delivery['production_image_built_verified'] is True,
            'ui_incomplete_production_proof')
    zero = ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')
    for suite in (proof['suite'], delivery['suite']):
        require(suite['tests_run'] == suite['tests_passed'] == 661 and all(suite[key] == 0 for key in zero),
                'ui_incomplete_production_proof')
    require(len(proof['financial_cases']) == 36 and all(case['outcome'] == 'passed' for case in proof['financial_cases'])
            and delivery['suite']['cases'] == proof['financial_cases'], 'ui_incomplete_production_proof')
    require(context == proof['application_context_digest'] == delivery['image']['context']['digest'] == CONTEXT
            and proof['source_commit'] == delivery['image']['revision']
            and proof['production_image_id'] == delivery['image']['image_id'], 'ui_receipt_binding_mismatch')
    require(delivery['secret_scan']['unreviewed_findings'] == 0 and delivery['compiled_catalog_in_sync'] is True
            and delivery['dependency_locks_reproduced'] is True and delivery['gunicorn_http_verified'] is True
            and delivery['static_export_from_same_image_verified'] is True, 'ui_incomplete_production_proof')


def static_file(root, name):
    relative = PurePosixPath(name)
    require(name and not relative.is_absolute() and '..' not in relative.parts, 'ui_static_path_rejected')
    root = Path(root).resolve()
    path = root / relative
    require(not path.is_symlink() and path.resolve().is_relative_to(root) and path.is_file(), 'ui_static_path_rejected')
    return path


def release_context(directory):
    from image import allowed, archive
    directory = Path(directory)
    files = {}
    for file in directory.rglob('*'):
        name = file.relative_to(directory).as_posix()
        if file.is_file() and allowed(name):
            require(not file.is_symlink(), 'ui_missing_source_file')
            files[name] = file.read_bytes()
    return archive(files)[1]['digest']


def digest(value):
    return 'sha256:' + hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


register()
