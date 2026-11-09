#!/usr/bin/env python3
"""S09 offline checks or public proof, with an explicit second check after reboot."""

import argparse
import csv
from datetime import datetime
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from zoneinfo import ZoneInfo

from cloud import require
import preview_common as common
import preview_http

RECORDS = common.ROOT / "docs/implementation"
BASE = "git:e64861e0673e7c051d8aeb2c8ae79ef5fccf8aac"


def offline(docker="docker", caddy=None):
    for relative in ("accounting/models.py", "accounting/views.py", "accounting/forms.py", "accounting/urls.py",
                     "requirements.txt", "requirements-tools.txt",
                     *(str(p.relative_to(common.ROOT)) for p in (common.ROOT / "accounting/migrations").glob("*.py"))):
        original = common.run(["git", "-C", str(common.ROOT), "show", BASE.removeprefix("git:") + ":" + relative])
        require((common.ROOT / relative).read_bytes() == original, "S09 business/migration/dependency scope differs")
    with (RECORDS / "traceability.csv").open(newline="") as stream:
        requirements = list(csv.DictReader(stream))
    require(len(requirements) == 85 and all(r["acceptance_status"] == "Pending" for r in requirements), "Full acceptance must remain Pending")
    suite = unittest.defaultTestLoader.discover(str(common.ROOT / "tools"), pattern="test_s09.py")
    output = io.StringIO()
    tests = unittest.TextTestRunner(stream=output).run(suite)
    if not tests.wasSuccessful():
        raise RuntimeError(output.getvalue())
    require(tests.testsRun > 0, "S09 safeguard tests not discovered")
    environment = {**common.compose_environment(), "APP_IMAGE": "example.invalid/accounting/web@sha256:" + "1" * 64,
                   "SITE_DOMAIN": "totalaccounting.duckdns.org", "ACME_EMAIL": "operator@example.invalid",
                   "DB_NAME": "accounting_platform", "DB_USER": "accounting_app", "STATIC_DIRECTORY": "/tmp/s09-static"}
    config = common.run([docker, "compose", "--file", str(common.ROOT / "compose.production.yml"), "config", "--format=json"], environment=environment, json_output=True)
    check_compose(config)
    caddy_validated = False
    if caddy:
        common.run([caddy, "validate", "--config", str(common.ROOT / "infrastructure/Caddyfile"), "--adapter", "caddyfile"], environment=environment)
        caddy_validated = True
    return {"mode": "offline", "status": "Prepared", "tests": tests.testsRun,
            "business_migrations_dependency_locks_unchanged": True, "full_acceptances_pending": 85,
            "compose_config_validated_without_engine": True, "caddy_native_validated": caddy_validated,
            "docker_containers_executed": False, "live_cloud_execution": False}


def check_compose(config):
    services = config["services"]
    require(set(services) == {"db", "web", "caddy"}, "Unexpected preview services")
    for name in ("db", "web"):
        require(not services[name].get("ports"), "Application/database publishes a port")
    require({(row["target"], str(row["published"]), row["protocol"]) for row in services["caddy"]["ports"]} == {(80, "80", "tcp"), (443, "443", "tcp")}, "Only proxy TCP 80/443 may be published")
    require(config["networks"]["database"]["internal"] and config["networks"]["application"]["internal"], "Private networks are not isolated")
    web = services["web"]
    require(web["read_only"] and web["user"] == "10001:10001", "Application root/user differs")
    require(web["environment"]["DJANGO_TRUST_PROXY_HEADERS"] == "true", "Proxy trust missing")
    require(web["environment"]["DJANGO_CSRF_TRUSTED_ORIGINS"] == "https://" + web["environment"]["DJANGO_ALLOWED_HOSTS"], "Host/origin mismatch")
    require("DJANGO_SECRET_KEY" not in web["environment"] and "DB_PASSWORD" not in web["environment"], "Credential value environment configured")
    require(services["db"]["environment"]["POSTGRES_USER"] == "postgres" and web["environment"]["DB_USER"] != "postgres", "Application is configured as database superuser")
    proxy_mounts = {mount["target"]: mount for mount in services["caddy"]["volumes"]}
    require(proxy_mounts["/srv/static"].get("read_only") and proxy_mounts["/data"]["source"] == "/srv/accounting/caddy/data"
            and proxy_mounts["/config"]["source"] == "/srv/accounting/caddy/config", "Certificate state/static mounts differ")
    for name, service in services.items():
        for mount in service.get("volumes", []):
            require(mount["type"] == "bind" and mount.get("bind", {}).get("create_host_path") is False, "A missing bind source could create a boot-disk directory")
            if str(mount["source"]).startswith("/run/accounting/"):
                require(mount.get("read_only"), "Writable credential mount")


