"""Shared S09 configuration and credential-free deployment helpers (stdlib only)."""

import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request

from cloud import account, require, validate as validate_gcp
import preview_events as events

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "private/preview.json"
HOST_CONFIG = Path("/etc/accounting/preview.json")
HOST_DATA = Path("/srv/accounting")
RUN = Path("/run/accounting")


def validate(config, published=False):
    gcp = config["gcp"]
    validate_gcp(gcp, gcp["project_id"])
    require(gcp["ssh_user"] and gcp["data_uuid"], "S08 SSH user/filesystem UUID required")
    require(ipaddress.ip_address(config["external_ipv4"]).version == 4, "A reserved IPv4 address is required")
    require(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.duckdns\.org", config["hostname"]), "An exact DuckDNS hostname is required")
    require(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", config["acme_email"]), "A standard certificate contact email is required")
    for name in ("db_name", "db_user"):
        require(re.fullmatch(r"[a-z][a-z0-9_]{2,40}", config[name]), "Invalid database identifier")
    require(config["db_user"] != "postgres", "The application role must not be postgres")
    require(all(type(v) is int and v > 0 for v in gcp["secret_versions"].values()), "Pin numeric secret versions")
    if published:
        release = config["published"]
        require(re.fullmatch(r"[0-9a-f]{40}", release["commit"]), "Pin the complete release commit")
        prefix = f"{gcp['region']}-docker.pkg.dev/{gcp['project_id']}/{gcp['repository']}/web@sha256:"
        require(re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", release["image"]), "Use the selected repository and immutable registry digest")
        for field in ("image_id", "context_digest"):
            require(re.fullmatch(r"sha256:[0-9a-f]{64}", release[field]), f"Invalid {field}")
        require(re.fullmatch(r"[0-9a-f]{40}", deployment_commit(config)), "Pin the complete deployment commit")
    return config


def deployment_commit(config):
    return config.get("deployment_commit", config["published"]["commit"])


def private_json(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if exclusive:
        with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CommandFailure(RuntimeError):
    def __init__(self, command, result):
        self.program = Path(str(command[0])).name
        self.exit_code = result.returncode
        self.child = events.child_failure(result.stderr)
        message = f"{self.program} operation failed (exit {self.exit_code})"
        if self.child:
            message += "; VM diagnostic: " + json.dumps(self.child, sort_keys=True)
        super().__init__(message)


class MaterialAccessError(RuntimeError):
    def __init__(self, status=None):
        self.http_status = status
        super().__init__("Pinned Secret Manager read failed; no payload printed")


def run(command, *, payload=None, environment=None, json_output=False):
    result = subprocess.run([str(v) for v in command], input=payload, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=environment)
    if result.returncode:
        # No captured output/command arguments: they may carry metadata tokens,
        # generated test credentials, psql input or private configuration.
        raise CommandFailure(command, result)
    return json.loads(result.stdout) if json_output else result.stdout


def metadata(path):
    request = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/" + path,
                                     headers={"Metadata-Flavor": "Google"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=20) as response:
        return response.read().decode().strip()


def vm_identity(config):
    gcp = config["gcp"]
    require(metadata("project/project-id") == gcp["project_id"], "Unexpected VM project")
    require(metadata("instance/name") == gcp["vm_name"], "Unexpected VM name")
    require(metadata("instance/service-accounts/default/email") == account(gcp), "Unexpected VM identity")


def access_token():
    return json.loads(metadata("instance/service-accounts/default/token"))["access_token"]


def crc32c(value):
    checksum = 0xffffffff
    for byte in value:
        checksum ^= byte
        for _ in range(8):
            checksum = (checksum >> 1) ^ (0x82f63b78 if checksum & 1 else 0)
    return checksum ^ 0xffffffff


def read_secret(config, ref, version, token):
    resource = f"projects/{config['gcp']['project_id']}/secrets/{ref}/versions/{version}"
    request = urllib.request.Request("https://secretmanager.googleapis.com/v1/" + resource + ":access",
                                     headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=25) as response:
            result = json.load(response)
    except urllib.error.HTTPError as error:
        raise MaterialAccessError(error.code) from None
    except (OSError, ValueError):
        raise MaterialAccessError() from None
    payload = result["payload"]
    value = base64.b64decode(payload["data"], validate=True)
    require(crc32c(value) == int(payload["dataCrc32c"]), "Secret payload checksum mismatch")
    require(len(value) >= 50 and b"\n" not in value and b"\r" not in value and b"\0" not in value, "Unexpected generated secret format")
    value.decode("utf-8")
    return value


def dns(config):
    hostname = config["hostname"]
    expected = config["external_ipv4"]
    records = {}
    for kind in ("A", "AAAA"):
        url = f"https://dns.google/resolve?name={hostname}&type={kind}"
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.load(response)
        require(data.get("Status") == 0, "Public DNS is not ready; add the hostname in DuckDNS first")
        values = sorted({row["data"] for row in data.get("Answer", []) if row.get("type") == (1 if kind == "A" else 28)})
        records[kind] = values
    require(records["A"] == [expected], "Public A record differs from the reserved VM address")
    require(records["AAAA"] == [], "Remove the stale DuckDNS IPv6 record before certificate issuance")
    return records


def compose_command(release):
    return ["docker", "compose", "--project-name", "accounting-preview", "--project-directory", str(release),
            "--file", str(release / "compose.production.yml"), "--env-file", str(HOST_DATA / "release-config" / (release.name + ".env"))]


def compose_environment():
    # Shell variables must not override the rendered, reviewed release environment.
    prefixes = ("COMPOSE_", "DJANGO_", "DB_", "POSTGRES_", "APP_IMAGE", "SITE_DOMAIN", "ACME_EMAIL", "STATIC_DIRECTORY")
    return {key: value for key, value in os.environ.items() if not key.startswith(prefixes)
            and key not in {"DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}}


def file_sha(path):
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
