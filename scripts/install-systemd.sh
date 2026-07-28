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

for unit in \
  core-stack.service media-stack.service automation-stack.service \
  site-deploy.service site-deploy.timer backup.service backup.timer \
  backup-status.service backup-status.timer; do
  sed \
    -e "s|__RPI_USER__|${TARGET_USER}|g" \
    -e "s|__RPI_GROUP__|${TARGET_GROUP}|g" \
    -e "s|__REPO_DIR__|${REPO_DIR}|g" \
    "${REPO_DIR}/systemd/${unit}" > "/etc/systemd/system/${unit}"
done

systemctl daemon-reload
systemctl enable core-stack.service site-deploy.timer backup-status.timer
if [[ -r ${REPO_DIR}/.env ]]; then
  bash "${REPO_DIR}/scripts/refresh-backup-status.sh" auto
  systemctl start backup-status.timer
fi

cat <<EOF
Installed systemd units.

- core-stack.service, site-deploy.timer and backup-status.timer are enabled for
  the next boot.
- Enable backup.timer only after Restic is configured and tested.
- Enable media-stack.service only after /srv/media passes check-media-mount.sh.
- Enable automation-stack.service when n8n/Ollama should start.
EOF
