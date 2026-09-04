#!/usr/bin/env bash
set -euo pipefail

BACKUP_ENV=/etc/rack-pi/backup.env
if [[ ! -r ${BACKUP_ENV} ]]; then
  echo "Missing ${BACKUP_ENV}." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${BACKUP_ENV}"
set +a
: "${BACKUP_MOUNTPOINT:?BACKUP_MOUNTPOINT is required}"

if [[ ${BACKUP_MOUNTPOINT} != /* || ${BACKUP_MOUNTPOINT} == / ]]; then
  echo "BACKUP_MOUNTPOINT must be a non-root absolute path." >&2
  exit 1
fi

marker=${BACKUP_MOUNTPOINT}/.rack-pi-restic

# Looking up the mountpoint itself can stop at the autofs layer without
# activating the underlying ext4 filesystem. Access a child path instead; the
# lookup triggers x-systemd.automount even when the marker does not yet exist.
timeout 30s stat -- "${marker}" >/dev/null 2>&1 || true
record=$(findmnt -rn --mountpoint "${BACKUP_MOUNTPOINT}" \
  --output TARGET,FSTYPE,SOURCE 2>/dev/null |
  awk '$2 != "autofs" { print; exit }' || true)
read -r target filesystem source <<<"${record}"
if [[ ${target:-} != "${BACKUP_MOUNTPOINT}" ]]; then
  mount_unit=$(systemd-escape --path --suffix=mount "${BACKUP_MOUNTPOINT}")
  timeout 30s systemctl start "${mount_unit}" >/dev/null 2>&1 || true
  timeout 30s stat -- "${marker}" >/dev/null 2>&1 || true
  record=$(findmnt -rn --mountpoint "${BACKUP_MOUNTPOINT}" \
    --output TARGET,FSTYPE,SOURCE 2>/dev/null |
    awk '$2 != "autofs" { print; exit }' || true)
  read -r target filesystem source <<<"${record}"
fi
if [[ ${target:-} != "${BACKUP_MOUNTPOINT}" ]]; then
  echo "Backup disk is not mounted at ${BACKUP_MOUNTPOINT}." >&2
  exit 1
fi
if [[ ${filesystem:-} != ext4 ]]; then
  echo "Backup disk must use ext4; detected ${filesystem:-unknown}." >&2
  exit 1
fi

# Device names can change after USB reconnects. Accept only the filesystem
# identified by the UUID in fstab, at its configured permanent mountpoint.
fstab_source=$(findmnt --fstab --target "${BACKUP_MOUNTPOINT}" -n -o SOURCE)
mounted_uuid=$(findmnt -rn --mountpoint "${BACKUP_MOUNTPOINT}" -o UUID)
if [[ ${fstab_source} != UUID=* || -z ${mounted_uuid} ||
      ${fstab_source#UUID=} != "${mounted_uuid}" ]]; then
  echo "Backup mount must match its UUID= entry in /etc/fstab." >&2
  exit 1
fi
mount_options=$(findmnt -rn --mountpoint "${BACKUP_MOUNTPOINT}" -o OPTIONS)
case ",${mount_options}," in
  *,ro,*|*,shutdown,*)
    echo "Backup filesystem is read-only or shut down; refusing backup." >&2
    exit 1
    ;;
esac

if [[ ${1:-} == --initialize-marker ]]; then
  touch "${marker}"
  chmod 0600 "${marker}"
elif [[ ! -f ${marker} ]]; then
  echo "Mounted disk lacks the identity marker ${marker}." >&2
  exit 1
fi

echo "Verified backup disk: ${source} on ${BACKUP_MOUNTPOINT} (${filesystem})."
