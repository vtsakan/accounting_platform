"""Offline safeguards for S08. Fixtures never stand in for cloud execution."""

import copy
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

import cloud
from probe_s08_vm import Probe, status_matches


def configuration():
    config = json.loads((cloud.ROOT / "infrastructure/gcp.example.json").read_text())
    config.update(project_id="accounting-preview-test", ssh_user="operator",
                  document_bucket="accounting-preview-test-documents",
                  backup_bucket="accounting-preview-test-backups")
    config["secret_versions"] = {"django": 1, "postgres": 1}
    return config


class FakeGCloud:
    """Resource-shaped responses with command capture; no subprocess/network use."""
    def __init__(self, config):
        self.config = config
        self.writes = []
        self.payloads = []
        self.missing = set()
        self.project_roles = []
        self.user_keys = []
        self.empty_versions = set()
        self.vm = {
            "name": config["vm_name"], "zone": config["zone"], "status": "RUNNING",
            "machineType": config["machine_type"],
            "scheduling": {"provisioningModel": "STANDARD", "preemptible": False},
            "tags": {"items": [config["vm_name"], "http-server", "https-server"]},
            "serviceAccounts": [{"email": cloud.account(config), "scopes": [cloud.SCOPE]}],
            "networkInterfaces": [{
                "network": f"projects/{config['project_id']}/global/networks/{config['network']}",
                "subnetwork": f"projects/{config['project_id']}/regions/{config['region']}/subnetworks/{config['subnet']}",
                "stackType": "IPV4_ONLY", "accessConfigs": [{"natIP": "192.0.2.10", "networkTier": "PREMIUM"}],
            }],
            "disks": [{"source": "boot", "boot": True, "diskSizeGb": "30"}, {
                "source": config["data_disk_name"], "boot": False, "autoDelete": False,
                "deviceName": config["data_disk_name"], "mode": "READ_WRITE",
            }],
        }
        self.firewalls = {"firewalls": [cloud.firewall_row(row, config) for row in cloud.firewall_specs(config)]}

    def bucket(self, name):
        return {"name": name, "projectNumber": "123456789012", "location": "EUROPE-WEST1",
                "storageClass": "STANDARD", "softDeletePolicy": {"retentionDurationSeconds": "604800"},
                "iamConfiguration": {"publicAccessPrevention": "enforced", "uniformBucketLevelAccess": {"enabled": True}}}

    def secret(self, name):
        return {"name": name, "replication": {"userManaged": {"replicas": [{"location": "europe-west1"}]}}}

    def read(self, *args):
        c = self.config
        args = tuple(args)
        if args[:2] == ("projects", "describe"):
            return {"projectNumber": "123456789012"}
        if args[:3] == ("billing", "projects", "describe"):
            return {"billingEnabled": True}
        if args[:3] == ("iam", "service-accounts", "list"):
            return [] if "sa" in self.missing else [{"email": cloud.account(c), "disabled": False}]
        if args[:3] == ("compute", "networks", "list"):
            return [{"name": c["network"], "autoCreateSubnetworks": False}]
        if args[:4] == ("compute", "networks", "subnets", "list"):
            return [{"name": c["subnet"], "network": c["network"], "region": c["region"], "ipCidrRange": c["subnet_cidr"]}]
        if args[:3] == ("compute", "firewall-rules", "list"):
            return copy.deepcopy(self.firewalls["firewalls"])
        if args[:2] == ("compute", "disks"):
            disk = {"name": c["data_disk_name"], "sizeGb": "50", "type": "pd-balanced"}
            return [disk] if args[2] == "list" else disk
        if args[:2] == ("compute", "addresses"):
            address = {"name": c["address_name"], "address": "192.0.2.10", "networkTier": "PREMIUM", "addressType": "EXTERNAL", "status": "IN_USE"}
            return [address] if args[2] == "list" else address
        if args[:4] == ("compute", "instances", "network-interfaces", "get-effective-firewalls"):
            return copy.deepcopy(self.firewalls)
        if args[:2] == ("compute", "instances"):
            return [copy.deepcopy(self.vm)] if args[2] == "list" else copy.deepcopy(self.vm)
        if args[:2] == ("projects", "get-iam-policy"):
            return {"bindings": copy.deepcopy(self.project_roles)}
        if args[:4] == ("iam", "service-accounts", "keys", "list"):
            return self.user_keys
        if args[:3] == ("storage", "buckets", "list"):
            return [self.bucket(c[key]) for key in ("document_bucket", "backup_bucket") if c[key] not in self.missing]
        if args[:3] == ("storage", "buckets", "describe"):
            return self.bucket(args[3].removeprefix("gs://"))
        if args[:2] == ("artifacts", "repositories") and args[2] in {"list", "describe"}:
            row = {"name": f"projects/{c['project_id']}/locations/{c['region']}/repositories/{c['repository']}", "format": "DOCKER", "dockerConfig": {"immutableTags": True}}
            return [row] if args[2] == "list" else row
        if args[:2] == ("secrets", "list"):
            return [self.secret(c[key]) for key in ("django_ref", "postgres_ref")]
        if args[:2] == ("secrets", "describe"):
            return self.secret(args[2])
        if args[:3] == ("secrets", "versions", "list"):
            return [] if args[3] in self.empty_versions else [{"state": "ENABLED", "name": "versions/1"}]
        if args[:3] == ("secrets", "versions", "describe"):
            return {"state": "ENABLED"}
        if "get-iam-policy" in args:
            resource = args[args.index("get-iam-policy") + 1]
            role = "roles/secretmanager.secretAccessor"
            if args[0] == "storage":
                role = "roles/storage.objectCreator" if resource.endswith(c["backup_bucket"]) else "roles/storage.objectUser"
            elif args[0] == "artifacts":
                role = "roles/artifactregistry.reader"
            return {"bindings": [{"members": ["serviceAccount:" + cloud.account(c)], "role": role}]}
        raise AssertionError(f"Unexpected fake read: {args}")

    def command(self, *args, payload=None):
        self.writes.append(args)
        self.payloads.append(payload)
        if args[:3] == ("iam", "service-accounts", "create"):
            self.missing.discard("sa")
        if args[:3] == ("storage", "buckets", "create"):
            self.missing.discard(args[3].removeprefix("gs://"))
        if args[:3] == ("secrets", "versions", "add"):
            self.empty_versions.discard(args[3])


