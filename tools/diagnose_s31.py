#!/usr/bin/env python3
"""Operator-only S31 performance diagnosis; never changes the release receipt."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

from dev import ROOT, require_local_docker
import image
import operations_common as common
from r1_gate import digest_bytes, digest_object, matrix, percentile95, preserved, profile, require
from s31_rehearsal import Rehearsal

DOCS = ROOT / 'docs/implementation'
RECEIPT = DOCS / 'evidence/S31-verification.json'
SOURCE = DOCS / 'evidence/S31-performance-diagnostics.json'
TRACKING = ('evidence/S31-verification.json', 'state.md', 'steps.csv', 'traceability.csv',
            'evidence/S31-operator-receipts.json', 'evidence/S31-historical-evidence.json')
ACCESS = re.compile(r'(?:^|: )\S+ GET (/[^\s?]*) ([0-9]{3}) ([0-9]+(?:\.[0-9]+)?)$')


def distribution(values):
    require(values and all(type(v) in (int, float) and v >= 0 for v in values), 'Invalid diagnostic timings')
    return {'samples': len(values), 'p50_seconds': sorted(values)[(len(values) - 1) // 2],
            'p95_seconds': percentile95(values), 'max_seconds': max(values)}


def service_times(data):
    """Normalise only the three synthetic routes; retain all timed attempts."""
    samples = {name: [] for name in ('list', 'detail', 'annual_report')}
    details = set()
    for line in data.decode(errors='strict').splitlines():
        match = ACCESS.search(line)
        if match is None:
            continue
        path, status, elapsed = match.groups()
        if path == '/transactions/':
            name = 'list'
        elif path == '/report/':
            name = 'annual_report'
        elif re.fullmatch(r'/entity/[0-9]+/', path):
            name = 'detail'; details.add(path)
        else:
            continue
        require(status == '200', 'Diagnostic HTTP access log contains a failed request')
        samples[name].append(float(elapsed))
    require(len(details) == 1 and all(len(row) == 151 for row in samples.values()),
            'Expected one warmup plus all 150 measured Gunicorn log entries per operation')
    # Access records have no request identifier. Keep all 151 entries rather
    # than assume inter-worker log ordering identifies the warmup reliably.
    # These descriptive distributions never enter the 150-attempt gate.
    return {name: {**distribution(row), 'warmup_included': 1} for name, row in samples.items()}


class DiagnosticRehearsal(Rehearsal):
    def counters(self, service):
        # Cgroup v2 accounting is read inside each owned service. No host paths,
        # process arguments, resolved environment, SQL or credentials are read.
        command = ('for leaf in cpu.stat cpu.max memory.current memory.max memory.events; do '
                   'if [ -r "/sys/fs/cgroup/$leaf" ]; then '
                   'printf "S31-CGROUP %s\\n" "$leaf"; cat "/sys/fs/cgroup/$leaf"; fi; done')
        began = time.monotonic()
        result = self.compose('exec', '-T', service, 'sh', '-c', command, timeout=20)
        sections = {}; current = None
        for line in result.stdout.decode().splitlines():
            if line.startswith('S31-CGROUP '):
                current = line.split(' ', 1)[1]; sections[current] = []
            elif current is not None:
                sections[current].append(line)
        if set(sections) != {'cpu.stat', 'cpu.max', 'memory.current', 'memory.max', 'memory.events'}:
            return {'availability': 'Unavailable; cgroup v2 accounting not exposed'}
        def counters(name):
            return {row.split()[0]: int(row.split()[1]) for row in sections[name]}
        return {'availability': 'Observed', 'monotonic': (began + time.monotonic()) / 2,
                'cpu': counters('cpu.stat'), 'cpu_max': ' '.join(sections['cpu.max']),
                'memory_current_bytes': int(sections['memory.current'][0]),
                'memory_max': ' '.join(sections['memory.max']), 'memory_events': counters('memory.events')}

    def interval(self, before, after):
        if before['availability'] != 'Observed' or after['availability'] != 'Observed':
            return {'availability': 'Unavailable; do not infer CPU contention'}
        elapsed = after['monotonic'] - before['monotonic']
        require(elapsed > 0 and before['cpu_max'] == after['cpu_max'], 'Diagnostic CPU scope changed')
        delta = {key: after['cpu'][key] - before['cpu'][key] for key in ('usage_usec', 'nr_periods', 'nr_throttled', 'throttled_usec')}
        require(all(v >= 0 for v in delta.values()), 'Diagnostic CPU counter reset')
        return {'availability': 'Observed', 'interval_seconds': elapsed, 'cpu_max': after['cpu_max'],
                'average_cpu_equivalents': delta['usage_usec'] / 1_000_000 / elapsed,
                **delta, 'memory_before_bytes': before['memory_current_bytes'],
                'memory_after_bytes': after['memory_current_bytes'], 'memory_limit': after['memory_max'],
                'memory_event_deltas': {k: after['memory_events'][k] - v for k, v in before['memory_events'].items()},
                'scope': 'entire unchanged benchmark probe, including fixture reads, 50 session creation and three warmups; web includes load generator'}

    def probe(self, action, *, suffix='candidate', host='db', running=None):
        if action != 'benchmark':
            return super().probe(action, suffix=suffix, host=host, running=running)
        require(running == 'web', 'Only the original isolated benchmark may be diagnosed')
        previous = self.compose('logs', '--no-color', '--no-log-prefix', 'web')
        before = {name: self.counters(name) for name in ('db', 'web')}
        measured = super().probe(action, suffix=suffix, host=host, running=running)
        after = {name: self.counters(name) for name in ('db', 'web')}
        self.stage = 'collect-performance-access-logs-and-profiles'
        # Logging may flush just after the last HTTP response. Wait only for all
        # 453 original accesses; do not discard a slow request or retry the load.
        logged = None
        for attempt in range(20):
            current = self.compose('logs', '--no-color', '--no-log-prefix', 'web')
            channels = ('stdout', 'stderr')
            require(all(getattr(current, name).startswith(getattr(previous, name)) for name in channels)
                    and sum(len(getattr(current, name)) for name in channels) <= 1024 * 1024,
                    'Diagnostic access log rotated or exceeded its bound')
            # Docker/Compose may forward a container's logging stream through
            # either channel. Preserve each channel's prefix independently.
            delta = b'\n'.join(getattr(current, name)[len(getattr(previous, name)):] for name in channels)
            try:
                logged = service_times(delta)
                break
            except RuntimeError:
                if attempt == 19:
                    raise
                time.sleep(.1)
        # Instrumented/in-process and single-session samples run afterwards.
        # They never enter or replace the original 450-request measurement.
        result = self.compose('exec', '-T', 'web', 'python', '/opt/s31/tools/s31_performance_probe.py', timeout=240)
        rows = [line.removeprefix('S31-PERFORMANCE ') for line in result.stdout.decode().splitlines()
                if line.startswith('S31-PERFORMANCE ')]
        require(len(rows) == 1, 'One isolated profiling result required')
        diagnostic = json.loads(rows[0])
        return {**measured, 'diagnostics': {
            'gunicorn_logged_seconds': logged,
            'cgroup_intervals': {name: self.interval(before[name], after[name]) for name in before},
            **diagnostic,
            'limitations': [
                'Client and Gunicorn distributions are not paired; do not subtract their p95 values to claim queue time',
                'All 151 Gunicorn entries per operation are retained, including one warmup; the unchanged client gate uses 150 measured attempts',
                'Client time includes scheduling, connection, socket/worker waiting and full body read; Gunicorn log time has another boundary',
                'Cgroup averages include the in-container load generator and are not peak utilisation or a VM capacity acceptance',
                'Sequential HTTP and instrumented in-process profiles are explanatory only; the original 50-session gate is unchanged']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', default=str(Path.home() / '.config/totalaccounting/recovered-backup-age.key'))
    args = parser.parse_args(); stage = 'retained-source-and-failed-receipt'
    try:
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(), 'Commit source before S31 diagnosis')
        source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        manifest = json.loads(SOURCE.read_text())
        require(set(manifest['operator_source_sha256']) == {'tools/diagnose_s31.py', 'tools/s31_performance_probe.py'},
                'Published diagnostic source inventory required')
        for name, expected in manifest['operator_source_sha256'].items():
            require(digest_bytes((ROOT / name).read_bytes()) == expected, 'Diagnostic source changed: ' + name)
        retained = preserved(ROOT, DOCS / 'evidence/S31-preserved-source.json')
        require(retained == 592, 'All 592 existing protections required')
        matrix(ROOT)
        workload = profile(json.loads((DOCS / 'r1_workload.json').read_text()))
        original = {name: digest_bytes((DOCS / name).read_bytes()) for name in TRACKING}
        receipt = json.loads(RECEIPT.read_text())
        require(digest_object(receipt) == manifest['observed_failed_receipt_sha256'] and receipt['technical_status'] == 'Failed'
                and receipt['status'] == 'Prepared' and receipt['release_decision'] == 'Blocked',
                'The actual supplied S31 failed receipt must remain unchanged')
        context = image.candidate_context()[1]
        require(context['file_count'] == 284 and context['digest'] == receipt['application_context_digest'], 'Unchanged S30 application context required')
        require_local_docker(); common.check_age(); common.identity_file(args.identity); common.require_tmpfs('/dev/shm')
        require(shutil.disk_usage('/dev/shm').free >= 64 * 1024 * 1024, 'At least 64 MiB free tmpfs required')
        selected = image.reuse_for_verification(receipt['image']['image_id'])
        stage = 'fresh-synthetic-rehearsal-and-performance-diagnosis'
        with tempfile.TemporaryDirectory(prefix='accounting-s31-diagnostic-', dir='/dev/shm') as directory:
            Path(directory).chmod(0o700)
            runner = DiagnosticRehearsal(directory, selected['image_id'], args.identity, workload)
            try:
                rehearsal = runner.execute(context['digest'])
            except Exception as error:
                print('S31-PERFORMANCE-DIAG ' + json.dumps({'stage': runner.stage, 'error': type(error).__name__}), flush=True)
                raise
            finally:
                runner.cleanup()
        require(not Path(directory).exists(), 'Diagnostic plaintext cleanup failed')
        require(original == {name: digest_bytes((DOCS / name).read_bytes()) for name in TRACKING}, 'S31 receipt, bindings or tracking changed')
        require(preserved(ROOT, DOCS / 'evidence/S31-preserved-source.json') == retained
                and image.candidate_context()[1]['digest'] == context['digest']
                and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == source
                and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(), 'Retained source changed during diagnosis')
        report = {'step': 'S31', 'scope': 'performance-diagnostics-only', 'status': 'Observed',
            'checked_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'), 'source_commit': 'git:' + source,
            'application_context_digest': context['digest'], 'image_id': selected['image_id'],
            'observed_failed_receipt_sha256': manifest['observed_failed_receipt_sha256'],
            'official_technical_status': 'Failed', 'official_receipt_unchanged': True, 'release_decision': 'Blocked',
            'full_requirement_acceptance': 'Pending', 'full_requirement_acceptances_pending': 85,
            'retained_source_files_checked': retained, 'full_848_suite_and_real_broker_rerun': False,
            'prior_848_36_40_and_real_broker_result': 'Retained actual S31 operator receipt; not rerun by this diagnostic',
            'rehearsal': {**rehearsal, 'owned_resources_removed': True, 'plaintext_removed': True},
            'agent_native_execution': False, 'live_cutover_executed': False, 'local_demo_or_vm_changed': False}
        parent = ROOT / 'private/s31'
        require(not any(p.is_symlink() for p in (ROOT / 'private', parent)), 'Diagnostic output parent must not be a symlink')
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = parent / ('performance-' + runner.nonce)
        destination.mkdir(mode=0o700)
        output = destination / 'performance.json'
        require(subprocess.run(['git', 'check-ignore', '--quiet', str(output.relative_to(ROOT))], cwd=ROOT).returncode == 0,
                'Diagnostic report must remain ignored by Git')
        with output.open('x', encoding='utf-8') as stream:
            output.chmod(0o600); json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
        performance = rehearsal['performance']
        summary = {key: report[key] for key in ('step', 'scope', 'status', 'checked_at', 'official_technical_status', 'official_receipt_unchanged', 'release_decision')}
        summary.update(performance={key: performance[key] for key in ('operations', 'errors', 'thresholds_passed', 'duration_seconds', 'requests')},
                       diagnostics=performance['diagnostics'], recovery_targets_met=rehearsal['recovery']['proposed_targets_met_in_this_rehearsal'],
                       owned_resources_removed=True, plaintext_removed=True)
        print('S31-PERFORMANCE-RESULT ' + json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
        print('[S31] Ιδιωτική διαγνωστική αναφορά: ' + str(output), flush=True)
        print('[S31] Η διάγνωση καταγράφηκε. Η επίσημη τεχνική αποτυχία και η έκδοση Blocked διατηρήθηκαν.', flush=True)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, AssertionError) as error:
        from verify_s05 import redact
        print('S31-PERFORMANCE-DIAG ' + json.dumps({'stage': stage, 'error': type(error).__name__}), file=sys.stderr)
        parser.exit(1, 'S31 diagnosis stopped: ' + redact(str(error)) + '\n')


if __name__ == '__main__':
    main()
