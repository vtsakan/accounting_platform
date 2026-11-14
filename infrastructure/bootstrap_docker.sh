#!/bin/bash
# Fresh-host installation or read-only validation of the existing selected layout.
set -euo pipefail
ACCOUNTING_HOST=${1:?Usage: bootstrap_docker.sh VM_NAME DATA_UUID}
ACCOUNTING_UUID=${2:?Missing mounted data filesystem UUID}
[[ "$ACCOUNTING_HOST" =~ ^[a-z][a-z0-9-]+$ ]]
[[ "$ACCOUNTING_UUID" =~ ^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$ ]]
test "$(id -u)" -eq 0
test "$(hostname -s)" = "$ACCOUNTING_HOST"
test "$(findmnt -rn -M /srv/accounting -o UUID)" = "$ACCOUNTING_UUID"
. /etc/os-release
test "$ID" = ubuntu
test "${UBUNTU_CODENAME:-$VERSION_CODENAME}" = resolute
test "$(dpkg --print-architecture)" = amd64
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH

accounting_check() {
  test "$(docker info --format '{{.DockerRootDir}}')" = /srv/accounting/docker
  containerd config dump | python3 -c \
    'import sys,tomllib; c=tomllib.loads(sys.stdin.read()); assert c["root"]=="/srv/accounting/containerd"'
  /usr/local/sbin/accounting-data-ready
  for ACCOUNTING_SERVICE in docker containerd; do
    systemctl is-active --quiet "$ACCOUNTING_SERVICE"
    systemctl cat "$ACCOUNTING_SERVICE" | grep -Fx 'RequiresMountsFor=/srv/accounting' >/dev/null
    systemctl cat "$ACCOUNTING_SERVICE" | grep -Fx 'ExecStartPre=/usr/local/sbin/accounting-data-ready' >/dev/null
  done
}

if command -v docker >/dev/null 2>&1; then
  # Never migrate or replace an existing engine's data/configuration automatically.
  accounting_check
  echo 'Existing Docker/containerd storage and mount guards verified; no changes.'
  exit 0
fi
if command -v containerd >/dev/null 2>&1; then
  echo 'An existing containerd installation needs inspection before Docker installation.'
  exit 1
fi
test ! -e /etc/docker/daemon.json
test ! -e /etc/containerd/config.toml
test ! -e /etc/systemd/system/docker.service
test ! -e /etc/systemd/system/containerd.service

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl python3
install -d -m 0755 /etc/apt/keyrings
curl -fsSL --retry 3 https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<REPO
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: resolute
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
REPO

# Block package post-install startup until storage and dependencies are configured.
systemctl mask docker.service docker.socket containerd.service
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

install -d -m 0711 /srv/accounting/docker /srv/accounting/containerd
install -d -m 0755 /etc/docker /etc/containerd
cat > /etc/docker/daemon.json <<'JSON'
{
  "data-root": "/srv/accounting/docker",
  "log-driver": "local",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
JSON

python3 - <<'PY'
from pathlib import Path
import re
import shutil
import tomllib

p = Path('/etc/containerd/config.toml')
original = p.read_text() if p.exists() else ''
if p.exists():
    shutil.copy2(p, str(p) + '.before-accounting')
lines = original.splitlines(keepends=True)
boundary = next((i for i, line in enumerate(lines) if line.lstrip().startswith('[')), len(lines))
header = [line for line in lines[:boundary] if not re.match(r'^\s*root\s*=', line)]
updated = 'root = "/srv/accounting/containerd"\n' + ''.join(header + lines[boundary:])
assert tomllib.loads(updated)['root'] == '/srv/accounting/containerd'
p.write_text(updated)
PY
ACCOUNTING_MIGRATED=$(mktemp /etc/containerd/config.toml.migrated.XXXXXX)
trap 'rm -f "$ACCOUNTING_MIGRATED"' EXIT
containerd config migrate > "$ACCOUNTING_MIGRATED"
python3 - "$ACCOUNTING_MIGRATED" <<'PY'
from pathlib import Path
import sys, tomllib
assert tomllib.loads(Path(sys.argv[1]).read_text())['root'] == '/srv/accounting/containerd'
PY
install -m 0644 "$ACCOUNTING_MIGRATED" /etc/containerd/config.toml

cat > /usr/local/sbin/accounting-data-ready <<GUARD
#!/bin/sh
set -eu
test "\$(findmnt -rn -M /srv/accounting -o UUID)" = "$ACCOUNTING_UUID"
GUARD
chmod 0755 /usr/local/sbin/accounting-data-ready
for ACCOUNTING_SERVICE in docker containerd; do
  install -d -m 0755 "/etc/systemd/system/${ACCOUNTING_SERVICE}.service.d"
  cat > "/etc/systemd/system/${ACCOUNTING_SERVICE}.service.d/accounting-data.conf" <<'UNIT'
[Unit]
RequiresMountsFor=/srv/accounting

[Service]
ExecStartPre=/usr/local/sbin/accounting-data-ready
UNIT
done
dockerd --validate --config-file=/etc/docker/daemon.json
systemctl unmask docker.service docker.socket containerd.service
systemctl daemon-reload
systemctl enable --now containerd.service docker.service
accounting_check
docker version
docker compose version
