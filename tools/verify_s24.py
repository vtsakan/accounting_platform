#!/usr/bin/env python3
"""Optional operator-run S24 Docker/PostgreSQL correction verification. Never run by APPLY_S24.sh."""
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


def preserve_source():
    document = json.loads((DOCS / 'evidence/S24-preserved-source.json').read_text())
    for name, expected in document['sha256'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('A retained migration, assertion, policy or dependency input changed: ' + name)


def execute(directory):
    preserve_source()
    require_local_docker()
    env_file = directory / 'env'
    create_local_env(env_file)
    HIDDEN_VALUES.update(line.split('=', 1)[1] for line in env_file.read_text().splitlines()
                         if line.startswith(('DJANGO_SECRET_KEY=', 'DB_PASSWORD=')))
    with env_file.open('a') as stream:
        stream.write('WEB_PORT=0\n')
    project = 'accounting-s24-check-' + secrets.token_hex(6)
    command, environment = compose_command(env_file, project), compose_environment()

    def compose(*args):
        return run(command + list(args), environment=environment)

    if compose('ps', '--all', '--quiet').stdout.strip() or run(
            ['docker', 'volume', 'ls', '--filter', 'label=com.docker.compose.project=' + project, '--quiet'],
            environment=environment).stdout.strip():
        raise RuntimeError('Refusing to adopt an existing Docker project')
    name = project + '-suite'
    try:
        print('[S24] Disposable local Docker project: ' + project, flush=True)
        compose('build', 'web')
        compose('up', '--detach', '--wait', '--wait-timeout', '180', 'db')

        def manage(*args):
            return compose('run', '--rm', '--no-deps', '--entrypoint', 'python', 'web', 'manage.py', *args)

        manage('migrate', '--noinput')
        manage('makemigrations', '--check', '--dry-run')
        manage('check', '--fail-level=WARNING')
        compose('run', '--name', name, '--no-deps', '--env', 'ACCOUNTING_REGRESSION_REPORT=/tmp/s24-suite.json',
                '--env', 'ACCOUNTING_BOUNDARY_REPORT=/tmp/s24-boundary.jsonl', '--entrypoint', 'python', 'web',
                'manage.py', 'test', '--settings=core.settings.test', '--testrunner=' + RUNNER, '--noinput', '--verbosity=1')
        run(['docker', 'cp', name + ':/tmp/s24-suite.json', directory / 'suite.json'], environment=environment)
        run(['docker', 'cp', name + ':/tmp/s24-boundary.jsonl', directory / 'boundary.jsonl'], environment=environment)
        suite = json.loads((directory / 'suite.json').read_text())
        boundary = [json.loads(line) for line in (directory / 'boundary.jsonl').read_text().splitlines()]
        count = sum(isinstance(node, ast.FunctionDef) and node.name.startswith('test_')
                    for node in ast.walk(ast.parse((ROOT / 'accounting/tests_corrections.py').read_text())))
        if suite['tests_run'] != 605 + count or suite['known_failures_reproduced'] != 0 or any(
                suite[key] for key in ('unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')):
            raise RuntimeError('Unexpected strict regression outcome; inspect the test output')
        cases = {row['case_id']: row for row in suite['cases']}
        if len(cases) != 36 or any(case['outcome'] != 'passed' for case in cases.values()):
            raise RuntimeError('All 36 retained financial assertions must pass, including TRF-001')
        expected_ids = {row['case_id'] for row in csv.DictReader((DOCS / 'evidence/S19-office-boundary.csv').open(newline=''))}
        personas = {'anonymous', 'owner', 'accountant', 'inactive-profile', 'inactive-user', 'missing-profile', 'inactive-office', 'platform-no-profile'}
        for route, has_post in (('agreement-charge-add', True), ('entity-settlements', False),
                                ('cash-allocation-add', True), ('allocation-release', True),
                                ('cash-correction', True), ('cash-refund', True), ('charge-correction', True),
                                ('agreement-amend', True), ('finance-period-close', True), ('finance-correction-history', False)):
            expected_ids |= {'http-get:' + route + ':' + persona + ':own-office' for persona in personas}
            if has_post:
                expected_ids |= {'http-post:' + route + ':' + persona + ':invalid-membership' for persona in personas - {'owner', 'accountant'}}
            expected_ids.add('inventory:' + route + ':review:declared-office-business')
        if len(boundary) != 922 or len({row['case_id'] for row in boundary}) != 922 or any(row['result'] != 'Passed' for row in boundary) or {row['case_id'] for row in boundary} != expected_ids:
            raise RuntimeError('Retain every previous boundary case and all 84 new route cases: 922 total')
        version = int(manage('shell', '--no-imports', '-c', 'from django.db import connection;print(connection.pg_version)').stdout.strip())
        if version // 10000 != 17:
            raise RuntimeError('PostgreSQL 17 required')
        return {'step': 'S24', 'status': 'Verified', 'mode': 'operator-docker-compose-postgresql17', 'docker_execution': True,
                'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
                'suite': {key: value for key, value in suite.items() if key != 'cases'}, 'financial_cases': suite['cases'],
                's24_tests': count, 'previous_test_count': 605, 'boundary_cases': 922, 'postgresql_version_num': version,
                'source_commit': 'git:' + subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'application_context_digest': candidate_context()[1]['digest'], 'local_demo_changed': False,
                'cloud_or_vm_changed': False, 'migrations_added': ['0019_financial_corrections', '0020_financial_correction_guards'], 'agent_tests_run': False,
                'browser_greek_acceptance': 'Pending', 'full_requirement_acceptance': 'Pending',
                'original_migrations_assertions_locks_preserved': True, 'baseline': 'S23 operator: 605 passes, 36 finance cases, 838 boundary cases',
                'owner_confirmed_grouped_corrections': True, 'source_linked_refunds': True,
                'prospective_terms_and_cancellation': True, 'declared_period_cutoff': True,
                'restricted_role_ddl': 'Pending', 'new_human_accounts_created': False}
    finally:
        # Only the fresh random project above is removed, never the retained demo.
        compose('down', '--volumes', '--remove-orphans')


def record(report):
    from prepare_s24 import record_result
    record_result(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    try:
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
            raise RuntimeError('Commit the candidate source/evidence before verification')
        before = candidate_context()[1]['digest']
        with tempfile.TemporaryDirectory(prefix='accounting-s24-') as tmp:
            result = execute(Path(tmp))
        if before != candidate_context()[1]['digest'] or subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip():
            raise RuntimeError('Source changed during verification; no result was recorded')
        if args.record:
            record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError) as error:
        parser.exit(1, 'S24 stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
