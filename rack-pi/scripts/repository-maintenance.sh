#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through systemd or sudo." >&2
  exit 1
fi
MODE=${1:?Usage: repository-maintenance.sh retention|integrity|restore}
case "${MODE}" in retention|integrity|restore) ;; *) exit 2 ;; esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
set -a
# shellcheck disable=SC1090
source /etc/rack-pi/backup.env
# shellcheck disable=SC1090
source /etc/rack-pi/orchestrator.env
set +a
rest_server_was_active=false
cleanup() {
  local result=$?
  trap - EXIT
  if [[ ${rest_server_was_active} == true ]] &&
     ! systemctl start rack-rest-server.service; then
    result=1
  fi
  if [[ -n ${restore_root:-} && -d ${restore_root} &&
        ${restore_root} == /tmp/rack-pi-restore.* ]]; then
    find "${restore_root}" -depth -mindepth 1 -delete || true
    rmdir "${restore_root}" || true
  fi
  if [[ -n ${UPTIME_KUMA_MAINTENANCE_PUSH_URL:-} ]]; then
    local push_state=up push_message="Manutenzione Restic ${MODE} riuscita"
    if (( result != 0 )); then
      push_state=down
      push_message="Manutenzione Restic ${MODE} fallita"
    fi
    curl -fsS --max-time 15 --get --data-urlencode "status=${push_state}" \
      --data-urlencode "msg=${push_message}" --data-urlencode ping= \
      "${UPTIME_KUMA_MAINTENANCE_PUSH_URL}" >/dev/null || true
  fi
  exit "${result}"
}
trap cleanup EXIT

bash "${SCRIPT_DIR}/check-backup-disk.sh"

exec 9>/run/lock/rack-pi-repository-maintenance.lock
flock -n 9 || { echo "Repository maintenance already active." >&2; exit 75; }
if systemctl is-active --quiet rack-backup.service; then
  echo "Backup is active; maintenance refused." >&2
  exit 75
fi

if systemctl is-active --quiet rack-rest-server.service; then
  systemctl stop rack-rest-server.service
  rest_server_was_active=true
fi

repo_exists() { [[ -f ${1:?repository}/config && -r ${2:?password} ]]; }
has_tag() {
  timeout 45s restic -r "$1" --password-file "$2" \
    snapshots --tag "$3" --json 2>/dev/null | jq -e 'length > 0' >/dev/null
}
run_check() {
  timeout --foreground --kill-after=5m "${RESTIC_OPERATION_TIMEOUT:-5h}" \
    restic -r "$1" --password-file "$2" check "${@:3}"
}
run_forget() {
  local repo=$1 pass=$2 tag=$3 daily=$4 weekly=$5 monthly=$6
  has_tag "${repo}" "${pass}" "${tag}" || return 0
  timeout --foreground --kill-after=5m "${RESTIC_OPERATION_TIMEOUT:-5h}" \
    restic -r "${repo}" --password-file "${pass}" forget --prune \
    --tag "${tag}" --group-by host,tags \
    --keep-within "${daily}" \
    --keep-within-weekly "${weekly}" \
    --keep-within-monthly "${monthly}"
}

repositories=(
  "${MINIPC_STATE_REPOSITORY}|${MINIPC_STATE_PASSWORD_FILE}|${MINIPC_STATE_TAG:-minipc-state}"
  "${PHOTOS_REPOSITORY}|${PHOTOS_PASSWORD_FILE}|${PHOTOS_TAG:-photos}"
  "${RACK_PI_REPOSITORY}|${RACK_PI_PASSWORD_FILE}|${RACK_PI_TAG:-rack-pi-state}"
)

# A process interrupted while using the append-only endpoint can leave a stale
# lock. The endpoint is stopped above, so this protected client can clear locks
# without racing an authorized remote backup.
for item in "${repositories[@]}"; do
  IFS='|' read -r repo pass tag <<<"${item}"
  if repo_exists "${repo}" "${pass}"; then
    restic -r "${repo}" --password-file "${pass}" unlock
  fi
done

case "${MODE}" in
  retention)
    run_forget "${MINIPC_STATE_REPOSITORY}" "${MINIPC_STATE_PASSWORD_FILE}" \
      "${MINIPC_STATE_TAG:-minipc-state}" 14d 2m 1y
    if [[ ${PHOTOS_ENABLED:-false} == true ]]; then
      run_forget "${PHOTOS_REPOSITORY}" "${PHOTOS_PASSWORD_FILE}" \
        "${PHOTOS_TAG:-photos}" 7d 1m 6m
    fi
    run_forget "${RACK_PI_REPOSITORY}" "${RACK_PI_PASSWORD_FILE}" \
      "${RACK_PI_TAG:-rack-pi-state}" 14d 2m 1y
    for item in "${repositories[@]}"; do
      IFS='|' read -r repo pass tag <<<"${item}"
      repo_exists "${repo}" "${pass}" && run_check "${repo}" "${pass}"
    done
    ;;
  integrity)
    for item in "${repositories[@]}"; do
      IFS='|' read -r repo pass tag <<<"${item}"
      repo_exists "${repo}" "${pass}" && \
        run_check "${repo}" "${pass}" --read-data-subset=10%
    done
    ;;
  restore)
    restore_root=$(mktemp -d /tmp/rack-pi-restore.XXXXXX)
    cleanup_restore() {
      [[ ${restore_root} == /tmp/rack-pi-restore.* ]] || return 1
      find "${restore_root}" -depth -mindepth 1 -delete
      rmdir "${restore_root}"
    }
    restore_one() {
      local repo=$1 pass=$2 tag=$3 include=$4 label=$5
      local target=${restore_root}/${label}
      has_tag "${repo}" "${pass}" "${tag}" || return 0
      install -d -m 0700 "${target}"
      restic -r "${repo}" --password-file "${pass}" restore latest \
        --tag "${tag}" --include "${include}" --target "${target}"
      [[ -e ${target}${include} ]] || {
        echo "Restore verification failed for ${label}: ${include}" >&2
        return 1
      }
    }
    restore_one "${MINIPC_STATE_REPOSITORY}" "${MINIPC_STATE_PASSWORD_FILE}" \
      "${MINIPC_STATE_TAG:-minipc-state}" /opt/raspberry-server/.env minipc
    if [[ ${PHOTOS_ENABLED:-false} == true ]]; then
      restore_one "${PHOTOS_REPOSITORY}" "${PHOTOS_PASSWORD_FILE}" \
        "${PHOTOS_TAG:-photos}" /srv/media/.piserver-media photos
    fi
    restore_one "${RACK_PI_REPOSITORY}" "${RACK_PI_PASSWORD_FILE}" \
      "${RACK_PI_TAG:-rack-pi-state}" /opt/raspberry-server/rack-pi/.env rack
    cleanup_restore
    ;;
esac

echo "Repository maintenance completed: ${MODE}."