class CloudSafeguards(unittest.TestCase):
    def setUp(self):
        self.config = configuration()
        self.client = FakeGCloud(self.config)

    def test_explicit_project_must_match(self):
        with self.assertRaises(ValueError):
            cloud.validate(self.config, "unrelated-project")

    def test_private_config_creation_is_0600_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(project=self.config["project_id"], config=Path(directory) / "gcp.json",
                                      ssh_user="operator", data_uuid=None, django_version=1, postgres_version=1)
            with patch.object(cloud.GCloud, "read", return_value=[{"account": "operator@example.invalid"}]), redirect_stdout(io.StringIO()):
                cloud.initialise(args)
                original = args.config.read_bytes()
                self.assertEqual(args.config.stat().st_mode & 0o777, 0o600)
                self.assertEqual(json.loads(original)["operator_identity"], "operator@example.invalid")
                with self.assertRaises(FileExistsError):
                    cloud.initialise(args)
                self.assertEqual(args.config.read_bytes(), original)

    def test_uk_or_swiss_region_is_not_an_eu_selection(self):
        for region in ("europe-west2", "europe-west6", "us-central1"):
            with self.subTest(region=region), self.assertRaises(ValueError):
                cloud.validate({**self.config, "region": region, "zone": region + "-b"}, self.config["project_id"])

    def test_shell_and_flag_injection_names_rejected(self):
        for name in ("--help", "vm;touch /tmp/unwanted", "vm$(id)", "vm/name", "vm\nother"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                cloud.validate({**self.config, "vm_name": name}, self.config["project_id"])

    def test_secret_version_aliases_rejected(self):
        self.config["secret_versions"]["django"] = "latest"
        with self.assertRaises(ValueError):
            cloud.validate(self.config, self.config["project_id"])

    def test_matching_existing_resources_do_not_recreate_or_rotate(self):
        report = cloud.provision(self.client, self.config)
        self.assertEqual(report["status"], "Passed")
        self.assertFalse(any("create" in command or "add" in command for command in self.client.writes))
        self.assertFalse(any(payload is not None for payload in self.client.payloads))

    def test_first_payload_generated_once_and_kept_on_retry(self):
        self.client.empty_versions = {self.config['django_ref'], self.config['postgres_ref']}
        cloud.provision(self.client, self.config)
        payloads = [payload for payload in self.client.payloads if payload is not None]
        self.assertEqual(len(payloads), 2)
        self.assertTrue(all(len(payload) >= 50 for payload in payloads))
        self.assertNotEqual(*payloads)
        cloud.provision(self.client, self.config)
        self.assertEqual(len([payload for payload in self.client.payloads if payload is not None]), 2)
        for command in self.client.writes:
            self.assertFalse(any(payload.decode() in str(argument) for payload in payloads for argument in command))

    def test_missing_resources_use_correct_sdk_identifiers(self):
        self.client.missing = {"sa", self.config["document_bucket"], self.config["backup_bucket"]}
        cloud.provision(self.client, self.config)
        creates = [row for row in self.client.writes if "create" in row]
        self.assertIn(("iam", "service-accounts", "create", self.config["service_account_id"], "--display-name=Accounting VM"), creates)
        buckets = [row[3] for row in creates if row[:2] == ("storage", "buckets")]
        self.assertCountEqual(buckets, ["gs://" + self.config["document_bucket"], "gs://" + self.config["backup_bucket"]])

    def test_ephemeral_data_disk_fails(self):
        self.client.vm["disks"][1]["autoDelete"] = True
        with self.assertRaises(ValueError):
            cloud.inspect(self.client, self.config)

    def test_shared_vpc_with_same_name_in_another_project_fails(self):
        self.client.vm["networkInterfaces"][0]["network"] = "projects/other-project/global/networks/accounting-network"
        with self.assertRaises(ValueError):
            cloud.inspect(self.client, self.config)

    def test_default_sa_or_limited_scope_fails(self):
        for identity in ({"email": "default@example.invalid", "scopes": [cloud.SCOPE]},
                         {"email": cloud.account(self.config), "scopes": ["read_only"]}):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                cloud.check_vm({**self.client.vm, "serviceAccounts": [identity]}, self.config)

    def test_public_ssh_or_database_ingress_fails(self):
        report = copy.deepcopy(self.client.firewalls)
        report["firewalls"][2]["sourceRanges"] = ["0.0.0.0/0"]
        with self.assertRaises(ValueError):
            cloud.check_firewalls(report, self.config)
        report = copy.deepcopy(self.client.firewalls)
        report["firewalls"][0]["allowed"][0]["ports"].append("5432")
        with self.assertRaises(ValueError):
            cloud.check_firewalls(report, self.config)

    def test_extra_firewall_policy_fails(self):
        with self.assertRaises(ValueError):
            cloud.check_firewalls({**self.client.firewalls, "firewallPolicys": [{"name": "unreviewed"}]}, self.config)

    def test_project_editor_role_for_vm_fails(self):
        self.client.project_roles = [{"role": "roles/editor", "members": ["serviceAccount:" + cloud.account(self.config)]}]
        with self.assertRaises(ValueError):
            cloud.inspect(self.client, self.config)

    def test_user_managed_sa_key_fails(self):
        self.client.user_keys = [{"name": "synthetic-key-reference"}]
        with self.assertRaises(ValueError):
            cloud.inspect(self.client, self.config)

    def test_missing_bucket_privacy_fails(self):
        original = self.client.bucket
        def public_bucket(name):
            result = original(name)
            result["iamConfiguration"]["publicAccessPrevention"] = "inherited"
            return result
        with patch.object(self.client, "bucket", side_effect=public_bucket), self.assertRaises(ValueError):
            cloud.inspect(self.client, self.config)

    def test_broad_backup_resource_role_fails(self):
        original = self.client.read
        def broad_role(*args):
            result = original(*args)
            if args[:3] == ("storage", "buckets", "get-iam-policy") and args[3].endswith(self.config["backup_bucket"]):
                result["bindings"][0]["role"] = "roles/storage.objectAdmin"
            return result
        with patch.object(self.client, "read", side_effect=broad_role), self.assertRaises(ValueError):
            cloud.inspect(self.client, self.config)

    def test_disabled_pinned_secret_version_fails(self):
        original = self.client.read
        def disabled_version(*args):
            return {"state": "DISABLED"} if args[:3] == ("secrets", "versions", "describe") else original(*args)
        with patch.object(self.client, "read", side_effect=disabled_version), self.assertRaises(ValueError):
            cloud.inspect(self.client, self.config)

    def test_sdk_error_does_not_expose_stdin_or_response(self):
        marker = "synthetic-sensitive-material"
        result = subprocess.CompletedProcess([], 1, stdout=marker.encode(), stderr=marker.encode())
        with patch("cloud.subprocess.run", return_value=result), self.assertRaises(RuntimeError) as raised:
            cloud.GCloud(self.config["project_id"]).command("secrets", "versions", "add", "synthetic", payload=marker.encode())
        self.assertNotIn(marker, str(raised.exception))


class AnonymousResponseSafeguards(unittest.TestCase):
    def test_anonymous_401_and_403_allowed_but_success_not_allowed(self):
        for status in (401, 403):
            self.assertTrue(status_matches(status, (401, 403), False))
        for status in (200, 302, 404, 412, 429, 500):
            self.assertFalse(status_matches(status, (401, 403), False))

    def test_authenticated_denial_still_requires_403(self):
        self.assertTrue(status_matches(403, 403, True))
        self.assertFalse(status_matches(401, 403, True))
        with self.assertRaises(ValueError):
            status_matches(401, (401, 403), True)

    def test_anonymous_request_has_no_bearer_header(self):
        probe = Probe()
        probe.token = "synthetic-not-a-credential"
        class Denied:
            def open(inner, request, **options):
                self.assertNotIn("Authorization", request.headers)
                raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", {}, io.BytesIO(b'{}'))
        probe.opener = Denied()
        self.assertEqual(probe.call("anonymous", "https://storage.googleapis.com/synthetic", expected=(401, 403), auth=False), b'{}')
        self.assertTrue(probe.results[0]["passed"])


if __name__ == "__main__":
    unittest.main()
