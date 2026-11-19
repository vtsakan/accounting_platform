"""Operator-only proof of effective selected Gunicorn runtime in owned services."""
import json
import time
import operations_common as common
from s31_profiles import validate_runtime

PROC = """
import json, os
from pathlib import Path
count = 0
for child in Path('/proc/1/task/1/children').read_text().split():
    try:
        fields = dict(line.split(':',1) for line in (Path('/proc')/child/'status').read_text().splitlines() if ':' in line)
    except FileNotFoundError:
        continue
    if fields.get('PPid','').strip() == '1' and not fields.get('State','').lstrip().startswith('Z'):
        count += 1
print(json.dumps({'configured_workers':int(os.environ['GUNICORN_WORKERS']),'live_worker_children':count}))
"""


def runtime_proof(runner, service):
    from r1_gate import require
    require(service in ('web', 'restored_web'), 'Fixed owned Gunicorn service required')
    template = ('{"image":{{json .Image}},"nano_cpus":{{json .HostConfig.NanoCpus}},'
                '"cpu_quota":{{json .HostConfig.CpuQuota}},"cpu_period":{{json .HostConfig.CpuPeriod}},'
                '"memory_bytes":{{json .HostConfig.Memory}},"entrypoint":{{json .Config.Entrypoint}},'
                '"command":{{json .Config.Cmd}}}')
    actual = json.loads(common.run(['docker', 'inspect', '--format', template, runner.container(service)], environment=runner.environment))
    limit = actual['nano_cpus'] / 1_000_000_000 if actual['nano_cpus'] > 0 else (
        actual['cpu_quota'] / actual['cpu_period'] if actual['cpu_quota'] > 0 and actual['cpu_period'] > 0 else None)
    workers = runner.workload['synthetic_envelope']['web_workers']
    for _ in range(30):
        observed = json.loads(runner.compose('exec', '-T', service, 'python', '-c', PROC, timeout=15).stdout)
        if observed == {'configured_workers': workers, 'live_worker_children': workers}:
            proof = {**actual, **observed, 'effective_cpu_limit': limit, 'worker_class': 'sync', 'service': service}
            return validate_runtime(proof, workers, runner.image_id, service)
        time.sleep(.2)
    raise RuntimeError('Selected live Gunicorn worker population was not observed')
