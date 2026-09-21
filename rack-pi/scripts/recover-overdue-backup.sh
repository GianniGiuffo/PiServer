#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through systemd." >&2
  exit 1
fi
if ! systemctl is-enabled --quiet rack-backup.timer; then
  echo "rack-backup.timer is disabled; recovery skipped."
  exit 0
fi
if systemctl is-active --quiet rack-backup.service; then
  echo "Backup already active."
  exit 0
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
bash "${SCRIPT_DIR}/refresh-backup-status.sh"
status_file=/srv/rack-pi/data/monitoring/backup.json
set -a
# shellcheck disable=SC1090
source /etc/rack-pi/backup.env
set +a

is_older_than() {
  local timestamp=${1:-}
  local hours=${2:?hours}
  [[ -n ${timestamp} ]] || return 0
  local epoch
  epoch=$(date --date="${timestamp}" +%s 2>/dev/null || echo 0)
  (( epoch == 0 || $(date +%s) - epoch > hours * 3600 ))
}

minipc=$(jq -r '.minipc_last_success // empty' "${status_file}")
rack=$(jq -r '.rack_pi_last_success // empty' "${status_file}")
photos=$(jq -r '.photos_last_success // empty' "${status_file}")
due=false
is_older_than "${minipc}" 26 && due=true
is_older_than "${rack}" 26 && due=true
if [[ ${PHOTOS_ENABLED:-false} == true ]] && is_older_than "${photos}" 192; then
  due=true
fi

if [[ ${due} != true ]]; then
  echo "All enabled backup sets are recent."
  exit 0
fi
if ! bash "${SCRIPT_DIR}/check-backup-disk.sh"; then
  echo "Overdue backup cannot start until the USB disk returns." >&2
  exit 0
fi

systemctl reset-failed rack-backup.service
systemctl start --no-block rack-backup.service
echo "Overdue rack backup queued."
