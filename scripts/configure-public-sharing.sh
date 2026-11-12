#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env

# Read only the non-secret hostnames; never source the credential-bearing
# Compose environment file into the shell.
# shellcheck source=read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}; configure it before public sharing." >&2
  exit 1
fi

NEXTCLOUD_PUBLIC_DOMAIN=$(read_stack_value "${STACK_ENV}" NEXTCLOUD_PUBLIC_DOMAIN)
TAILSCALE_FQDN=$(read_stack_value "${STACK_ENV}" TAILSCALE_FQDN)

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
validate_hostname TAILSCALE_FQDN "${TAILSCALE_FQDN}"

COMPOSE=(
  docker compose --project-directory "${REPO_DIR}"
  -f "${REPO_DIR}/compose.yaml"
  -f "${REPO_DIR}/compose.media.yaml"
)
OCC=("${COMPOSE[@]}" exec -T --user www-data nextcloud php occ)

"${COMPOSE[@]}" config --quiet

running=$("${COMPOSE[@]}" ps --services --status running)
if ! grep -qx nextcloud <<<"${running}"; then
  echo "Nextcloud is not running; start media-stack.service first." >&2
  exit 1
fi
if ! grep -qx caddy <<<"${running}"; then
  echo "Caddy is not running; start core-stack.service first." >&2
  exit 1
fi

"${COMPOSE[@]}" exec -T caddy caddy validate \
  --config /etc/caddy/Caddyfile --adapter caddyfile

# Fail before changing application settings if the running container still
# uses the old trust settings or if a local config fragment overrides them.
if [[ $("${OCC[@]}" config:system:get trusted_proxies) != "10.203.253.10" ||
      $("${OCC[@]}" config:system:get forwarded_for_headers) != "HTTP_X_FORWARDED_FOR" ||
      $("${OCC[@]}" config:system:get overwriteprotocol) != "https" ||
      $("${COMPOSE[@]}" exec -T nextcloud printenv APACHE_DISABLE_REWRITE_IP) != "1" ]]; then
  echo "Unexpected Nextcloud proxy settings. Recreate Nextcloud and verify its effective configuration." >&2
  exit 1
fi

# A historical OVERWRITEHOST forced every generated URL back to the Tailnet.
# Remove it so public and private browser hostnames can coexist.
overwrite_host=$("${OCC[@]}" config:system:get overwritehost --default-value='')
if [[ -n ${overwrite_host} ]]; then
  "${OCC[@]}" config:system:delete overwritehost
  if [[ -n $("${OCC[@]}" config:system:get overwritehost --default-value='') ]]; then
    echo "A Nextcloud config fragment still overrides the hostname. Remove it before publishing." >&2
    exit 1
  fi
fi

for domain in "${TAILSCALE_FQDN}" "${NEXTCLOUD_PUBLIC_DOMAIN}"; do
  domains=$("${OCC[@]}" config:system:get trusted_domains --output=json)
  if ! jq -e --arg domain "${domain}" 'any(.[]; . == $domain)' <<<"${domains}" >/dev/null; then
    # PHP may encode sparse numeric indexes as an object. Append after the
    # highest index so an existing internal domain is never overwritten.
    index=$(jq -er 'if type == "array" then length else (keys | map(tonumber) | max // -1) + 1 end' <<<"${domains}")
    "${OCC[@]}" config:system:set trusted_domains "${index}" --value="${domain}"
  fi
done

"${OCC[@]}" config:system:set overwrite.cli.url \
  --value="https://${NEXTCLOUD_PUBLIC_DOMAIN}"
"${OCC[@]}" config:system:set auth.bruteforce.protection.enabled \
  --type=boolean --value=true
"${OCC[@]}" config:system:set auth.bruteforce.protection.testing \
  --type=boolean --value=false
"${OCC[@]}" config:system:set ratelimit.protection.enabled \
  --type=boolean --value=true

# Disable the old clipboard override if it was installed. Leave its files
# on existing servers for rollback and leave share tokens and policies intact.
apps=$("${OCC[@]}" app:list --output=json)
legacy_enabled=$(jq -r '(.enabled // {}) | has("public_share_domain")' <<<"${apps}")
if [[ ${legacy_enabled} == true ]]; then
  "${OCC[@]}" app:disable public_share_domain
fi

# Anonymous folder uploads remain disabled.
"${OCC[@]}" config:app:set core shareapi_allow_public_upload --value=no

cat <<EOF
Nextcloud is prepared for https://${NEXTCLOUD_PUBLIC_DOMAIN}.
Follow docs/public-sharing.md to check MFA and Cloudflare rules, enable the
public hostname and run the external checks.
EOF
