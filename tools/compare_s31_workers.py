#!/usr/bin/env python3
"""Operator-only 2/4/2 sync-worker comparison; official S31 stays unchanged."""
import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

from dev import ROOT, require_local_docker
import image
import operations_common as common
import operations_pg as pg
from diagnose_s31 import DiagnosticRehearsal, TRACKING
from r1_gate import digest_bytes, digest_object, matrix, preserved, profile, require

DOCS = ROOT / 'docs/implementation'
MANIFEST = DOCS / 'evidence/S31-worker-comparison.json'
SEQUENCE = (('control_before', 2), ('candidate_four', 4), ('control_after', 2))
PROC_PROBE = """
import json, os
from pathlib import Path
children = Path('/proc/1/task/1/children').read_text().split()
live = 0
for child in children:
    value = Path('/proc') / child / 'status'
    try:
        fields = dict(row.split(':', 1) for row in value.read_text().splitlines() if ':' in row)
    except FileNotFoundError:
        continue
    if fields.get('PPid', '').strip() == '1' and not fields.get('State', '').lstrip().startswith('Z'):
        live += 1
print(json.dumps({'configured_workers': int(os.environ['GUNICORN_WORKERS']), 'live_worker_children': live}))
"""


class WorkerComparison(DiagnosticRehearsal):
    def business_state(self):
        # Only this fresh nonce-owned candidate is reachable. Authentication
        # fixtures may change sessions/login/MFA bookkeeping; business cannot.
        with pg.snapshot(self.pg_command('db', 'candidate', 'psql'), environment=self.environment) as (_, rows):
            business = [row for row in rows if row['table'].startswith('public.accounting_') and row['table'] not in {
                'public.accounting_authsecuritystate', 'public.accounting_authenticatordevice'}]
        require(len(business) >= 30, 'Complete accounting business snapshot required')
        return business

    def effective_runtime(self, workers):
        template = ('{"image":{{json .Image}},"nano_cpus":{{json .HostConfig.NanoCpus}},'
                    '"cpu_quota":{{json .HostConfig.CpuQuota}},"cpu_period":{{json .HostConfig.CpuPeriod}},'
                    '"memory_bytes":{{json .HostConfig.Memory}},"entrypoint":{{json .Config.Entrypoint}},'
                    '"command":{{json .Config.Cmd}}}')
        actual = json.loads(common.run(['docker', 'inspect', '--format', template, self.container('web')],
                                       environment=self.environment))
        cpu_limit = actual['nano_cpus'] / 1_000_000_000 if actual['nano_cpus'] > 0 else (
            actual['cpu_quota'] / actual['cpu_period'] if actual['cpu_quota'] > 0 and actual['cpu_period'] > 0 else None)
        require(cpu_limit == 2 and actual['image'] == self.image_id and actual['memory_bytes'] == 1024 * 1024 * 1024
                and actual['entrypoint'] == ['gunicorn']
                and actual['command'] == ['core.wsgi:application', '--config', 'gunicorn.conf.py'],
                'Worker comparison image, command or resource limits changed')
        for _ in range(30):
            result = self.compose('exec', '-T', 'web', 'python', '-c', PROC_PROBE, timeout=15)
            observed = json.loads(result.stdout)
            if observed == {'configured_workers': workers, 'live_worker_children': workers}:
                return {**actual, **observed, 'effective_cpu_limit': cpu_limit,
                        'worker_class': 'sync', 'scope': 'fresh owned comparison web only'}
            time.sleep(.2)
        raise RuntimeError('Expected live Gunicorn worker count was not observed')

    def switch_workers(self, baseline, workers):
        require(workers in (2, 4) and baseline['environment']['GUNICORN_WORKERS'] == '2', 'Fixed 2/4 comparison only')
        replacement = copy.deepcopy(baseline)
        replacement['environment']['GUNICORN_WORKERS'] = str(workers)
        self.definition['services']['web'] = replacement
        self.write_definition()
        self.compose('up', '--detach', '--no-deps', '--force-recreate', 'web')
        self.ready('web')
        return self.effective_runtime(workers)

    def probe(self, action, *, suffix='candidate', host='db', running=None):
        if action != 'benchmark':
            return super().probe(action, suffix=suffix, host=host, running=running)
        require((suffix, host, running) == ('candidate', 'db', 'web'), 'Only the owned candidate benchmark may be compared')
        baseline = copy.deepcopy(self.definition['services']['web'])
        original_database = self.container('db')
        original_business = self.business_state()
        trials = []
        try:
            for label, workers in SEQUENCE:
                self.stage = 'worker-comparison-' + label
                print('[S31] Σύγκριση ' + label + ': ' + str(workers) + ' sync workers.', flush=True)
                effective = self.switch_workers(baseline, workers)
                require(self.container('db') == original_database and self.business_state() == original_business,
                        'Comparison database or accounting business data changed before measurement')
                measured = super().probe('benchmark', suffix=suffix, host=host, running=running)
                require(self.business_state() == original_business, 'Comparison HTTP/profiling changed accounting business data')
                # Check the worker population and quota again after each run.
                require(self.effective_runtime(workers) == effective, 'Comparison runtime changed during measurement')
                trials.append({'condition': label, 'web_workers': workers, 'effective_runtime': effective,
                               'business_tables_unchanged': len(original_business), 'performance': measured})
        finally:
            # On error main's finally removes this owned project. The source
            # workload, base/recovery environment and every other service were
            # never changed. A successful third condition has recreated web=2.
            self.definition['services']['web'] = baseline
            self.write_definition()
        require(len(trials) == 3 and self.effective_runtime(2)['live_worker_children'] == 2,
                'Comparison must finish with the two-worker control')
        before, candidate, after = [trial['performance'] for trial in trials]
        ratios = {}
        for operation in ('list', 'detail', 'annual_report'):
            a, b, c = [row['operations'][operation]['p95_seconds'] for row in (before, candidate, after)]
            require(a > 0 and c > 0, 'Positive control p95 required')
            ratios[operation] = {'candidate_to_control_before': b / a, 'candidate_to_control_after': b / c,
                                 'control_after_to_before': c / a}
        comparison = {'sequence': [row['condition'] for row in trials], 'trials': trials,
                      'candidate_meets_original_timing_thresholds_in_this_comparison': candidate['thresholds_passed'],
                      'p95_ratios': ratios, 'measured_http_requests': 1350, 'excluded_client_warmups': 9,
                      'business_tables_compared_before_and_after_every_trial': len(original_business),
                      'original_database_container_unchanged': True, 'finished_with_two_sync_workers': True,
                      'automatic_runtime_profile_promotion': False,
                      'scope': 'fixed exploratory 2/4/2 experiment; original workload and official S31 receipt remain unchanged',
                      'limitations': ['Single three-condition sequence; no randomisation or statistical confidence claim',
                                      'Host contention and caches may drift; both controls and all errors are retained',
                                      'Each condition recreates web, then uses the unchanged three warmups and 450 measured attempts',
                                      'Fixture auth/session rows grow; all accounting business tables are checked unchanged',
                                      'The load generator shares the web quota; real VM/workload acceptance is Pending']}
        # The inherited recovery harness sees a truthful final two-worker
        # control. Four-worker measurements remain a separately labelled trial.
        return {**after, 'worker_comparison': comparison}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', default=str(Path.home() / '.config/totalaccounting/recovered-backup-age.key'))
    args = parser.parse_args(); stage = 'source-and-receipt-preflight'
    try:
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(), 'Commit source before S31 worker comparison')
        source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        manifest = json.loads(MANIFEST.read_text())
        require(set(manifest['operator_source_sha256']) == {'tools/compare_s31_workers.py', 'tools/prepare_s31_worker_comparison.py'},
                'Published worker comparison source inventory required')
        for name, expected in (manifest['operator_source_sha256'] | manifest['unchanged_guard_sha256']).items():
            require(digest_bytes((ROOT / name).read_bytes()) == expected, 'Worker comparison source changed: ' + name)
        retained = preserved(ROOT, DOCS / 'evidence/S31-preserved-source.json')
        require(retained == 592, 'All original S31 protected paths required')
        matrix(ROOT)
        workload = profile(json.loads((DOCS / 'r1_workload.json').read_text()))
        original = {name: digest_bytes((DOCS / name).read_bytes()) for name in TRACKING}
        receipt = json.loads((DOCS / 'evidence/S31-verification.json').read_text())
        require(digest_object(receipt) == manifest['observed_failed_receipt_sha256'] and receipt['technical_status'] == 'Failed'
                and receipt['status'] == 'Prepared' and receipt['release_decision'] == 'Blocked', 'Actual formal Failed receipt must remain unchanged')
        context = image.candidate_context()[1]
        require(context['file_count'] == 284 and context['digest'] == receipt['application_context_digest'], 'Exact S30 application inputs required')
        require_local_docker(); common.check_age(); common.identity_file(args.identity); common.require_tmpfs('/dev/shm')
        require(shutil.disk_usage('/dev/shm').free >= 64 * 1024 * 1024, 'At least 64 MiB free tmpfs required')
        selected = image.reuse_for_verification(receipt['image']['image_id'])
        host_before = {'logical_cpus': os.cpu_count(), 'affinity_cpus': len(os.sched_getaffinity(0)), 'load_average': list(os.getloadavg())}
        stage = 'fresh-owned-synthetic-worker-comparison'
        with tempfile.TemporaryDirectory(prefix='accounting-s31-workers-', dir='/dev/shm') as directory:
            Path(directory).chmod(0o700)
            runner = WorkerComparison(directory, selected['image_id'], args.identity, workload)
            try:
                rehearsal = runner.execute(context['digest'])
            except Exception as error:
                print('S31-WORKERS-DIAG ' + json.dumps({'stage': runner.stage, 'error': type(error).__name__}), flush=True)
                raise
            finally:
                runner.cleanup()
        require(not Path(directory).exists(), 'Worker comparison plaintext cleanup failed')
        require(original == {name: digest_bytes((DOCS / name).read_bytes()) for name in TRACKING}
                and preserved(ROOT, DOCS / 'evidence/S31-preserved-source.json') == retained
                and image.candidate_context()[1]['digest'] == context['digest']
                and subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() == source
                and not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(),
                'Formal result, historical bindings or source changed during comparison')
        comparison = rehearsal['performance']['worker_comparison']
        report = {'step': 'S31', 'scope': 'exploratory-sync-worker-comparison', 'status': 'Observed',
                  'checked_at': datetime.now(ZoneInfo('Europe/Athens')).isoformat(timespec='seconds'),
                  'source_commit': 'git:' + source, 'application_context_digest': context['digest'],
                  'image_id': selected['image_id'], 'observed_failed_receipt_sha256': manifest['observed_failed_receipt_sha256'],
                  'official_technical_status': 'Failed', 'official_receipt_unchanged': True, 'release_decision': 'Blocked',
                  'all_85_full_acceptances': 'Pending', 'full_848_suite_and_real_broker_rerun': False,
                  'host_before': host_before, 'host_load_average_after': list(os.getloadavg()),
                  'rehearsal': {**rehearsal, 'owned_resources_removed': True, 'plaintext_removed': True},
                  'automatic_runtime_profile_promotion': False, 'local_demo_or_vm_changed': False, 'agent_native_execution': False}
        parent = ROOT / 'private/s31'
        require(not any(p.is_symlink() for p in (ROOT / 'private', parent)), 'Comparison output parent must not be a symlink')
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = parent / ('workers-' + runner.nonce); destination.mkdir(mode=0o700)
        output = destination / 'comparison.json'
        require(subprocess.run(['git', 'check-ignore', '--quiet', str(output.relative_to(ROOT))], cwd=ROOT).returncode == 0,
                'Comparison output must remain ignored by Git')
        with output.open('x', encoding='utf-8') as stream:
            output.chmod(0o600); json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
        summaries = []
        for trial in comparison['trials']:
            measured = trial['performance']; diagnostic = measured['diagnostics']
            summaries.append({'condition': trial['condition'], 'web_workers': trial['web_workers'],
                'effective_runtime': trial['effective_runtime'], 'operations': measured['operations'],
                'errors': measured['errors'], 'thresholds_passed': measured['thresholds_passed'],
                'duration_seconds': measured['duration_seconds'], 'requests': measured['requests'],
                'gunicorn_logged_seconds': diagnostic['gunicorn_logged_seconds'], 'cgroup_intervals': diagnostic['cgroup_intervals']})
        summary = {key: report[key] for key in ('step', 'scope', 'status', 'checked_at', 'official_technical_status', 'official_receipt_unchanged', 'release_decision')}
        summary.update(trials=summaries, p95_ratios=comparison['p95_ratios'],
            candidate_meets_original_timing_thresholds_in_this_comparison=comparison['candidate_meets_original_timing_thresholds_in_this_comparison'],
            measured_http_requests=1350, business_tables_unchanged=comparison['business_tables_compared_before_and_after_every_trial'],
            finished_with_two_sync_workers=True, automatic_runtime_profile_promotion=False,
            recovery_targets_met=rehearsal['recovery']['proposed_targets_met_in_this_rehearsal'],
            host_before=host_before, host_load_average_after=report['host_load_average_after'],
            owned_resources_removed=True, plaintext_removed=True)
        print('S31-WORKERS-RESULT ' + json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
        print('[S31] Ιδιωτική αναφορά σύγκρισης: ' + str(output), flush=True)
        print('[S31] Η σύγκριση ολοκληρώθηκε. Η επίσημη τεχνική αποτυχία και η έκδοση Blocked διατηρήθηκαν.', flush=True)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError, AssertionError) as error:
        from verify_s05 import redact
        print('S31-WORKERS-DIAG ' + json.dumps({'stage': stage, 'error': type(error).__name__}), file=sys.stderr)
        parser.exit(1, 'S31 worker comparison stopped: ' + redact(str(error)) + '\n')


if __name__ == '__main__':
    main()
