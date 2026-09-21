#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through systemd." >&2
  exit 1
fi
if ! systemctl is-enabled --quiet rack-rest-server.service; then
  echo "Rest Server is disabled; recovery skipped."
  exit 0
fi
# An active backup or repository maintenance owns this lock. Never interrupt
# either, including a oneshot service still in systemd's 'activating' state.
exec 8>/run/lock/rack-pi-repository-maintenance.lock
if ! flock -n 8; then
  echo "Backup or repository maintenance is active; recovery deferred."
  exit 0
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! bash "${SCRIPT_DIR}/ensure-rest-server.sh"; then
  echo "Backup storage is unavailable; recovery will retry without stopping applications."
fi
