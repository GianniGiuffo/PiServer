#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "The backup reads root-owned state; run it through systemd or sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
BACKUP_ENV=/etc/raspberry-server/backup.env
STACK_ENV=${REPO_DIR}/.env
# shellcheck source=scripts/read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

if [[ ! -r ${BACKUP_ENV} ]]; then
  echo "Missing ${BACKUP_ENV}; see docs/backup-and-restore.md." >&2
  exit 1
fi
if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}." >&2
  exit 1
fi

set -a
# This administrator-owned file may contain S3/SFTP credentials for Restic.
# shellcheck disable=SC1090
source "${BACKUP_ENV}"
set +a
umask 077

DATA_DIR=$(read_stack_value "${STACK_ENV}" DATA_DIR)
STAGING_DIR=$(read_stack_value "${STACK_ENV}" STAGING_DIR)
: "${RESTIC_REPOSITORY:?RESTIC_REPOSITORY is required in ${BACKUP_ENV}}"
: "${RESTIC_PASSWORD_FILE:?RESTIC_PASSWORD_FILE is required in ${BACKUP_ENV}}"

if [[ -n ${RESTIC_MOUNTPOINT:-} ]] && ! mountpoint -q "${RESTIC_MOUNTPOINT}"; then
  echo "Restic disk is not mounted at ${RESTIC_MOUNTPOINT}; refusing to continue." >&2
  exit 1
fi

mkdir -p "${STAGING_DIR}"
rm -f \
  "${STAGING_DIR}/nextcloud.sql" \
  "${STAGING_DIR}/immich.sql" \
  "${STAGING_DIR}/n8n.sql"
BASE=(docker compose --project-directory "${REPO_DIR}" -f "${REPO_DIR}/compose.yaml")
MEDIA=("${BASE[@]}" -f "${REPO_DIR}/compose.media.yaml")
AUTOMATION=("${BASE[@]}" -f "${REPO_DIR}/compose.automation.yaml")

is_running() {
  local array_name=${1:?compose array is required}
  local service=${2:?service is required}
  local -n compose_ref=${array_name}
  "${compose_ref[@]}" ps --services --status running | grep -qx "${service}"
}

NEXTCLOUD_MAINTENANCE=false
N8N_STOPPED=false
IMMICH_STOPPED=false
JELLYFIN_STOPPED=false
STREAMINGCOMMUNITY_STOPPED=false
AURRAL_STOPPED=false
NAVIDROME_STOPPED=false
LIDARR_STOPPED=false
SLSKD_STOPPED=false
UPTIME_STOPPED=false
VAULTWARDEN_STOPPED=false
PIHOLE_STOPPED=false
BACKUP_COMPLETED=false
BACKUP_STARTED_EPOCH=$(date +%s)

