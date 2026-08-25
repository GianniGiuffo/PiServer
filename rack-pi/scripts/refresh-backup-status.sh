#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo or systemd." >&2
  exit 1
fi

BACKUP_ENV=/etc/rack-pi/backup.env
status_dir=/srv/rack-pi/data/monitoring
status_file=${status_dir}/backup.json
attempt_file=${status_dir}/backup-attempt.json
install -d -m 0755 -o root -g root "${status_dir}"

set -a
# shellcheck disable=SC1090
source "${BACKUP_ENV}"
set +a

latest_time() {
  local repository=${1:?repository}
  local password_file=${2:?password file}
  local tag=${3:?tag}
  [[ -f ${repository}/config && -r ${password_file} ]] || return 0
  local payload
  payload=$(timeout 45s restic -r "${repository}" \
    --password-file "${password_file}" snapshots --tag "${tag}" \
    --latest 1 --json 2>/dev/null || true)
  if [[ -n ${payload} ]]; then
    jq -r '.[-1].time // empty' <<<"${payload}"
  fi
  return 0
}

minipc_last=
photos_last=
rack_last=
disk_ready=false
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if bash "${script_dir}/check-backup-disk.sh" >/dev/null 2>&1; then
  disk_ready=true
  minipc_last=$(latest_time "${MINIPC_STATE_REPOSITORY}" \
    "${MINIPC_STATE_PASSWORD_FILE}" "${MINIPC_STATE_TAG:-minipc-state}")
  if [[ ${PHOTOS_ENABLED:-false} == true ]]; then
    photos_last=$(latest_time "${PHOTOS_REPOSITORY}" \
      "${PHOTOS_PASSWORD_FILE}" "${PHOTOS_TAG:-photos}")
  fi
  rack_last=$(latest_time "${RACK_PI_REPOSITORY}" \
    "${RACK_PI_PASSWORD_FILE}" "${RACK_PI_TAG:-rack-pi-state}")
fi

status="Pronto"
if [[ ${disk_ready} != true ]]; then
  status="Disco non montato"
elif [[ -z ${minipc_last} || -z ${rack_last} ]]; then
  status="Non ancora completo"
elif [[ ${PHOTOS_ENABLED:-false} == true && -z ${photos_last} ]]; then
  status="Foto mai salvate"
fi
if [[ -r ${attempt_file} ]] &&
   [[ $(jq -r '.status // empty' "${attempt_file}" 2>/dev/null || true) == failure ]]; then
  status="Fallito"
fi

next_run_raw=$(systemctl show rack-backup.timer \
  --property=NextElapseUSecRealtime --value 2>/dev/null || true)
next_run=
if [[ -n ${next_run_raw} && ${next_run_raw} != n/a ]]; then
  next_run=$(date --date="${next_run_raw}" --iso-8601=seconds 2>/dev/null || true)
fi

temporary=$(mktemp "${status_dir}/backup.json.XXXXXX")
trap 'rm -f -- "${temporary}"' EXIT
jq -n \
  --arg status "${status}" \
  --arg minipc "${minipc_last}" \
  --arg photos "${photos_last}" \
  --arg rack "${rack_last}" \
  --arg next "${next_run}" \
  '{
    status:$status,
    minipc_last_success:(if $minipc=="" then null else $minipc end),
    photos_last_success:(if $photos=="" then null else $photos end),
    rack_pi_last_success:(if $rack=="" then null else $rack end),
    next_run:(if $next=="" then null else $next end)
  }' > "${temporary}"
chmod 0644 "${temporary}"
mv -f "${temporary}" "${status_file}"
trap - EXIT
