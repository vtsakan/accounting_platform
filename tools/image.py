#!/usr/bin/env python3
"""Build one production image per clean commit, or export its static artifact."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

from dev import ROOT, require_local_docker

EXACT = {"Dockerfile", ".dockerignore", "manage.py", "requirements.txt", "gunicorn.conf.py",
         "accounting/regression_cases.json", "tools/init_local_env.py",
         "docker/production-entrypoint.sh", "docker/healthcheck.py"}
PRIVATE_PARTS = {"private", "secrets", "media", "uploads", "sessions", ".sessions", "backups", "logs", "__pycache__"}
STATIC_SUFFIXES = {".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf", ".map", ".txt"}


def git_environment():
    return {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}


def allowed(path):
    path = str(path)
    parts = PurePosixPath(path).parts
    if not parts or path.startswith("/") or ".." in parts or any(part.startswith(".") or part in PRIVATE_PARTS for part in parts):
        return path == ".dockerignore"
    if any(word in part.lower() for part in parts for word in ("credential", "service-account")):
        return False
    if path in EXACT:
        return True
    suffix = PurePosixPath(path).suffix.lower()
    return ((parts[0] in {"core", "accounting"} and suffix == ".py")
            or (path.startswith(("templates/", "accounting/templates/")) and suffix == ".html")
            or (path.startswith("accounting/static/") and suffix in STATIC_SUFFIXES)
            or (path.startswith("locale/") and suffix in {".po", ".mo"}))


def archive(files):
    """Deterministic regular-file archive: callers supply only selected bytes."""
    assert EXACT <= set(files), "Missing required production source inputs"
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in sorted(files.items()):
            assert allowed(name), name
            member = tarfile.TarInfo(name)
            member.size, member.mode, member.mtime = len(data), 0o644, 0
            tar.addfile(member, io.BytesIO(data))
    payload = result.getvalue()
    return payload, {"file_count": len(files), "paths": sorted(files),
                     "digest": "sha256:" + hashlib.sha256(payload).hexdigest()}


def committed_context():
    environment = git_environment()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, env=environment, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, env=environment).strip():
        raise RuntimeError("Commit tracked changes before building the production image; the build uses committed files only.")
    entries = subprocess.check_output(["git", "ls-tree", "-rz", "--full-tree", revision], cwd=ROOT, env=environment)
    files = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, name = entry.split(b"\t", 1); name = name.decode()
        if allowed(name):
            mode, kind, sha = metadata.decode().split()
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise RuntimeError("Production inputs must be regular committed files: " + name)
            files[name] = subprocess.check_output(["git", "cat-file", "blob", sha], cwd=ROOT, env=environment)
    payload, manifest = archive(files)
    return revision, payload, manifest


def candidate_context():
    """Prepared-mode audit only; not a release image or a committed identity."""
    names = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT, env=git_environment())
    files = {}
    for name in sorted(set(name.decode() for name in names.split(b"\0") if name)):
        if allowed(name):
            path = ROOT / name
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
                raise RuntimeError("Symbolic/private source input rejected: " + name)
            files[name] = path.read_bytes()
    return archive(files)


def inspect(reference):
    result = subprocess.run(["docker", "image", "inspect", reference], capture_output=True, text=True)
    return json.loads(result.stdout)[0] if result.returncode == 0 else None


def build():
    require_local_docker()
    revision, payload, manifest = committed_context()
    reference = "accounting-platform:" + revision
    existing = inspect(reference)
    reused = existing is not None
    if not existing:
        command = ["docker", "build", "--pull", "--platform", "linux/amd64", "--file", "Dockerfile",
                   "--build-arg", "APP_REVISION=" + revision, "--label", "gr.accounting.source-context=" + manifest["digest"],
                   "--tag", reference, "-"]
        result = subprocess.run(command, input=payload, capture_output=True)
        if result.returncode:
            raise RuntimeError("Production image build failed.\n" + result.stderr.decode(errors="replace")[-10000:])
        existing = inspect(reference)
    labels = existing["Config"].get("Labels") or {}
    if labels.get("org.opencontainers.image.revision") != revision or labels.get("gr.accounting.source-context") != manifest["digest"]:
        raise RuntimeError("The commit image tag exists with a different source identity; it was not overwritten.")
    assert existing["Config"]["User"] == "10001:10001" and existing["Architecture"] == "amd64"
    # Explicit identity type prevents this public commit from being mistaken
    # for an opaque hexadecimal credential in subsequently committed evidence.
    return {"revision": "git:" + revision, "reference": reference, "image_id": existing["Id"],
            "reused_existing_image": reused, "context": manifest}


def export_static(reference, output):
    require_local_docker()
    metadata = inspect(reference)
    if metadata is None:
        raise RuntimeError("Image is not present locally")
    if output.exists():
        raise RuntimeError("Choose a new static output directory; existing files are not overwritten")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    container = subprocess.check_output(["docker", "create", "--network", "none", "--entrypoint", "python",
                                         metadata["Id"], "-c", "pass"], text=True).strip()
    try:
        subprocess.run(["docker", "cp", container + ":/app/staticfiles/.", str(output)], check=True, capture_output=True)
    finally:
        subprocess.run(["docker", "rm", container], check=True, capture_output=True)
    assert (output / "staticfiles.json").is_file() and (output / "admin/css/base.css").is_file()
    # The operator owns the host export; Caddy receives a read-only mount at
    # S09. Writable host directory modes also allow safe temporary cleanup.
    output.chmod(0o755)
    for path in output.rglob("*"):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return {"image_id": metadata["Id"], "output": str(output), "file_count": sum(path.is_file() for path in output.rglob("*"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("build")
    export = sub.add_parser("static")
    export.add_argument("--image", required=True)
    export.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build() if args.action == "build" else export_static(args.image, args.output.resolve())
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
