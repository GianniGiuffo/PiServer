#!/usr/bin/env bash
set -uo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "This restricted entry point must run through sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec 9>/run/lock/raspberry-server-remote-backup.lock
if ! flock -n 9; then
  echo "Another remote backup invocation is active." >&2
  exit 75
fi

state_result=0
photo_result=0
bash "${SCRIPT_DIR}/backup.sh" || state_result=$?
bash "${SCRIPT_DIR}/backup-photos.sh" || photo_result=$?

if (( state_result != 0 || photo_result != 0 )); then
  echo "Remote backup failed: state=${state_result}, photos=${photo_result}." >&2
  exit 1
fi

echo "Mini-PC state and enabled photo backup completed."
