#!/usr/bin/env python3
"""Optional operator-run S20 Docker verification. Never run by APPLY_S20.sh."""
import argparse
import ast
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
from zoneinfo import ZoneInfo
from dev import ROOT, compose_command, compose_environment, require_local_docker
from init_local_env import create_local_env
from verify_s05 import HIDDEN_VALUES, run
from image import candidate_context

DOCS = ROOT / 'docs/implementation'
RUNNER = 'accounting.regression_runner.FinancialRegressionRunner'


def execute(directory):
    require_local_docker()
    env_file = directory / 'env'
    create_local_env(env_file)
    HIDDEN_VALUES.update(line.split('=', 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(('DJANGO_SECRET_KEY=', 'DB_PASSWORD=')))
    with env_file.open('a') as stream:
        stream.write('WEB_PORT=0\n')
    project = 'accounting-s20-check-' + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()

    def compose(*args):
        return run(command + list(args), environment=environment)

    if compose('ps', '--all', '--quiet').stdout.strip() or run(
            ['docker', 'volume', 'ls', '--filter', 'label=com.docker.compose.project=' + project, '--quiet'],
            environment=environment).stdout.strip():
        raise RuntimeError('Refusing to adopt an existing Docker project')
    name = project + '-suite'
    try:
        print('[S20] Disposable local Docker project: ' + project, flush=True)
        compose('build', 'web')
        compose('up', '--detach', '--wait', '--wait-timeout', '180', 'db')

        def manage(*args):
            return compose('run', '--rm', '--no-deps', '--entrypoint', 'python', 'web', 'manage.py', *args)

        manage('migrate', '--noinput')
        manage('makemigrations', '--check', '--dry-run')
        manage('check', '--fail-level=WARNING')
        compose('run', '--name', name, '--no-deps', '--env', 'ACCOUNTING_REGRESSION_REPORT=/tmp/s20-suite.json',
                '--env', 'ACCOUNTING_BOUNDARY_REPORT=/tmp/s20-boundary.jsonl', '--entrypoint', 'python', 'web',
                'manage.py', 'test', '--settings=core.settings.test', '--testrunner=' + RUNNER, '--noinput', '--verbosity=1')
        run(['docker', 'cp', name + ':/tmp/s20-suite.json', directory / 'suite.json'], environment=environment)
        run(['docker', 'cp', name + ':/tmp/s20-boundary.jsonl', directory / 'boundary.jsonl'], environment=environment)
        suite = json.loads((directory / 'suite.json').read_text())
        boundary = [json.loads(line) for line in (directory / 'boundary.jsonl').read_text().splitlines()]
        count = sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
                    for node in ast.walk(ast.parse((ROOT / 'accounting/tests_cash_movements.py').read_text())))
        if suite['tests_run'] != 495 + count or suite['known_failures_reproduced'] != 1 or any(
                suite[key] for key in ('unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')):
            raise RuntimeError('Unexpected strict regression outcome; inspect the test output')
        cases = {row['case_id']: row for row in suite['cases']}
        if any(cases['FLT-' + str(n).zfill(3)]['outcome'] != 'passed' for n in range(1, 10)):
            raise RuntimeError('A malformed-filter correction did not pass')
        expected_ids = {row['case_id'] for row in csv.DictReader((DOCS / 'evidence/S19-office-boundary.csv').open(newline=''))}
        if len(boundary) != 784 or len({row['case_id'] for row in boundary}) != 784 or any(row['result'] != 'Passed' for row in boundary) or {row['case_id'] for row in boundary} != expected_ids:
            raise RuntimeError('The inherited 784-case office boundary did not pass unchanged')
        version = int(manage('shell', '--no-imports', '-c', 'from django.db import connection;print(connection.pg_version)').stdout.strip())
        if version // 10000 != 17:
            raise RuntimeError('PostgreSQL 17 required')
        return {'step': 'S20', 'status': 'Verified', 'mode': 'operator-docker-compose-postgresql17', 'docker_execution': True,
                'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
                'suite': {key: value for key, value in suite.items() if key != 'cases'}, 'financial_cases': suite['cases'],
                's20_tests': count, 'boundary_cases': 784, 'postgresql_version_num': version,
                'source_commit': 'git:' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'application_context_digest': candidate_context()[1]['digest'], 'local_demo_changed': False,
                'cloud_or_vm_changed': False, 'full_requirement_acceptance': 'Pending'}
    finally:
        # Only the fresh random project above is removed, never the retained demo.
        compose('down', '--volumes', '--remove-orphans')


def record(report):
    (DOCS / 'evidence/S20-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with (DOCS / 'steps.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S20')
    row.update(status='Verified', code_reference_commit=report['source_commit'].removeprefix('git:'), blocker='',
               evidence='docs/implementation/evidence/S20-verification.json; accounting/tests_cash_movements.py',
               next_step='S21 atomic internal transfers')
    with (DOCS / 'steps.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
    path = DOCS / 'state.md'
    text = path.read_text()
    import re
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + report['verified_at'][:10] + '. Current step: **S20 Verified — ordinary cash and validated filters**. Next step: **S21**.\n', text, count=1)
    text = re.sub(r'<!-- S20-RESULT -->.*?<!-- /S20-RESULT -->',
                  '<!-- S20-RESULT -->\nVerified by operator-run Docker/PostgreSQL suite; see S20-verification.json. Historical S19 evidence is unchanged. Full acceptance remains Pending.\n<!-- /S20-RESULT -->', text, flags=re.S)
    path.write_text(text)
    with (DOCS / 'traceability.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] in {'UR-CSH-02', 'UR-CSH-06', 'UR-LOC-01'}:
            row['notes'] += ' S20 operator Docker verification recorded; full acceptance remains Pending.'
            row['last_reviewed'] = report['verified_at'][:10]
    with (DOCS / 'traceability.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n'); writer.writeheader(); writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    try:
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
            raise RuntimeError('Commit the candidate source/evidence before verification')
        before = candidate_context()[1]['digest']
        with tempfile.TemporaryDirectory(prefix='accounting-s20-') as tmp:
            result = execute(Path(tmp))
        if before != candidate_context()[1]['digest'] or subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
            raise RuntimeError('Source changed during verification; no result was recorded')
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, 'S20 stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
