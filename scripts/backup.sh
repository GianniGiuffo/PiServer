#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "The backup reads root-owned state; run it through the systemd service or sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
BACKUP_ENV=/etc/raspberry-server/backup.env

if [[ ! -r ${BACKUP_ENV} ]]; then
  echo "Missing ${BACKUP_ENV}; see docs/backup-and-restore.md." >&2
  exit 1
fi

set -a
source "${REPO_DIR}/.env"
source "${BACKUP_ENV}"
set +a
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required in ${BACKUP_ENV}}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required in ${BACKUP_ENV}}"

# A local USB backup must never silently fall back to the Pi's root filesystem
# when the disk is absent. Remote repositories (S3/SFTP) leave this unset.
if [[ -n ${RESTIC_MOUNTPOINT:-} ]] && ! mountpoint -q "${RESTIC_MOUNTPOINT}"; then
  echo "Restic backup disk is not mounted at ${RESTIC_MOUNTPOINT}; refusing to continue." >&2
  exit 1
fi

mkdir -p "${STAGING_DIR}"
COMPOSE=(docker compose --project-directory "${REPO_DIR}" -f "${REPO_DIR}/compose.yaml")
NEXTCLOUD_MAINTENANCE=false
VAULTWARDEN_STOPPED=false

cleanup() {
  if [[ ${VAULTWARDEN_STOPPED} == true ]]; then
    "${COMPOSE[@]}" start vaultwarden || true
  fi
  if [[ ${NEXTCLOUD_MAINTENANCE} == true ]]; then
    "${COMPOSE[@]}" exec -T --user www-data nextcloud php occ maintenance:mode --off || true
  fi
}
trap cleanup EXIT

# A database dump plus maintenance mode gives a coherent Nextcloud restore point.
"${COMPOSE[@]}" exec -T --user www-data nextcloud php occ maintenance:mode --on
NEXTCLOUD_MAINTENANCE=true
"${COMPOSE[@]}" exec -T postgres pg_dump -U nextcloud nextcloud > "${STAGING_DIR}/nextcloud.sql"

# Vaultwarden uses a local data directory by default. Briefly stop it so the
# SQLite database and any WAL files are captured consistently.
"${COMPOSE[@]}" stop vaultwarden
VAULTWARDEN_STOPPED=true

# PostgreSQL is deliberately excluded: its files are not safe to copy while the
# server is running. The consistent SQL dump above is the recovery source for
# Nextcloud's database. Redis is a cache and needs no backup. Nextcloud's data
# directory is intentionally omitted: it holds the user's photos and videos on
# a separate disk and needs its own backup policy.
BACKUP_PATHS=(
  "${REPO_DIR}/.env"
  "${DATA_DIR}/pihole"
  "${DATA_DIR}/vaultwarden"
  "${DATA_DIR}/caddy"
  "${STAGING_DIR}"
)
for nextcloud_path in \
  "${DATA_DIR}/nextcloud/html/config" \
  "${DATA_DIR}/nextcloud/html/custom_apps" \
  "${DATA_DIR}/nextcloud/html/themes"; do
  [[ -e ${nextcloud_path} ]] && BACKUP_PATHS+=("${nextcloud_path}")
done

restic backup --tag raspberry-server "${BACKUP_PATHS[@]}"
restic forget --prune --tag raspberry-server \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 12

rm -f "${STAGING_DIR}/nextcloud.sql"
echo "Encrypted backup completed."
