#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

RESULT=${1:-auto}
DURATION_SECONDS=${2:-}
case "${RESULT}" in
  auto|success|failure) ;;
  *)
    echo "Usage: sudo bash scripts/refresh-backup-status.sh [auto|success|failure] [duration-seconds]" >&2
    exit 1
    ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env
BACKUP_ENV=/etc/raspberry-server/backup.env
# shellcheck source=scripts/read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}." >&2
  exit 1
fi

DATA_DIR=$(read_stack_value "${STACK_ENV}" DATA_DIR)
STATUS_DIR=${DATA_DIR}/monitoring
STATUS_FILE=${STATUS_DIR}/backup.json
install -d -m 0755 -o root -g root "${STATUS_DIR}"

previous_last_success=
previous_status=
if [[ -r ${STATUS_FILE} ]]; then
  previous_last_success=$(jq -r '.last_success // empty' "${STATUS_FILE}" 2>/dev/null || true)
  previous_status=$(jq -r '.status // empty' "${STATUS_FILE}" 2>/dev/null || true)
fi

last_success=${previous_last_success}
status="Non ancora eseguito"
last_attempt=

if [[ ${RESULT} == success ]]; then
  status="Riuscito"
  last_success=$(date --iso-8601=seconds)
  last_attempt=${last_success}
elif [[ ${RESULT} == failure ]]; then
  status="Fallito"
  last_attempt=$(date --iso-8601=seconds)
elif [[ -n ${previous_status} ]]; then
  status=${previous_status}
elif [[ -n ${last_success} ]]; then
  status="Riuscito"
fi

# On first installation, seed the timestamp from the actual latest Restic
# snapshot. Failure to contact the repository must not block the core stack.
if [[ -z ${last_success} && -r ${BACKUP_ENV} ]]; then
  set -a
  # shellcheck disable=SC1090
source "${BACKUP_ENV}"
set +a
BACKUP_TAG=${RESTIC_BACKUP_TAG:-pi-server}
  if [[ -z ${RESTIC_MOUNTPOINT:-} ]] || mountpoint -q "${RESTIC_MOUNTPOINT}"; then
    snapshot_json=$(
      timeout 30s restic snapshots --tag "${BACKUP_TAG}" --latest 1 --json 2>/dev/null ||
        true
    )
    if [[ -n ${snapshot_json} ]]; then
      last_success=$(jq -r '.[-1].time // empty' <<<"${snapshot_json}")
      if [[ -n ${last_success} && ${RESULT} == auto ]]; then
        status="Riuscito"
      fi
    fi
  fi
fi

next_run_raw=$(
  systemctl show backup.timer \
    --property=NextElapseUSecRealtime --value 2>/dev/null || true
)
next_run=
if [[ -n ${next_run_raw} && ${next_run_raw} != n/a ]]; then
  next_run=$(date --date="${next_run_raw}" --iso-8601=seconds 2>/dev/null || true)
fi
if [[ -z ${next_run} ]]; then
  schedule_time=${BACKUP_SCHEDULE_TIME:-04:15}
  if [[ ! ${schedule_time} =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
    schedule_time=04:15
  fi
  today_run=$(date --date="today ${schedule_time}" +%s)
  if (( $(date +%s) < today_run )); then
    next_run=$(date --date="today ${schedule_time}" --iso-8601=seconds)
  else
    next_run=$(date --date="tomorrow ${schedule_time}" --iso-8601=seconds)
  fi
fi

temporary=$(mktemp "${STATUS_DIR}/backup.json.XXXXXX")
trap 'rm -f "${temporary}"' EXIT
jq -n \
  --arg status "${status}" \
  --arg last_success "${last_success}" \
  --arg last_attempt "${last_attempt}" \
  --arg next_run "${next_run}" \
  --arg duration_seconds "${DURATION_SECONDS}" \
  '{
    status: $status,
    last_success: (if $last_success == "" then null else $last_success end),
    last_attempt: (if $last_attempt == "" then null else $last_attempt end),
    next_run: (if $next_run == "" then null else $next_run end),
    duration_seconds: (
      if $duration_seconds == "" then null else ($duration_seconds | tonumber)
      end
    )
  }' > "${temporary}"
chmod 0644 "${temporary}"
mv -f "${temporary}" "${STATUS_FILE}"
trap - EXIT

echo "Homepage backup status updated: ${STATUS_FILE}"
