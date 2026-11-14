#!/usr/bin/env python3
"""Optional operator S24A production-image gate; package apply never calls it."""
import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo

from dev import ROOT
from image import committed_context
from verify_s24 import preserve_source

DOCS = ROOT / 'docs/implementation'
REPORT = ROOT / 'private/s24a-delivery.json'


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def verified_report(path, revision, context):
    proof = json.loads(path.read_text())
    image, suite = proof['image'], proof['suite']
    require(proof['step'] == 'delivery' and proof['status'] == 'Verified'
            and proof['mode'] == 'docker-production-image' and proof['docker_execution_this_step'] is True
            and proof['production_image_built_verified'] is True, 'A completed production Docker delivery receipt is required')
    require(image['revision'] == 'git:' + revision and image['context']['digest'] == context['digest'],
            'Receipt belongs to another source/image; execute the current-source delivery gate')
    require(suite['tests_run'] == 661 and suite['tests_passed'] == 661, 'Expected all 656 retained and 5 new S24A tests: 661 passes')
    require(all(suite[key] == 0 for key in ('known_failures_reproduced', 'unexpected_failures', 'unexpected_errors', 'unexpected_successes', 'skips')),
            'Delivery contains a failed or incomplete outcome')
    require(len(suite['cases']) == 36 and all(case['outcome'] == 'passed' for case in suite['cases']), 'All 36 financial assertions must pass')
    require(proof['secret_scan']['unreviewed_findings'] == 0 and proof['compiled_catalog_in_sync'] is True
            and proof['dependency_locks_reproduced'] is True, 'Secret/Greek catalog/lock gate incomplete')
    require({'accounting/static/accounting/workspace/' + name for name in ('workspace.css', 'workspace.js', 'mark.svg')}
            <= set(image['context']['paths']), 'Theme assets are absent from the production image context')
    require(proof['gunicorn_http_verified'] and proof['static_export_from_same_image_verified']
            and proof['admin_manifest_references_verified'], 'Production HTTP/static verification incomplete')
    return {
        'step': 'S24A', 'status': 'Verified', 'mode': 'operator-docker-production-image',
        'verified_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
        'source_commit': 'git:' + revision, 'application_context_digest': context['digest'],
        'suite': {key: value for key, value in suite.items() if key != 'cases'}, 'financial_cases': suite['cases'],
        'retained_test_count': 656, 'new_presentation_tests': 5, 'historical_boundary_cases_preserved': 922,
        'separate_boundary_csv_generated': False, 'migrations_added': [],
        'production_image_id': image['image_id'], 'delivery_receipt': str(path.relative_to(ROOT)),
        'delivery_receipt_sha256': 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest(),
        'secret_scan_unreviewed_findings': 0, 'greek_catalog_and_dependency_locks_verified': True,
        'existing_financial_assertions_migrations_and_locks_preserved': True,
        'agent_tests_builds_migrations_or_vm_execution': False, 'local_demo_or_vm_updated': False,
        'browser_responsive_keyboard_dark_theme_acceptance': 'Pending',
        'full_s47_accessibility_conformance': 'Pending', 'full_requirement_acceptance': 'Pending',
    }


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)


def record(result):
    (DOCS / 'evidence/S24A-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    path = DOCS / 'state.md'
    text = re.sub(r'<!-- S24A-RESULT -->.*?<!-- /S24A-RESULT -->',
                  '<!-- S24A-RESULT -->\nOperator production-image gate Verified: 661 passes, all 36 finance assertions,\n'
                  'Greek catalog, dependency locks, secret scan and manifest static assets.\n'
                  'Historical S24 receipt remains unchanged. Browser/keyboard/responsive/dark\n'
                  'theme acceptance and S24A local/VM deployment remain Pending. S25 is separate.\n<!-- /S24A-RESULT -->',
                  path.read_text(), flags=re.S)
    text = re.sub(r'Updated .*?Current step:.*?\n', 'Updated ' + result['verified_at'][:10] +
                  '. Current step: **S24A Verified — Material-inspired workspace**. Next step: **Browser review; S25 remains separate**.\n', text, count=1)
    path.write_text(text)
    path = DOCS / 'steps.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row['step_id'] == 'S24A')
    row.update(status='Verified', code_reference_commit=result['source_commit'].removeprefix('git:'), blocker='',
               manual_acceptance='Operator production-image gate passed; responsive/keyboard/dark theme browser acceptance and S24A VM rollout Pending')
    write_csv(path, rows)
    path = DOCS / 'traceability.csv'
    with path.open(newline='') as stream: rows = list(csv.DictReader(stream))
    for row in rows:
        if row['requirement_id'] in {'QR-07', 'QR-08', 'UR-LOC-01'}:
            note = ' S24A operator production-image verification: 661 passes and all 36 finance cases. Manual responsive/accessibility and full acceptance remain Pending.'
            if note not in row['notes']: row['notes'] += note
            row['last_reviewed'] = result['verified_at'][:10]
    write_csv(path, rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', type=Path, help='Read an already completed current-commit delivery receipt instead of executing it again')
    parser.add_argument('--record', action='store_true')
    args = parser.parse_args()
    try:
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(), 'Commit reviewed source/evidence first')
        preserve_source()
        revision, _, context = committed_context()
        path = (args.delivery or REPORT).resolve()
        require(path.is_relative_to((ROOT / 'private').resolve()), 'Keep the production delivery receipt in ignored private/')
        if not args.delivery:
            print('[S24A] Operator production image: retained 656 tests plus 5 overview/search contracts.', flush=True)
            subprocess.run([sys.executable, str(ROOT / 'tools/verify_delivery.py'), '--report', str(path)], cwd=ROOT, check=True)
        result = verified_report(path, revision, context)
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip()
                and committed_context()[0] == revision, 'Source changed during verification; no result was recorded')
        if args.record: record(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'S24A stopped: ' + str(error) + '\n')


if __name__ == '__main__': main()
