"""Operator-only bounded ClamD and owned swap for the existing4GiB test VM."""
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import time

import preview_common as common
import preview_host as host
from r1_gate import require

IMAGE = ('clamav/clamav:stable_base@'
    'sha256:7e43db777ae70ed9b60e75fcbdfda6f462c710565c69ccff2ed83a7ec5aba417')
MEMORY_MIB = 2560
MEMORY_SWAP_MIB = 4096
SWAP_BYTES = 2 * 1024**3
SWAP_FILE = common.HOST_DATA / 'cr008-test.swap'
SWAP_BINDING = Path('/etc/accounting/cr008-test-swap.json')
VOLUME = 'accounting-preview_clamav_signatures'
OWNER = 'cr008-test-scanner'
TIMER = 'accounting-cr008-scanner-update.timer'
SERVICE = 'accounting-cr008-scanner-update.service'


def memory():
    result = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        result[key] = int(value.strip().split()[0])
    return {key: result[key] for key in ('MemTotal', 'MemAvailable', 'SwapTotal', 'SwapFree')}


def active_swap():
    return {row.split()[0] for row in Path('/proc/swaps').read_text().splitlines()[1:] if row.strip()}


def check_owned_swap(binding):
    require(not SWAP_FILE.is_symlink() and SWAP_FILE.is_file(), 'The owned test swap file is missing or not regular')
    value = SWAP_FILE.stat()
    require(binding.get('purpose') == OWNER and binding.get('path') == str(SWAP_FILE)
        and binding.get('bytes') == value.st_size == SWAP_BYTES
        and binding.get('device') == value.st_dev and binding.get('inode') == value.st_ino
        and value.st_uid == 0 and stat.S_IMODE(value.st_mode) == 0o600,
        'Existing swap identity differs; no file was overwritten or reformatted')


