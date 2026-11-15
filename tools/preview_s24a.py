#!/usr/bin/env python3
"""Operator-only local UI restart; requires an existing S24 database, never migrates."""
import argparse
import json
import subprocess

from dev import ROOT, compose_command, compose_environment, require_local_docker


def require(value, reason):
    if not value: raise RuntimeError(reason)


def compose_failure_reason(output):
    """Return only an allowlisted code; provider output can contain credentials."""
    lowered = output.lower()
    for reason, patterns in (
        ('database_authentication_failed', (b'password authentication failed', b'no password supplied')),
        ('database_schema_missing', (b'relation "django_migrations" does not exist',)),
        ('docker_unavailable', (b'cannot connect to the docker daemon', b'permission denied while trying to connect')),
        ('port_in_use', (b'port is already allocated', b'address already in use')),
        ('container_not_running', (b'is not running', b'no container found')),
        ('unhealthy_or_timed_out', (b'is unhealthy', b'did not become healthy', b'timed out', b'timeout')),
        ('unsupported_compose_option', (b'unknown flag', b'unknown shorthand flag')),
    ):
        if any(pattern in lowered for pattern in patterns):
            return reason
    return 'compose_failed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8003)
    parser.add_argument('--inspect', action='store_true',
                        help='Read the existing schema without building/replacing web; starts its existing database if stopped')
    args = parser.parse_args()
    stage = 'local-preflight'
    try:
        require(1024 <= args.port <= 65535, 'Choose a local port between 1024 and 65535')
        require_local_docker()
        require((ROOT / '.env').is_file(), 'Existing local demo .env is required; no credentials were generated')
        command = compose_command(ROOT / '.env', 'accounting-client-demo')
        environment = {**compose_environment(), 'WEB_PORT': str(args.port)}

        def call(phase, *arguments, payload=None):
            nonlocal stage
            stage = phase
            stdin = {'input': payload} if payload is not None else {'stdin': subprocess.DEVNULL}
            result = subprocess.run([str(value) for value in [*command, *arguments]], cwd=ROOT,
                                    env=environment, capture_output=True, **stdin)
            require(result.returncode == 0,
                    'Compose exit=' + str(result.returncode) + '; reason=' +
                    compose_failure_reason(result.stderr + b'\n' + result.stdout) +
                    '. Raw output and resolved credentials omitted')
            return result.stdout.decode().strip()

        containers = call('database-container', 'ps', '--all', '--quiet', 'db').splitlines()
        require(len(containers) == 1, 'Exactly one existing accounting-client-demo database container is required')
        call('database-start', 'start', '--wait', '--wait-timeout', '120', 'db')
        sql = "SELECT json_build_object('version',current_setting('server_version_num')::integer,'migrations'," \
              "(SELECT json_agg(name ORDER BY name) FROM django_migrations WHERE app='accounting'));\n"
        actual = json.loads(call('database-schema', 'exec', '-T', 'db', 'sh', '-c',
                          'set -eu; export PGPASSWORD="$POSTGRES_PASSWORD"; '
                          'exec psql -X -qAt --no-password --set=ON_ERROR_STOP=1 '
                          '--username="$POSTGRES_USER" --dbname="$POSTGRES_DB"',
                          payload=sql.encode()))
        expected = sorted(path.stem for path in (ROOT / 'accounting/migrations').glob('[0-9]*.py'))
        require(isinstance(actual, dict) and type(actual.get('version')) is int
                and isinstance(actual.get('migrations'), list), 'Unexpected schema response; no web replacement was attempted')
        matches = actual['version'] // 10000 == 17 and actual['migrations'] == expected and len(expected) == 20
        if args.inspect:
            print(json.dumps({'status': 'Inspected', 'project': 'accounting-client-demo',
                              'postgresql_version_num': actual['version'],
                              'applied_migration_count': len(actual['migrations']),
                              'expected_migration_count': len(expected), 's24_schema_matches': matches,
                              'database_migrated': False, 'web_rebuilt_or_replaced': False,
                              'existing_database_started_if_stopped': True, 'cloud_or_vm_changed': False}, indent=2))
            return
        require(matches, 'Local demo is not at S24/0020: found ' + str(len(actual['migrations'])) +
                ' applied migrations; expected exactly 20 on PostgreSQL 17. '
                'No migration or web replacement was performed. Use PREVIEW_S24A.html until the separate local upgrade is reviewed')
        stage = 'local-upgrade-receipt'
        journal = ROOT / 'private/s24a-local-upgrade.json'
        if journal.exists():
            upgrade = json.loads(journal.read_text())
            require(not upgrade.get('migration_attempted')
                    or upgrade.get('migration', {}).get('original_columns_and_rows_preserved') is True,
                    'A local upgrade lacks its preservation receipt; keep web stopped and retain its backup for review')
        stage = 'preview-config'
        override = ROOT / 'private/s24a-compose.override.yml'
        override.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        override.write_text('services:\n  web:\n    entrypoint: ["python", "manage.py"]\n'
                            '    command: ["runserver", "0.0.0.0:8000"]\n'
                            '    environment:\n      DJANGO_DEBUG: "true"\n')
        override.chmod(0o600)
        command.extend(['--file', str(override)])
        resolved = json.loads(call('compose-config', 'config', '--format', 'json'))
        ports = resolved['services']['web']['ports']
        require(len(ports) == 1 and all(port.get('host_ip') == '127.0.0.1' and int(port['published']) == args.port
                    for port in ports) and not resolved['services']['db'].get('ports'),
                'Preview must bind web only to local loopback and keep the database private')
        print('[S24A] Existing S24 local demo; building/restarting web without migrations or account changes.', flush=True)
        call('web-build', 'build', 'web')
        call('web-start', 'up', '--detach', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180', 'web')
        print(json.dumps({'status': 'Local preview started', 'url': 'http://localhost:' + str(args.port) + '/',
                          'database_migrated': False, 'accounts_mfa_or_keys_reset': False,
                          'cloud_or_vm_changed': False}, indent=2))
    except RuntimeError as error:
        parser.exit(1, 'S24A local preview stopped at ' + stage + ': ' + str(error) + '\n')
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, 'S24A local preview stopped at ' + stage + ': local input/configuration could not be read; raw output omitted\n')


if __name__ == '__main__': main()
