#!/usr/bin/env bash
set -euo pipefail

REPO_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
APP_DIR=/var/www/html/custom_apps/brevo_admin_link
COMPOSE=(docker compose --project-directory "${REPO_DIR}"
  -f "${REPO_DIR}/compose.yaml" -f "${REPO_DIR}/compose.media.yaml")

"${COMPOSE[@]}" exec -T --user www-data nextcloud mkdir -p "${APP_DIR}"
"${COMPOSE[@]}" cp "${REPO_DIR}/config/nextcloud-apps/brevo_admin_link/." "nextcloud:${APP_DIR}"
"${COMPOSE[@]}" exec -T --user www-data nextcloud php -l "${APP_DIR}/lib/Settings/Brevo.php"
"${COMPOSE[@]}" exec -T --user www-data nextcloud php -l "${APP_DIR}/templates/admin.php"
"${COMPOSE[@]}" exec -T --user www-data nextcloud php occ app:enable brevo_admin_link
