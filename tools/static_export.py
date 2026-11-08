"""Bounded static archive streaming and extraction with host-owned permissions."""

import json
import os
from pathlib import Path, PurePosixPath
import selectors
import subprocess
import tarfile
import tempfile
import time

from verify_s05 import redact

MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 20000
EXPORT_TIMEOUT = 120
EXPORT_CODE = """from pathlib import Path
import sys, tarfile
root = Path('/app/staticfiles')
if not (root / 'staticfiles.json').is_file():
    raise SystemExit('The image has no static manifest at /app/staticfiles')
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive:
    archive.add(str(root), arcname='.')
"""


def relative_path(name, *, root_allowed=False):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        raise RuntimeError("Invalid static archive path")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("Unsafe static archive path")
    if not path.parts:
        if root_allowed:
            return None
        raise RuntimeError("Static file cannot replace the export root")
    return path


def stream_archive(command, target):
    """Docker writes only to a pipe; host Python owns the archive file."""
    with tempfile.TemporaryFile() as diagnostics:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=diagnostics) as process:
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + EXPORT_TIMEOUT
            size = 0
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise RuntimeError("Static archive stream timed out")
                    block = os.read(process.stdout.fileno(), 65536)
                    if not block:
                        break
                    size += len(block)
                    if size > MAX_ARCHIVE_BYTES:
                        raise RuntimeError("Static archive exceeds the export size limit")
                    target.write(block)
                result = process.wait(timeout=max(0.1, deadline - time.monotonic()))
                diagnostics.seek(max(0, diagnostics.seek(0, os.SEEK_END) - 6000))
                message = redact(diagnostics.read().decode(errors="replace"))
                if result:
                    raise RuntimeError(f"Static export command failed (exit {result}):\n{message}")
            except BaseException:
                if process.poll() is None:
                    process.kill(); process.wait()
                raise
            finally:
                selector.close()
    target.seek(0)
    return message


def extract_static_archive(source, destination):
    """Prevalidate every member, then create regular files with safe modes.

    Image UID/GID and read-only directory modes are deliberately not restored.
    Links, traversal, duplicate paths, special files and oversized archives fail.
    The caller owns this staging directory and publishes it only after success.
    """
    source.seek(0, os.SEEK_END)
    if source.tell() > MAX_ARCHIVE_BYTES:
        raise RuntimeError("Static archive exceeds the export size limit")
    source.seek(0)
    entries, seen, file_paths, total = [], set(), set(), 0
    with tarfile.open(fileobj=source, mode="r:") as archive:
        root_seen = False
        for count, member in enumerate(archive, start=1):
            if count > MAX_ENTRIES:
                raise RuntimeError("Too many static archive entries")
            if not member.isdir() and not member.isfile():
                raise RuntimeError("Static archive links and special files are forbidden")
            relative = relative_path(member.name, root_allowed=member.isdir())
            if relative is None:
                if root_seen:
                    raise RuntimeError("Duplicate static archive root")
                root_seen = True
                continue
            if relative in seen:
                raise RuntimeError("Duplicate static archive path")
            seen.add(relative)
            if member.size < 0:
                raise RuntimeError("Invalid static file size")
            total += member.size
            if total > MAX_ARCHIVE_BYTES:
                raise RuntimeError("Static archive exceeds the export size limit")
            if member.isfile():
                file_paths.add(relative)
            entries.append((member, relative))
        if any(parent in file_paths for _, path in entries for parent in path.parents):
            raise RuntimeError("Static file is used as a directory")
        destination.mkdir(mode=0o755)
        for member, relative in entries:
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            if member.isdir():
                target.mkdir(exist_ok=True, mode=0o755)
            else:
                with archive.extractfile(member) as incoming, target.open("xb") as output:
                    copied = 0
                    while True:
                        block = incoming.read(65536)
                        if not block:
                            break
                        output.write(block); copied += len(block)
                if copied != member.size:
                    raise RuntimeError("Incomplete static archive file")
                target.chmod(0o644)
        # Ignore the invoking process's umask for public static directory modes.
        destination.chmod(0o755)
        for path in destination.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)
    manifest = destination / "staticfiles.json"
    if not manifest.is_file() or not (destination / "admin/css/base.css").is_file():
        raise RuntimeError("Static export is missing its manifest or admin stylesheet")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("paths"), dict):
        raise RuntimeError("Invalid static manifest")
    for name in data["paths"].values():
        relative = relative_path(name)
        if not destination.joinpath(*relative.parts).is_file():
            raise RuntimeError("Static manifest references a missing file")
    return {"file_count": len(file_paths), "manifest_entries": len(data["paths"])}
