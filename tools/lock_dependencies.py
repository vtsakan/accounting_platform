#!/usr/bin/env python3
"""Compile or check the runtime and maintenance requirements locks."""

import argparse
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOCKS = ("requirements", "requirements-tools")


def compile_locks(directory, upgrade=False):
    for stem in LOCKS:
        command = [
            sys.executable, "-m", "uv", "pip", "compile", f"{stem}.in",
            "--python-version", (ROOT / ".python-version").read_text().strip(),
            "--python-platform", "x86_64-unknown-linux-gnu",
            "--generate-hashes", "--only-binary", ":all:",
            "--index-url", "https://pypi.org/simple", "--no-python-downloads",
            "--output-file", f"{stem}.txt",
            "--custom-compile-command", "python tools/lock_dependencies.py", "--quiet",
        ]
        if upgrade:
            command.append("--upgrade")
        subprocess.run(command, cwd=directory, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Recompile copies and fail on drift")
    group.add_argument("--upgrade", action="store_true", help="Review new versions allowed by the inputs")
    args = parser.parse_args()
    expected = "0.13.7"
    if importlib.metadata.version("uv") != expected:
        parser.error(f"Use uv {expected} from requirements-tools.txt")
    if args.check:
        with tempfile.TemporaryDirectory(prefix="accounting-lock-") as temp:
            directory = Path(temp)
            for stem in LOCKS:
                for suffix in (".in", ".txt"):
                    shutil.copyfile(ROOT / (stem + suffix), directory / (stem + suffix))
            compile_locks(directory)
            drift = [f"{stem}.txt" for stem in LOCKS
                     if (ROOT / f"{stem}.txt").read_bytes() != (directory / f"{stem}.txt").read_bytes()]
            if drift:
                raise SystemExit("Lock drift: " + ", ".join(drift))
        print("Both dependency locks reproduce byte for byte.")
    else:
        compile_locks(ROOT, upgrade=args.upgrade)
        print("Compiled runtime and maintenance locks; review and commit the changes.")


if __name__ == "__main__":
    main()
