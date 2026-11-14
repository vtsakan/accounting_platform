#!/usr/bin/env python3
"""Operator-only local UI restart; requires an existing S24 database, never migrates."""
import argparse
import json
from pathlib import Path
import subprocess

from dev import ROOT, compose_command, compose_environment, require_local_docker


def require(value, reason):
    if not value: raise RuntimeError(reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8003)
    args = parser.parse_args()
    try:
        require(1024 <= args.port <= 65535, 'Choose a local port between 1024 and 65535')
        require_local_docker()
        require((ROOT / '.env').is_file(), 'Existing local demo .env is required; no credentials were generated')
        command = compose_command(ROOT / '.env', 'accounting-client-demo')
        environment = {**compose_environment(), 'WEB_PORT': str(args.port)}

        def call(*arguments, payload=None):
            result = subprocess.run([str(value) for value in [*command, *arguments]], cwd=ROOT,
                                    env=environment, input=payload, capture_output=True)
            require(result.returncode == 0, 'Local Compose operation failed; resolved credentials/output omitted')
            return result.stdout.decode().strip()

        require(call('ps', '--all', '--quiet', 'db'), 'Existing accounting-client-demo database container is required')
        call('start', '--wait', '--wait-timeout', '120', 'db')
        sql = "SELECT json_build_object('version',current_setting('server_version_num')::integer,'migrations'," \
              "(SELECT json_agg(name ORDER BY name) FROM django_migrations WHERE app='accounting'));\n"
        actual = json.loads(call('exec', '-T', 'db', 'sh', '-c',
                          'exec psql -X -qAt --set=ON_ERROR_STOP=1 --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"',
                          payload=sql.encode()))
        expected = sorted(path.stem for path in (ROOT / 'accounting/migrations').glob('[0-9]*.py'))
        require(actual['version'] // 10000 == 17 and actual['migrations'] == expected and len(expected) == 20,
                'Local demo is not at S24/0020. Its schema was not changed; use the supplied static preview until its separate upgrade is reviewed')
        override = ROOT / 'private/s24a-compose.override.yml'
        override.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        override.write_text('services:\n  web:\n    entrypoint: ["python", "manage.py"]\n'
                            '    command: ["runserver", "0.0.0.0:8000"]\n'
                            '    environment:\n      DJANGO_DEBUG: "true"\n')
        override.chmod(0o600)
        command.extend(['--file', str(override)])
        resolved = json.loads(call('config', '--format', 'json'))
        require(all(port.get('host_ip') == '127.0.0.1' and int(port['published']) == args.port
                    for port in resolved['services']['web']['ports']) and not resolved['services']['db'].get('ports'),
                'Preview must bind web only to local loopback and keep the database private')
        print('[S24A] Existing S24 local demo; building/restarting web without migrations or account changes.', flush=True)
        call('build', 'web')
        call('up', '--detach', '--no-deps', '--force-recreate', '--wait', '--wait-timeout', '180', 'web')
        print(json.dumps({'status': 'Local preview started', 'url': 'http://localhost:' + str(args.port) + '/',
                          'database_migrated': False, 'accounts_mfa_or_keys_reset': False,
                          'cloud_or_vm_changed': False}, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        parser.exit(1, 'S24A local preview stopped: ' + str(error) + '\n')


if __name__ == '__main__': main()
