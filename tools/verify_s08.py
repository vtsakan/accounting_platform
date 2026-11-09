#!/usr/bin/env python3
"""Check S08 source/evidence offline. This command never provisions cloud resources."""

import argparse
import csv
from datetime import datetime
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from zoneinfo import ZoneInfo

import cloud
import image

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs/implementation"


def verify():
    s07 = json.loads((RECORDS / "evidence/S07-verification.json").read_text())
    cloud.require(s07["status"] == "Verified" and s07["production_image_built_verified"], "S07 Docker gate is not recorded Verified")
    context = image.committed_context()[2]
    cloud.require(context["digest"] == s07["image"]["context"]["digest"], "S08 changed the tested application image context")

    output = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tools"), pattern="test_s08.py")
    result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    if not result.wasSuccessful():
        sys.stderr.write(output.getvalue())
        raise ValueError("S08 safeguard tests failed")
    shells = sorted((ROOT / "infrastructure").glob("*.sh"))
    for path in shells:
        subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True)
    sources = [ROOT / "tools" / name for name in ("cloud.py", "probe_s08_vm.py", "test_s08.py", "verify_s08.py")]
    for path in sources:
        compile(path.read_bytes(), str(path), "exec")

    evidence = json.loads((RECORDS / "evidence/S08-verification.json").read_text())
    cloud.require(evidence["status"] == "Verified" and evidence["provenance"]["execution_owner"] == "user", "Operator execution evidence is missing")
    cloud.require(evidence["storage_probe"]["authenticated_denial_status"] == 403, "Authenticated IAM denials were weakened")
    cloud.require(evidence["storage_probe"]["anonymous_denial_statuses_allowed"] == [401, 403], "Anonymous status contract differs")
    cloud.require(evidence["storage_probe"]["backup_probe_cleanup_verified"], "Operator test-object cleanup is not recorded")
    with (RECORDS / "traceability.csv").open(newline="") as stream:
        requirements = list(csv.DictReader(stream))
    cloud.require(len(requirements) == 85 and all(row["acceptance_status"] == "Pending" for row in requirements), "Full requirement acceptance must remain Pending")
    inventory = json.loads((RECORDS / "cloud_inventory.json").read_text())
    cloud.require(inventory["data_disk"]["auto_delete"] is False, "Retained data-disk inventory differs")
    cloud.require(inventory["network"]["public_ingress_tcp"] == [80, 443], "Public ingress inventory differs")

    return {"verified_at": datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            "status": "Passed", "safeguard_tests": result.testsRun,
            "shell_syntax_checks": len(shells), "python_source_checks": len(sources),
            "application_context_unchanged": True, "application_context_digest": context["digest"],
            "acceptance_statuses_pending": len(requirements),
            "cloud_calls_run_by_this_verifier": False, "host_scripts_run_by_this_verifier": False,
            "application_or_database_tests_run": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="Record local safeguard results; preserve the operator's cloud evidence")
    args = parser.parse_args()
    result = verify()
    if args.record:
        path = RECORDS / "evidence/S08-verification.json"
        evidence = json.loads(path.read_text())
        result["code_commit"] = "git:" + subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        evidence["repository_checks"] = result
        path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({"step": "S08", "operator_cloud_status": "Verified", "repository_checks": result}, indent=2))


if __name__ == "__main__":
    main()
