#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through systemd or sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
set -a
# shellcheck disable=SC1090
source /etc/rack-pi/backup.env
set +a
bash "${SCRIPT_DIR}/check-backup-disk.sh"

: "${RACK_PI_REPOSITORY:?RACK_PI_REPOSITORY is required}"
: "${RACK_PI_PASSWORD_FILE:?RACK_PI_PASSWORD_FILE is required}"
[[ -f ${RACK_PI_REPOSITORY}/config ]] || {
  echo "rack-pi Restic repository is not initialized." >&2
  exit 1
}

exec 9>/run/lock/rack-pi-local-backup.lock
flock -n 9 || { echo "rack-pi local backup already active." >&2; exit 75; }

compose=(docker compose --project-directory "${RACK_DIR}" -f "${RACK_DIR}/compose.yaml")
pihole_stopped=false
kuma_stopped=false
cleanup() {
  local result=$?
  trap - EXIT
  if [[ ${pihole_stopped} == true ]] && ! "${compose[@]}" start pihole; then
    result=1
  fi
  if [[ ${kuma_stopped} == true ]] && ! "${compose[@]}" start uptime-kuma; then
    result=1
  fi
  exit "${result}"
}
trap cleanup EXIT

if "${compose[@]}" ps --services --status running | grep -qx pihole; then
  "${compose[@]}" stop pihole
  pihole_stopped=true
fi
if "${compose[@]}" ps --services --status running | grep -qx uptime-kuma; then
  "${compose[@]}" stop uptime-kuma
  kuma_stopped=true
fi

XDG_CACHE_HOME=/var/cache/rack-pi/restic
install -d -m 0700 -o root -g root "${XDG_CACHE_HOME}"
export XDG_CACHE_HOME

paths=("${RACK_DIR}/.env" /etc/rack-pi /srv/rack-pi/data)
timeout --foreground --kill-after=5m "${RESTIC_OPERATION_TIMEOUT:-5h}" \
  restic -r "${RACK_PI_REPOSITORY}" \
  --password-file "${RACK_PI_PASSWORD_FILE}" backup \
  --tag "${RACK_PI_TAG:-rack-pi-state}" \
  --exclude '/srv/rack-pi/data/monitoring/*.json' \
  "${paths[@]}"

echo "rack-pi state snapshot completed."
