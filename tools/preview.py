#!/usr/bin/env python3
"""S09 laptop commands. No DuckDNS token or service-account key is required."""

import argparse
import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import tempfile

import cloud
from dev import require_local_docker
import image
import preview_common as common


def gcloud(config, *arguments, json_output=False):
    return common.run(["gcloud", *arguments, "--project=" + config["gcp"]["project_id"], "--quiet"],
                      environment={**os.environ, "CLOUDSDK_CORE_LOG_HTTP": "false"}, json_output=json_output)


def ssh(config, action):
    require = cloud.require
    require(action in {"inspect", "probe-create", "probe-delete"}, "Unsupported remote query")
    gcp = config["gcp"]
    return gcloud(config, "compute", "ssh", f"{gcp['ssh_user']}@{gcp['vm_name']}", "--zone=" + gcp["zone"],
                  "--tunnel-through-iap", "--command=" + shlex.join(["sudo", "-n", "/usr/local/sbin/accounting-preview", action]), json_output=True)


def configure(path, hostname, email):
    inventory = json.loads((common.ROOT / "docs/implementation/cloud_inventory.json").read_text())
    gcp_path = common.ROOT / "private/gcp.json"
    if not gcp_path.exists():
        cloud.initialise(argparse.Namespace(project=inventory["project_id"], config=gcp_path,
                         ssh_user=inventory["administration"]["linux_user"], data_uuid=inventory["data_disk"]["uuid"],
                         django_version=inventory["secrets"]["django"]["enabled_version"],
                         postgres_version=inventory["secrets"]["postgres"]["enabled_version"]))
    config = {"gcp": json.loads(gcp_path.read_text()), "hostname": hostname,
              "acme_email": email, "external_ipv4": inventory["network"]["external_ipv4"],
              "db_name": "accounting_platform", "db_user": "accounting_app", "published": None}
    common.validate(config)
    common.private_json(path, config, exclusive=True)
    return {"status": "Configured", "hostname": hostname, "ipv4": config["external_ipv4"], "private_config": str(path)}


def verified_delivery(built, report):
    cloud.require(report["step"] == "delivery" and report["status"] == "Verified" and report["mode"] == "docker-production-image"
                  and report["docker_execution_this_step"] is True and report["production_image_built_verified"] is True,
                  "Run current-source verify_delivery.py with --report private/s09-delivery.json first")
    tested = report["image"]
    cloud.require(tested["revision"] == built["revision"] and tested["image_id"] == built["image_id"]
                  and tested["context"]["digest"] == built["context"]["digest"], "Delivery proof belongs to a different committed image")
    cloud.require(all(report["suite"][key] == 0 for key in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")), "Delivery proof contains unexpected outcomes")


def publish(config, path):
    require_local_docker()
    built = image.build()
    proof = common.ROOT / "private/s09-delivery.json"
    verified_delivery(built, json.loads(proof.read_text()))
    commit = built["revision"].removeprefix("git:")
    gcp = config["gcp"]
    tag = f"{gcp['region']}-docker.pkg.dev/{gcp['project_id']}/{gcp['repository']}/web:{commit}"
    registry = tag.split("/", 1)[0]
    token = gcloud(config, "auth", "print-access-token").strip()
    cloud.require(token and b"\n" not in token, "Unexpected Google access-token response")
    endpoint = os.environ.get("DOCKER_HOST") if not os.environ.get("DOCKER_CONTEXT") else None
    if not endpoint:
        endpoint = json.loads(common.run(["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"] ))
    environment = {key: value for key, value in os.environ.items() if key != "DOCKER_CONTEXT"}
    environment["DOCKER_HOST"] = endpoint
    with tempfile.TemporaryDirectory(prefix="accounting-publish-") as temporary:
        cli = ["docker", "--config", temporary]
        common.run(cli + ["login", registry, "--username", "oauth2accesstoken", "--password-stdin"], payload=token, environment=environment)
        common.run(cli + ["tag", built["image_id"], tag], environment=environment)
        pushed = common.run(cli + ["push", tag], environment=environment).decode()
    metadata = image.inspect(tag)
    prefix = tag.rsplit(":", 1)[0] + "@sha256:"
    digests = [item for item in metadata.get("RepoDigests", []) if item.startswith(prefix)]
    if not digests:
        matches = re.findall(r"\bdigest: (sha256:[0-9a-f]{64})\b", pushed)
        cloud.require(len(set(matches)) == 1, "Registry digest was not recorded after publication")
        digests = [tag.rsplit(":", 1)[0] + "@" + matches[0]]
    cloud.require(len(digests) == 1, "Ambiguous registry digest after publication")
    config["published"] = {"commit": commit, "image": digests[0], "image_id": built["image_id"],
                           "context_digest": built["context"]["digest"], "delivery_evidence": common.file_sha(proof)}
    common.validate(config, published=True)
    common.private_json(path, config)
    return {"status": "Published", **config["published"]}


def ship(config):
    common.validate(config, published=True)
    common.dns(config)
    commit = config["published"]["commit"]
    gcp = config["gcp"]
    with tempfile.TemporaryDirectory(prefix="accounting-ship-") as temporary:
        stage = Path(temporary)
        bundle = stage / "source.tar"
        bundle.write_bytes(common.run(["git", "archive", "--format=tar", commit]))
        for name in ("cloud.py", "preview_common.py", "preview_host.py"):
            (stage / name).write_bytes(common.run(["git", "show", f"{commit}:tools/{name}"]))
        private = stage / "preview.json"
        common.private_json(private, config)
        target = f"{gcp['ssh_user']}@{gcp['vm_name']}"
        gcloud(config, "compute", "ssh", target, "--zone=" + gcp["zone"], "--tunnel-through-iap",
               "--command=umask 077; mkdir -p accounting-s09-stage")
        files = [bundle, private, *(stage / name for name in ("cloud.py", "preview_common.py", "preview_host.py"))]
        gcloud(config, "compute", "scp", "--zone=" + gcp["zone"], "--tunnel-through-iap", *map(str, files), target + ":accounting-s09-stage/")
        command = ["sudo", "-n", "python3", "accounting-s09-stage/preview_host.py", "install",
                   "--config=accounting-s09-stage/preview.json", "--bundle=accounting-s09-stage/source.tar", "--bundle-hash=" + common.file_sha(bundle)]
        return gcloud(config, "compute", "ssh", target, "--zone=" + gcp["zone"], "--tunnel-through-iap",
                      "--command=" + shlex.join(command), json_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "dns", "publish", "ship"))
    parser.add_argument("--config", type=Path, default=common.PRIVATE)
    parser.add_argument("--hostname", default="totalaccounting.duckdns.org")
    parser.add_argument("--email")
    args = parser.parse_args()
    try:
        if args.action == "configure":
            email = args.email or input("Certificate contact email (stored in private configuration): ").strip()
            result = configure(args.config, args.hostname, email)
        else:
            config = common.validate(json.loads(args.config.read_text()))
            if args.action == "dns":
                result = common.dns(config)
            elif args.action == "publish":
                result = publish(config, args.config)
            else:
                result = ship(config)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(1, f"S09 stopped ({type(error).__name__}): {error}\n")


if __name__ == "__main__":
    main()
