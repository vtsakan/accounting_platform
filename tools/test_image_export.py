"""Host-side export regressions; no Docker Engine, database or app secrets used."""

import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import image
import static_export


def member(name, data=b"", *, kind=tarfile.REGTYPE, mode=0o444, linkname=""):
    item = tarfile.TarInfo(name)
    item.type, item.mode, item.linkname = kind, mode, linkname
    item.uid = item.gid = 10001
    item.size = len(data) if item.isfile() else 0
    return item, data


def fixture_members(*, manifest=None):
    if manifest is None:
        manifest = {"paths": {"admin/css/base.css": "admin/css/base.123.css"}, "version": "1.1"}
    return [
        member(".", kind=tarfile.DIRTYPE, mode=0o555),
        member("./admin/css/base.css", b"body{color:black}"),
        member("./admin/css/base.123.css", b"body{color:black}"),
        member("./admin/css", kind=tarfile.DIRTYPE, mode=0o555),
        member("./admin", kind=tarfile.DIRTYPE, mode=0o555),
        member("./staticfiles.json", json.dumps(manifest).encode()),
    ]


def archive_bytes(members):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for item, data in members:
            archive.addfile(item, io.BytesIO(data) if item.isfile() else None)
    return result.getvalue()


class StaticArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="accounting-export-test-")
        self.addCleanup(self.directory.cleanup)
        self.parent = Path(self.directory.name)
        self.destination = self.parent / "static"

    def extract(self, members):
        return static_export.extract_static_archive(io.BytesIO(archive_bytes(members)), self.destination)

    def test_read_only_image_modes_become_host_owned_and_writable(self):
        old_umask = os.umask(0o077)
        try:
            result = self.extract(fixture_members())
        finally:
            os.umask(old_umask)
        self.assertEqual(result, {"file_count": 3, "manifest_entries": 1})
        for path in [self.destination, *self.destination.rglob("*")]:
            self.assertEqual(path.stat().st_uid, os.geteuid())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755 if path.is_dir() else 0o644)
        stylesheet = self.destination / "admin/css/base.css"
        stylesheet.write_bytes(b"host can write")
        self.assertEqual(stylesheet.read_bytes(), b"host can write")

    def test_unsafe_paths_fail_before_extracting_any_file(self):
        for name in ["../outside", "nested/../../outside", "/absolute", "C:/drive", "..\\outside"]:
            with self.subTest(path=name), self.assertRaisesRegex(RuntimeError, "path"):
                self.extract([*fixture_members(), member(name, b"untrusted")])
            self.assertFalse(self.destination.exists())
        self.assertFalse((self.parent / "outside").exists())

    def test_links_and_special_files_are_rejected(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE]:
            with self.subTest(kind=kind), self.assertRaisesRegex(RuntimeError, "links and special"):
                self.extract([*fixture_members(), member("unsafe", kind=kind, linkname="../outside")])
            self.assertFalse(self.destination.exists())

    def test_duplicate_normalized_paths_and_roots_are_rejected(self):
        for item in [member("admin/css/base.css", b"duplicate"), member("./", kind=tarfile.DIRTYPE)]:
            with self.subTest(path=item[0].name), self.assertRaisesRegex(RuntimeError, "Duplicate"):
                self.extract([*fixture_members(), item])
            self.assertFalse(self.destination.exists())

    def test_file_used_as_parent_is_rejected_before_writing(self):
        with self.assertRaisesRegex(RuntimeError, "used as a directory"):
            self.extract([*fixture_members(), member("blocked", b"file"), member("blocked/child", b"file")])
        self.assertFalse(self.destination.exists())

    def test_entry_and_byte_limits_are_enforced(self):
        with patch.object(static_export, "MAX_ENTRIES", 2), self.assertRaisesRegex(RuntimeError, "Too many"):
            self.extract(fixture_members())
        with patch.object(static_export, "MAX_ARCHIVE_BYTES", 10), self.assertRaisesRegex(RuntimeError, "size limit"):
            self.extract(fixture_members())
        self.assertFalse(self.destination.exists())

    def test_invalid_archive_is_rejected(self):
        with self.assertRaises(tarfile.ReadError):
            static_export.extract_static_archive(io.BytesIO(b"not a tar archive"), self.destination)
        self.assertFalse(self.destination.exists())

    def test_missing_manifest_or_manifest_target_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "missing its manifest"):
            self.extract([member("admin/css/base.css", b"css")])
        destination = self.parent / "missing-target"
        data = archive_bytes(fixture_members(manifest={"paths": {"admin/css/base.css": "missing.css"}}))
        with self.assertRaisesRegex(RuntimeError, "references a missing file"):
            static_export.extract_static_archive(io.BytesIO(data), destination)
        invalid = archive_bytes(fixture_members(manifest=["not a manifest object"]))
        with self.assertRaisesRegex(RuntimeError, "Invalid static manifest"):
            static_export.extract_static_archive(io.BytesIO(invalid), self.parent / "invalid-manifest")


class ExportProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="accounting-export-process-")
        self.addCleanup(self.directory.cleanup)
        self.parent = Path(self.directory.name)
        self.archive = self.parent / "fixture.tar"
        self.archive.write_bytes(archive_bytes(fixture_members()))
        self.destination = self.parent / "static"
        self.container = "a" * 64
        self.image_id = "sha256:" + "b" * 64

    def producer(self):
        return [sys.executable, "-c", "import pathlib,sys;sys.stdout.buffer.write(pathlib.Path(sys.argv[1]).read_bytes())", str(self.archive)]

    def test_binary_stream_round_trip_and_redacted_process_errors(self):
        with tempfile.TemporaryFile() as target:
            static_export.stream_archive(self.producer(), target)
            self.assertEqual(target.read(), self.archive.read_bytes())
        placeholder = "synthetic-" + "export-password"
        command = [sys.executable, "-c", "import sys;sys.stderr.write('export failed '+sys.argv[1]);sys.exit(7)", placeholder]
        with patch.dict(os.environ, {"ACCOUNTING_TEST_PASSWORD": placeholder}), tempfile.TemporaryFile() as target:
            with self.assertRaisesRegex(RuntimeError, r"exit 7.*\nexport failed \[REDACTED\]") as raised:
                static_export.stream_archive(command, target)
        self.assertNotIn(placeholder, str(raised.exception))

    def test_stream_timeout_and_size_limit_stop_the_child(self):
        with patch.object(static_export, "EXPORT_TIMEOUT", 0.05), tempfile.TemporaryFile() as target:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                static_export.stream_archive([sys.executable, "-c", "import time;time.sleep(10)"], target)
        with patch.object(static_export, "MAX_ARCHIVE_BYTES", 32), tempfile.TemporaryFile() as target:
            with self.assertRaisesRegex(RuntimeError, "size limit"):
                static_export.stream_archive(self.producer(), target)

    def docker_result(self, arguments):
        output = self.container if arguments[0] == "create" else "0" if arguments[0] == "inspect" else self.container
        return subprocess.CompletedProcess(["docker", *arguments], 0, stdout=output + "\n", stderr="")

    def test_export_streams_without_sending_host_paths_to_docker(self):
        attached = []
        def stream(command, target):
            attached.append(command)
            return static_export.stream_archive(self.producer(), target)
        with patch.object(image, "require_local_docker"), patch.object(image, "inspect", return_value={"Id": self.image_id}), \
                patch.object(image, "docker_command", side_effect=self.docker_result) as docker, \
                patch.object(image, "stream_archive", side_effect=stream):
            proof = image.export_static(self.image_id, self.destination)
        self.assertEqual(proof["image_id"], self.image_id)
        self.assertEqual(proof["file_count"], 3)
        self.assertEqual(attached, [["docker", "start", "--attach", self.container]])
        create = docker.call_args_list[0].args[0]
        for flag in ["--read-only", "--no-healthcheck", "--cap-drop", "--security-opt"]:
            self.assertIn(flag, create)
        self.assertEqual(create[create.index("--network") + 1], "none")
        self.assertIn(self.image_id, create)
        self.assertNotIn(str(self.parent), " ".join(create))
        self.assertEqual(docker.call_args_list[-1].args[0], ["rm", self.container])
        self.assertFalse(list(self.parent.glob(".accounting-static-export-*")))

    def test_container_error_is_reported_even_when_docker_attach_returns_zero(self):
        def docker_result(arguments):
            if arguments[0] == "inspect":
                return subprocess.CompletedProcess(["docker", *arguments], 0, "9\n", "")
            return self.docker_result(arguments)
        with patch.object(image, "require_local_docker"), patch.object(image, "inspect", return_value={"Id": self.image_id}), \
                patch.object(image, "docker_command", side_effect=docker_result), \
                patch.object(image, "stream_archive", return_value="archive permission denied"), \
                patch.object(image.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as cleanup:
            with self.assertRaisesRegex(RuntimeError, r"exit 9.*\narchive permission denied"):
                image.export_static(self.image_id, self.destination)
        self.assertEqual(cleanup.call_args.args[0], ["docker", "rm", "--force", self.container])
        self.assertFalse(self.destination.exists())

    def test_failed_stream_preserves_diagnostic_and_removes_only_owned_container(self):
        with patch.object(image, "require_local_docker"), patch.object(image, "inspect", return_value={"Id": self.image_id}), \
                patch.object(image, "docker_command", side_effect=self.docker_result), \
                patch.object(image, "stream_archive", side_effect=RuntimeError("specific exporter diagnostic")), \
                patch.object(image.subprocess, "run", side_effect=OSError("cleanup also failed")) as cleanup:
            with self.assertRaisesRegex(RuntimeError, "specific exporter diagnostic"):
                image.export_static(self.image_id, self.destination)
        self.assertEqual(cleanup.call_args.args[0], ["docker", "rm", "--force", self.container])
        self.assertFalse(self.destination.exists())
        self.assertFalse(list(self.parent.glob(".accounting-static-export-*")))

    def test_existing_directory_and_dangling_symlink_are_not_overwritten(self):
        self.destination.mkdir()
        marker = self.destination / "keep.txt"
        marker.write_text("keep")
        dangling = self.parent / "dangling"
        dangling.symlink_to(self.parent / "absent")
        with patch.object(image, "require_local_docker") as docker:
            for path in [self.destination, dangling]:
                with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, "not overwritten"):
                    image.export_static(self.image_id, path)
            docker.assert_not_called()
        self.assertEqual(marker.read_text(), "keep")
        self.assertTrue(dangling.is_symlink())

    def test_docker_command_surfaces_redacted_stderr(self):
        placeholder = "synthetic-" + "docker-password"
        failure = subprocess.CompletedProcess(["docker", "create"], 1, "", "permission denied " + placeholder)
        with patch.dict(os.environ, {"ACCOUNTING_TEST_PASSWORD": placeholder}), \
                patch.object(image.subprocess, "run", return_value=failure):
            with self.assertRaisesRegex(RuntimeError, "permission denied \\[REDACTED\\]") as raised:
                image.docker_command(["create", "fixture-image"])
        self.assertNotIn(placeholder, str(raised.exception))


