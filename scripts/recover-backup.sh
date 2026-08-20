#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env
BACKUP_ENV=/etc/raspberry-server/backup.env
# shellcheck source=scripts/read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

# A disabled timer is an explicit administrator choice. Recovery must not run
# backups while the repository is under maintenance.
if ! systemctl is-enabled --quiet backup.timer; then
  echo "Backup timer is disabled; automatic recovery skipped."
  exit 0
fi
if systemctl is-active --quiet backup.service; then
  echo "Backup is already running."
  exit 0
fi
if [[ ! -r ${STACK_ENV} || ! -r ${BACKUP_ENV} ]]; then
  echo "Backup configuration is incomplete; automatic recovery skipped." >&2
  exit 0
fi

set -a
# shellcheck disable=SC1090
source "${BACKUP_ENV}"
set +a
max_age_hours=${RESTIC_RECOVERY_MAX_AGE_HOURS:-26}
if [[ ! ${max_age_hours} =~ ^[1-9][0-9]*$ ]]; then
  echo "RESTIC_RECOVERY_MAX_AGE_HOURS must be a positive integer." >&2
  exit 1
fi

DATA_DIR=$(read_stack_value "${STACK_ENV}" DATA_DIR)
status_file=${DATA_DIR}/monitoring/backup.json
last_success=
if [[ -r ${status_file} ]]; then
  last_success=$(jq -r '.last_success // empty' "${status_file}" 2>/dev/null || true)
fi

backup_due=true
if [[ -n ${last_success} ]]; then
  last_success_epoch=$(date --date="${last_success}" +%s 2>/dev/null || true)
  if [[ ${last_success_epoch} =~ ^[0-9]+$ ]]; then
    age_seconds=$(( $(date +%s) - last_success_epoch ))
    if (( age_seconds < max_age_hours * 3600 )); then
      backup_due=false
    fi
  fi
fi

if [[ ${backup_due} != true ]]; then
  echo "Latest successful backup is recent; recovery not needed."
  exit 0
fi

if ! timeout 150s bash "${SCRIPT_DIR}/check-backup-target.sh"; then
  echo "Restic target is not ready; automatic recovery will retry."
  exit 0
fi

systemctl reset-failed backup.service
systemctl start --no-block backup.service
echo "Overdue backup recovery queued."
