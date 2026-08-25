#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
units=(
  rack-core-stack.service rack-rest-server.service rack-backup.service rack-backup.timer
  rack-backup-recovery.service rack-backup-recovery.timer
  rack-backup-status.service rack-backup-status.timer
  rack-storage-status.service rack-storage-status.timer
  rack-retention.service rack-retention.timer rack-integrity.service rack-integrity.timer
  rack-restore-test.service rack-restore-test.timer
)
for unit in "${units[@]}"; do
  sed -e "s|__RACK_DIR__|${RACK_DIR}|g" \
    "${RACK_DIR}/systemd/${unit}" > "/etc/systemd/system/${unit}"
done
systemctl daemon-reload
systemctl enable rack-core-stack.service rack-backup-status.timer rack-storage-status.timer
systemctl start rack-backup-status.timer rack-storage-status.timer

echo "Core/status units installed. Backup and maintenance timers stay disabled until repository setup is verified."
