"""Download one exact generation and restore only to a local disposable PG17."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from cloud import require
from dev import require_local_docker
import operations_common as common
import operations_pg as pg
import preview as laptop
import preview_common as preview


@contextmanager
def plaintext_directory():
    base = Path('/dev/shm')
    require(base.is_dir(), 'Use a Linux laptop with /dev/shm for recovery')
    common.require_tmpfs(base)
    with tempfile.TemporaryDirectory(prefix='accounting-s10-recovery-', dir=base) as value:
        yield Path(value)


def download(config, receipt, output):
    common.validate_receipt(receipt, config, max_age=None)
    token = laptop.gcloud(config['preview'], 'auth', 'print-access-token').decode().strip()
    require(token and '\n' not in token, 'Unexpected recovery operator token')
    url = 'https://storage.googleapis.com/storage/v1/b/' + receipt['bucket'] + '/o/' + urllib.parse.quote(receipt['object'], safe='')
    url += '?' + urllib.parse.urlencode({'alt': 'media', 'generation': receipt['generation']})
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + token, 'Accept-Encoding': 'identity'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    total = 0
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=120) as response, output.open('xb') as destination:
            require(response.status == 200, 'Unexpected object download status')
            require(response.headers.get('x-goog-generation', receipt['generation']) == receipt['generation'], 'Object generation differs')
            while block := response.read(1024 * 1024):
                total += len(block)
                require(total <= receipt['size'], 'Object download exceeds receipt size')
                destination.write(block)
    except urllib.error.HTTPError as error:
        raise common.APIError(error.code) from None
    require(total == receipt['size'] and common.sha(output) == receipt['sha256']
            and common.crc32c_file(output) == receipt['crc32c'], 'Downloaded object integrity differs')


def decrypt(encrypted, identity, directory):
    target = directory / 'recovery.tar'
    # An output file avoids age's deliberate refusal to print binary plaintext
    # to a terminal. Captured errors never contain key contents in our output.
    with target.open('xb') as output:
        target.chmod(0o600)
        common.run(['age', '--decrypt', '--identity', identity, encrypted], output=output, timeout=300)
    require(target.stat().st_size <= common.MAX_ARCHIVE, 'Decrypted archive exceeds the preview budget')
    return common.unpack(target, directory)


@contextmanager
def recovery_database():
    require_local_docker()
    image = json.loads((common.ROOT / 'docker/image-pins.json').read_text())['postgresql']['reference']
    try:
        inspected = json.loads(common.run(['docker', 'image', 'inspect', image]))[0]
    except common.CommandFailure:
        common.run(['docker', 'pull', '--platform=linux/amd64', image], timeout=600)
        inspected = json.loads(common.run(['docker', 'image', 'inspect', image]))[0]
    pins = json.loads((common.ROOT / 'docker/image-pins.json').read_text())['postgresql']
    digests = {image.split('@', 1)[1], pins['platform_manifest']}
    accepted = {repository + '@' + digest for repository in ('postgres', 'docker.io/library/postgres') for digest in digests}
    require(inspected['Os'] == 'linux' and inspected['Architecture'] == 'amd64'
            and accepted.intersection(inspected.get('RepoDigests', [])), 'Recovery image platform/digest differs')
    identifier = uuid.uuid4().hex
    name = 'accounting-s10-recovery-' + identifier[:16]
    label = 'gr.accounting.s10.recovery=' + identifier
    created = False
    try:
        common.run(['docker', 'run', '--detach', '--name', name, '--label', label, '--pull=never', '--network=none',
                    '--read-only', '--memory=768m', '--cpus=1', '--pids-limit=128',
                    '--cap-drop=ALL', '--cap-add=CHOWN', '--cap-add=DAC_OVERRIDE', '--cap-add=FOWNER',
                    '--cap-add=SETGID', '--cap-add=SETUID', '--security-opt=no-new-privileges:true',
                    '--tmpfs', '/var/lib/postgresql/data:rw,nosuid,size=512m',
                    '--tmpfs', '/var/run/postgresql:rw,nosuid,size=16m,mode=2775,uid=999,gid=999',
                    '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777',
                    '--env', 'POSTGRES_HOST_AUTH_METHOD=trust',
                    '--env', 'POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C.UTF-8 --auth-local=trust --auth-host=reject',
                    image, 'postgres', '-c', 'shared_buffers=32MB', '-c', 'max_connections=10', '-c', 'listen_addresses=',
                    '-c', 'log_statement=none', '-c', 'log_min_error_statement=panic'])
        created = True
        for _ in range(60):
            ready = subprocess.run(['docker', 'exec', '--user', 'postgres', name, 'pg_isready', '-U', 'postgres', '-d', 'postgres'], capture_output=True)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError('Isolated recovery database did not become ready')
        metadata = json.loads(common.run(['docker', 'inspect', name]))[0]
        allowed_tmpfs = {'/var/lib/postgresql/data', '/var/run/postgresql', '/tmp'}
        require(metadata['HostConfig']['NetworkMode'] == 'none' and not metadata['HostConfig'].get('PortBindings')
                and not metadata['HostConfig'].get('Binds')
                and all(mount.get('Type') == 'tmpfs' and mount.get('Destination') in allowed_tmpfs for mount in metadata.get('Mounts', []))
                and metadata['Config']['Labels'].get('gr.accounting.s10.recovery') == identifier,
                'Recovery database must have no network, ports or persistent mounts')
        prefix = ['docker', 'exec', '-i', '--user', 'postgres', name]
        common.run(prefix + ['createdb', '--username=postgres', 's10_recovery'])
        yield prefix, {'container': name, 'image': image, 'network': 'none', 'published_ports': [], 'persistent_mounts': []}
    finally:
        if created:
            # Delete only the container whose exact random ownership label was checked.
            metadata = json.loads(common.run(['docker', 'inspect', name]))[0]
            require(metadata['Config']['Labels'].get('gr.accounting.s10.recovery') == identifier, 'Refusing cleanup of a container owned by another operation')
            common.run(['docker', 'rm', '--force', '--volumes', name])


def restore(config, receipt, identity):
    began = time.monotonic()
    common.check_age()
    original = Path(config['local_identity']).expanduser().resolve()
    recovered = common.identity_file(identity)
    require(recovered != original, 'Use the separately stored recovery copy to demonstrate key recovery')
    recipient = common.run(['age-keygen', '-y', recovered]).decode().strip()
    require(recipient == config['recipient'], 'Recovered key does not match the backup recipient')
    common.validate_receipt(receipt, config, max_age=None)
    with plaintext_directory() as directory:
        require(shutil.disk_usage(directory).free >= receipt['size'] + 2 * common.MAX_ARCHIVE,
                'Insufficient tmpfs capacity for encrypted recovery; increase laptop /dev/shm after reviewing memory')
        encrypted = directory / 'backup.tar.age'
        download(config, receipt, encrypted)
        manifest, recovery = decrypt(encrypted, recovered, directory)
        require(manifest['project_id'] == receipt['project_id'] and manifest['recipient_id'] == config['recipient_id']
                and manifest['snapshot_started_at'] == receipt['snapshot_started_at']
                and manifest['image'] == config['preview']['published']
                and recovery['preview'] == config['preview'], 'Recovery manifest differs from selected deployment/receipt')
        require(common.sha(directory / 'manifest.json') == receipt['manifest_sha256'], 'Recovery manifest hash differs')
        with recovery_database() as (prefix, isolation):
            pg.restore_dump(prefix + ['pg_restore', '--username=postgres', '--dbname=s10_recovery'], directory / 'database.dump')
            psql = prefix + ['psql', '-X', '-qAt', '--set=ON_ERROR_STOP=1', '--username=postgres', '--dbname=s10_recovery']
            verified = pg.verify_tables(psql, manifest['tables'])
            version = int(common.run(psql, payload=b'SHOW server_version_num;\n').strip())
            require(version // 10000 == 17, 'Recovered database is not PostgreSQL 17')
        elapsed = round(time.monotonic() - began, 3)
        require(elapsed <= 8 * 3600, 'Synthetic recovery exceeded the proposed eight-hour target')
    return {'status': 'Restored', 'mode': 'off-vm-gcs-download-local-docker', 'verified_at': common.now(),
            'receipt': receipt, 'restore_seconds': elapsed, 'rpo_age_seconds': round(time.time() - common.timestamp(receipt['snapshot_started_at']), 3),
            **verified, 'isolation': isolation, 'recovery_container_removed': True, 'plaintext_removed': True,
            'separate_recovery_key_used': True, 'preview_database_modified': False,
            'scope': 'Synthetic database only; document/full-environment recovery and accepted workload targets remain Pending'}
