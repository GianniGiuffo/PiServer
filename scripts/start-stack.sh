#!/usr/bin/env bash
set -euo pipefail

STACK=${1:?Usage: start-stack.sh <core|media|automation>}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
BASE=(docker compose --project-directory "${REPO_DIR}" -f "${REPO_DIR}/compose.yaml")

case "${STACK}" in
  core)
    COMPOSE=("${BASE[@]}")
    SERVICES=()
    ;;
  media)
    bash "${SCRIPT_DIR}/check-media-mount.sh"
    COMPOSE=("${BASE[@]}" -f "${REPO_DIR}/compose.media.yaml")
    SERVICES=(
      nextcloud-postgres nextcloud-redis nextcloud nextcloud-cron
      jellyfin immich-postgres immich-redis immich-server
    )
    ;;
  automation)
    COMPOSE=("${BASE[@]}" -f "${REPO_DIR}/compose.automation.yaml")
    SERVICES=(n8n-postgres ollama n8n)
    ;;
  *)
    echo "Unknown stack '${STACK}'." >&2
    exit 1
    ;;
esac

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d "${SERVICES[@]}"
"${COMPOSE[@]}" ps
