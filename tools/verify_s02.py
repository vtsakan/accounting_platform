#!/usr/bin/env python3
"""Verify the S02 planning snapshot without importing or running the application."""

import argparse
import ast
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "docs/implementation"
S01 = "86d01abaf76fbbed669ae39a12b41ff4d47b831a"


def read_json(name):
    return json.loads((RECORDS / name).read_text(encoding="utf-8"))


def read_csv(name):
    with (RECORDS / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def git_bytes(path):
    return subprocess.check_output(["git", "show", f"{S01}:{path}"], cwd=ROOT)


def verify():
    checks = []

    def check(name, condition, detail):
        if not condition:
            raise AssertionError(f"{name}: {detail}")
        checks.append({"check": name, "result": "PASS", "detail": detail})

    reqs = read_json("requirements.json")
    ids = {r["requirement_id"] for r in reqs}
    users = [r for r in reqs if r["type"] == "User"]
    quality = [r for r in reqs if r["type"] == "Quality"]
    check("effective requirements", len(users) == 71 and len(quality) == 14 and len(ids) == 85,
          "71 UR and 14 QR, all identifiers unique")
    check("CSV/JSON parity", read_csv("traceability.csv") == reqs,
          "both requirement registers contain identical records")
    check("application acceptance pending", all(r["acceptance_status"] == "Pending" and not r["evidence"] for r in reqs),
          "planning checks do not pass application acceptance")
    check("acceptance identifiers", all(r["acceptance_test_id"] == ("AT-" if r["type"] == "User" else "QT-") + r["requirement_id"][3:] for r in reqs),
          "AT/QT identifiers preserve requirement identity")
    old_reqs = json.loads(git_bytes("docs/implementation/requirements.json"))
    current = {r["requirement_id"]: r for r in reqs}
    check("original requirement definitions preserved",
          all(all(current[r["requirement_id"]][k] == v for k, v in r.items() if k != "notes") for r in old_reqs),
          "the original 84 definitions, priorities, statuses and allocations are unchanged")
    locale = current["UR-LOC-01"]
    check("Greek requirement confirmed", locale["definition_status"] == "Confirmed" and locale["source_codes"] == "U" and locale["priority"] == "Must",
          "explicit user instruction recorded separately from pending implementation")
    effective = read_json("effective_baseline.json")
    check("effective baseline totals", (effective["effective_user_requirements"], effective["effective_quality_requirements"], effective["effective_total"]) == (71, 14, 85),
          "controlled addendum agrees with the registers")
    for change in effective["changes"]:
        data = (ROOT / change["path"]).read_bytes()
        check(change["id"] + " provenance", hashlib.sha256(data).hexdigest() == change["sha256"] and change["added_requirements"] == ["UR-LOC-01"],
              "the recorded approved addendum checksum matches")

    steps = read_csv("steps.csv")
    step_ids = [s["step_id"] for s in steps]
    prompts = read_json("prompts.json")
    check("64-step sequence", step_ids == [f"S{i:02}" for i in range(1, 65)] and [p["step_id"] for p in prompts] == step_ids,
          "original identifiers retained, no renumbering")
    check("step status", [s["status"] for s in steps[:2]] == ["Verified", "Verified"] and all(s["status"] == "Not started" for s in steps[2:]),
          "only S01 and S02 are complete")
    for s, p in zip(steps, prompts):
        check(s["step_id"] + " allocation",
              s["dependencies"].split() == p["dependencies"] and s["requirements"].split() == p["requirements"]
              and set(p["requirements"]) <= ids and all(d in step_ids and int(d[1:]) < int(s["step_id"][1:]) for d in p["dependencies"]),
              "step, prompt, requirement and dependency references agree")
    greek_steps = set(locale["implementation_steps"].split())
    check("Greek release coverage", {"S02", "S04", "S13", "S15", "S30", "S31", "S41", "S43", "S47", "S48", "S63"} <= greek_steps,
          "locale foundation, core UI, emails, portal, reports and release gates covered")
    check("Greek prompt propagation", all(("UR-LOC-01" in p["requirements"]) == (p["step_id"] in greek_steps) for p in prompts)
          and all("CR-001 effective-baseline addendum" in p["prompt"] for p in prompts if p["step_id"] in greek_steps),
          "effective prompts include the user language requirement")
    check("requirement steps valid", all(set(r["implementation_steps"].split()) <= set(step_ids) for r in reqs),
          "every requirement maps to valid implementation steps")

    decisions = read_json("decision_register.json")
    check("decision identifiers", [d["id"] for d in decisions["decisions"]] == [f"D{i:02}" for i in range(1, 10)],
          "D01 through D09 retained")
    overview = (RECORDS / "decisions.md").read_text(encoding="utf-8")
    for d in decisions["decisions"]:
        check(d["id"] + " actionable record", bool(d["owner"] and d["status"] and d["gate"] and d["recommendation"] and d["unresolved"] and d["evidence"])
              and len(d["options"]) >= 2 and bool(d["dependent_steps"]) and set(d["dependent_steps"]) <= set(step_ids)
              and d["approval_evidence"] is None and d["recommendation"] in overview and d["owner"] in overview,
              "owner, options, open inputs, affected steps and unapproved recommendation are explicit")

    connectors = read_json("connector_feasibility.json")
    sources = {s["id"]: s for s in connectors["sources"]}
    allowed_hosts = {"www.aade.gr", "aade.gr", "www.gsis.gr", "www.e-efka.gov.gr", "europa.eu", "ec.europa.eu"}
    check("official evidence sources", all(urlparse(s["url"]).scheme == "https" and urlparse(s["url"]).hostname in allowed_hosts and s["reviewed"] for s in sources.values()),
          "dated first-party sources with explicit review limits")
    check("six connector records", {c["id"] for c in connectors["connectors"]} == {"AADE_REGISTRY", "MYDATA", "VIES", "TAXISNET_PROFILE", "AADE_DEBT", "EFKA_NOTICE"},
          "all required feasibility investigations recorded")
    for c in connectors["connectors"]:
        check(c["id"] + " feasibility", bool(c["owner"] and c["status"] and c["eligibility_and_authority"] and c["required_accounts"] and c["required_sample_evidence"] and c["unresolved"])
              and set(c["source_ids"]) <= set(sources) and set(c["requirement_ids"]) <= ids and set(c["dependent_steps"]) <= set(step_ids)
              and c["live_test_status"] == "Not run" and c["authorised_access_demonstrated"] is False and c["production_enabled"] is False and c["contract_pinned"] is False,
              "access requirements and next evidence are explicit; no live success claimed")
        if c["id"] in {"TAXISNET_PROFILE", "AADE_DEBT", "EFKA_NOTICE"}:
            check(c["id"] + " conditional gate", "blocked" in c["status"] and "fallback" in c,
                  "unsupported route is blocked and manual upload is distinct")

    params = read_json("deployment_parameters.example.json")
    check("cloud timing", params["provisioning_step"] == "S08" and params["prerequisite_steps"] == ["S02", "S07"] and params["resources_created"] is False,
          "VM checkpoint retained; no environment provisioned")
    check("unknown target visible", all(params[k] is None for k in ["project_id", "billing_enabled", "region", "zone", "vm_name", "operator_identity", "monthly_budget_eur"])
          and params["network"]["duckdns_hostname"] is None,
          "target values remain unknown rather than assumed")
    check("secret references empty", all(v is None for v in params["secret_version_refs"].values()),
          "public template contains no secret values")
    check("private services and persistence", not params["proposed"]["database_public"] and not params["proposed"]["redis_public"] and not params["proposed"]["data_disk_auto_delete"],
          "proposed controls protect private services and persistent data")

    for row in read_csv("source_manifest.csv"):
        if row["working_path"]:
            path = ROOT / row["working_path"]
            check("source " + row["working_path"], hashlib.sha256(path.read_bytes()).hexdigest() == row["working_sha256"],
                  "S02 leaves all 38 working legacy source files unchanged")
    immutable = ["tools/verify_s01.py", "docs/implementation/baseline_sources.json", "docs/implementation/source_manifest.csv"]
    immutable += [str(p.relative_to(ROOT)) for p in (ROOT / "docs/baselines").iterdir() if p.is_file()]
    check("historical baseline bytes preserved", all((ROOT / path).read_bytes() == git_bytes(path) for path in immutable),
          "all original baseline files, provenance and S01 verifier match the S01 commit")
    ast.parse((ROOT / "tools/verify_s02.py").read_text(encoding="utf-8"))
    check("verification script syntax", True, "parsed without importing the application")
    return {
        "step": "S02", "verified_at": "2026-11-07", "status": "Verified",
        "checks_passed": len(checks), "requirements": {"user": 71, "quality": 14, "acceptance": "Pending"},
        "decisions": 9, "connectors_reviewed": 6, "source_reference_commit": S01,
        "application_tests_run": False, "database_or_migration_execution": False,
        "greek_frontend_implemented": False, "live_connector_tests_run": False,
        "google_cloud_resources_created": False, "checks": checks
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "checks"}, indent=2))
