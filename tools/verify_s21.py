#!/usr/bin/env python3
"""Optional operator-run S21 Docker verification. Never run by APPLY_S21.sh."""
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
    project = 'accounting-s21-check-' + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()

    def compose(*args):
        return run(command + list(args), environment=environment)

    if compose('ps', '--all', '--quiet').stdout.strip() or run(
            ['docker', 'volume', 'ls', '--filter', 'label=com.docker.compose.project=' + project, '--quiet'],
            environment=environment).stdout.strip():
        raise RuntimeError('Refusing to adopt an existing Docker project')
    name = project + '-suite'
    try:
        print('[S21] Disposable local Docker project: ' + project, flush=True)
        compose('build', 'web')
        compose('up', '--detach', '--wait', '--wait-timeout', '180', 'db')

        def manage(*args):
            return compose('run', '--rm', '--no-deps', '--entrypoint', 'python', 'web', 'manage.py', *args)

        manage('migrate', '--noinput')
        manage('makemigrations', '--check', '--dry-run')
        manage('check', '--fail-level=WARNING')
        compose('run', '--name', name, '--no-deps', '--env', 'ACCOUNTING_REGRESSION_REPORT=/tmp/s21-suite.json',
                '--env', 'ACCOUNTING_BOUNDARY_REPORT=/tmp/s21-boundary.jsonl', '--entrypoint', 'python', 'web',
                'manage.py', 'test', '--settings=core.settings.test', '--testrunner=' + RUNNER, '--noinput', '--verbosity=1')
        run(['docker', 'cp', name + ':/tmp/s21-suite.json', directory / 'suite.json'], environment=environment)
        run(['docker', 'cp', name + ':/tmp/s21-boundary.jsonl', directory / 'boundary.jsonl'], environment=environment)
        suite = json.loads((directory / 'suite.json').read_text())
        boundary = [json.loads(line) for line in (directory / 'boundary.jsonl').read_text().splitlines()]
        count = sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
                    for node in ast.walk(ast.parse((ROOT / 'accounting/tests_internal_transfers.py').read_text())))
        if suite['tests_run'] != 511 + count or suite['known_failures_reproduced'] != 0 or any(
                suite[key] for key in ('unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')):
            raise RuntimeError('Unexpected strict regression outcome; inspect the test output')
        cases = {row['case_id']: row for row in suite['cases']}
        if len(cases) != 36 or any(case['outcome'] != 'passed' for case in cases.values()):
            raise RuntimeError('All 36 retained financial assertions must pass, including TRF-001')
        expected_ids = {row['case_id'] for row in csv.DictReader((DOCS / 'evidence/S19-office-boundary.csv').open(newline=''))}
        if len(boundary) != 784 or len({row['case_id'] for row in boundary}) != 784 or any(row['result'] != 'Passed' for row in boundary) or {row['case_id'] for row in boundary} != expected_ids:
            raise RuntimeError('The inherited 784-case office boundary did not pass unchanged')
        version = int(manage('shell', '--no-imports', '-c', 'from django.db import connection;print(connection.pg_version)').stdout.strip())
        if version // 10000 != 17:
            raise RuntimeError('PostgreSQL 17 required')
        return {'step': 'S21', 'status': 'Verified', 'mode': 'operator-docker-compose-postgresql17', 'docker_execution': True,
                'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
                'suite': {key: value for key, value in suite.items() if key != 'cases'}, 'financial_cases': suite['cases'],
                's21_tests': count, 'previous_test_count': 511, 'boundary_cases': 784, 'postgresql_version_num': version,
                'source_commit': 'git:' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'application_context_digest': candidate_context()[1]['digest'], 'local_demo_changed': False,
                'cloud_or_vm_changed': False, 'migration_added': False, 'agent_tests_run': False,
                'browser_greek_acceptance': 'Pending', 'full_requirement_acceptance': 'Pending'}
    finally:
        # Only the fresh random project above is removed, never the retained demo.
        compose('down', '--volumes', '--remove-orphans')


def record(report):
    (DOCS / 'evidence/S21-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with (DOCS / 'steps.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S21')
    row.update(status='Verified', code_reference_commit=report['source_commit'].removeprefix('git:'), blocker='',
               evidence='docs/implementation/evidence/S21-verification.json; accounting/tests_internal_transfers.py',
               next_step='S22 agreement terms and charge obligations')
    with (DOCS / 'steps.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n'); writer.writeheader(); writer.writerows(rows)
    path = DOCS / 'state.md'
    text = path.read_text()
    import re
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + report['verified_at'][:10] + '. Current step: **S21 Verified — atomic internal transfers**. Next step: **S22**.\n', text, count=1)
    text = re.sub(r'<!-- S21-RESULT -->.*?<!-- /S21-RESULT -->',
                  '<!-- S21-RESULT -->\nVerified by operator-run Docker/PostgreSQL suite; see S21-verification.json. Historical S20 evidence is unchanged. Full acceptance remains Pending.\n<!-- /S21-RESULT -->', text, flags=re.S)
    path.write_text(text)
    with (DOCS / 'traceability.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] in {'UR-CSH-04', 'UR-REP-02', 'QR-03', 'UR-LOC-01'}:
            if ' S21 operator Docker verification recorded;' not in row['notes']:
                row['notes'] += ' S21 operator Docker verification recorded; full acceptance remains Pending.'
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
        with tempfile.TemporaryDirectory(prefix='accounting-s21-') as tmp:
            result = execute(Path(tmp))
        if before != candidate_context()[1]['digest'] or subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
            raise RuntimeError('Source changed during verification; no result was recorded')
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, 'S21 stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
