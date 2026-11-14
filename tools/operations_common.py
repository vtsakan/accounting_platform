"""S10 formats and bounded operator I/O. No application dependency is added."""

import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

from cloud import require
import preview_common as preview

ROOT = preview.ROOT
PRIVATE = ROOT / "private/operations.json"
HOST_CONFIG = Path("/etc/accounting/operations.json")
STATE = Path("/srv/accounting/operations/state.json")
METRICS = Path("/srv/accounting/operations/monitor.json")
UNITS = ("accounting-backup.timer", "accounting-monitor.timer")
PREFIX = "s10/v1/"
MAX_DUMP = 256 * 1024 * 1024
MAX_ARCHIVE = MAX_DUMP + 8 * 1024 * 1024
METRIC_PREFIX = "custom.googleapis.com/accounting_preview/"
AGE_VERSION = '1.3.2'
METRIC_NAMES = ("heartbeat", "backup_age_seconds", "disk_used_ratio", "memory_used_ratio",
                "certificate_seconds", "readiness", "backup_last_attempt_ok", "alert_probe")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def timestamp(value):
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(date.tzinfo is not None, "A timezone-aware timestamp is required")
    return date.timestamp()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def recipient_id(recipient):
    return "sha256:" + hashlib.sha256(recipient.encode("ascii")).hexdigest()


def check_age():
    version = run(['age', '--version']).decode().strip()
    require(version.removeprefix('v') == AGE_VERSION, 'Install the pinned age tool with tools/install_age.py and put its directory on PATH')
    return version


def require_tmpfs(path):
    kinds = set(run(['findmnt', '-rn', '-T', path, '-o', 'FSTYPE']).decode().splitlines())
    # Some container mount namespaces expose duplicate entries for the same
    # tmpfs. A conflicting filesystem type still fails closed.
    require(kinds == {'tmpfs'}, 'Backup/recovery plaintext must stay on tmpfs')


