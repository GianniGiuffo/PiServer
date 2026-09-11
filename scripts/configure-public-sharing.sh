#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env

# Read only the two non-secret hostnames; never source the credential-bearing
# Compose environment file into the shell.
# shellcheck source=read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}; configure it before public sharing." >&2
  exit 1
fi

NEXTCLOUD_PUBLIC_DOMAIN=$(read_stack_value "${STACK_ENV}" NEXTCLOUD_PUBLIC_DOMAIN)
NAVIDROME_PUBLIC_DOMAIN=$(read_stack_value "${STACK_ENV}" NAVIDROME_PUBLIC_DOMAIN)

validate_hostname() {
  local name=${1:?hostname is required}
  local value=${2:?value is required}

  if [[ ! ${value} =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ ]] ||
     [[ ${value} != *.* ]] || [[ ${value} == *..* ]]; then
    echo "${name} must be a hostname without scheme, port, path or spaces." >&2
    exit 1
  fi
}

validate_hostname NEXTCLOUD_PUBLIC_DOMAIN "${NEXTCLOUD_PUBLIC_DOMAIN}"
validate_hostname NAVIDROME_PUBLIC_DOMAIN "${NAVIDROME_PUBLIC_DOMAIN}"

COMPOSE=(
  docker compose --project-directory "${REPO_DIR}"
  -f "${REPO_DIR}/compose.yaml"
  -f "${REPO_DIR}/compose.media.yaml"
)
OCC=("${COMPOSE[@]}" exec -T --user www-data nextcloud php occ)
LOCAL_APP_DIR=${REPO_DIR}/config/nextcloud-apps/public_share_domain
CONTAINER_APP_DIR=/var/www/html/custom_apps/public_share_domain

"${COMPOSE[@]}" config --quiet

if ! "${COMPOSE[@]}" ps --services --status running | grep -qx nextcloud; then
  echo "Nextcloud is not running; start media-stack.service first." >&2
  exit 1
fi

# A historical OVERWRITEHOST forced every generated URL back to the Tailnet.
# Remove it so public and private browser hostnames can coexist.
if "${OCC[@]}" config:system:get overwritehost >/dev/null 2>&1; then
  "${OCC[@]}" config:system:delete overwritehost
fi

mapfile -t current_domains < <("${OCC[@]}" config:system:get trusted_domains)
domain_present=false
for current_domain in "${current_domains[@]}"; do
  if [[ ${current_domain} == "${NEXTCLOUD_PUBLIC_DOMAIN}" ]]; then
    domain_present=true
    break
  fi
done

if [[ ${domain_present} == false ]]; then
  "${OCC[@]}" config:system:set trusted_domains "${#current_domains[@]}" \
    --value="${NEXTCLOUD_PUBLIC_DOMAIN}"
fi

"${OCC[@]}" config:system:set overwrite.cli.url \
  --value="https://${NEXTCLOUD_PUBLIC_DOMAIN}"
"${OCC[@]}" config:system:set auth.bruteforce.protection.enabled \
  --type=boolean --value=true

# The Files UI intentionally builds copied links from window.location rather
# than using the public URL returned by the OCS API. Install the bundled local
# app into the persistent Nextcloud volume, then enable it. Copying instead of
# bind-mounting keeps the official image's startup permission repair intact.
"${COMPOSE[@]}" exec -T --user root nextcloud \
  mkdir -p "${CONTAINER_APP_DIR}"
"${COMPOSE[@]}" cp "${LOCAL_APP_DIR}/." "nextcloud:${CONTAINER_APP_DIR}"
"${COMPOSE[@]}" exec -T --user root nextcloud \
  chown -R www-data:www-data "${CONTAINER_APP_DIR}"
"${OCC[@]}" app:enable public_share_domain

# Password and expiry stay selectable per link; anonymous uploads are not part
# of this deployment's download-only sharing model.
"${OCC[@]}" config:app:set core shareapi_enforce_links_password --value=no
"${OCC[@]}" config:app:set core shareapi_default_expire_date --value=no
"${OCC[@]}" config:app:set core shareapi_enforce_expire_date --value=no
"${OCC[@]}" config:app:set core shareapi_allow_public_upload --value=no

if "${COMPOSE[@]}" ps --services --status running | grep -qx caddy; then
  "${COMPOSE[@]}" exec -T caddy caddy validate \
    --config /etc/caddy/Caddyfile --adapter caddyfile
fi

cat <<EOF
Public sharing application settings are ready.

Nextcloud: https://${NEXTCLOUD_PUBLIC_DOMAIN}
Navidrome shares: https://${NAVIDROME_PUBLIC_DOMAIN}/share/...

Add both hostnames to the existing Cloudflare Tunnel as Published applications
pointing to http://caddy:80, then run the external-network checks documented in
docs/public-sharing.md.
EOF
