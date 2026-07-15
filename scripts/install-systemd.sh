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

for unit in site-deploy.service site-deploy.timer backup.service backup.timer; do
  sed \
    -e "s|__RPI_USER__|${TARGET_USER}|g" \
    -e "s|__RPI_GROUP__|${TARGET_GROUP}|g" \
    -e "s|__REPO_DIR__|${REPO_DIR}|g" \
    "${REPO_DIR}/systemd/${unit}" > "/etc/systemd/system/${unit}"
done

systemctl daemon-reload
systemctl enable site-deploy.timer backup.timer
