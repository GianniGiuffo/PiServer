#!/usr/bin/env bash
set -euo pipefail

STACK=${1:?Usage: update-images.sh <core|media|automation>}
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
      nextcloud-postgres nextcloud-redis nextcloud nextcloud-readonly nextcloud-cron
      jellyfin streamingcommunity immich-postgres immich-redis immich-server
      lidarr slskd navidrome aurral
    )
    ;;
  automation)
    COMPOSE=("${BASE[@]}" -f "${REPO_DIR}/compose.automation.yaml")
    SERVICES=(n8n-postgres ollama ollama-model-init searxng ai-ops-bridge n8n ai-ops-telegram)
    ;;
  *)
    echo "Unknown stack '${STACK}'." >&2
    exit 1
    ;;
esac

echo "Run and verify a Restic backup before continuing."
echo "This command pulls only the versions already selected in .env."
"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" pull "${SERVICES[@]}"
echo "Images downloaded. Recreate the selected stack with:"
echo "  sudo systemctl restart ${STACK}-stack.service"
