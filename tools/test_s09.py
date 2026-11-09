"""Offline rejection tests. No fixture is evidence of a live deployment."""

import base64
import copy
from contextlib import redirect_stderr
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
import preview_events as events
import preview
from test_s08 import configuration as gcp_configuration
from preview import verified_delivery
from verify_s09 import check_tmpfs


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
    def test_new_tooling_keeps_the_verified_application_identity(self):
        config = configuration()
        old_image = dict(config["published"])
        context = {"digest": old_image["context_digest"]}
        with patch.object(preview.image, "committed_context", return_value=("b" * 40, b"", context)):
            self.assertEqual(preview.select_deployment_source(config), "b" * 40)
        self.assertEqual(config["published"], old_image)
        common.validate(config, published=True)
        self.assertEqual(host.release_path(config).name, "b" * 40)

    def test_changed_application_or_dirty_source_cannot_reuse_publication(self):
        config = configuration()
        with patch.object(preview.image, "committed_context", return_value=("b" * 40, b"", {"digest": "sha256:" + "9" * 64})), self.assertRaises(ValueError):
            preview.select_deployment_source(config)
        self.assertNotIn("deployment_commit", config)
        with patch.object(preview.image, "committed_context", side_effect=RuntimeError("Commit tracked changes first")), self.assertRaises(RuntimeError):
            preview.select_deployment_source(config)

    def test_invalid_operator_revision_denied(self):
        config = configuration(); config["deployment_commit"] = "main; untrusted"
        with self.assertRaises(ValueError):
            common.validate(config, published=True)

    def test_release_environment_uses_new_tools_and_original_static_export(self):
        config = configuration(); config["deployment_commit"] = "b" * 40
        with tempfile.TemporaryDirectory() as temporary, patch.object(common, "HOST_DATA", Path(temporary)):
            host.environment_file(config)
            environment = Path(temporary) / "release-config" / ("b" * 40 + ".env")
            text = environment.read_text()
            self.assertIn(config["published"]["image"], text)
            self.assertIn(str(Path(temporary) / "static" / ("a" * 40)), text)
            self.assertIn(str(environment), common.compose_command(host.release_path(config)))
            self.assertEqual(environment.stat().st_mode & 0o777, 0o600)

    def test_retry_ships_all_helpers_from_the_operator_commit(self):
        config = configuration(); published = dict(config["published"])
        def source(command, **kwargs):
            if command[:2] == ["git", "archive"]:
                return b"synthetic-source-archive"
            if command[:2] == ["git", "ls-tree"]:
                return b"tools/preview_events.py\n"
            if command[:2] == ["git", "show"]:
                return b"# synthetic helper\n"
            raise AssertionError("Unexpected command")
        context = {"digest": published["context_digest"]}
        with tempfile.TemporaryDirectory() as temporary, patch.object(preview.image, "committed_context", return_value=("b" * 40, b"", context)), patch.object(common, "dns"), patch.object(common, "run", side_effect=source) as commands, patch.object(preview, "gcloud", return_value={"status": "Started"}) as remote, redirect_stderr(io.StringIO()):
            private = Path(temporary) / "preview.json"
            result = preview.ship(config, current_tools=True, config_path=private)
            self.assertEqual(result["status"], "Started")
            saved = json.loads(private.read_text())
            self.assertEqual(saved["deployment_commit"], "b" * 40)
            self.assertEqual(saved["published"], published)
            shown = [call.args[0][-1] for call in commands.call_args_list if call.args[0][:2] == ["git", "show"]]
            self.assertEqual(len(shown), 4)
            self.assertTrue(all(path.startswith("b" * 40 + ":tools/") for path in shown))
            self.assertIn("b" * 40 + ":tools/preview_events.py", shown)
            self.assertEqual(remote.call_count, 3)

    def test_pulled_image_check_uses_original_application_revision(self):
        config = configuration(); config["deployment_commit"] = "b" * 40
        pub = config["published"]
        data = {"Id": pub["image_id"], "RepoDigests": [pub["image"]], "Os": "linux", "Architecture": "amd64", "Config": {"User": "10001:10001", "Labels": {
            "org.opencontainers.image.source": "https://github.com/vtsakan/accounting_platform",
            "org.opencontainers.image.revision": pub["commit"], "gr.accounting.source-context": pub["context_digest"]}}}
        with patch.object(common, "run", return_value=[data]):
            self.assertEqual(host.image_check(config), data)

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


