#!/usr/bin/env python3
"""Read a private declared R1 review; no source, account or environment changes."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from dev import ROOT
import image
from r1_gate import digest_object, matrix, pending_review, profile, require, review_blockers, technical_valid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True)
    args = parser.parse_args()
    try:
        path = Path(args.review).expanduser().resolve(strict=True)
        require(path.is_file() and path.is_relative_to((ROOT / 'private/s31').resolve()) and path.stat().st_uid == os.getuid()
                and path.stat().st_mode & 0o077 == 0 and path.stat().st_size <= 1024 * 1024,
                'Use a private owner-only JSON review under ignored private/s31 (max 1 MiB)')
        matrix(ROOT)
        report = json.loads((ROOT / 'docs/implementation/evidence/S31-verification.json').read_text())
        technical_valid(report)
        require(re.fullmatch(r'git:[0-9a-f]{40}', report['source_commit']), 'Exact verified source commit required')
        tracking = {'docs/implementation/evidence/S31-verification.json', 'docs/implementation/state.md',
                    'docs/implementation/steps.csv', 'docs/implementation/traceability.csv'}
        changed = subprocess.check_output(['git', 'diff', '--name-only', report['source_commit'][4:]], cwd=ROOT, text=True).splitlines()
        require(set(changed) <= tracking and not subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=ROOT).strip(),
                'Source changed since the S31 rehearsal; obtain a newly bound technical report')
        docs = ROOT / 'docs/implementation'
        require(report['matrix_sha256'] == digest_object(json.loads((docs / 'r1_acceptance_matrix.json').read_text()))
                and report['workload_sha256'] == digest_object(profile(json.loads((docs / 'r1_workload.json').read_text())))
                and report['application_context_digest'] == image.candidate_context()[1]['digest'],
                'Current matrix/workload/application differs from the reviewed rehearsal')
        expected = pending_review(report['source_commit'], report['application_context_digest'], digest_object(report),
                                  report['matrix_sha256'], report['workload_sha256'])
        blockers = review_blockers(json.loads(path.read_text()), expected)
        # Names, personal observations and private references are never echoed.
        print(json.dumps({'step': 'S31', 'release_decision': 'Blocked', 'declared_review_only': True,
              'review_blockers': blockers, 'writes_performed': False, 'live_cutover_executed': False}, ensure_ascii=False, indent=2))
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        parser.exit(1, 'S31 review stopped: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
