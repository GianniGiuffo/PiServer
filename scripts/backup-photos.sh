#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "The photo backup must run through systemd or sudo." >&2
  exit 1
fi

BACKUP_ENV=/etc/raspberry-server/photos-backup.env
if [[ ! -r ${BACKUP_ENV} ]]; then
  echo "Photo backup is not configured; skipping."
  exit 0
fi

set -a
# shellcheck disable=SC1090
source "${BACKUP_ENV}"
set +a
umask 077

case "${PHOTO_BACKUP_ENABLED:-false}" in
  false)
    echo "Photo backup is disabled; skipping."
    exit 0
    ;;
  true) ;;
  *)
    echo "PHOTO_BACKUP_ENABLED must be true or false." >&2
    exit 1
    ;;
esac

: "${PHOTO_SOURCE:?PHOTO_SOURCE is required}"
: "${PHOTO_MEDIA_MOUNTPOINT:?PHOTO_MEDIA_MOUNTPOINT is required}"
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required}"

if [[ ${PHOTO_SOURCE} != /* || ${PHOTO_MEDIA_MOUNTPOINT} != /* ||
      ${PHOTO_MEDIA_MOUNTPOINT} == / ]]; then
  echo "Photo paths must be absolute and the media mount cannot be /." >&2
  exit 1
fi

mount_record=$(findmnt -rn --mountpoint "${PHOTO_MEDIA_MOUNTPOINT}" \
  --output TARGET,FSTYPE 2>/dev/null || true)
read -r mounted_target filesystem <<<"${mount_record}"
if [[ ${mounted_target:-} != "${PHOTO_MEDIA_MOUNTPOINT}" ||
      ${filesystem:-} == autofs ]]; then
  echo "Photo media is not mounted at ${PHOTO_MEDIA_MOUNTPOINT}." >&2
  exit 1
fi

marker=${PHOTO_MEDIA_MOUNTPOINT}/${PHOTO_MEDIA_MARKER:-.piserver-media}
if [[ ! -f ${marker} ]]; then
  echo "Missing media identity marker: ${marker}" >&2
  exit 1
fi
if [[ ! -d ${PHOTO_SOURCE} ]]; then
  echo "Photo source does not exist: ${PHOTO_SOURCE}" >&2
  exit 1
fi

resolved_mount=$(readlink -f -- "${PHOTO_MEDIA_MOUNTPOINT}")
resolved_source=$(readlink -f -- "${PHOTO_SOURCE}")
if [[ ${resolved_source} != "${resolved_mount}"/* ]]; then
  echo "PHOTO_SOURCE must resolve inside PHOTO_MEDIA_MOUNTPOINT." >&2
  exit 1
fi

exec 9>/run/lock/raspberry-server-photo-backup.lock
if ! flock -n 9; then
  echo "Another photo backup is already running." >&2
  exit 75
fi

XDG_CACHE_HOME=${XDG_CACHE_HOME:-/var/cache/raspberry-server/photos}
install -d -m 0700 -o root -g root "${XDG_CACHE_HOME}"
export XDG_CACHE_HOME

timeout_value=${RESTIC_OPERATION_TIMEOUT:-5h}
tag=${RESTIC_BACKUP_TAG:-photos}

# Immich remains online. Its asset files are backed up after the state backup
# has produced the database dump; existing assets are not modified by Restic.
timeout --foreground --kill-after=5m "${timeout_value}" \
  restic backup --tag "${tag}" --one-file-system "${PHOTO_SOURCE}" "${marker}"

echo "Live photo snapshot completed without stopping Immich."
