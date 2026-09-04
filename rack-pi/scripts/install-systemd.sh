#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
BACKUP_MOUNTPOINT=/mnt/rack-backup
if [[ -r /etc/rack-pi/backup.env ]]; then
  # shellcheck disable=SC1091
  source /etc/rack-pi/backup.env
fi
if [[ ${BACKUP_MOUNTPOINT} != /* || ${BACKUP_MOUNTPOINT} == / ||
      ${BACKUP_MOUNTPOINT} =~ [[:space:]\|\&] ]]; then
  echo "Invalid BACKUP_MOUNTPOINT." >&2
  exit 1
fi
backup_mount_unit=$(systemd-escape --path --suffix=mount "${BACKUP_MOUNTPOINT}")
# Preserve systemd's literal backslash escapes (for example rack\x2dbackup)
# when substituting the unit name through sed's replacement syntax.
escaped_mount_unit=${backup_mount_unit//\\/\\\\}
units=(
  rack-core-stack.service rack-rest-server.service rack-backup.service rack-backup.timer
  rack-rest-server-recovery.service rack-rest-server-recovery.timer
  rack-backup-recovery.service rack-backup-recovery.timer
  rack-backup-status.service rack-backup-status.timer
  rack-storage-status.service rack-storage-status.timer
  rack-retention.service rack-retention.timer rack-integrity.service rack-integrity.timer
  rack-restore-test.service rack-restore-test.timer
)
for unit in "${units[@]}"; do
  sed -e "s|__RACK_DIR__|${RACK_DIR}|g" \
    -e "s|__BACKUP_MOUNTPOINT__|${BACKUP_MOUNTPOINT}|g" \
    -e "s|__BACKUP_MOUNT_UNIT__|${escaped_mount_unit}|g" \
    "${RACK_DIR}/systemd/${unit}" > "/etc/systemd/system/${unit}"
done
systemctl daemon-reload
systemctl enable rack-core-stack.service rack-backup-status.timer rack-storage-status.timer
systemctl start rack-backup-status.timer rack-storage-status.timer
systemctl enable --now rack-rest-server-recovery.timer

echo "Core/status units installed. Backup and maintenance timers stay disabled until repository setup is verified."
