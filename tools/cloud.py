#!/usr/bin/env python3
"""S08: initialise private parameters, inspect, or provision one selected preview.

Standard library only. No user credentials, secret values, SSH private keys or
service-account keys are stored by this tool. Every gcloud call selects a project.
"""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "private/gcp.json"
IAP = "35.235.240.0/20"
SCOPE = "https://www.googleapis.com/auth/cloud-platform"
APIS = ("compute", "iam", "storage", "artifactregistry", "secretmanager")
EU_REGIONS = {"europe-west1", "europe-west3", "europe-west4", "europe-west8", "europe-west9",
              "europe-west10", "europe-west12", "europe-north1", "europe-north2",
              "europe-central2", "europe-southwest1"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tail(value):
    return str(value).rstrip("/").rsplit("/", 1)[-1]


def same_resource(value, path):
    return value == path or str(value).rstrip("/").endswith("/" + path)


def validate(config, project):
    require(config["project_id"] == project, "--project must match the private configuration")
    require(re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project), "Invalid project ID")
    require(config["environment"] == "synthetic-preview", "Only the synthetic preview is supported")
    require(config["region"] in EU_REGIONS, "Select an EU region")
    require(re.fullmatch(re.escape(config["region"]) + r"-[a-z]", config["zone"]), "Zone/region mismatch")
    for key in ("vm_name", "network", "subnet", "address_name", "data_disk_name", "repository", "service_account_id"):
        require(isinstance(config[key], str) and re.fullmatch(r"[a-z][a-z0-9-]{1,60}[a-z0-9]", config[key]), f"Invalid {key}")
    require(len(config["service_account_id"]) <= 30, "Service-account ID exceeds 30 characters")
    for key in ("django_ref", "postgres_ref"):
        require(isinstance(config[key], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,255}", config[key]), f"Invalid {key}")
    for key in ("document_bucket", "backup_bucket"):
        require(isinstance(config[key], str) and re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", config[key]), f"Invalid {key}")
    require(config["document_bucket"] != config["backup_bucket"], "Documents and backups need separate buckets")
    require(config["django_ref"] != config["postgres_ref"], "Signing and database secrets must differ")
    require(config["disk_type"] == "pd-balanced", "Review a disk-type change before provisioning")
    for key in ("boot_disk_gb", "data_disk_gb"):
        require(type(config[key]) is int and config[key] >= 10, f"Invalid {key}")
    require(config["network_tier"] in {"PREMIUM", "STANDARD"}, "Invalid network tier")
    require(re.fullmatch(r"e2-(medium|standard-[248])", config["machine_type"]), "Unsupported preview machine type")
    require(config["image_project"] == "ubuntu-os-cloud", "Select an official Ubuntu image")
    require(re.fullmatch(r"ubuntu-[a-z0-9-]+", config["image_name"]), "An exact Ubuntu image name is required")
    require(config["mount_path"] == "/srv/accounting", "Review storage paths before changing the mount")
    require(config["data_uuid"] is None or re.fullmatch(r"[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}", config["data_uuid"]), "Invalid data UUID")
    require(config["ssh_user"] is None or re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", config["ssh_user"]), "Invalid SSH user")
    network = ipaddress.ip_network(config["subnet_cidr"], strict=True)
    require(network.version == 4 and network.is_private, "Select a private IPv4 subnet")
    require(set(config["secret_versions"]) == {"django", "postgres"}, "Unexpected secret-version keys")
    for value in config["secret_versions"].values():
        require(value is None or (type(value) is int and value > 0), "Pin numeric secret versions")
    return config


class GCloud:
    def __init__(self, project):
        self.project = project

    def command(self, *args, payload=None, read=False):
        command = ["gcloud", *args, f"--project={self.project}", "--quiet", "--format=json"]
        environment = {**os.environ, "CLOUDSDK_CORE_LOG_HTTP": "false"}
        result = subprocess.run(command, input=payload, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=environment)
        if result.returncode:
            # Do not reproduce SDK output: secret commands may have consumed stdin.
            raise RuntimeError(f"gcloud {' '.join(args[:3])} failed (exit {result.returncode}); inspect that operation in Cloud Shell")
        if read:
            return json.loads(result.stdout or b"null")
        return None

    def read(self, *args):
        return self.command(*args, read=True)


def account(config):
    return f"{config['service_account_id']}@{config['project_id']}.iam.gserviceaccount.com"


def firewall_specs(config):
    return (
        (config["network"] + "-allow-http", "80", "0.0.0.0/0", "http-server"),
        (config["network"] + "-allow-https", "443", "0.0.0.0/0", "https-server"),
        ("accounting-allow-iap-ssh", "22", IAP, config["vm_name"]),
    )


def check_firewalls(report, config):
    require(not report.get("firewallPolicys"), "Additional firewall policies need explicit inspection")
    expected = {row[0]: row[1:] for row in firewall_specs(config)}
    active = [row for row in report.get("firewalls", []) if not row.get("disabled") and row.get("direction") == "INGRESS"]
    require({row["name"] for row in active} == set(expected), "Unexpected or missing effective ingress rules")
    for row in active:
        port, source, tag = expected[row["name"]]
        require(row.get("allowed") == [{"IPProtocol": "tcp", "ports": [port]}], "Unexpected ingress protocol/ports")
        require(row.get("sourceRanges") == [source] and row.get("targetTags") == [tag], "Unexpected ingress sources/targets")
        require(not row.get("sourceTags") and not row.get("sourceServiceAccounts"), "Additional ingress sources")
        require(not row.get("denied") and row.get("priority") == 1000, "Unexpected firewall policy")


def check_vm(vm, config):
    require(vm["name"] == config["vm_name"] and tail(vm["zone"]) == config["zone"], "Wrong VM/zone")
    require(vm.get("status") == "RUNNING", "VM is not running")
    require(tail(vm["machineType"]) == config["machine_type"], "Machine type differs from configuration")
    require(vm.get("scheduling", {}).get("provisioningModel") == "STANDARD" and not vm["scheduling"].get("preemptible"), "A regular non-Spot VM is required")
    identities = vm.get("serviceAccounts", [])
    require(len(identities) == 1 and identities[0]["email"] == account(config) and set(identities[0]["scopes"]) == {SCOPE}, "VM identity/scope mismatch; use the documented stop/set/start procedure")
    interfaces = vm.get("networkInterfaces", [])
    require(len(interfaces) == 1, "Unexpected extra network interfaces")
    nic = interfaces[0]
    require(same_resource(nic["network"], f"projects/{config['project_id']}/global/networks/{config['network']}") and same_resource(nic["subnetwork"], f"projects/{config['project_id']}/regions/{config['region']}/subnetworks/{config['subnet']}"), "VM network/subnet mismatch")
    require(nic.get("stackType", "IPV4_ONLY") == "IPV4_ONLY", "Review IPv6 before enabling it")
    access = nic.get("accessConfigs", [])
    require(len(access) == 1 and access[0]["networkTier"] == config["network_tier"], "External IP/tier mismatch")
    attached = [row for row in vm["disks"] if tail(row["source"]) == config["data_disk_name"]]
    require(len(attached) == 1 and not attached[0].get("boot") and attached[0].get("autoDelete") is False, "Data disk must be attached and retained on VM deletion")
    require(attached[0]["deviceName"] == config["data_disk_name"] and attached[0]["mode"] == "READ_WRITE", "Wrong data disk attachment")
    boots = [row for row in vm["disks"] if row.get("boot")]
    require(len(boots) == 1 and int(boots[0]["diskSizeGb"]) == config["boot_disk_gb"], "Unexpected boot disk")
    require(set(vm.get("tags", {}).get("items", [])) == {config["vm_name"], "http-server", "https-server"}, "Unexpected VM network tags")


def binding(client, resource_args, identity, role):
    # Commands have the resource name after the verb, not before it.
    family, resource = resource_args[:-1], resource_args[-1]
    policy = client.read(*family, "get-iam-policy", resource)
    current = [item for item in policy.get("bindings", []) if identity in item.get("members", [])]
    require(all(item["role"] == role and not item.get("condition") for item in current), "Unexpected VM role on selected resource")
    if not current:
        client.command(*family, "add-iam-policy-binding", resource, f"--member={identity}", f"--role={role}", "--condition=None")


def provision(client, config):
    """Create missing named resources. Conflicting existing resources fail closed."""
    require(all(type(version) is int and version > 0 for version in config["secret_versions"].values()), "Set numeric secret versions before provisioning (1 for a new secret)")
    project = client.read("projects", "describe", config["project_id"])
    billing = client.read("billing", "projects", "describe", config["project_id"])
    require(billing.get("billingEnabled") is True, "Billing must already be enabled")
    client.command("services", "enable", *(item + ".googleapis.com" for item in APIS))
    zone, region = config["zone"], config["region"]

    def ensure(family, name, create, check=lambda row: None, *, flags=(), key="name", create_name=None):
        rows = client.read(*family, "list", *flags)
        require(isinstance(rows, list), "Unexpected resource-list response")
        matches = [row for row in rows if tail(row[key]) == name]
        require(len(matches) <= 1, "Ambiguous resource selection")
        if matches:
            check(matches[0])
        else:
            client.command(*family, "create", create_name or name, *create)

    ensure(("iam", "service-accounts"), account(config), ("--display-name=Accounting VM",),
           lambda row: require(not row.get("disabled"), "VM service account is disabled"),
           key="email", create_name=config["service_account_id"])
    ensure(("compute", "networks"), config["network"], ("--subnet-mode=custom",),
           lambda row: require(row.get("autoCreateSubnetworks") is False, "Expected a custom VPC"))
    ensure(("compute", "networks", "subnets"), config["subnet"],
           (f"--network={config['network']}", f"--region={region}", f"--range={config['subnet_cidr']}"),
           lambda row: require(tail(row["network"]) == config["network"] and row["ipCidrRange"] == config["subnet_cidr"] and tail(row["region"]) == region, "Existing subnet differs"),
           flags=(f"--regions={region}",))
    for name, port, source, tag in firewall_specs(config):
        ensure(("compute", "firewall-rules"), name,
               (f"--network={config['network']}", "--direction=INGRESS", "--action=ALLOW", f"--rules=tcp:{port}", f"--source-ranges={source}", f"--target-tags={tag}"),
               lambda row, name=name: check_firewalls({"firewalls": [row, *[firewall_row(spec, config) for spec in firewall_specs(config) if spec[0] != name]]}, config))
    ensure(("compute", "disks"), config["data_disk_name"],
           (f"--zone={zone}", f"--type={config['disk_type']}", f"--size={config['data_disk_gb']}GB"),
           lambda row: require(int(row["sizeGb"]) == config["data_disk_gb"] and tail(row["type"]) == config["disk_type"], "Existing data disk differs"), flags=(f"--zones={zone}",))
    ensure(("compute", "addresses"), config["address_name"],
           (f"--region={region}", f"--network-tier={config['network_tier']}"),
           lambda row: require(row.get("networkTier") == config["network_tier"] and row.get("addressType") == "EXTERNAL", "Existing IP/tier differs"), flags=(f"--regions={region}",))
    address = client.read("compute", "addresses", "describe", config["address_name"], f"--region={region}")
    instances = client.read("compute", "instances", "list", f"--zones={zone}")
    vm = next((row for row in instances if row["name"] == config["vm_name"]), None)
    if vm is None:
        require(not address.get("users"), "Reserved IP is in use by another resource")
        client.command("compute", "instances", "create", config["vm_name"], f"--zone={zone}",
                       f"--machine-type={config['machine_type']}", "--provisioning-model=STANDARD",
                       f"--image-project={config['image_project']}", f"--image={config['image_name']}",
                       f"--boot-disk-size={config['boot_disk_gb']}GB", f"--boot-disk-type={config['disk_type']}",
                       f"--disk=name={config['data_disk_name']},device-name={config['data_disk_name']},auto-delete=no",
                       f"--subnet={config['subnet']}", f"--address={address['address']}", f"--network-tier={config['network_tier']}",
                       f"--service-account={account(config)}", "--scopes=cloud-platform",
                       f"--tags={config['vm_name']},http-server,https-server")
    else:
        check_vm(vm, config)
        require(vm["networkInterfaces"][0]["accessConfigs"][0]["natIP"] == address["address"], "VM does not use the selected reserved IP")

    for key, role in (("document_bucket", "roles/storage.objectUser"), ("backup_bucket", "roles/storage.objectCreator")):
        bucket = config[key]
        ensure(("storage", "buckets"), bucket,
               (f"--location={region}", "--default-storage-class=STANDARD", "--uniform-bucket-level-access", "--public-access-prevention", "--soft-delete-duration=7d"),
               lambda row: require(str(row["projectNumber"]) == str(project["projectNumber"]) and row["location"].lower() == region, "Bucket ownership/location differs"), flags=("--raw",), create_name=f"gs://{bucket}")
        client.command("storage", "buckets", "update", f"gs://{bucket}", "--uniform-bucket-level-access", "--public-access-prevention")
        binding(client, ("storage", "buckets", f"gs://{bucket}"), f"serviceAccount:{account(config)}", role)
    repo_path = f"projects/{config['project_id']}/locations/{region}/repositories/{config['repository']}"
    ensure(("artifacts", "repositories"), config["repository"],
           (f"--location={region}", "--repository-format=docker", "--immutable-tags"),
           lambda row: require(row["format"] == "DOCKER" and tail(row["name"].split("/repositories/")[0]) == region, "Repository differs"), flags=(f"--location={region}",))
    client.command("artifacts", "repositories", "update", repo_path, "--immutable-tags")
    binding(client, ("artifacts", "repositories", repo_path), f"serviceAccount:{account(config)}", "roles/artifactregistry.reader")
    for key in ("django_ref", "postgres_ref"):
        secret = config[key]
        ensure(("secrets",), secret, ("--replication-policy=user-managed", f"--locations={region}"),
               lambda row: require(row.get("replication", {}).get("userManaged", {}).get("replicas") == [{"location": region}], "Secret replication differs"))
        versions = client.read("secrets", "versions", "list", secret)
        if not versions:
            client.command("secrets", "versions", "add", secret, "--data-file=-", payload=secrets.token_urlsafe(64).encode("ascii"))
        else:
            require(any(row.get("state") == "ENABLED" for row in versions), "Secret has no enabled version; no automatic rotation performed")
        binding(client, ("secrets", secret), f"serviceAccount:{account(config)}", "roles/secretmanager.secretAccessor")
    return inspect(client, config)


def firewall_row(spec, config):
    name, port, source, tag = spec
    return {"name": name, "direction": "INGRESS", "priority": 1000, "allowed": [{"IPProtocol": "tcp", "ports": [port]}], "sourceRanges": [source], "targetTags": [tag]}


def inspect(client, config):
    vm = client.read("compute", "instances", "describe", config["vm_name"], f"--zone={config['zone']}")
    check_vm(vm, config)
    firewalls = client.read("compute", "instances", "network-interfaces", "get-effective-firewalls", config["vm_name"], f"--zone={config['zone']}", "--network-interface=nic0")
    check_firewalls(firewalls, config)
    policy = client.read("projects", "get-iam-policy", config["project_id"])
    identity = "serviceAccount:" + account(config)
    require(not any(identity in row.get("members", []) for row in policy.get("bindings", [])), "VM has unexpected project-level roles")
    keys = client.read("iam", "service-accounts", "keys", "list", f"--iam-account={account(config)}", "--managed-by=user")
    require(not keys, "Unexpected user-managed service-account keys")
    address = client.read("compute", "addresses", "describe", config["address_name"], f"--region={config['region']}")
    require(address["address"] == vm["networkInterfaces"][0]["accessConfigs"][0]["natIP"] and address["status"] == "IN_USE" and address["networkTier"] == config["network_tier"], "Reserved IP is not attached to the VM")
    disk = client.read("compute", "disks", "describe", config["data_disk_name"], f"--zone={config['zone']}")
    require(int(disk["sizeGb"]) == config["data_disk_gb"] and tail(disk["type"]) == config["disk_type"], "Data disk size/type differs")
    project = client.read("projects", "describe", config["project_id"])

    def check_binding(family, resource, role):
        policy = client.read(*family, "get-iam-policy", resource)
        selected = [row for row in policy.get("bindings", []) if identity in row.get("members", [])]
        require(len(selected) == 1 and selected[0]["role"] == role and not selected[0].get("condition"), "Unexpected VM resource permissions")

    for key, role in (("document_bucket", "roles/storage.objectUser"), ("backup_bucket", "roles/storage.objectCreator")):
        row = client.read("storage", "buckets", "describe", f"gs://{config[key]}", "--raw")
        require(str(row["projectNumber"]) == str(project["projectNumber"]) and row["location"].lower() == config["region"], "Bucket ownership/location differs")
        iam = row.get("iamConfiguration", {})
        require(iam.get("uniformBucketLevelAccess", {}).get("enabled") is True and iam.get("publicAccessPrevention") == "enforced", "Bucket privacy is not enforced")
        require(row.get("storageClass") == "STANDARD", "Unexpected bucket storage class")
        require(int(row.get("softDeletePolicy", {}).get("retentionDurationSeconds", 0)) == 604800, "Initial seven-day soft-delete setting differs")
        check_binding(("storage", "buckets"), f"gs://{config[key]}", role)
    repository = f"projects/{config['project_id']}/locations/{config['region']}/repositories/{config['repository']}"
    row = client.read("artifacts", "repositories", "describe", repository)
    require(row["format"] == "DOCKER" and row.get("dockerConfig", {}).get("immutableTags") is True, "Docker repository/tag policy differs")
    check_binding(("artifacts", "repositories"), repository, "roles/artifactregistry.reader")
    for key, version_key in (("django_ref", "django"), ("postgres_ref", "postgres")):
        row = client.read("secrets", "describe", config[key])
        require(row.get("replication", {}).get("userManaged", {}).get("replicas") == [{"location": config["region"]}], "Secret location differs")
        check_binding(("secrets",), config[key], "roles/secretmanager.secretAccessor")
        version = config["secret_versions"][version_key]
        require(version is not None, "Pin the secret version in the private config")
        row = client.read("secrets", "versions", "describe", str(version), f"--secret={config[key]}")
        require(row.get("state") == "ENABLED", "Pinned secret version is not enabled")
    return {"project": config["project_id"], "vm": config["vm_name"], "status": "Passed", "checks": ["regular VM", "retained data disk", "reserved IPv4", "dedicated scoped identity", "effective ingress", "no VM project roles", "no user-managed SA keys", "private EU buckets", "resource IAM", "immutable registry tags", "pinned enabled EU secrets"], "application_deployment_tested": False}


def initialise(args):
    config = json.loads((ROOT / "infrastructure/gcp.example.json").read_text())
    config.update(project_id=args.project, ssh_user=args.ssh_user, data_uuid=args.data_uuid,
                  document_bucket=args.project + "-documents", backup_bucket=args.project + "-backups")
    config["secret_versions"] = {"django": args.django_version, "postgres": args.postgres_version}
    validate(config, args.project)
    active = GCloud(args.project).read("auth", "list", "--filter=status:ACTIVE")
    require(len(active) == 1 and not active[0]["account"].endswith(".gserviceaccount.com"), "Initialise from the administrator's laptop or Cloud Shell user account")
    config["operator_identity"] = active[0]["account"]
    args.config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.config.resolve().is_relative_to(ROOT):
        checked = subprocess.run(["git", "check-ignore", "--quiet", str(args.config)], cwd=ROOT)
        require(checked.returncode == 0, "Private config must be ignored by Git")
    with open(args.config, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as stream:
        json.dump(config, stream, indent=2)
        stream.write("\n")
    print(f"Created private configuration: {args.config}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "inspect", "apply"))
    parser.add_argument("--project", required=True, help="Explicit selected project; must match config")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--ssh-user")
    parser.add_argument("--data-uuid")
    parser.add_argument("--django-version", type=int)
    parser.add_argument("--postgres-version", type=int)
    args = parser.parse_args()
    try:
        if args.action == "init":
            initialise(args)
            return
        config = validate(json.loads(args.config.read_text()), args.project)
        client = GCloud(args.project)
        result = inspect(client, config) if args.action == "inspect" else provision(client, config)
        print(json.dumps(result, indent=2))
    except (ValueError, RuntimeError, KeyError, OSError, json.JSONDecodeError) as error:
        parser.exit(1, f"S08 stopped: {error}\n")


if __name__ == "__main__":
    main()
