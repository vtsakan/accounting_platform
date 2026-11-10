#!/usr/bin/env python3
"""Scan the candidate source and reachable Git text blobs without verifying tokens online."""

import argparse
import csv
import importlib.metadata
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def run_scanner(directory, path="."):
    command = [sys.executable, "-m", "detect_secrets", "scan", "--no-verify", "--all-files", path]
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("Secret scanner execution failed; no source lines printed")
    return json.loads(result.stdout)["results"]


def scan():
    if importlib.metadata.version("detect-secrets") != "1.5.0":
        raise RuntimeError("Install the pinned requirements-tools.txt environment")
    with (ROOT / "docs/security/secret_scan_allowlist.csv").open(newline="", encoding="utf-8") as stream:
        entries = list(csv.DictReader(stream))
    allowed = set()
    for item in entries:
        if (item["detector"] not in {"Hex High Entropy String", "Base64 High Entropy String", "Secret Keyword"}
                or not re.fullmatch(r"[a-f0-9]{40}", item["fingerprint"])
                or not item["reason"] or not item["evidence"]):
            raise RuntimeError("Invalid reviewed non-secret entry")
        allowed.add((item["detector"], item["fingerprint"]))

    commits = git("rev-list", "--all").decode().splitlines()
    historical = {}
    for commit in commits:
        for entry in git("ls-tree", "-rz", "--full-tree", commit).split(b"\0"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            mode, kind, sha = metadata.decode().split()
            if mode == "120000":
                raise RuntimeError("Review tracked symbolic links before scanning")
            if kind == "blob":
                historical.setdefault(sha, path.decode())

    files = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    candidate_paths = sorted(set(p.decode() for p in files.split(b"\0") if p))
    sources = {}
    skipped = 0
    candidate_count = 0
    with tempfile.TemporaryDirectory(prefix="accounting-secrets-") as temp:
        directory = Path(temp)
        probe = directory / "scanner_probe.py"
        probe.write_text("PASSWORD" + " = " + json.dumps(secrets.token_urlsafe(40)) + "\n", encoding="utf-8")
        if not run_scanner(directory, probe.name):
            raise RuntimeError("Secret scanner failed its synthetic-password self-check")
        probe.unlink()

        def materialise(relative, data, scope, original):
            nonlocal skipped
            try:
                data.decode("utf-8")
                if b"\0" in data:
                    raise UnicodeError()
            except UnicodeError:
                skipped += 1
                return False
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            sources[str(target)] = {"scope": scope, "path": original}
            return True

        for path in candidate_paths:
            source = ROOT / path
            if source.is_symlink():
                raise RuntimeError("Review symbolic links before scanning")
            if source.is_file():
                candidate_count += materialise("candidate/" + path, source.read_bytes(), "candidate", path)
        for sha, path in historical.items():
            materialise(f"history/{sha}/{path}", git("cat-file", "blob", sha), "history", path)
        findings = run_scanner(directory)
        unreviewed = []
        reviewed_count = 0
        for name, matches in findings.items():
            key = str((directory / name).resolve())
            origin = sources[key]
            for match in matches:
                fingerprint = (match["type"], match["hashed_secret"])
                if fingerprint in allowed:
                    reviewed_count += 1
                else:
                    unreviewed.append({**origin, "detector": match["type"],
                                       "line": match["line_number"], "fingerprint": match["hashed_secret"]})
    return {
        "scanner": "detect-secrets", "version": "1.5.0", "network_verification": False,
        "scanner_self_check": "Passed: detected an ephemeral synthetic password",
        "history_scope": "All locally reachable Git refs plus the current candidate source",
        "history_commits": len(commits), "unique_history_blobs": len(historical),
        "candidate_text_files": candidate_count, "binary_files_or_blobs_skipped": skipped,
        "reviewed_non_secret_matches": reviewed_count, "unreviewed_findings": len(unreviewed),
        "findings": unreviewed,
        "limitations": "Heuristic text scan; does not prove absence of every possible secret or inspect binary documents."
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = scan()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["unreviewed_findings"]))
