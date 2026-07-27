#!/usr/bin/env bash
set -euo pipefail

STACK=${1:?Usage: stop-stack.sh <core|media|automation>}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
BASE=(docker compose --project-directory "${REPO_DIR}" -f "${REPO_DIR}/compose.yaml")

case "${STACK}" in
  core)
    COMPOSE=("${BASE[@]}")
    SERVICES=()
    ;;
  media)
    COMPOSE=("${BASE[@]}" -f "${REPO_DIR}/compose.media.yaml")
    SERVICES=(
      aurral navidrome lidarr slskd
      streamingcommunity nextcloud-cron nextcloud jellyfin immich-server
      nextcloud-redis nextcloud-postgres immich-redis immich-postgres
    )
    ;;
  automation)
    COMPOSE=("${BASE[@]}" -f "${REPO_DIR}/compose.automation.yaml")
    SERVICES=(n8n ollama n8n-postgres)
    ;;
  *)
    echo "Unknown stack '${STACK}'." >&2
    exit 1
    ;;
esac

if ((${#SERVICES[@]})); then
  "${COMPOSE[@]}" stop "${SERVICES[@]}"
else
  "${COMPOSE[@]}" stop
fi
