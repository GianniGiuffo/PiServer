#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo or systemd." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
status_dir=/srv/rack-pi/data/monitoring
status_file=${status_dir}/storage.json
install -d -m 0755 -o root -g root "${status_dir}"

status="Non montato"
free_bytes=null
total_bytes=null
used_percent=null
if bash "${SCRIPT_DIR}/check-backup-disk.sh" >/dev/null 2>&1; then
  set -a
  # shellcheck disable=SC1091
  source /etc/rack-pi/backup.env
  set +a
  read -r total_bytes used_bytes free_bytes used_raw < <(
    df -B1 --output=size,used,avail,pcent "${BACKUP_MOUNTPOINT}" | tail -1
  )
  used_percent=${used_raw%%%}
  status="Montato"
fi

temporary=$(mktemp "${status_dir}/storage.json.XXXXXX")
trap 'rm -f -- "${temporary}"' EXIT
jq -n \
  --arg status "${status}" \
  --argjson free_bytes "${free_bytes}" \
  --argjson total_bytes "${total_bytes}" \
  --argjson used_percent "${used_percent}" \
  '{status:$status,free_bytes:$free_bytes,total_bytes:$total_bytes,used_percent:$used_percent}' \
  > "${temporary}"
chmod 0644 "${temporary}"
mv -f "${temporary}" "${status_file}"
trap - EXIT
