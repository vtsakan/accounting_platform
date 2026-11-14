#!/usr/bin/env python3
"""Install the reviewed official age binary after checksum verification."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import tarfile
import tempfile
import urllib.request

from cloud import require

ROOT = Path(__file__).resolve().parents[1]


def install(directory, archive=None):
    pin = json.loads((ROOT / 'infrastructure/operations/age-pin.json').read_text())
    require(platform.system() == 'Linux' and platform.machine() in {'x86_64', 'amd64'}, 'This reviewed tool asset is for Linux amd64')
    if archive:
        data = archive.read_bytes()
    else:
        with urllib.request.urlopen(pin['url'], timeout=120) as response:
            data = response.read(32 * 1024 * 1024 + 1)
    require(len(data) <= 32 * 1024 * 1024 and hashlib.sha256(data).hexdigest() == pin['sha256'], 'age release checksum/size differs')
    directory = directory.expanduser().resolve(); directory.mkdir(parents=True, exist_ok=True)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as bundle:
        for name in ('age', 'age-keygen'):
            matches = [m for m in bundle.getmembers() if m.name == 'age/' + name]
            require(len(matches) == 1 and matches[0].isfile() and 0 < matches[0].size < 20 * 1024 * 1024, 'Unexpected age release member')
            files[name] = bundle.extractfile(matches[0]).read()
    for name, content in files.items():
        fd, temporary = tempfile.mkstemp(prefix='.age-install-', dir=directory)
        try:
            with os.fdopen(fd, 'wb') as stream: stream.write(content); stream.flush(); os.fsync(stream.fileno())
            os.chmod(temporary, 0o755)
            os.replace(temporary, directory / name)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {'status': 'Installed', 'version': pin['version'], 'directory': str(directory), 'verified_sha256': pin['sha256']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path.home() / '.local/bin')
    parser.add_argument('--archive', type=Path, help='Optional already downloaded official release; same checksum is required')
    args = parser.parse_args()
    print(json.dumps(install(args.directory, args.archive), indent=2))
