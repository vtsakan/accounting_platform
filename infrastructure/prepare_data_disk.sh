#!/bin/bash
# Run as root on the explicitly selected VM. Existing filesystems are never formatted.
set -euo pipefail

ACCOUNTING_HOST=${1:?Usage: prepare_data_disk.sh VM_NAME DISK_NAME SIZE_GB [--format-blank]}
ACCOUNTING_DISK=${2:?Missing disk name}
ACCOUNTING_SIZE=${3:?Missing disk size in GiB}
ACCOUNTING_FORMAT=${4:-}
[[ "$ACCOUNTING_HOST" =~ ^[a-z][a-z0-9-]+$ && "$ACCOUNTING_DISK" =~ ^[a-z][a-z0-9-]+$ ]]
[[ "$ACCOUNTING_SIZE" =~ ^[1-9][0-9]*$ ]]
[[ -z "$ACCOUNTING_FORMAT" || "$ACCOUNTING_FORMAT" = --format-blank ]]
test "$(id -u)" -eq 0
test "$(hostname -s)" = "$ACCOUNTING_HOST"
ACCOUNTING_DEVICE="/dev/disk/by-id/google-${ACCOUNTING_DISK}"
ACCOUNTING_MOUNT=/srv/accounting
test -b "$ACCOUNTING_DEVICE"
test "$(blockdev --getsize64 "$ACCOUNTING_DEVICE")" -eq "$((ACCOUNTING_SIZE * 1024 * 1024 * 1024))"
test "$(lsblk -dn -o TYPE "$ACCOUNTING_DEVICE")" = disk
python3 - "$ACCOUNTING_DEVICE" <<'PY'
import os
from pathlib import Path
import sys

root, selected = os.stat('/').st_dev, os.stat(sys.argv[1]).st_rdev
def sysfs(device):
    return Path(f'/sys/dev/block/{os.major(device)}:{os.minor(device)}').resolve()
if sysfs(root).is_relative_to(sysfs(selected)):
    raise SystemExit('Selected disk contains the root filesystem; stopping.')
PY

ACCOUNTING_TYPE=$(blkid -s TYPE -o value "$ACCOUNTING_DEVICE" || true)
if [ -z "$ACCOUNTING_TYPE" ]; then
  test "$ACCOUNTING_FORMAT" = --format-blank || {
    echo "Blank disk: formatting requires the explicit --format-blank option."
    exit 1
  }
  test -z "$(wipefs --no-act --noheadings --output TYPE "$ACCOUNTING_DEVICE")"
  if findmnt --fstab --mountpoint "$ACCOUNTING_MOUNT" >/dev/null; then
    echo 'Existing fstab entry conflicts with the blank selected disk; stopping.'
    exit 1
  fi
  if [ -d "$ACCOUNTING_MOUNT" ] && [ -n "$(find "$ACCOUNTING_MOUNT" -mindepth 1 -maxdepth 1 -print -quit)" ]; then
    echo 'Mount destination already contains files; stopping before formatting.'
    exit 1
  fi
  test "$(lsblk -nr -o TYPE "$ACCOUNTING_DEVICE" | wc -l)" -eq 1
  test -z "$(lsblk -nr -o MOUNTPOINTS "$ACCOUNTING_DEVICE" | tr -d '[:space:]')"
  mkfs.ext4 -m 0 -L accounting-data \
    -E lazy_itable_init=0,lazy_journal_init=0,discard "$ACCOUNTING_DEVICE"
else
  test "$ACCOUNTING_TYPE" = ext4
fi

ACCOUNTING_UUID=$(blkid -s UUID -o value "$ACCOUNTING_DEVICE")
test -n "$ACCOUNTING_UUID"
if findmnt -rn -M "$ACCOUNTING_MOUNT" >/dev/null; then
  test "$(findmnt -rn -M "$ACCOUNTING_MOUNT" -o UUID)" = "$ACCOUNTING_UUID"
fi

export ACCOUNTING_UUID ACCOUNTING_MOUNT
python3 - <<'PY'
import os
from pathlib import Path
import shutil

target, uuid = os.environ['ACCOUNTING_MOUNT'], os.environ['ACCOUNTING_UUID']
fstab = Path('/etc/fstab')
entries = [line.split() for line in fstab.read_text().splitlines()
           if line.strip() and not line.lstrip().startswith('#')]
matches = [row for row in entries if len(row) > 1 and row[1] == target]
if matches:
    if len(matches) != 1 or matches[0][0] != 'UUID=' + uuid or matches[0][2] != 'ext4':
        raise SystemExit('Conflicting fstab mount; stopping.')
else:
    mount = Path(target)
    if mount.exists() and any(mount.iterdir()):
        raise SystemExit('Refusing to hide existing files beneath a new mount.')
    mount.mkdir(parents=True, exist_ok=True)
    backup = fstab.with_name('fstab.before-accounting-data')
    if not backup.exists():
        shutil.copy2(fstab, backup)
    with fstab.open('a') as stream:
        stream.write(f'\nUUID={uuid} {target} ext4 defaults,discard,nofail 0 2\n')
PY
systemctl daemon-reload
mountpoint -q "$ACCOUNTING_MOUNT" || mount "$ACCOUNTING_MOUNT"
test "$(findmnt -rn -M "$ACCOUNTING_MOUNT" -o UUID)" = "$ACCOUNTING_UUID"
findmnt --mountpoint "$ACCOUNTING_MOUNT" -o TARGET,SOURCE,FSTYPE,UUID
