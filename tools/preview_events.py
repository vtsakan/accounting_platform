"""Bounded S09 diagnostics: no command arguments, provider bodies or credentials."""

import json
from pathlib import Path
import re
import sys
import traceback
import urllib.error

PREFIX = "S09-DIAG "
STAGES = {
    "configuration", "ship-source", "ship-ssh", "ship-transfer", "ship-install",
    "vm-preflight", "source-extract", "storage-layout", "runtime-files",
    "runtime-signing-read", "runtime-database-read", "metadata-firewall",
    "registry-login", "application-pull", "image-identity", "proxy-pull",
    "postgres-pull", "static-export", "compose-config", "database-start",
    "database-role", "database-migrate", "services-start", "synthetic-markers",
    "boot-install", "inspection", "resume",
}
ERRORS = {"OSError", "FileNotFoundError", "PermissionError", "ValueError", "RuntimeError",
          "KeyError", "CommandFailure", "MaterialAccessError", "HTTPError", "URLError",
          "JSONDecodeError", "UnicodeDecodeError", "CalledProcessError", "TypeError",
          "ImportError", "ModuleNotFoundError", "AssertionError", "Error"}
PROGRAMS = {"docker", "gcloud", "findmnt", "systemctl", "iptables", "git", "python3"}
REASONS = {
    "Unexpected VM project", "Unexpected VM name", "Unexpected VM identity",
    "Expected data filesystem is not mounted", "Unexpected Docker data root",
    "Runtime credentials require a tmpfs /run", "Secret payload checksum mismatch",
    "Unexpected generated secret format", "Release bundle hash differs",
    "Unsafe archive path", "Private/runtime path in release bundle",
    "Links/devices are not accepted in release bundles",
    "Existing release differs; it was not overwritten",
    "Refusing incompatible or unknown PostgreSQL data", "Static export manifest missing",
    "Image platform/user differs", "Pulled image ID differs from published image",
    "Pulled image is not bound to pinned registry digest",
    "Pulled image descriptor differs from pinned registry digest",
    "Running container image differs from release", "Running application image ID differs",
    "Unexpected image source", "Image revision/context differs",
    "Application credential failed", "Existing application role has elevated privileges",
    "Database is owned by another role; stopping",
    "Public DNS is not ready; add the hostname in DuckDNS first",
    "Public A record differs from the reserved VM address",
    "Remove the stale DuckDNS IPv6 record before certificate issuance",
}
CURRENT = "configuration"


def checkpoint(stage):
    global CURRENT
    if stage not in STAGES:
        raise ValueError("Unknown diagnostic stage")
    CURRENT = stage
    print(PREFIX + json.dumps({"event": "stage", "stage": stage}), file=sys.stderr, flush=True)


def failure(error):
    name = type(error).__name__
    record = {"event": "failure", "stage": CURRENT, "error": name if name in ERRORS else "Error"}
    # Only reviewed literal validation text is accepted, never an arbitrary error.
    if type(error) in {ValueError, RuntimeError} and str(error) in REASONS:
        record["reason"] = str(error)
    for key, low, high in (("exit_code", -255, 255), ("http_status", 100, 599), ("errno", 1, 4096)):
        value = getattr(error, key, None)
        if type(value) is int and low <= value <= high:
            record[key] = value
    if isinstance(error, urllib.error.HTTPError) and type(error.code) is int and 100 <= error.code <= 599:
        record["http_status"] = error.code
    if getattr(error, "program", None) in PROGRAMS:
        record["program"] = error.program
    for frame in reversed(traceback.extract_tb(error.__traceback__)):
        module = Path(frame.filename).stem
        if module in {"preview_host", "preview_common", "image", "dev", "static_export"} and frame.name.isidentifier():
            record["at"] = f"{module}:{frame.lineno}"
            break
    print(PREFIX + json.dumps(record), file=sys.stderr, flush=True)
    return record


def child_failure(stderr):
    """Allow only our small typed failure record through captured SSH stderr."""
    allowed = {"event", "stage", "error", "reason", "exit_code", "http_status", "errno", "program", "at"}
    for line in reversed(stderr[-65536:].decode(errors="replace").splitlines()):
        if not line.startswith(PREFIX) or len(line) > 2048:
            continue
        try:
            data = json.loads(line[len(PREFIX):])
        except ValueError:
            continue
        if not isinstance(data, dict) or set(data) - allowed:
            continue
        if any(key in data and not isinstance(data[key], str) for key in ("event", "stage", "error", "reason", "program", "at")):
            continue
        if data.get("event") != "failure" or data.get("stage") not in STAGES or data.get("error") not in ERRORS:
            continue
        if "reason" in data and data["reason"] not in REASONS:
            continue
        if "program" in data and data["program"] not in PROGRAMS:
            continue
        if "at" in data and not re.fullmatch(r"(?:preview_host|preview_common|image|dev|static_export):[0-9]{1,6}", data["at"]):
            continue
        if any(key in data and (type(data[key]) is not int or not low <= data[key] <= high)
               for key, low, high in (("exit_code", -255, 255), ("http_status", 100, 599), ("errno", 1, 4096))):
            continue
        return data
    return None