def ensure_swap():
    """Never replace another swap area, change fstab or remove an in-use file."""
    require(os.geteuid() == 0, 'Swap preparation requires the existing root-operated VM helper')
    if SWAP_BINDING.exists() or SWAP_BINDING.is_symlink():
        require(SWAP_BINDING.is_file() and not SWAP_BINDING.is_symlink(), 'Invalid owned swap binding')
        binding = json.loads(SWAP_BINDING.read_text())
        check_owned_swap(binding)
    elif memory()['SwapTotal'] * 1024 >= SWAP_BYTES:
        require(memory()['SwapFree'] * 1024 >= 1536 * 1024**2, 'Insufficient free existing swap for this test profile')
        return {'mode': 'existing-swap-retained', 'size_mib': memory()['SwapTotal'] // 1024}
    else:
        require(not SWAP_FILE.exists() and not SWAP_FILE.is_symlink(),
            'An unbound swap path already exists; it was not overwritten')
        descriptor = os.open(SWAP_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.posix_fallocate(descriptor, 0, SWAP_BYTES)
            os.fsync(descriptor)
            value = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        binding = {'purpose': OWNER, 'path': str(SWAP_FILE), 'bytes': SWAP_BYTES,
            'device': value.st_dev, 'inode': value.st_ino, 'formatted': False}
        common.private_json(SWAP_BINDING, binding, exclusive=True)
    check_owned_swap(binding)
    if not binding.get('formatted'):
        kind = subprocess.run(['blkid', '-p', '-s', 'TYPE', '-o', 'value', str(SWAP_FILE)],
            capture_output=True, text=True)
        require(kind.returncode in (0, 2) and kind.stdout.strip() in ('', 'swap'), 'Unexpected filesystem in the owned new swap file')
        if kind.stdout.strip() != 'swap':
            common.run(['mkswap', str(SWAP_FILE)])
        binding['formatted'] = True
        common.private_json(SWAP_BINDING, binding)
    if str(SWAP_FILE) not in active_swap():
        common.run(['swapon', '--', str(SWAP_FILE)])
    require(str(SWAP_FILE) in active_swap() and memory()['SwapFree'] >= 256 * 1024,
        'The owned test swap could not be activated with available headroom')
    return {'mode': 'owned-swap-retained', 'size_mib': 2048, 'fstab_modified': False}


def volume():
    result = subprocess.run(['docker', 'volume', 'inspect', VOLUME], capture_output=True, text=True)
    if result.returncode:
        common.run(['docker', 'volume', 'create', '--label', 'gr.accounting.owner=' + OWNER, VOLUME])
        result = subprocess.run(['docker', 'volume', 'inspect', VOLUME], capture_output=True, text=True)
    require(result.returncode == 0, 'Could not inspect the owned scanner-signature volume')
    rows = json.loads(result.stdout)
    require(len(rows) == 1 and rows[0]['Name'] == VOLUME
        and (rows[0].get('Labels') or {}).get('gr.accounting.owner') == OWNER,
        'An unrelated signature volume was retained without modification')
    return VOLUME


def prepare(config):
    require(common.run(['docker','info','--format','{{json .SwapLimit}}']).decode().strip()=='true',
        'This test profile requires actual Docker memory/swap limit support')
    swap = ensure_swap()
    require(memory()['SwapFree']>=1536*1024,'At least1.5GiB free swap is required before this test update')
    volume()
    common.run(['docker', 'pull', '--platform=linux/amd64', IMAGE])
    return {'swap': swap, 'scanner_image': IMAGE, 'scanner_memory_cap_mib': MEMORY_MIB,
        'scanner_memory_plus_swap_cap_mib': MEMORY_SWAP_MIB, 'vm_resized': False}


def update(config, compose, *, staging=False):
    """Serial signature update: no second engine loads beside the daemon."""
    ensure_swap(); volume()
    compose(config, 'stop', '--timeout', '30', 'scanner', staging=staging)
    release = host.release_path(config)
    command = ['docker', 'run', '--rm', '--name', 'accounting-cr008-signature-update', '--label',
        'gr.accounting.owner='+OWNER, '--pull=never',
        '--network', 'accounting-preview_egress', '--memory', str(MEMORY_MIB) + 'm',
        '--memory-swap', str(MEMORY_SWAP_MIB) + 'm', '--cpus', '1', '--pids-limit', '64',
        '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777',
        '--cap-drop', 'ALL', '--cap-add', 'CHOWN', '--cap-add', 'SETUID', '--cap-add', 'SETGID',
        '--security-opt', 'no-new-privileges:true',
        '--mount', 'type=volume,source=' + VOLUME + ',target=/var/lib/clamav',
        '--mount', 'type=bind,source=' + str(release / 'docker/preview-cr008-freshclam.conf') + ',target=/etc/clamav/cr008-freshclam.conf,readonly',
        '--entrypoint', '/bin/sh', IMAGE, '-ec',
        'chown clamav:clamav /var/lib/clamav; exec freshclam --stdout --config-file=/etc/clamav/cr008-freshclam.conf']
    try:
        result = subprocess.run(command, env=common.compose_environment(), capture_output=True, timeout=900)
    except subprocess.TimeoutExpired:
        # Stop only the explicitly owned updater; the scanner remains stopped.
        item=subprocess.run(['docker','inspect','accounting-cr008-signature-update'],capture_output=True,text=True)
        if item.returncode==0:
            rows=json.loads(item.stdout)
            require(len(rows)==1 and rows[0]['Config']['Image']==IMAGE
                and (rows[0]['Config'].get('Labels') or {}).get('gr.accounting.owner')==OWNER,
                'Unexpected update container identity; nothing was removed')
            subprocess.run(['docker','stop','--time','10',rows[0]['Id']],capture_output=True,check=True)
        raise RuntimeError('Signature update timed out; uploads remain unavailable') from None
    require(result.returncode == 0, 'Signature update failed; uploads remain unavailable, raw provider output omitted')
    compose(config, 'up', '--detach', '--no-deps', '--pull', 'never', 'scanner', staging=staging)


def wait(config, container):
    until = time.monotonic() + 900
    while time.monotonic() < until:
        item = container(config, 'scanner')
        require(item['State'].get('Running') is True and not item['State'].get('OOMKilled') and item.get('RestartCount', 0) == 0,
            'Scanner exceeded this test budget; uploads were not approved')
        if item['State'].get('Health', {}).get('Status') == 'healthy':
            return
        time.sleep(5)
    raise RuntimeError('The private scanner did not become ready within this test budget')


PROBE = """import base64,json,django;django.setup()
from django.conf import settings
from django.core.exceptions import ValidationError
from accounting.attachment_validation import scan_content
if settings.ATTACHMENT_SCANNER_HOST!='scanner':raise RuntimeError('Unexpected private scanner')
version=scan_content(b'CR008 safe scanner readiness probe')
eicar=base64.b64decode('WDVPIVAlQEFQWzRcUFpYNTQoUF4pN0NDKTd9JEVJQ0FSLVNUQU5EQVJELUFOVElWSVJVUy1URVNULUZJTEUhJEgrSCo=')
if len(eicar)!=68:raise RuntimeError('Invalid official antivirus test fixture')
try:scan_content(eicar)
except ValidationError as error:
    if error.error_dict['file'][0].code!='infected':raise RuntimeError('No genuine antivirus denial')
else:raise RuntimeError('The scanner accepted the official antivirus fixture')
settings.ATTACHMENT_SCANNER_HOST=''
try:scan_content(b'CR008 unavailable scanner probe')
except ValidationError:pass
else:raise RuntimeError('Unavailable scanner accepted data')
print(json.dumps({'attachment_uploads_enabled':True,'real_clean_stream_accepted':True,
    'real_eicar_denied':True,'scanner_unavailable_denied_without_writes':True,'scanner_version':version}))
"""


def proof(config, compose):
    value = json.loads(compose(config, 'exec', '-T', 'web', 'python', '-c', PROBE))
    require(value.get('attachment_uploads_enabled') is True and all(value.get(key) is True for key in
        ('real_clean_stream_accepted', 'real_eicar_denied', 'scanner_unavailable_denied_without_writes')),
        'Actual private scanner clean/EICAR/fail-closed proof is incomplete')
    observed = memory()
    require(3_500_000 <= observed['MemTotal'] < 4_500_000 and observed['MemAvailable'] >= 256 * 1024
        and observed['SwapFree'] >= 256 * 1024, 'Insufficient remaining real test-VM headroom')
    return {**value, 'memory_observed_kib': observed, 'scanner_memory_cap_mib': MEMORY_MIB,
        'scanner_memory_plus_swap_cap_mib': MEMORY_SWAP_MIB, 'full_workload_acceptance': 'Pending D06'}


def install_timer():
    files = {
        SERVICE: '[Unit]\nDescription=Refresh private CR008 test scanner signatures\nAfter=docker.service accounting-preview.service\nConditionPathExists=!/etc/accounting/cr008-preview-in-progress\n\n[Service]\nType=oneshot\nExecStart=/usr/local/sbin/accounting-preview scanner-refresh\nTimeoutStartSec=35min\n',
        TIMER: '[Unit]\nDescription=Daily private CR008 scanner update\n\n[Timer]\nOnCalendar=*-*-* 04:30:00 Europe/Athens\nRandomizedDelaySec=15min\nPersistent=false\n\n[Install]\nWantedBy=timers.target\n',
    }
    for name, value in files.items():
        path = Path('/etc/systemd/system') / name
        require(not path.is_symlink() and (not path.exists() or path.read_text() == value),
            'An unrelated scanner unit was retained without overwrite')
        if not path.exists():
            with path.open('x') as stream: stream.write(value)
    drop=Path('/etc/systemd/system/accounting-preview.service.d/cr008-test-budget.conf')
    value='[Service]\nTimeoutStartSec=1200\n'
    require(not drop.is_symlink() and (not drop.exists() or drop.read_text()==value),
        'An unrelated startup timeout override was retained without overwrite')
    drop.parent.mkdir(parents=True,exist_ok=True)
    if not drop.exists():
        with drop.open('x') as stream:stream.write(value)
    common.run(['systemctl', 'daemon-reload'])


def start_timer():
    common.run(['systemctl', 'enable', '--now', TIMER])


def stop_timer():
    if (Path('/etc/systemd/system') / TIMER).is_file():
        common.run(['systemctl', 'disable', '--now', TIMER])
