#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env
# shellcheck source=scripts/read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}." >&2
  exit 1
fi

DATA_DIR=$(read_stack_value "${STACK_ENV}" DATA_DIR)
MEDIA_DIR=$(read_stack_value "${STACK_ENV}" MEDIA_DIR)
STATUS_DIR=${DATA_DIR}/monitoring
STATUS_FILE=${STATUS_DIR}/media.json
install -d -m 0755 -o root -g root "${STATUS_DIR}"

status="Non montato"
total_bytes=null
free_bytes=null
used_percent=null

mount_record=$(
  findmnt -rn --mountpoint "${MEDIA_DIR}" --output TARGET,FSTYPE 2>/dev/null |
    awk '$2 != "autofs" { print; exit }' || true
)
read -r mounted_target filesystem <<<"${mount_record}"
if [[ ${mounted_target:-} == "${MEDIA_DIR}" && ${filesystem:-} != autofs ]]; then
  status="Non disponibile"
  filesystem_stats=$(
    timeout 10s df -B1 --output=size,avail,pcent -- "${MEDIA_DIR}" 2>/dev/null |
      tail -n 1 || true
  )
  read -r total free used <<<"${filesystem_stats}"
  used=${used%\%}
  if [[ ${total:-} =~ ^[0-9]+$ && ${free:-} =~ ^[0-9]+$ && ${used:-} =~ ^[0-9]+$ ]]; then
    status="Montato"
    total_bytes=${total}
    free_bytes=${free}
    used_percent=${used}
  fi
fi

temporary=$(mktemp "${STATUS_DIR}/media.json.XXXXXX")
trap 'rm -f "${temporary}"' EXIT
jq -n \
  --arg status "${status}" \
  --arg updated_at "$(date --iso-8601=seconds)" \
  --argjson free_bytes "${free_bytes}" \
  --argjson total_bytes "${total_bytes}" \
  --argjson used_percent "${used_percent}" \
  '{
    status: $status,
    free_bytes: $free_bytes,
    total_bytes: $total_bytes,
    used_percent: $used_percent,
    updated_at: $updated_at
  }' > "${temporary}"
chmod 0644 "${temporary}"
mv -f "${temporary}" "${STATUS_FILE}"
trap - EXIT

echo "Homepage media status updated: ${STATUS_FILE} (${status})"
