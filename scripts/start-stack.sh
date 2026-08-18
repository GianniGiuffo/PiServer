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
      nextcloud-postgres nextcloud-redis nextcloud nextcloud-readonly nextcloud-cron
      jellyfin streamingcommunity immich-postgres immich-redis immich-server
      lidarr slskd navidrome aurral
    )
    ;;
  automation)
    COMPOSE=("${BASE[@]}" -f "${REPO_DIR}/compose.automation.yaml")
    SERVICES=(n8n-postgres ollama ollama-model-init searxng ai-ops-bridge n8n)
    if [[ -r /etc/raspberry-server/ai-ops-telegram-bot-token ]]; then
      SERVICES+=(ai-ops-telegram)
    else
      echo "AI Ops Telegram bot token is absent; its polling bridge will not start." >&2
    fi
    ;;
  *)
    echo "Unknown stack '${STACK}'." >&2
    exit 1
    ;;
esac

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d "${SERVICES[@]}"
"${COMPOSE[@]}" ps