def validate(config, *, local=False):
    keys = {'schema', 'preview', 'bucket', 'prefix', 'recipient', 'recipient_id', 'retention_days', 'max_dump_bytes',
            'synthetic_only', 'policy_confirmed', 'separate_key_copy_confirmed', 'incident_owner', 'restore_owner',
            'key_custodian', 'alert_email', 'instance_id', 'code_commit', 'policy_confirmed_at', 'local_identity', 'cloud'}
    require(set(config) <= keys, 'Unknown recovery configuration field; private payloads must not be shipped')
    require(config["schema"] == 1, "Unsupported S10 configuration")
    p = preview.validate(config["preview"], published=True)
    inventory = json.loads((ROOT / "docs/implementation/cloud_inventory.json").read_text())
    gcp = p["gcp"]
    require(gcp["project_id"] == inventory["project_id"] and gcp["vm_name"] == inventory["vm"]["name"]
            and gcp["zone"] == inventory["zone"] and gcp["data_uuid"] == inventory["data_disk"]["uuid"],
            "S10 supports only the selected accounting preview")
    require(config["bucket"] == inventory["storage"]["backup_bucket"] and config["prefix"] == PREFIX,
            "Unexpected backup destination")
    require(re.fullmatch(r"age1[023456789acdefghjklmnpqrstuvwxyz]{58}", config["recipient"]), "Use a native age X25519 recipient")
    require(config["recipient_id"] == recipient_id(config["recipient"]), "Recipient fingerprint differs")
    require(type(config["retention_days"]) is int and 7 <= config["retention_days"] <= 90, "Preview retention must be 7 to 90 days")
    require(config["max_dump_bytes"] == MAX_DUMP, "Review the tmpfs budget before increasing backup size")
    require(config["synthetic_only"] is True, "S10 is a synthetic recovery rehearsal")
    require(config['instance_id'] == inventory['vm']['instance_id'], 'Unexpected recovery source instance')
    require(config["policy_confirmed"] is True and config["separate_key_copy_confirmed"] is True, "Confirm preview retention and separate key custody during configuration")
    for role in ("incident_owner", "restore_owner", "key_custodian"):
        require(isinstance(config[role], str) and 1 <= len(config[role]) <= 100 and not any(ord(c) < 32 for c in config[role]), "An operational owner is required")
    require(re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", config["alert_email"]), "An alert email is required")
    if "code_commit" in config:
        require(re.fullmatch(r"[0-9a-f]{40}", config["code_commit"]), "Pin the operations commit")
    if local:
        identity = Path(config['local_identity']).expanduser().resolve()
        require(identity.is_absolute() and not identity.is_relative_to(ROOT.resolve()), 'Keep the primary identity path outside Git')
        if identity.exists():
            identity_file(identity)
    else:
        require("local_identity" not in config, "A laptop identity path must never be shipped to the VM")
    return config


def identity_file(value):
    path = Path(value).expanduser().resolve(strict=True)
    require(not path.is_relative_to(ROOT.resolve()), "Keep decryption identities outside the repository")
    info = path.stat()
    require(path.is_file() and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0, "Identity must be a private file owned by the current user")
    return path


def host_config(config):
    result = dict(config)
    result.pop("local_identity", None)
    result.pop("cloud", None)
    return validate(result)


class CommandFailure(RuntimeError):
    def __init__(self, command, result):
        message = f"{Path(str(command[0])).name} failed (exit {result.returncode})"
        # Only typed diagnostics emitted by our VM wrapper are forwarded.
        for line in result.stderr.decode('utf-8', errors='replace').splitlines():
            if not line.startswith('S10-DIAG ') or len(line) > 2000:
                continue
            try:
                row = json.loads(line[9:])
                record = {key: row[key] for key in ('stage', 'error') if key in row}
                if type(row.get('http_status')) is int and 100 <= row['http_status'] <= 599:
                    record['http_status'] = row['http_status']
                if re.fullmatch(r'[a-z0-9-]{1,40}', record.get('stage', '')) and re.fullmatch(r'[A-Za-z]{1,80}', record.get('error', '')):
                    message += '; VM diagnostic: ' + json.dumps(record, sort_keys=True)
            except (ValueError, TypeError):
                pass
        super().__init__(message)


def run(command, *, payload=None, environment=None, output=None, timeout=300):
    result = subprocess.run([str(v) for v in command], input=payload, env=environment,
                            stdout=output or subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        # No stderr, SQL, arguments, session URL or credentials in failure output.
        raise CommandFailure(command, result)
    return result.stdout


class APIError(RuntimeError):
    def __init__(self, status, *, operation=None, api_status=None, fields=()):
        self.status = status
        self.operation, self.api_status, self.fields = operation, api_status, tuple(fields)
        message = f"S10 cloud request failed (HTTP {status})"
        if operation:
            message += '; operation=' + operation
        if api_status:
            message += '; status=' + api_status
        if fields:
            message += '; fields=' + ','.join(fields)
        super().__init__(message)


def api_operation(method, url, body):
    """Return structural API names only; never project IDs, emails or URLs."""
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).strip('/').split('/')
    if url.startswith('https://monitoring.googleapis.com/') and len(path) >= 4:
        resource = path[3]
        if resource in {'metricDescriptors', 'notificationChannels', 'uptimeCheckConfigs', 'alertPolicies', 'timeSeries'}:
            verb = {'GET': 'get' if len(path) > 4 else 'list', 'POST': 'create', 'PATCH': 'patch'}.get(method, 'request')
            label = 'monitoring.' + resource + '.' + verb
            if resource == 'metricDescriptors' and path[-1] in METRIC_NAMES:
                label += ':' + path[-1]
            if resource == 'metricDescriptors' and isinstance(body, dict):
                name = str(body.get('type', '')).removeprefix(METRIC_PREFIX)
                if name in METRIC_NAMES:
                    label += ':' + name
            if resource == 'alertPolicies' and isinstance(body, dict):
                labels = body.get('userLabels')
                name = labels.get('check') if isinstance(labels, dict) else None
                if isinstance(name, str) and name in {'backup-age', 'backup-failed', 'disk', 'memory', 'certificate', 'readiness', 'alert-test', 'heartbeat', 'public-https'}:
                    label += ':' + name
            return label
    if url.startswith('https://storage.googleapis.com/'):
        if path[:4] == ['upload', 'storage', 'v1', 'b']:
            return 'storage.objects.insert'
        if path[:3] == ['storage', 'v1', 'b']:
            if len(path) == 4:
                return 'storage.buckets.' + ('patch' if method == 'PATCH' else 'get')
            if path[4:] == ['iam']:
                return 'storage.buckets.getIamPolicy'
            if path[4:] == ['iam', 'testPermissions']:
                return 'storage.buckets.testIamPermissions'
            if path[4:5] == ['o']:
                return 'storage.objects.' + ('list' if len(path) == 5 else 'get')
    return 'cloud.request'


def api_error_details(raw, body):
    """Read Google RPC status/field *names*, ignoring all messages and values."""
    statuses = {'INVALID_ARGUMENT', 'FAILED_PRECONDITION', 'NOT_FOUND', 'PERMISSION_DENIED', 'UNAUTHENTICATED',
                'RESOURCE_EXHAUSTED', 'INTERNAL', 'UNAVAILABLE', 'DEADLINE_EXCEEDED', 'ABORTED', 'ALREADY_EXISTS',
                'OUT_OF_RANGE', 'DATA_LOSS', 'CANCELLED', 'UNKNOWN'}
    keys = {'name', 'parent', 'filter', 'page_size', 'page_token', 'notification_channel', 'metric_descriptor',
            'uptime_check_config', 'alert_policy', 'bucket'}
    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key):
                    keys.add(key)
                    keys.add(re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower())
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
    try:
        collect(body)
        if len(raw) > 16384:
            return None, []
        error = json.loads(raw).get('error', {})
        if not isinstance(error, dict):
            return None, []
        api_status = error.get('status') if error.get('status') in statuses else None
        fields = set()
        details = error.get('details', [])
        for detail in details if isinstance(details, list) else []:
            if not isinstance(detail, dict) or detail.get('@type') != 'type.googleapis.com/google.rpc.BadRequest':
                continue
            violations = detail.get('fieldViolations', [])
            for violation in violations if isinstance(violations, list) else []:
                field = violation.get('field', '') if isinstance(violation, dict) else ''
                if not isinstance(field, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]{1,3}\])?(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[[0-9]{1,3}\])?)*', field) or len(field) > 200:
                    continue
                if all(component in keys for component in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', field)):
                    fields.add(field)
        return api_status, sorted(fields)[:10]
    except (ValueError, TypeError, AttributeError):
        return None, []


def api(method, url, token, body=None, *, headers=None, json_response=True):
    require(url.startswith(("https://storage.googleapis.com/", "https://monitoring.googleapis.com/")), "Unexpected API endpoint")
    data = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", **(headers or {})})
    # Disable redirects so credentials and resumable-upload locations cannot be forwarded.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=120) as response:
            if not json_response:
                return response.read(4 * 1024 * 1024 + 1)
            raw = response.read(4 * 1024 * 1024 + 1)
            require(len(raw) <= 4 * 1024 * 1024, "Oversized API response")
            return json.loads(raw or b"{}")
    except urllib.error.HTTPError as error:
        try:
            api_status, fields = api_error_details(error.read(16385), body)
        except (OSError, ValueError):
            api_status, fields = None, []
        raise APIError(error.code, operation=api_operation(method, url, body), api_status=api_status, fields=fields) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError("S10 cloud request failed; response omitted") from None


def crc32c_file(path):
    table = []
    for index in range(256):
        value = index
        for _ in range(8):
            value = (value >> 1) ^ (0x82f63b78 if value & 1 else 0)
        table.append(value)
    checksum = 0xffffffff
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            for byte in block:
                checksum = table[(checksum ^ byte) & 0xff] ^ (checksum >> 8)
    return base64.b64encode((checksum ^ 0xffffffff).to_bytes(4, "big")).decode()


def upload(config, path, object_name):
    require(re.fullmatch(re.escape(PREFIX) + r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.tar\.age", object_name), "Unsafe backup object name")
    size = path.stat().st_size
    require(0 < size <= MAX_ARCHIVE + 1024 * 1024, "Encrypted backup size exceeds the preview budget")
    with path.open('rb') as stream:
        require(stream.read(22) == b'age-encryption.org/v1\n', 'Only an age-encrypted archive may be uploaded')
    crc = crc32c_file(path)
    token = preview.access_token()
    query = urllib.parse.urlencode({"uploadType": "media", "name": object_name, "ifGenerationMatch": "0"})
    url = f"https://storage.googleapis.com/upload/storage/v1/b/{config['bucket']}/o?{query}"
    # A file object with Content-Length streams through http.client, without
    # reading the archive into RAM or using a credential-bearing command line.
    with path.open("rb") as stream:
        response = api("POST", url, token, stream, headers={"Content-Type": "application/octet-stream", "Content-Length": str(size)})
    require(response.get("bucket") == config["bucket"] and response.get("name") == object_name
            and int(response["size"]) == size and response.get("crc32c") == crc
            and re.fullmatch(r"[1-9][0-9]*", response["generation"]), "Upload response/checksum differs")
    return {"bucket": config["bucket"], "object": object_name, "generation": response["generation"],
            "size": size, "sha256": sha(path), "crc32c": crc}


def validate_receipt(receipt, config, *, max_age=86400):
    require(receipt["bucket"] == config["bucket"] and re.fullmatch(re.escape(PREFIX) + r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}\.tar\.age", receipt["object"]), "Receipt destination differs")
    require(re.fullmatch(r"[1-9][0-9]*", receipt["generation"]) and re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["sha256"]), "Invalid object generation/hash")
    require(type(receipt["size"]) is int and 0 < receipt["size"] <= MAX_ARCHIVE + 1024 * 1024, "Invalid backup size")
    require(receipt["recipient_id"] == config["recipient_id"], "Backup uses another recovery key")
    age = datetime.now(timezone.utc).timestamp() - timestamp(receipt['snapshot_started_at'])
    require(age >= 0 and (max_age is None or age <= max_age), "Backup exceeds the requested recovery age or has a future timestamp")
    require(receipt["project_id"] == config["preview"]["gcp"]["project_id"], "Backup belongs to another project")
    return receipt


def upload_receipt(config, receipt):
    # This small sidecar is recovery routing/integrity metadata, never a DB or
    # secret payload. It makes recovery independent of the original VM's state.
    allowed = {'bucket', 'object', 'generation', 'size', 'sha256', 'crc32c', 'snapshot_started_at', 'uploaded_at',
               'recipient_id', 'project_id', 'operations_commit', 'image', 'manifest_sha256'}
    require(set(receipt) == allowed, 'Unexpected private material in backup receipt')
    validate_receipt(receipt, config)
    data = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode()
    require(len(data) < 16384, 'Oversized recovery receipt')
    name = receipt['object'].removesuffix('.tar.age') + '.receipt.json'
    query = urllib.parse.urlencode({'uploadType': 'media', 'name': name, 'ifGenerationMatch': '0'})
    response = api('POST', 'https://storage.googleapis.com/upload/storage/v1/b/' + config['bucket'] + '/o?' + query,
                   preview.access_token(), data, headers={'Content-Type': 'application/json', 'Content-Length': str(len(data))})
    crc = base64.b64encode(preview.crc32c(data).to_bytes(4, 'big')).decode()
    require(response.get('bucket') == config['bucket'] and response.get('name') == name
            and int(response['size']) == len(data) and response.get('crc32c') == crc,
            'Recovery receipt upload integrity differs')
    return name


def write_archive(output, dump, manifest, recovery):
    with tarfile.open(fileobj=output, mode="w|") as archive:
        for name, data in (("manifest.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode()),
                           ("recovery.json", json.dumps(recovery, ensure_ascii=False, sort_keys=True).encode())):
            member = tarfile.TarInfo(name); member.size = len(data); member.mode = 0o600
            archive.addfile(member, io.BytesIO(data))
        member = tarfile.TarInfo("database.dump"); member.size = dump.stat().st_size; member.mode = 0o600
        with dump.open("rb") as stream:
            archive.addfile(member, stream)


def unpack(archive_path, directory):
    expected = {"database.dump": MAX_DUMP, "manifest.json": 4 * 1024 * 1024, "recovery.json": 1024 * 1024}
    with tarfile.open(archive_path) as archive:
        members = archive.getmembers()
        require(len(members) == 3 and {m.name for m in members} == set(expected), "Unexpected recovery archive members")
        for member in members:
            require(member.isfile() and 0 < member.size <= expected[member.name], "Invalid recovery member type/size")
            with archive.extractfile(member) as source, (directory / member.name).open("xb") as stream:
                while block := source.read(1024 * 1024):
                    stream.write(block)
            (directory / member.name).chmod(0o600)
    manifest = json.loads((directory / "manifest.json").read_text())
    require(manifest["format"] == "accounting-s10-v1" and manifest["dump_sha256"] == sha(directory / "database.dump"), "Dump integrity/format differs")
    return manifest, json.loads((directory / "recovery.json").read_text())
