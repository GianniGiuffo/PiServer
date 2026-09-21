#!/usr/bin/env bash
set -uo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through systemd or sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ ! -r /etc/rack-pi/orchestrator.env ]]; then
  echo "Missing /etc/rack-pi/orchestrator.env." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source /etc/rack-pi/orchestrator.env
set +a

exec 9>/run/lock/rack-pi-orchestrator.lock
if ! flock -n 9; then
  echo "Another rack backup orchestration is active." >&2
  exit 75
fi

exec 8>/run/lock/rack-pi-repository-maintenance.lock
if ! flock -n 8; then
  echo "Repository maintenance or storage recovery is active; backup deferred." >&2
  exit 75
fi

status_dir=/srv/rack-pi/data/monitoring
attempt_file=${status_dir}/backup-attempt.json
install -d -m 0755 -o root -g root "${status_dir}"
started=$(date --iso-8601=seconds)
started_epoch=$(date +%s)

push_status() {
  local result=${1:?result}
  local message=${2:?message}
  [[ -n ${UPTIME_KUMA_BACKUP_PUSH_URL:-} ]] || return 0
  curl -fsS --max-time 15 --get \
    --data-urlencode "status=${result}" \
    --data-urlencode "msg=${message}" \
    --data-urlencode "ping=" \
    "${UPTIME_KUMA_BACKUP_PUSH_URL}" >/dev/null || true
}

remote_result=0
local_result=0
disk_result=0
bash "${SCRIPT_DIR}/check-backup-disk.sh" || disk_result=$?

if (( disk_result == 0 )); then
  bash "${SCRIPT_DIR}/ensure-rest-server.sh" || remote_result=$?
  if (( remote_result == 0 )); then
    : "${MINIPC_SSH_HOST:?MINIPC_SSH_HOST is required}"
    : "${MINIPC_SSH_USER:?MINIPC_SSH_USER is required}"
    : "${MINIPC_SSH_KEY:?MINIPC_SSH_KEY is required}"
    : "${MINIPC_KNOWN_HOSTS:?MINIPC_KNOWN_HOSTS is required}"
    timeout --foreground --kill-after=2m "${REMOTE_BACKUP_TIMEOUT:-7h}" \
      ssh -T \
      -o BatchMode=yes \
      -o IdentitiesOnly=yes \
      -o StrictHostKeyChecking=yes \
      -o "UserKnownHostsFile=${MINIPC_KNOWN_HOSTS}" \
      -p "${MINIPC_SSH_PORT:-2222}" \
      -i "${MINIPC_SSH_KEY}" \
      "${MINIPC_SSH_USER}@${MINIPC_SSH_HOST}" run-backup || remote_result=$?
  fi
  bash "${SCRIPT_DIR}/rack-local-backup.sh" || local_result=$?
else
  remote_result=${disk_result}
  local_result=${disk_result}
fi

finished=$(date --iso-8601=seconds)
duration=$(( $(date +%s) - started_epoch ))
result=success
message="Backup mini-PC, foto abilitate e rack-pi completato"
exit_status=0
if (( remote_result != 0 || local_result != 0 )); then
  result=failure
  message="Backup fallito: remoto=${remote_result}, rack-pi=${local_result}"
  exit_status=1
fi

temporary=$(mktemp "${status_dir}/backup-attempt.json.XXXXXX")
trap 'rm -f -- "${temporary}"' EXIT
jq -n \
  --arg status "${result}" \
  --arg started "${started}" \
  --arg finished "${finished}" \
  --argjson duration "${duration}" \
  --argjson remote "${remote_result}" \
  --argjson local "${local_result}" \
  '{status:$status,started:$started,finished:$finished,duration_seconds:$duration,remote_exit:$remote,local_exit:$local}' \
  > "${temporary}"
chmod 0644 "${temporary}"
mv -f "${temporary}" "${attempt_file}"
trap - EXIT

bash "${SCRIPT_DIR}/refresh-backup-status.sh" || true
push_status "$([[ ${result} == success ]] && echo up || echo down)" "${message}"
echo "${message}"
exit "${exit_status}"