cleanup() {
  local exit_status=$?
  local media_can_restart=true
  if [[ ${NEXTCLOUD_MAINTENANCE} == true ||
        ${IMMICH_STOPPED} == true ||
        ${JELLYFIN_STOPPED} == true ||
        ${STREAMINGCOMMUNITY_STOPPED} == true ||
        ${AURRAL_STOPPED} == true ||
        ${NAVIDROME_STOPPED} == true ||
        ${LIDARR_STOPPED} == true ||
        ${SLSKD_STOPPED} == true ]]; then
    if ! bash "${SCRIPT_DIR}/check-media-mount.sh"; then
      echo "WARNING: media mount failed validation; media services remain stopped." >&2
      media_can_restart=false
    fi
  fi
  if [[ ${PIHOLE_STOPPED} == true ]]; then
    "${BASE[@]}" start pihole || true
  fi
  if [[ ${VAULTWARDEN_STOPPED} == true ]]; then
    "${BASE[@]}" start vaultwarden || true
  fi
  if [[ ${UPTIME_STOPPED} == true ]]; then
    "${BASE[@]}" start uptime-kuma || true
  fi
  if [[ ${JELLYFIN_STOPPED} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" start jellyfin || true
  fi
  if [[ ${STREAMINGCOMMUNITY_STOPPED} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" start streamingcommunity || true
  fi
  if [[ ${IMMICH_STOPPED} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" start immich-server || true
  fi
  if [[ ${SLSKD_STOPPED} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" start slskd || true
  fi
  if [[ ${LIDARR_STOPPED} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" start lidarr || true
  fi
  if [[ ${NAVIDROME_STOPPED} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" start navidrome || true
  fi
  if [[ ${AURRAL_STOPPED} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" start aurral || true
  fi
  if [[ ${N8N_STOPPED} == true ]]; then
    "${AUTOMATION[@]}" start n8n || true
  fi
  if [[ ${NEXTCLOUD_MAINTENANCE} == true && ${media_can_restart} == true ]]; then
    "${MEDIA[@]}" exec -T --user www-data nextcloud \
      php occ maintenance:mode --off || true
  fi
  local duration
  duration=$(( $(date +%s) - BACKUP_STARTED_EPOCH ))
  if [[ ${BACKUP_COMPLETED} == true && ${exit_status} -eq 0 ]]; then
    bash "${SCRIPT_DIR}/refresh-backup-status.sh" success "${duration}" ||
      echo "WARNING: failed to update Homepage backup status." >&2
  else
    bash "${SCRIPT_DIR}/refresh-backup-status.sh" failure "${duration}" ||
      echo "WARNING: failed to update Homepage backup status." >&2
  fi
}
trap cleanup EXIT

# SQL databases are dumped after their application writer is quiesced. Raw
# PostgreSQL directories are never copied while running.
if is_running AUTOMATION n8n; then
  "${AUTOMATION[@]}" stop n8n
  N8N_STOPPED=true
fi
if is_running AUTOMATION n8n-postgres; then
  "${AUTOMATION[@]}" exec -T n8n-postgres pg_dump -U n8n n8n \
    > "${STAGING_DIR}/n8n.sql"
else
  echo "WARNING: n8n-postgres is not running; this snapshot has no new n8n dump." >&2
fi

if is_running MEDIA nextcloud; then
  "${MEDIA[@]}" exec -T --user www-data nextcloud \
    php occ maintenance:mode --on
  NEXTCLOUD_MAINTENANCE=true
fi
if is_running MEDIA nextcloud-postgres; then
  "${MEDIA[@]}" exec -T nextcloud-postgres \
    pg_dump -U nextcloud nextcloud > "${STAGING_DIR}/nextcloud.sql"
else
  echo "WARNING: nextcloud-postgres is not running; this snapshot has no new Nextcloud dump." >&2
fi

if is_running MEDIA immich-server; then
  "${MEDIA[@]}" stop immich-server
  IMMICH_STOPPED=true
fi
if is_running MEDIA immich-postgres; then
  "${MEDIA[@]}" exec -T immich-postgres \
    pg_dump -U immich immich > "${STAGING_DIR}/immich.sql"
else
  echo "WARNING: immich-postgres is not running; this snapshot has no new Immich dump." >&2
fi

# SQLite-backed services are stopped briefly so their database and WAL files
# belong to the same point in time.
if is_running MEDIA aurral; then
  "${MEDIA[@]}" stop aurral
  AURRAL_STOPPED=true
fi
if is_running MEDIA navidrome; then
  "${MEDIA[@]}" stop navidrome
  NAVIDROME_STOPPED=true
fi
if is_running MEDIA lidarr; then
  "${MEDIA[@]}" stop lidarr
  LIDARR_STOPPED=true
fi
if is_running MEDIA slskd; then
  "${MEDIA[@]}" stop slskd
  SLSKD_STOPPED=true
fi
if is_running MEDIA streamingcommunity; then
  "${MEDIA[@]}" stop streamingcommunity
  STREAMINGCOMMUNITY_STOPPED=true
fi
if is_running MEDIA jellyfin; then
  "${MEDIA[@]}" stop jellyfin
  JELLYFIN_STOPPED=true
fi
if is_running BASE uptime-kuma; then
  "${BASE[@]}" stop uptime-kuma
  UPTIME_STOPPED=true
fi
if is_running BASE vaultwarden; then
  "${BASE[@]}" stop vaultwarden
  VAULTWARDEN_STOPPED=true
fi
if is_running BASE pihole; then
  "${BASE[@]}" stop pihole
  PIHOLE_STOPPED=true
fi

# User files and reproducible caches are intentionally excluded. In particular,
# nothing below MEDIA_DIR, Nextcloud data, Immich photos/videos, Jellyfin media,
# thumbnails, transcodes or Ollama models enters this repository.
BACKUP_PATHS=(
  "${REPO_DIR}/.env"
  "${DATA_DIR}/pihole"
  "${DATA_DIR}/vaultwarden"
  "${DATA_DIR}/caddy"
  "${DATA_DIR}/uptime-kuma"
  "${STAGING_DIR}"
  "/etc/raspberry-server"
)

if [[ -e ${DATA_DIR}/jellyfin/config ]]; then
  BACKUP_PATHS+=("${DATA_DIR}/jellyfin/config")
fi
for nextcloud_path in \
  "${DATA_DIR}/nextcloud/html/config" \
  "${DATA_DIR}/nextcloud/html/custom_apps" \
  "${DATA_DIR}/nextcloud/html/themes"; do
  [[ -e ${nextcloud_path} ]] && BACKUP_PATHS+=("${nextcloud_path}")
done
if [[ -e ${DATA_DIR}/n8n/n8n ]]; then
  BACKUP_PATHS+=("${DATA_DIR}/n8n/n8n")
fi
if [[ -e ${DATA_DIR}/streamingcommunity ]]; then
  BACKUP_PATHS+=("${DATA_DIR}/streamingcommunity")
fi
for music_state_path in \
  "${DATA_DIR}/aurral" \
  "${DATA_DIR}/lidarr" \
  "${DATA_DIR}/slskd" \
  "${DATA_DIR}/navidrome"; do
  [[ -e ${music_state_path} ]] && BACKUP_PATHS+=("${music_state_path}")
done

RESTIC_EXCLUDES=(
  --exclude "${DATA_DIR}/jellyfin/config/log"
  --exclude "${DATA_DIR}/jellyfin/config/metadata"
  --exclude "${DATA_DIR}/jellyfin/config/transcodes"
  --exclude "${DATA_DIR}/aurral/cache"
  --exclude "${DATA_DIR}/aurral/image-cache"
  --exclude "${DATA_DIR}/aurral/_staging"
  --exclude "${DATA_DIR}/lidarr/logs"
  --exclude "${DATA_DIR}/lidarr/MediaCover"
  --exclude "${DATA_DIR}/slskd/logs"
)

restic backup --tag pi-server "${RESTIC_EXCLUDES[@]}" "${BACKUP_PATHS[@]}"
restic forget --prune --tag pi-server \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 12

rm -f \
  "${STAGING_DIR}/nextcloud.sql" \
  "${STAGING_DIR}/immich.sql" \
  "${STAGING_DIR}/n8n.sql"
BACKUP_COMPLETED=true
echo "Encrypted configuration and database backup completed."