def live(path, after_reboot):
    from preview import ssh
    config = common.validate(json.loads(path.read_text()), published=True)
    records = common.dns(config)
    runtime = ssh(config, "inspect")
    cert = preview_http.certificate(config["hostname"])
    require(preview_http.ssl.cert_time_to_seconds(cert["not_after"]) > datetime.now().timestamp() + 86400, "Certificate expires within one day")
    ports = preview_http.private_ports(config["external_ipv4"])
    try:
        credentials = ssh(config, "probe-create")
        web = preview_http.check_web("https://" + config["hostname"], "http://" + config["hostname"], credentials,
                                     runtime["static_path"], runtime["static_digest"])
    finally:
        ssh(config, "probe-delete")
    baseline_path = common.ROOT / "private/s09-before-reboot.json"
    current = {"commit": "git:" + config["published"]["commit"], "boot_id": runtime["boot_id"],
               "certificate": cert["fingerprint"], "persistence": runtime["persistence"], "static": runtime["static_digest"]}
    reboot = False
    if after_reboot:
        baseline = json.loads(baseline_path.read_text())
        require(baseline["boot_id"] != current["boot_id"], "VM boot ID has not changed")
        require(all(baseline[key] == current[key] for key in ("commit", "certificate", "persistence", "static")), "Image, certificate, static assets or synthetic records did not persist")
        reboot = True
    elif not baseline_path.exists():
        common.private_json(baseline_path, current, exclusive=True)
    else:
        baseline = json.loads(baseline_path.read_text())
        require(baseline == current, "Existing baseline differs; use --after-reboot for a genuine reboot, or inspect the previous release")
    return {"step": "S09", "verified_at": datetime.now(ZoneInfo("Europe/Athens")).isoformat(timespec="seconds"),
            "status": "Verified" if reboot else "Prepared", "hostname": config["hostname"],
            "image": {**config["published"], "commit": "git:" + config["published"]["commit"]}, "dns": records, "certificate": cert,
            "public_http": web, "private_ports": ports, "vm_runtime": runtime,
            "reboot_persistence_verified": reboot, "temporary_login_user_removed": True,
            "certificate_auto_renewal_configured": True, "actual_renewal_observed": False,
            "off_vm_restore_verified": False, "real_client_data_imported": False,
            "full_requirement_acceptance": "Pending"}


def record(report):
    path = RECORDS / "evidence/S09-verification.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    if report.get("mode") == "offline":
        old.setdefault("step", "S09")
        old.setdefault("status", "Prepared")
        old["repository_checks"] = report
        report = old
    else:
        report["repository_checks"] = old.get("repository_checks", {})
        report["native_proxy_checks"] = old.get("native_proxy_checks", {})
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    status = report.get("status", "Prepared")
    with (RECORDS / "steps.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    row = next(row for row in rows if row["step_id"] == "S09")
    row.update(status=status, blocker="" if status == "Verified" else "Actual DNS/control, image pull, public HTTPS/login and controlled reboot proof required",
               next_step="S10" if status == "Verified" else "Complete S09 operator deployment/proof")
    with (RECORDS / "steps.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0], lineterminator="\n"); writer.writeheader(); writer.writerows(rows)
    state = RECORDS / "state.md"
    content = state.read_text()
    import re
    headline = f"Updated {datetime.now(ZoneInfo('Europe/Athens')).date()}. Current step: **S09 {status} — DuckDNS HTTPS preview**. Next step: **{'S10 — backup and restore' if status == 'Verified' else 'complete public deployment and reboot proof'}**."
    content = re.sub(r"Updated .*?\n", headline + "\n", content, count=1)
    content = re.sub(r"<!-- S09-RESULT -->.*?<!-- /S09-RESULT -->", "<!-- S09-RESULT -->\n" + ("Public DNS/TLS/login/static/isolation and actual reboot persistence are Verified. S10 is eligible; full release acceptance remains Pending." if status == "Verified" else "S09 is Prepared. Run the operator deployment and public/reboot checks; local proof does not complete this gate.") + "\n<!-- /S09-RESULT -->", content, flags=re.S)
    state.write_text(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--after-reboot", action="store_true")
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--config", type=Path, default=common.PRIVATE)
    parser.add_argument("--docker", default=shutil.which("docker") or "docker")
    parser.add_argument("--caddy")
    args = parser.parse_args()
    try:
        require(not args.after_reboot or args.live, "--after-reboot requires --live")
        report = live(args.config, args.after_reboot) if args.live else offline(args.docker, args.caddy)
        if args.record:
            record(report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, f"S09 verification stopped ({type(error).__name__}); no credentials printed.\n")


if __name__ == "__main__":
    main()
