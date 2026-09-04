#!/usr/bin/env bash
set -euo pipefail

BACKUP_ENV=/etc/raspberry-server/backup.env
if [[ ! -r ${BACKUP_ENV} ]]; then
  echo "Missing ${BACKUP_ENV}; see docs/backup-and-restore.md." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${BACKUP_ENV}"
set +a

: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required in ${BACKUP_ENV}}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required in ${BACKUP_ENV}}"

# Verify the actual encrypted repository before any application is stopped.
# A listening HTTP server can still return 500 for a disconnected bind mount.
check_repository() {
  if ! timeout --foreground --kill-after=5s 30s \
      restic --no-cache --no-lock cat config >/dev/null 2>&1; then
    echo "Restic repository is not readable; applications will remain online." >&2
    return 1
  fi
}

# Remote repositories do not have a host mount to validate.
if [[ -z ${RESTIC_MOUNTPOINT:-} ]]; then
  check_repository
  exit 0
fi

if [[ ${RESTIC_MOUNTPOINT} != /* || ${RESTIC_MOUNTPOINT} == "/" ]]; then
  echo "RESTIC_MOUNTPOINT must be a non-root absolute path." >&2
  exit 1
fi
if [[ ${RESTIC_REPOSITORY} != "${RESTIC_MOUNTPOINT}"/* ]]; then
  echo "RESTIC_REPOSITORY must be inside RESTIC_MOUNTPOINT." >&2
  exit 1
fi

marker=${RESTIC_MOUNTPOINT}/.piserver-restic-backup
repository_config=${RESTIC_REPOSITORY}/config

# Access below the mountpoint activates x-systemd.automount. If the automount
# is unavailable or stale, retry the matching /etc/fstab entry explicitly.
timeout 30s stat -- "${marker}" "${repository_config}" >/dev/null 2>&1 || true
mount_record=$(
  findmnt -rn --mountpoint "${RESTIC_MOUNTPOINT}" \
    --output TARGET,FSTYPE 2>/dev/null |
    awk '$2 != "autofs" { print; exit }' || true
)
read -r mounted_target filesystem <<<"${mount_record}"
if [[ ${mounted_target:-} != "${RESTIC_MOUNTPOINT}" ]]; then
  timeout 30s mount "${RESTIC_MOUNTPOINT}" >/dev/null 2>&1 || true
  mount_record=$(
    findmnt -rn --mountpoint "${RESTIC_MOUNTPOINT}" \
      --output TARGET,FSTYPE 2>/dev/null |
      awk '$2 != "autofs" { print; exit }' || true
  )
  read -r mounted_target filesystem <<<"${mount_record}"
fi

if [[ ${mounted_target:-} != "${RESTIC_MOUNTPOINT}" ]]; then
  echo "Restic disk is not mounted at ${RESTIC_MOUNTPOINT}." >&2
  exit 1
fi

# The marker identifies a prepared backup disk. The existing Restic config is
# accepted during migration so the first run can add the marker safely.
if ! timeout 30s stat -- "${marker}" >/dev/null 2>&1 &&
   ! timeout 30s stat -- "${repository_config}" >/dev/null 2>&1; then
  echo "The mounted disk is not the configured Restic repository." >&2
  exit 1
fi

check_repository
echo "Verified Restic target on ${RESTIC_MOUNTPOINT}."
