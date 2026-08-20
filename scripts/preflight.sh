#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env

if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}; copy .env.example and fill it first." >&2
  exit 1
fi

if grep -Eq 'CHANGE_ME|render-group-number' "${STACK_ENV}"; then
  echo "The .env file still contains CHANGE_ME or render-group-number." >&2
  exit 1
fi

required=(awk docker tailscale restic findmnt flock timeout)
for command_name in "${required[@]}"; do
  command -v "${command_name}" >/dev/null || {
    echo "Missing required command: ${command_name}" >&2
    exit 1
  }
done

if ! timeout --foreground --kill-after=1s 1s true; then
  echo "The installed timeout command lacks the required GNU options." >&2
  exit 1
fi

docker compose --project-directory "${REPO_DIR}" \
  -f "${REPO_DIR}/compose.yaml" config --quiet
docker compose --project-directory "${REPO_DIR}" \
  -f "${REPO_DIR}/compose.yaml" \
  -f "${REPO_DIR}/compose.media.yaml" config --quiet
docker compose --project-directory "${REPO_DIR}" \
  -f "${REPO_DIR}/compose.yaml" \
  -f "${REPO_DIR}/compose.automation.yaml" config --quiet

if ss -H -lntu '( sport = :53 )' 2>/dev/null | grep -q .; then
  echo "WARNING: port 53 is already in use; Pi-hole cannot bind it until the conflict is removed." >&2
fi

if [[ ! -e /dev/dri/renderD128 ]]; then
  echo "WARNING: /dev/dri/renderD128 is absent; Jellyfin Quick Sync will not start." >&2
fi

echo "Compose and host preflight completed."
