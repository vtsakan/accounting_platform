#!/usr/bin/env python3
"""Compile the reviewed Greek catalog using the pinned maintenance environment."""

import argparse
from pathlib import Path
import tempfile

import polib

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sources = sorted((ROOT / "locale").rglob("*.po"))
    if not sources:
        raise SystemExit("Greek message catalog is missing.")
    for source in sources:
        catalog = polib.pofile(str(source), check_for_duplicates=True)
        if catalog.fuzzy_entries() or catalog.untranslated_entries():
            raise SystemExit("Complete and review every catalog entry before compiling.")
        target = source.with_suffix(".mo")
        if args.check:
            with tempfile.TemporaryDirectory(prefix="accounting-catalog-") as temp:
                compiled = Path(temp) / "django.mo"
                catalog.save_as_mofile(str(compiled))
                if not target.is_file() or compiled.read_bytes() != target.read_bytes():
                    raise SystemExit("Compiled Greek catalog is stale.")
        else:
            catalog.save_as_mofile(str(target))
    print("Greek message catalog verified." if args.check else "Greek message catalog compiled.")
