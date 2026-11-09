#!/usr/bin/env python3
"""Root S09 operator commands for the selected VM; startup never migrates data."""

import argparse
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import shutil
import subprocess
import sys
import tarfile
import tempfile

from cloud import require
import preview_common as common
import preview_events as events

RELEASES = Path("/opt/accounting/releases")


def load():
    return common.validate(json.loads(common.HOST_CONFIG.read_text()), published=True)


def mounted(config):
    common.vm_identity(config)
    actual = common.run(["findmnt", "-rn", "-M", "/srv/accounting", "-o", "UUID"]).decode().strip()
    require(actual == config["gcp"]["data_uuid"], "Expected data filesystem is not mounted")


def release_path(config):
    return RELEASES / common.deployment_commit(config)


def compose(config, *arguments, payload=None, json_output=False):
    return common.run(common.compose_command(release_path(config)) + list(arguments),
                      payload=payload, environment=common.compose_environment(), json_output=json_output)


def unpack(bundle, expected, commit):
    data = Path(bundle).read_bytes()
    require(len(data) <= 100 * 1024 * 1024, "Release bundle exceeds size limit")
    require("sha256:" + hashlib.sha256(data).hexdigest() == expected, "Release bundle hash differs")
    require(len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "Invalid release identity")
    target = RELEASES / commit
    if target.exists():
        require((target / ".bundle.sha256").read_text().strip() == expected, "Existing release differs; it was not overwritten")
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".s09-", dir=target.parent))
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            members = archive.getmembers()
            require(len(members) <= 5000 and sum(m.size for m in members) <= 100 * 1024 * 1024, "Oversize archive")
            for member in members:
                path = PurePosixPath(member.name)
                require(not path.is_absolute() and ".." not in path.parts and member.name, "Unsafe archive path")
                require(member.isdir() or member.isfile(), "Links/devices are not accepted in release bundles")
                require(not any(p in {".git", "private", "secrets", "media", "uploads"} for p in path.parts), "Private/runtime path in release bundle")
                dest = staging / path
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as source, dest.open("xb") as stream:
                        shutil.copyfileobj(source, stream)
                    dest.chmod(0o555 if member.mode & 0o111 else 0o444)
        (staging / ".bundle.sha256").write_text(expected + "\n")
        for folder, directories, files in os.walk(staging):
            Path(folder).chmod(0o755)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def secret_file(name, value, uid):
    common.RUN.mkdir(parents=True, exist_ok=True, mode=0o700)
    common.RUN.chmod(0o700)
    fd, temporary = tempfile.mkstemp(prefix=".new-", dir=common.RUN)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(temporary, uid, uid)
        os.chmod(temporary, 0o400)
        os.replace(temporary, common.RUN / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh(config):
    mounted(config)
    require(common.run(["findmnt", "-rn", "-T", str(common.RUN.parent), "-o", "FSTYPE"]).decode().strip() == "tmpfs", "Runtime credentials require a tmpfs /run")
    state = common.HOST_DATA / "preview-state.json"
    if state.exists():
        require((common.HOST_DATA / "postgres17/PG_VERSION").read_text().strip() == "17", "Existing PostgreSQL 17 data missing; refusing a fresh database at boot")
    token = common.access_token()
    gcp = config["gcp"]
    for name, ref_key, version_key in (("signing", "django_ref", "django"), ("database", "postgres_ref", "postgres")):
        events.checkpoint("runtime-" + name + "-read")
        value = common.read_secret(config, gcp[ref_key], gcp["secret_versions"][version_key], token)
        secret_file(name, value, 10001)
    # Initialization-only entropy. The postgres network password is disabled by
    # explicit bootstrap; later starts keep PGDATA and ignore this initial value.
    secret_file("pg-init", secrets.token_urlsafe(64).encode(), 0)
    events.checkpoint("metadata-firewall")
    metadata_firewall()


def metadata_firewall():
    # A host-only metadata consumer: Docker bridge workloads cannot obtain the
    # VM token, including Caddy's internet-enabled certificate client. The chain
    # can be created before dockerd starts; Docker preserves DOCKER-USER rules.
    check = subprocess.run(["iptables", "-w", "-S", "DOCKER-USER"], capture_output=True)
    if check.returncode:
        common.run(["iptables", "-w", "-N", "DOCKER-USER"])
    rule = ["DOCKER-USER", "-d", "169.254.169.254/32", "-j", "REJECT"]
    check = subprocess.run(["iptables", "-w", "-C", *rule], capture_output=True)
    if check.returncode:
        common.run(["iptables", "-w", "-I", "DOCKER-USER", "1", *rule[1:]])
    # GCE also serves its DNS resolver on this IP. Preserve TCP/UDP DNS ahead
    # of the metadata rejection, otherwise Caddy's ACME lookup can be blocked.
    for protocol in ("tcp", "udp"):
        dns = ["-d", "169.254.169.254/32", "-p", protocol, "--dport", "53", "-j", "RETURN"]
        check = subprocess.run(["iptables", "-w", "-C", "DOCKER-USER", *dns], capture_output=True)
        if check.returncode:
            common.run(["iptables", "-w", "-I", "DOCKER-USER", "1", *dns])


def literal(value):
    require("\0" not in value, "NUL in SQL value")
    return "'" + value.replace("'", "''") + "'"


def psql(config, sql):
    return compose(config, "exec", "-T", "--user", "postgres", "db", "psql", "--no-psqlrc", "--quiet",
                   "--tuples-only", "--no-align", "--set=ON_ERROR_STOP=1", "--dbname=postgres",
                   payload=("SET standard_conforming_strings=on;\n" + sql).encode()).decode().strip()


def bootstrap_database(config):
    name, role = config["db_name"], config["db_user"]
    row = psql(config, "SELECT row_to_json(r) FROM (SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=" + literal(role) + ") r;")
    if row:
        require(not any(json.loads(row).values()), "Existing application role has elevated privileges")
    else:
        value = (common.RUN / "database").read_text()
        psql(config, f'CREATE ROLE "{role}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD ' + literal(value) + ";")
    owner = psql(config, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=" + literal(name) + ";")
    require(owner in {"postgres", role}, "Database is owned by another role; stopping")
    psql(config, f'ALTER DATABASE "{name}" OWNER TO "{role}"; ALTER ROLE postgres PASSWORD NULL;')
    # Authenticate using the restricted app credential before any migration.
    check = "import django;django.setup();from django.db import connection; c=connection.cursor();c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user');assert not any(c.fetchone());print('restricted-role-ready')"
    require(b"restricted-role-ready" in compose(config, "run", "--rm", "--no-deps", "web", "python", "-c", check), "Application credential failed")


def image_metadata_check(config, data):
    published = config["published"]
    registry_digest = published["image"].split("@", 1)[1]
    labels = data["Config"].get("Labels", {})
    require(data.get("Os") == "linux" and data["Architecture"] == "amd64" and data["Config"]["User"] == "10001:10001", "Image platform/user differs")
    require(published["image"] in (data.get("RepoDigests") or []), "Pulled image is not bound to pinned registry digest")
    # Classic stores report a configuration ID; containerd reports the target
    # manifest/index ID. Both anchors were recorded during publication. Never
    # accept an unrelated ID or learn/overwrite an expected ID from the VM.
    require(data["Id"] in {published["image_id"], registry_digest}, "Pulled image ID differs from published image")
    descriptor = data.get("Descriptor")
    require(descriptor is None or (isinstance(descriptor, dict) and descriptor.get("digest") == registry_digest),
            "Pulled image descriptor differs from pinned registry digest")
    require(labels.get("org.opencontainers.image.source") == "https://github.com/vtsakan/accounting_platform", "Unexpected image source")
    require(labels.get("org.opencontainers.image.revision") == published["commit"] and labels.get("gr.accounting.source-context") == published["context_digest"], "Image revision/context differs")


def image_check(config):
    data = common.run(["docker", "image", "inspect", config["published"]["image"]], json_output=True)[0]
    image_metadata_check(config, data)
    return data


def running_image_check(config, audited_image, container):
    require(container["Config"]["Image"] == config["published"]["image"], "Running container image differs from release")
    require(container["Image"] in {config["published"]["image_id"], audited_image["Id"]}, "Running application image ID differs")


def environment_file(config):
    pairs = {"APP_IMAGE": config["published"]["image"], "SITE_DOMAIN": config["hostname"], "ACME_EMAIL": config["acme_email"],
             "DB_NAME": config["db_name"], "DB_USER": config["db_user"],
             "STATIC_DIRECTORY": str(common.HOST_DATA / "static" / config["published"]["commit"])}
    path = common.HOST_DATA / "release-config" / (common.deployment_commit(config) + ".env")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    require(all("\n" not in value and "\r" not in value for value in pairs.values()), "Multiline release configuration")
    path.write_text("".join(key + "=" + value + "\n" for key, value in pairs.items()))
    path.chmod(0o600)


def install(config, bundle, expected):
    events.checkpoint("vm-preflight")
    mounted(config)
    common.dns(config)
    require(common.run(["docker", "info", "--format", "{{.DockerRootDir}}" ]).decode().strip() == "/srv/accounting/docker", "Unexpected Docker data root")
    if common.HOST_CONFIG.exists():
        previous = load()
        for key in ("hostname", "db_name", "db_user"):
            require(previous[key] == config[key], "Existing preview identity differs")
        for key in ("project_id", "vm_name", "data_uuid", "service_account_id", "django_ref", "postgres_ref"):
            require(previous["gcp"][key] == config["gcp"][key], "Existing cloud/storage/credential identity differs")
        require(previous["gcp"]["secret_versions"] == config["gcp"]["secret_versions"], "Password/signing rotation is a separate explicit operation")
    events.checkpoint("source-extract")
    release = unpack(bundle, expected, common.deployment_commit(config))
    events.checkpoint("storage-layout")
    for relative in ("postgres17", "media", "caddy/data", "caddy/config", "static"):
        path = common.HOST_DATA / relative
        require(not path.is_symlink(), "Unexpected storage symlink")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    pg = common.HOST_DATA / "postgres17"
    require(not any(pg.iterdir()) or (pg / "PG_VERSION").is_file() and (pg / "PG_VERSION").read_text().strip() == "17", "Refusing incompatible or unknown PostgreSQL data")
    os.chown(common.HOST_DATA / "media", 10001, 10001)
    events.checkpoint("runtime-files")
    refresh(config)
    registry = config["published"]["image"].split("/", 1)[0]
    with tempfile.TemporaryDirectory(prefix="accounting-registry-", dir=common.RUN) as private:
        cli = ["docker", "--config", private]
        events.checkpoint("registry-login")
        common.run(cli + ["login", registry, "--username", "oauth2accesstoken", "--password-stdin"], payload=common.access_token().encode())
        events.checkpoint("application-pull")
        common.run(cli + ["pull", config["published"]["image"]])
    events.checkpoint("image-identity")
    image_check(config)
    pins = json.loads((release / "docker/preview-pins.json").read_text())
    for phase, ref in (("proxy-pull", pins["caddy"]["reference"]), ("postgres-pull", pins["postgresql"]["reference"])):
        events.checkpoint(phase)
        common.run(["docker", "pull", ref])
    events.checkpoint("static-export")
    static = common.HOST_DATA / "static" / config["published"]["commit"]
    if not static.exists():
        sys.path.insert(0, str(release / "tools"))
        import image
        image.export_static(config["published"]["image"], static)
    require((static / "staticfiles.json").is_file(), "Static export manifest missing")
    environment_file(config)
    events.checkpoint("compose-config")
    compose(config, "config", "--quiet")
    events.checkpoint("database-start")
    compose(config, "up", "--detach", "--wait", "--wait-timeout", "180", "db")
    events.checkpoint("database-role")
    bootstrap_database(config)
    # Migrations are an explicit release action here, never an entrypoint/boot action.
    events.checkpoint("database-migrate")
    compose(config, "run", "--rm", "--no-deps", "web", "python", "manage.py", "migrate", "--noinput")
    events.checkpoint("services-start")
    compose(config, "up", "--detach", "--wait", "--wait-timeout", "180")
    events.checkpoint("synthetic-markers")
    persistence(config, create=True)
    common.private_json(common.HOST_CONFIG, config)
    common.private_json(common.HOST_DATA / "preview-state.json", {"commit": "git:" + config["published"]["commit"], "initialised": True})
    events.checkpoint("boot-install")
    install_units(release)
    return {"status": "Started", "hostname": config["hostname"], "application_commit": "git:" + config["published"]["commit"],
            "deployment_commit": "git:" + common.deployment_commit(config), "public_verification": "Pending", "reboot_verification": "Pending"}


def install_units(release):
    parent = Path("/usr/local/lib")
    temporary = parent / ".accounting-new"
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(release / "tools", target_is_directory=True)
    os.replace(temporary, parent / "accounting")
    wrapper = Path("/usr/local/sbin/accounting-preview")
    wrapper.write_text('#!/bin/sh\nexec /usr/bin/python3 /usr/local/lib/accounting/preview_host.py "$@"\n')
    wrapper.chmod(0o755)
    drop = Path("/etc/systemd/system/docker.service.d/accounting-secrets.conf")
    drop.parent.mkdir(parents=True, exist_ok=True)
    drop.write_text('[Unit]\nWants=network-online.target\nAfter=network-online.target\n\n[Service]\nExecStartPre=/usr/local/sbin/accounting-preview secrets\n')
    unit = Path("/etc/systemd/system/accounting-preview.service")
    unit.write_text('[Unit]\nDescription=Accounting synthetic HTTPS preview\nRequires=docker.service\nAfter=docker.service\nRequiresMountsFor=/srv/accounting\n\n[Service]\nType=oneshot\nRemainAfterExit=yes\nExecStart=/usr/local/sbin/accounting-preview resume\nTimeoutStartSec=240\n\n[Install]\nWantedBy=multi-user.target\n')
    common.run(["systemctl", "daemon-reload"])
    common.run(["systemctl", "enable", "accounting-preview.service"])


def settings_check(config):
    code = "import django,json,os;django.setup();from django.conf import settings as s;print(json.dumps({'debug':s.DEBUG,'hosts':s.ALLOWED_HOSTS,'origins':s.CSRF_TRUSTED_ORIGINS,'secure_cookies':s.SESSION_COOKIE_SECURE and s.CSRF_COOKIE_SECURE,'proxy':s.SECURE_PROXY_SSL_HEADER,'media':str(s.MEDIA_ROOT),'uid':os.getuid()}))"
    return json.loads(compose(config, "exec", "-T", "web", "python", "-c", code))


def inspect(config):
    mounted(config)
    audited_image = image_check(config)
    pins = json.loads((release_path(config) / "docker/preview-pins.json").read_text())
    expected_images = {"web": config["published"]["image"], "db": pins["postgresql"]["reference"], "caddy": pins["caddy"]["reference"]}
    ports = {}
    running_web_id = None
    for service in ("db", "web", "caddy"):
        identifier = compose(config, "ps", "--quiet", service).decode().strip()
        require(identifier, "Expected service is missing")
        data = common.run(["docker", "inspect", identifier], json_output=True)[0]
        require(data["State"]["Running"], "Expected service is stopped")
        require(data["Config"]["Image"] == expected_images[service], "Running container image differs from release")
        if service == "web":
            running_image_check(config, audited_image, data)
            running_web_id = data["Image"]
        ports[service] = data["HostConfig"].get("PortBindings") or {}
        if service != "caddy":
            require(not ports[service], "Application/database has a published port")
        else:
            require(set(ports[service]) == {"80/tcp", "443/tcp"}, "Unexpected proxy ports")
    settings = settings_check(config)
    require(settings["debug"] is False and settings["hosts"] == [config["hostname"]], "Unexpected production settings")
    require(settings["origins"] == ["https://" + config["hostname"]] and settings["secure_cookies"] and settings["uid"] == 10001, "Insecure application settings")
    require(settings["proxy"] == ["HTTP_X_FORWARDED_PROTO", "https"] and settings["media"] == "/app/media", "Proxy/media settings differ")
    code = "import django,json;django.setup();from django.db import connection;c=connection.cursor();c.execute('SHOW server_version_num');v=int(c.fetchone()[0]);c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user');print(json.dumps({'version':v,'elevated':any(c.fetchone())}))"
    role = json.loads(compose(config, "exec", "-T", "web", "python", "-c", code))
    require(role["version"] == 170011 and role["elevated"] is False, "Unexpected PostgreSQL version/role")
    common.run(["iptables", "-w", "-C", "FORWARD", "-j", "DOCKER-USER"])
    common.run(["iptables", "-w", "-C", "DOCKER-USER", "-d", "169.254.169.254/32", "-j", "REJECT"])
    for protocol in ("tcp", "udp"):
        common.run(["iptables", "-w", "-C", "DOCKER-USER", "-d", "169.254.169.254/32", "-p", protocol, "--dport", "53", "-j", "RETURN"])
    compose(config, "exec", "-T", "caddy", "sh", "-c", "command -v wget >/dev/null")
    # A successful container metadata request must fail this check. Request the
    # non-secret email endpoint, never a token, for the connectivity probe.
    metadata_url = "http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/email"
    test = subprocess.run(common.compose_command(release_path(config)) + ["exec", "-T", "caddy", "wget", "-q", "-T", "3", "--header=Metadata-Flavor: Google", "-O", "/dev/null", metadata_url], env=common.compose_environment(), capture_output=True)
    require(test.returncode != 0, "Proxy container can access VM metadata")
    manifest = json.loads((common.HOST_DATA / "static" / config["published"]["commit"] / "staticfiles.json").read_text())
    name = manifest["paths"]["admin/css/base.css"]
    static = common.HOST_DATA / "static" / config["published"]["commit"] / name
    return {"status": "Passed", "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(), "ports": ports,
            "image_identity": {"published_build_id": config["published"]["image_id"], "daemon_image_id": audited_image["Id"],
                               "pinned_registry_image": config["published"]["image"], "running_image_id": running_web_id},
            "settings": settings, "database": role, "container_metadata_blocked": True, "static_path": "/static/" + name,
            "static_digest": common.file_sha(static), "persistence": persistence(config)}


PERSISTENCE_CODE = """import django,json,os;django.setup()
from decimal import Decimal
from accounting.models import Entity,CashAccount
from django.db import transaction
with transaction.atomic():
    if os.environ.get('S09_CREATE_MARKERS')=='1':
        Entity.objects.get_or_create(vat_number='000000000',defaults={'name':'ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S09','entity_type':Entity.EntityType.CUSTOMER})
        CashAccount.objects.get_or_create(name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S09',defaults={'opening_balance':Decimal('0.00')})
    e=Entity.objects.get(vat_number='000000000');a=CashAccount.objects.get(name='ΔΟΚΙΜΑΣΤΙΚΟ ΤΑΜΕΙΟ S09')
    assert e.name=='ΔΟΚΙΜΑΣΤΙΚΟΣ ΠΕΛΑΤΗΣ S09' and e.entity_type==Entity.EntityType.CUSTOMER and a.opening_balance==Decimal('0.00')
print(json.dumps({'entity':e.pk,'account':a.pk,'vat':e.vat_number,'opening':str(a.opening_balance)}))
"""


def persistence(config, create=False):
    return json.loads(compose(config, "exec", "-T", "--env", "S09_CREATE_MARKERS=" + ("1" if create else "0"), "web", "python", "-c", PERSISTENCE_CODE))


def probe_user(config, action):
    name = "s09_probe_" + config["published"]["commit"][:12]
    code = """import django,json,secrets,os;django.setup()
from django.contrib.auth import get_user_model
U=get_user_model();name=os.environ['S09_PROBE_NAME'];action=os.environ['S09_PROBE_ACTION']
u=U.objects.filter(username=name).first()
assert u is None or (u.first_name=='ΔΟΚΙΜΗ S09' and not u.is_staff and not u.is_superuser)
if action=='delete':
    if u:u.delete()
    print('{}')
else:
    p=secrets.token_urlsafe(32)
    if u is None:u=U(username=name,first_name='ΔΟΚΙΜΗ S09')
    u.set_password(p);u.is_active=True;u.save()
    print(json.dumps({'username':name,'password':p}))
"""
    return compose(config, "exec", "-T", "--env", "S09_PROBE_NAME=" + name, "--env", "S09_PROBE_ACTION=" + action,
                   "web", "python", "-c", code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "secrets", "resume", "inspect", "probe-create", "probe-delete", "admin"))
    parser.add_argument("--config", type=Path, default=common.HOST_CONFIG)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--bundle-hash")
    args = parser.parse_args()
    try:
        require(os.geteuid() == 0, "Run this host operation with sudo")
        config = common.validate(json.loads(args.config.read_text()), published=True)
        os.environ.pop("DOCKER_HOST", None)
        os.environ.pop("DOCKER_CONTEXT", None)
        if args.action == "install":
            with open("/run/accounting-preview.lock", "a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = install(config, args.bundle, args.bundle_hash)
        elif args.action == "secrets":
            events.checkpoint("runtime-files")
            refresh(config)
            result = {"status": "Loaded pinned runtime secrets"}
        elif args.action == "resume":
            events.checkpoint("resume")
            mounted(config)
            require((common.HOST_DATA / "postgres17/PG_VERSION").read_text().strip() == "17", "PostgreSQL data missing")
            compose(config, "up", "--detach", "--wait", "--wait-timeout", "180", "--pull", "never")
            result = {"status": "Resumed without migrations"}
        elif args.action == "inspect":
            events.checkpoint("inspection")
            result = inspect(config)
        elif args.action in {"probe-create", "probe-delete"}:
            sys.stdout.buffer.write(probe_user(config, "create" if args.action == "probe-create" else "delete"))
            return
        else:
            mounted(config)
            subprocess.run(common.compose_command(release_path(config)) + ["exec", "web", "python", "manage.py", "createsuperuser"],
                           env=common.compose_environment(), check=True)
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as error:
        events.failure(error)
        parser.exit(1, f"S09 host operation stopped ({type(error).__name__}); no credentials printed.\n")


if __name__ == "__main__":
    main()