class ImageReuseTests(unittest.TestCase):
    def metadata(self):
        return {"Id": "sha256:" + "a" * 64, "Architecture": "amd64", "Config": {"User": "10001:10001", "Labels": {
            "org.opencontainers.image.source": "https://github.com/vtsakan/accounting_platform",
            "org.opencontainers.image.revision": "b" * 40,
            "gr.accounting.source-context": "sha256:matching-context"}}}

    def test_matching_context_preserves_image_and_verifier_revisions(self):
        metadata = self.metadata()
        with patch.object(image, "require_local_docker"), \
                patch.object(image, "committed_context", return_value=("c" * 40, b"", {"digest": "sha256:matching-context"})), \
                patch.object(image, "inspect", return_value=metadata), patch.object(image, "build") as build:
            result = image.reuse_for_verification(metadata["Id"])
        self.assertEqual(result["revision"], "git:" + "b" * 40)
        self.assertEqual(result["verification_revision"], "git:" + "c" * 40)
        self.assertEqual(result["image_id"], metadata["Id"])
        self.assertTrue(result["reused_existing_image"])
        build.assert_not_called()

    def test_mismatched_context_or_unsafe_image_is_rejected(self):
        cases = []
        wrong_context = self.metadata()
        wrong_context["Config"]["Labels"]["gr.accounting.source-context"] = "sha256:different"
        cases.append(wrong_context)
        wrong_user = self.metadata(); wrong_user["Config"]["User"] = "root"; cases.append(wrong_user)
        wrong_source = self.metadata(); wrong_source["Config"]["Labels"]["org.opencontainers.image.source"] = "other"; cases.append(wrong_source)
        wrong_arch = self.metadata(); wrong_arch["Architecture"] = "arm64"; cases.append(wrong_arch)
        for metadata in cases:
            with self.subTest(metadata=metadata), patch.object(image, "require_local_docker"), \
                    patch.object(image, "committed_context", return_value=("c" * 40, b"", {"digest": "sha256:matching-context"})), \
                    patch.object(image, "inspect", return_value=metadata), self.assertRaisesRegex(RuntimeError, "does not match"):
                image.reuse_for_verification(metadata["Id"])


if __name__ == "__main__":
    unittest.main()
