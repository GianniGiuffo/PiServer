#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on the Debian 13 mini PC." >&2
  exit 1
fi
TARGET_USER=${1:?Usage: sudo bash scripts/install-cockpit-files.sh <linux-admin>}
if [[ ${TARGET_USER} == root ]] || ! id "${TARGET_USER}" >/dev/null 2>&1; then
  echo "Choose an existing non-root administrator with a Linux password and sudo access." >&2
  exit 1
fi
sudo -l -U "${TARGET_USER}" >/dev/null
source /etc/os-release
if [[ ${ID} != debian || ${VERSION_ID} != 13 ]]; then
  echo "This installer targets Debian 13 (trixie)." >&2
  exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
source "${SCRIPT_DIR}/read-stack-path.sh"
DATA_DIR=$(read_stack_value "${REPO_DIR}/.env" DATA_DIR)
TAILSCALE_FQDN=$(read_stack_value "${REPO_DIR}/.env" TAILSCALE_FQDN)
if [[ ${DATA_DIR} != /* || ${DATA_DIR} == / || ${DATA_DIR} == *'|'* ]]; then
  echo "DATA_DIR must be an absolute application-state directory." >&2
  exit 1
fi
actual_fqdn=$(tailscale status --json | jq -r 'select(.BackendState == "Running") | .Self.DNSName // empty')
if [[ ${TAILSCALE_FQDN} != "${actual_fqdn%.}" ]]; then
  echo "TAILSCALE_FQDN must match this authenticated Tailscale host." >&2
  exit 1
fi
tailscale serve status --json | python3 "${SCRIPT_DIR}/configure-cockpit.py" \
  --check-serve "${TAILSCALE_FQDN}"

# Bind to loopback BEFORE apt can start Cockpit on its default public socket.
install -d -m 0755 /etc/systemd/system/cockpit.socket.d /etc/cockpit
install -m 0644 "${REPO_DIR}/config/cockpit/listen.conf" \
  /etc/systemd/system/cockpit.socket.d/listen.conf
python3 "${SCRIPT_DIR}/configure-cockpit.py" --fqdn "${TAILSCALE_FQDN}" --user "${TARGET_USER}"
systemctl daemon-reload

if ! apt-cache policy | grep 'trixie-backports' >/dev/null; then
  printf '%s\n' 'deb https://deb.debian.org/debian trixie-backports main' \
    > /etc/apt/sources.list.d/piserver-cockpit-backports.list
fi
apt-get update
# cockpit-system contains the browser shell required to open Files after login.
# No storage/sharing plugins or recommended host managers are installed.
apt-get install -y --no-install-recommends -o Dpkg::Options::=--force-confold \
  -t trixie-backports cockpit-ws cockpit-bridge cockpit-system cockpit-files
systemctl stop cockpit.service
systemctl enable --now cockpit.socket
systemctl restart cockpit.socket

STATUS_DIR=${DATA_DIR}/monitoring
install -d -m 0755 -o root -g root "${STATUS_DIR}"
for unit in cockpit-status.service cockpit-status.timer; do
  sed -e "s|__REPO_DIR__|${REPO_DIR}|g" -e "s|__STATUS_DIR__|${STATUS_DIR}|g" \
    "${REPO_DIR}/systemd/${unit}" > "/etc/systemd/system/${unit}"
done
systemctl daemon-reload
# Add only this route; preserve all existing Serve endpoints.
tailscale serve --bg --https=8465 --set-path=/ http://127.0.0.1:9090
systemctl enable --now cockpit-status.timer
systemctl start cockpit-status.service
echo "Cockpit Files: https://${TAILSCALE_FQDN}:8465/files/"
echo "Log in as ${TARGET_USER} with the Linux password and enable Administrative access."
