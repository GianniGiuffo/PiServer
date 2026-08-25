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

# Access activates x-systemd.automount; an explicit retry covers a stale unit.
timeout 30s stat -- "${BACKUP_MOUNTPOINT}" >/dev/null 2>&1 || true
record=$(findmnt -rn --mountpoint "${BACKUP_MOUNTPOINT}" \
  --output TARGET,FSTYPE,SOURCE 2>/dev/null || true)
read -r target filesystem source <<<"${record}"
if [[ ${target:-} != "${BACKUP_MOUNTPOINT}" || ${filesystem:-} == autofs ]]; then
  timeout 30s mount "${BACKUP_MOUNTPOINT}" >/dev/null 2>&1 || true
  record=$(findmnt -rn --mountpoint "${BACKUP_MOUNTPOINT}" \
    --output TARGET,FSTYPE,SOURCE 2>/dev/null || true)
  read -r target filesystem source <<<"${record}"
fi
if [[ ${target:-} != "${BACKUP_MOUNTPOINT}" || ${filesystem:-} == autofs ]]; then
  echo "Backup disk is not mounted at ${BACKUP_MOUNTPOINT}." >&2
  exit 1
fi
if [[ ${filesystem:-} != ext4 ]]; then
  echo "Backup disk must use ext4; detected ${filesystem:-unknown}." >&2
  exit 1
fi

marker=${BACKUP_MOUNTPOINT}/.rack-pi-restic
if [[ ${1:-} == --initialize-marker ]]; then
  touch "${marker}"
  chmod 0600 "${marker}"
elif [[ ! -f ${marker} ]]; then
  echo "Mounted disk lacks the identity marker ${marker}." >&2
  exit 1
fi

echo "Verified backup disk: ${source} on ${BACKUP_MOUNTPOINT} (${filesystem})."