class ImageIdentityTests(unittest.TestCase):
    def metadata(self, containerd=False):
        config = configuration(); pub = config["published"]
        data = {"Id": pub["image_id"], "RepoDigests": [pub["image"]], "Os": "linux", "Architecture": "amd64",
                "Config": {"User": "10001:10001", "Labels": {"org.opencontainers.image.source": "https://github.com/vtsakan/accounting_platform",
                    "org.opencontainers.image.revision": pub["commit"], "gr.accounting.source-context": pub["context_digest"]}}}
        if containerd:
            data["Id"] = pub["image"].split("@", 1)[1]
            data["Descriptor"] = {"digest": data["Id"], "mediaType": "application/vnd.oci.image.manifest.v1+json"}
        return config, data

    def test_classic_and_containerd_ids_keep_the_same_publication_receipt(self):
        for containerd in (False, True):
            config, data = self.metadata(containerd)
            before = copy.deepcopy(config)
            host.image_metadata_check(config, data)
            self.assertEqual(config, before)

    def test_pinned_manifest_does_not_accept_a_different_image_id(self):
        config, data = self.metadata(True); data["Id"] = "sha256:" + "9" * 64
        with self.assertRaisesRegex(ValueError, "Pulled image ID differs"):
            host.image_metadata_check(config, data)

    def test_matching_id_or_labels_never_replace_registry_binding(self):
        for containerd in (False, True):
            for refs in ([], ["other.invalid/web@sha256:" + "1" * 64], ["example.invalid/web@sha256:" + "8" * 64]):
                config, data = self.metadata(containerd); data["RepoDigests"] = refs
                with self.subTest(containerd=containerd, refs=refs), self.assertRaisesRegex(ValueError, "not bound"):
                    host.image_metadata_check(config, data)

    def test_a_present_descriptor_must_match_the_published_manifest(self):
        for value in ({"digest": "sha256:" + "9" * 64}, "untrusted"):
            config, data = self.metadata(True); data["Descriptor"] = value
            with self.assertRaisesRegex(ValueError, "descriptor differs"):
                host.image_metadata_check(config, data)

    def test_containerd_still_checks_source_revision_and_context(self):
        for key in ("org.opencontainers.image.source", "org.opencontainers.image.revision", "gr.accounting.source-context"):
            config, data = self.metadata(True); data["Config"]["Labels"][key] = "untrusted"
            with self.subTest(key=key), self.assertRaises(ValueError):
                host.image_metadata_check(config, data)

    def test_containerd_still_rejects_other_platforms_and_root_user(self):
        for key, value in (("Architecture", "arm64"), ("Os", "windows"), ("User", "0:0")):
            config, data = self.metadata(True)
            if key == "User":
                data["Config"][key] = value
            else:
                data[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                host.image_metadata_check(config, data)

    def test_running_container_must_use_pinned_reference_and_validated_ids(self):
        for containerd in (False, True):
            config, data = self.metadata(containerd); host.image_metadata_check(config, data)
            for identifier in {config["published"]["image_id"], data["Id"]}:
                host.running_image_check(config, data, {"Config": {"Image": config["published"]["image"]}, "Image": identifier})
            for image_ref, identifier in (("untrusted:latest", data["Id"]), (config["published"]["image"], "sha256:" + "8" * 64)):
                with self.assertRaises(ValueError):
                    host.running_image_check(config, data, {"Config": {"Image": image_ref}, "Image": identifier})


class CredentialTests(unittest.TestCase):
    def test_vm_failure_record_survives_ssh_without_secret_values(self):
        stream = io.StringIO()
        marker = "synthetic-credential-canary"
        error = common.MaterialAccessError(403)
        with patch.object(events, "CURRENT", "runtime-signing-read"), redirect_stderr(stream):
            events.failure(error)
        failed = MagicMock(returncode=1, stdout=marker.encode(), stderr=stream.getvalue().encode())
        with patch.object(common.subprocess, "run", return_value=failed), self.assertRaises(common.CommandFailure) as caught:
            common.run(["gcloud", marker], payload=marker.encode())
        self.assertIn("runtime-signing-read", str(caught.exception))
        self.assertIn("403", str(caught.exception))
        self.assertNotIn(marker, str(caught.exception))

    def test_unknown_errors_and_forged_diagnostic_values_are_suppressed(self):
        marker = "synthetic-private-canary"
        stream = io.StringIO()
        with redirect_stderr(stream):
            events.failure(ValueError(marker))
        self.assertNotIn(marker, stream.getvalue())
        for extra in ({"reason": marker}, {"error": marker}, {"stage": {"private": marker}}, {"program": marker}, {"at": marker}, {"secret": marker}, {"http_status": marker}):
            record = {"event": "failure", "stage": "registry-login", "error": "RuntimeError", **extra}
            self.assertIsNone(events.child_failure((events.PREFIX + json.dumps(record)).encode()))

    def test_secret_api_diagnostics_keep_only_status(self):
        import urllib.error
        error = urllib.error.HTTPError("https://example.invalid/private", 403, "private canary", {}, None)
        opener = MagicMock(); opener.open.side_effect = error
        with patch("preview_common.urllib.request.build_opener", return_value=opener), self.assertRaises(common.MaterialAccessError) as caught:
            common.read_secret(configuration(), "test-material", 1, "not-printed")
        self.assertEqual(caught.exception.http_status, 403)
        self.assertNotIn("canary", str(caught.exception))

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
    def test_tmpfs_options_cannot_become_separate_mounts(self):
        check_tmpfs(["/tmp:rw,noexec,nosuid,size=128m,mode=1777"])
        for mounts in (["/tmp:rw", "noexec", "nosuid", "size=128m", "mode=1777"], ["/tmp:rw,size=128m"], ["/tmp"]):
            with self.subTest(mounts=mounts), self.assertRaises(ValueError):
                check_tmpfs(mounts)

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
