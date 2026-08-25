#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

TARGET_USER=${1:?Usage: sudo bash ./scripts/install-systemd.sh <linux-user> [linux-group]}
if ! id "${TARGET_USER}" >/dev/null 2>&1; then
  echo "User '${TARGET_USER}' does not exist." >&2
  exit 1
fi
TARGET_GROUP=${2:-$(id -gn "${TARGET_USER}")}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)

# The deploy service runs as TARGET_USER and must be able to traverse the
# configuration directory. Files such as backup.env can remain root-only.
install -d -m 0750 -o root -g "${TARGET_GROUP}" /etc/raspberry-server
install -d -m 0750 -o root -g "${TARGET_GROUP}" /etc/raspberry-server/sites
install -d -m 0700 -o root -g root /var/lib/raspberry-server/ai-ops

# Separate secrets prevent n8n from granting its own approval. Existing values
# are preserved across reinstalls.
for token_file in ai-ops-token ai-ops-approval-token ai-ops-telegram-bridge-token; do
  if [[ ! -s /etc/raspberry-server/${token_file} ]]; then
    umask 0027
    openssl rand -hex 32 > "/etc/raspberry-server/${token_file}"
  fi
  chown root:"${TARGET_GROUP}" "/etc/raspberry-server/${token_file}"
  chmod 0640 "/etc/raspberry-server/${token_file}"
done

for unit in \
  core-stack.service media-stack.service automation-stack.service \
  ai-ops-gateway.service \
  site-deploy.service site-deploy.timer backup.service backup.timer \
  backup-recovery.service backup-recovery.timer \
  backup-status.service backup-status.timer \
  media-status.service media-status.timer \
  media-recovery.service media-recovery.timer \
  lidarr-weekly-search.service lidarr-weekly-search.timer; do
  sed \
    -e "s|__RPI_USER__|${TARGET_USER}|g" \
    -e "s|__RPI_GROUP__|${TARGET_GROUP}|g" \
    -e "s|__REPO_DIR__|${REPO_DIR}|g" \
    "${REPO_DIR}/systemd/${unit}" > "/etc/systemd/system/${unit}"
done

systemctl daemon-reload

BACKUP_TIMER_MANAGED_EXTERNALLY=false
if [[ -r /etc/raspberry-server/backup.env ]] &&
   grep -Eq '^[[:space:]]*BACKUP_TIMER_MANAGED_EXTERNALLY=true([[:space:]]*(#.*)?)?$' \
     /etc/raspberry-server/backup.env; then
  BACKUP_TIMER_MANAGED_EXTERNALLY=true
fi

systemctl enable \
  core-stack.service ai-ops-gateway.service site-deploy.timer backup-status.timer \
  media-status.timer media-recovery.timer
if [[ ${BACKUP_TIMER_MANAGED_EXTERNALLY} == true ]]; then
  systemctl disable --now backup.timer backup-recovery.timer
else
  systemctl enable backup-recovery.timer
fi
systemctl start ai-ops-gateway.service
if [[ -r ${REPO_DIR}/.env ]]; then
  bash "${REPO_DIR}/scripts/refresh-backup-status.sh" auto
  bash "${REPO_DIR}/scripts/refresh-media-status.sh"
  systemctl start backup-status.timer media-status.timer media-recovery.timer
  if [[ ${BACKUP_TIMER_MANAGED_EXTERNALLY} != true ]]; then
    systemctl start backup-recovery.timer
  fi
fi

cat <<EOF
Installed systemd units.

- core-stack.service, ai-ops-gateway.service, site-deploy.timer,
  backup-status.timer and media-status.timer are enabled for the next boot.
  The AI Ops gateway exposes only a local Unix socket. media-recovery.timer
  retries an enabled media stack when its storage becomes available.
- Enable media-stack.service only after /srv/media passes check-media-mount.sh.
- Enable lidarr-weekly-search.timer after Lidarr is configured and its API is
  reachable; it refreshes metadata and searches recent releases every Monday.
- Enable automation-stack.service when n8n/Ollama should start.
- Before enabling the local AI Ops workflow, create the root-only Telegram bot
  token file described in docs/n8n-ai-ops-local.md.
EOF

if [[ ${BACKUP_TIMER_MANAGED_EXTERNALLY} == true ]]; then
  echo "- backup.timer and backup-recovery.timer remain disabled: an external orchestrator owns the schedule."
else
  echo "- backup-recovery.timer is enabled; enable backup.timer only after Restic is configured and tested."
fi
