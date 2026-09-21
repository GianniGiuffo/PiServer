#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run through systemd or sudo." >&2
  exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
# Callers hold the repository-maintenance lock to avoid restarting the server
# while retention, a restore test, or another backup is using the repositories.
set -a
# shellcheck disable=SC1091
source /etc/rack-pi/backup.env
set +a
if ! systemctl is-enabled --quiet rack-rest-server.service; then
  echo "Rest Server is disabled; automatic recovery refused." >&2
  exit 1
fi
bash "${SCRIPT_DIR}/check-backup-disk.sh"

compose=(docker compose --project-directory "${RACK_DIR}" -f "${RACK_DIR}/compose.yaml")
configs=("${MINIPC_STATE_REPOSITORY:?MINIPC_STATE_REPOSITORY is required}/config")
if [[ ${PHOTOS_ENABLED:-false} == true ]]; then
  configs+=("${PHOTOS_REPOSITORY:?PHOTOS_REPOSITORY is required}/config")
fi
rest_server_ip=$(grep -m1 '^RACK_PI_TAILSCALE_IP=' "${RACK_DIR}/.env" | cut -d= -f2- | tr -d '\r')

server_ready() {
  local container pid code
  container=$("${compose[@]}" ps --all --quiet rest-server) || return 1
  [[ -n ${container} ]] || return 1
  pid=$(docker inspect --format '{{.State.Pid}}' "${container}") || return 1
  timeout --kill-after=2s 10s python3 "${SCRIPT_DIR}/check-rest-server-mount.py" \
    "${pid}" "${BACKUP_MOUNTPOINT}/repositories" "${configs[@]}" || return 1
  [[ -n ${rest_server_ip} ]] || return 1
  code=$(curl -sS --max-time 2 -o /dev/null -w '%{http_code}' \
    "http://${rest_server_ip}:8000/") || return 1
  # 401 is expected at the unauthenticated root. A 500 is never readiness.
  [[ ${code} == 200 || ${code} == 401 ]]
}

if server_ready; then
  echo "Rest Server uses the current backup filesystem."
  exit 0
fi
echo "Recreating Rest Server to attach the current backup filesystem."
systemctl reset-failed rack-rest-server.service
systemctl restart rack-rest-server.service
for _ in {1..10}; do
  if server_ready; then
    echo "Rest Server storage recovered."
    exit 0
  fi
  sleep 2
done
echo "Rest Server is not ready; mini-PC backup will not be invoked." >&2
exit 1
