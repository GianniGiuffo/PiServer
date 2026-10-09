#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
COMPOSE=(docker compose --project-directory "${REPO_DIR}" -f "${REPO_DIR}/compose.yaml" -f "${REPO_DIR}/compose.media.yaml")

# systemd serializes runs. Never start containers or touch user documents here.
office_id=$("${COMPOSE[@]}" ps --status running -q onlyoffice)
cloud_id=$("${COMPOSE[@]}" ps --status running -q nextcloud)
if [[ -z ${office_id} || -z ${cloud_id} ]]; then
  exit 0
fi
office_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "${office_id}")
if [[ ${office_health} != healthy ]]; then
  exit 0
fi

OCC=("${COMPOSE[@]}" exec -T --user www-data nextcloud php occ)
error=$("${OCC[@]}" config:app:get onlyoffice settings_error --default-value=)
if [[ -z ${error} ]]; then
  exit 0
fi

# The connector's cron stops checking after any failed request. Its official
# check clears the stored error only after a successful end-to-end conversion.
# Do not log the old error: it may contain internal URLs or credentials.
echo "ONLYOFFICE is healthy; rechecking the disabled Nextcloud connector."
timeout 120s "${OCC[@]}" onlyoffice:documentserver --check
