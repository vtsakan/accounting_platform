"""Offline rejection tests. No fixture is evidence of a live deployment."""

import base64
import errno
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import preview_common as common
import preview_host as host
import preview_http
from test_s08 import configuration as gcp_configuration
from preview import verified_delivery


def configuration():
    gcp = gcp_configuration()
    gcp["data_uuid"] = "22415b2c-1e1b-4e39-9ce5-5fb0c19dd663"
    return {"gcp": gcp, "hostname": "totalaccounting.duckdns.org",
            "external_ipv4": "192.0.2.10", "acme_email": "operator@example.invalid",
            "db_name": "accounting_platform", "db_user": "accounting_app",
            "published": {"commit": "a" * 40,
                          "image": f"{gcp['region']}-docker.pkg.dev/{gcp['project_id']}/{gcp['repository']}/web@sha256:" + "1" * 64,
                          "image_id": "sha256:" + "2" * 64, "context_digest": "sha256:" + "3" * 64}}


class ConfigurationTests(unittest.TestCase):
    def test_exact_hostname_and_pinned_release(self):
        common.validate(configuration(), published=True)

    def test_urls_wildcards_shell_and_multiline_hosts_denied(self):
        for value in ("https://totalaccounting.duckdns.org", "*.duckdns.org", "a.b.duckdns.org", "x.duckdns.org\nBAD=1", "$(id).duckdns.org"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config = configuration(); config["hostname"] = value; common.validate(config)

    def test_wrong_registry_mutable_tag_and_short_commit_denied(self):
        for key, value in (("image", "elsewhere.invalid/web@sha256:" + "1" * 64), ("image", "web:latest"), ("commit", "abc123")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                config = configuration(); config["published"][key] = value; common.validate(config, published=True)

    def test_configuration_injection_and_superuser_denied(self):
        for key, value in (("acme_email", "x@example.invalid\nDB_PASSWORD=value"), ("db_user", "postgres"), ("db_user", "app;DROP ROLE postgres"), ("external_ipv4", "localhost")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                config = configuration(); config[key] = value; common.validate(config)

    def test_latest_or_boolean_secret_versions_denied(self):
        for version in ("latest", True, 0):
            with self.subTest(version=version), self.assertRaises(ValueError):
                config = configuration(); config["gcp"]["secret_versions"]["django"] = version; common.validate(config)

    def test_inherited_shell_overrides_removed(self):
        with patch.dict(os.environ, {"DB_USER": "postgres", "COMPOSE_FILE": "/tmp/other.yml", "DOCKER_HOST": "tcp://remote:2375", "SITE_DOMAIN": "wrong.invalid"}):
            self.assertFalse({"DB_USER", "COMPOSE_FILE", "DOCKER_HOST", "SITE_DOMAIN"} & common.compose_environment().keys())

    def test_native_or_other_image_proof_cannot_authorize_publication(self):
        built = {"revision": "git:" + "a" * 40, "image_id": "sha256:" + "1" * 64, "context": {"digest": "sha256:" + "2" * 64}}
        report = {"step": "delivery", "status": "Verified", "mode": "docker-production-image", "docker_execution_this_step": True,
                  "production_image_built_verified": True, "image": built,
                  "suite": {key: 0 for key in ("unexpected_failures", "unexpected_errors", "unexpected_successes", "skips")}}
        verified_delivery(built, report)
        with self.assertRaises(ValueError):
            verified_delivery(built, {**report, "status": "Prepared"})
        with self.assertRaises(ValueError):
            verified_delivery({**built, "revision": "git:" + "b" * 40}, report)


class CredentialTests(unittest.TestCase):
    def test_castagnoli_reference_vector(self):
        self.assertEqual(common.crc32c(b"123456789"), 0xe3069283)

    def test_corrupt_or_multiline_payload_denied(self):
        for value, checksum in ((b"a" * 64, 1), (b"a" * 64 + b"\n", None)):
            response = io.BytesIO(json.dumps({"payload": {"data": base64.b64encode(value).decode(), "dataCrc32c": str(checksum if checksum is not None else common.crc32c(value))}}).encode())
            opener = MagicMock(); opener.open.return_value = response
            with patch("preview_common.urllib.request.build_opener", return_value=opener), self.assertRaises(ValueError):
                common.read_secret(configuration(), "test-material", 1, "synthetic")

    def test_runtime_file_owner_and_no_other_readers(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(common, "RUN", Path(directory) / "runtime"):
            host.secret_file("signing", b"synthetic-only", os.getuid())
            path = common.RUN / "signing"
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)
            self.assertEqual(path.stat().st_uid, os.getuid())
            self.assertEqual(common.RUN.stat().st_mode & 0o777, 0o700)

    def test_boot_rejects_disk_backed_runtime(self):
        with patch.object(host, "mounted"), patch.object(common, "run", return_value=b"ext4\n"), patch.object(common, "access_token") as token, self.assertRaises(ValueError):
            host.refresh(configuration())
        token.assert_not_called()

    def test_sql_literal_does_not_escape_into_a_statement(self):
        self.assertEqual(host.literal("a'; SELECT 'b"), "'a''; SELECT ''b'")
        with self.assertRaises(ValueError):
            host.literal("invalid\0value")

    def test_failed_subprocess_does_not_disclose_input_or_output(self):
        failed = MagicMock(returncode=1, stdout=b"sensitive output", stderr=b"private details")
        with patch("preview_common.subprocess.run", return_value=failed), self.assertRaises(RuntimeError) as error:
            common.run(["example", "private argument"], payload=b"private payload")
        self.assertNotIn("private", str(error.exception)); self.assertNotIn("sensitive", str(error.exception))


class ArchiveTests(unittest.TestCase):
    def unpack(self, name="tools/example.py", kind=tarfile.REGTYPE, wrong_hash=False):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); bundle = root / "source.tar"
            with tarfile.open(bundle, "w") as archive:
                member = tarfile.TarInfo(name); member.type = kind
                member.linkname = "/etc/passwd" if kind == tarfile.SYMTYPE else ""
                payload = b"print('synthetic')\n"; member.size = len(payload) if kind == tarfile.REGTYPE else 0
                archive.addfile(member, io.BytesIO(payload) if member.size else None)
            with patch.object(host, "RELEASES", root / "releases"):
                expected = "sha256:" + "0" * 64 if wrong_hash else common.file_sha(bundle)
                target = host.unpack(bundle, expected, "a" * 40)
                self.assertTrue((target / name).is_file())
                self.assertEqual(host.unpack(bundle, expected, "a" * 40), target)

    def test_regular_bundle_and_idempotent_same_hash(self):
        self.unpack()

    def test_traversal_absolute_links_and_runtime_paths_denied(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/absolute", tarfile.REGTYPE), ("tools/link", tarfile.SYMTYPE), ("tools/hard", tarfile.LNKTYPE), ("private/preview.json", tarfile.REGTYPE), ("media/private.txt", tarfile.REGTYPE)):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.unpack(name, kind)

    def test_changed_bundle_hash_denied(self):
        with self.assertRaises(ValueError):
            self.unpack(wrong_hash=True)


class NetworkTests(unittest.TestCase):
    def test_gce_dns_exceptions_precede_metadata_rejection(self):
        installed = []
        missing = MagicMock(returncode=1)
        with patch("preview_host.subprocess.run", return_value=missing), patch.object(common, "run", side_effect=lambda command: installed.append(command)):
            host.metadata_firewall()
        rules = [row for row in installed if "-I" in row]
        self.assertEqual(rules[0][-1], "REJECT")
        self.assertEqual([row[row.index("-p") + 1] for row in rules[1:]], ["tcp", "udp"])
        self.assertTrue(all(row[row.index("--dport") + 1] == "53" and row[-1] == "RETURN" and row[row.index("DOCKER-USER") + 1] == "1" for row in rules[1:]))

    def test_public_dns_must_match_without_ipv6(self):
        for answers in ((["192.0.2.11"], []), (["192.0.2.10"], ["2001:db8::1"])):
            records = [{"Status": 0, "Answer": [{"type": kind, "data": value} for value in values]} for kind, values in zip((1, 28), answers)]
            with patch("preview_common.urllib.request.urlopen", side_effect=[io.BytesIO(json.dumps(row).encode()) for row in records]), self.assertRaises(ValueError):
                common.dns(configuration())

    def test_reachable_private_port_fails(self):
        with patch("preview_http.socket.create_connection", return_value=MagicMock()), self.assertRaises(ValueError):
            preview_http.private_ports("192.0.2.10")

    def test_no_route_is_not_a_successful_denied_access_probe(self):
        with patch("preview_http.socket.create_connection", side_effect=OSError(errno.ENETUNREACH, "no route")), self.assertRaises(OSError):
            preview_http.private_ports("192.0.2.10")

    def test_explicit_refusal_is_accepted(self):
        with patch("preview_http.socket.create_connection", side_effect=ConnectionRefusedError):
            self.assertEqual(set(preview_http.private_ports("192.0.2.10")), {"5432", "8000"})


if __name__ == "__main__":
    unittest.main()
