#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "The backup reads root-owned state; run it through the systemd service or sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
BACKUP_ENV=/etc/raspberry-server/backup.env
STACK_ENV=${REPO_DIR}/.env

if [[ ! -r ${BACKUP_ENV} ]]; then
  echo "Missing ${BACKUP_ENV}; see docs/backup-and-restore.md." >&2
  exit 1
fi
if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}." >&2
  exit 1
fi

# Docker Compose accepts values which are not valid Bash assignments. This
# script only needs these two non-secret paths, so never source the whole
# stack .env file (which contains passwords and tokens).
read_stack_path() {
  local key=${1:?key is required}
  local line value
  line=$(grep -m 1 -E "^${key}=" "${STACK_ENV}" || true)
  value=${line#*=}
  value=${value%$'\r'}

  # Accept the ordinary single- or double-quoted Compose forms as well.
  if [[ ${value} == \"*\" && ${value} == *\" ]]; then
    value=${value:1:-1}
  elif [[ ${value} == \'*\' && ${value} == *\' ]]; then
    value=${value:1:-1}
  fi

  if [[ -z ${value} ]]; then
    echo "Missing ${key} in ${STACK_ENV}." >&2
    exit 1
  fi
  printf '%s\n' "${value}"
}

set -a
source "${BACKUP_ENV}"
set +a
umask 077
DATA_DIR=$(read_stack_path DATA_DIR)
STAGING_DIR=$(read_stack_path STAGING_DIR)
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
AUTOMATION_COMPOSE=()
NEXTCLOUD_MAINTENANCE=false
VAULTWARDEN_STOPPED=false
N8N_STOPPED=false
N8N_ACTIVE=false

# n8n is optional and lives in a separate Compose file so the current
# Raspberry Pi stack never needs its secrets. Enable this only on the mini PC
# by setting AUTOMATION_COMPOSE_FILE in /etc/raspberry-server/backup.env.
if [[ -n ${AUTOMATION_COMPOSE_FILE:-} ]]; then
  if [[ ! -r ${AUTOMATION_COMPOSE_FILE} ]]; then
    echo "AUTOMATION_COMPOSE_FILE is not readable: ${AUTOMATION_COMPOSE_FILE}" >&2
    exit 1
  fi
  AUTOMATION_COMPOSE=(docker compose --project-directory "${REPO_DIR}" \
    -f "${REPO_DIR}/compose.yaml" -f "${AUTOMATION_COMPOSE_FILE}")
  if "${AUTOMATION_COMPOSE[@]}" ps --services --status running | grep -qx n8n; then
    N8N_ACTIVE=true
  fi
fi

cleanup() {
  if [[ ${N8N_STOPPED} == true ]]; then
    "${AUTOMATION_COMPOSE[@]}" start n8n || true
  fi
  if [[ ${VAULTWARDEN_STOPPED} == true ]]; then
    "${COMPOSE[@]}" start vaultwarden || true
  fi
  if [[ ${NEXTCLOUD_MAINTENANCE} == true ]]; then
    "${COMPOSE[@]}" exec -T --user www-data nextcloud php occ maintenance:mode --off || true
  fi
}
trap cleanup EXIT

# n8n stores workflows, executions and encrypted credentials in its dedicated
# PostgreSQL database. Stop it before dumping the database and copying its
# settings directory, so this snapshot is a consistent restore point.
if [[ ${N8N_ACTIVE} == true ]]; then
  "${AUTOMATION_COMPOSE[@]}" stop n8n
  N8N_STOPPED=true
  "${AUTOMATION_COMPOSE[@]}" exec -T n8n-postgres pg_dump -U n8n n8n > "${STAGING_DIR}/n8n.sql"
fi

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
if [[ ${N8N_ACTIVE} == true && -e ${DATA_DIR}/n8n/n8n ]]; then
  BACKUP_PATHS+=("${DATA_DIR}/n8n/n8n")
fi

restic backup --tag raspberry-server "${BACKUP_PATHS[@]}"
restic forget --prune --tag raspberry-server \
  --keep-daily 7 --keep-weekly 4 --keep-monthly 12

rm -f "${STAGING_DIR}/nextcloud.sql" "${STAGING_DIR}/n8n.sql"
echo "Encrypted backup completed."
