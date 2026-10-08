#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on the mini PC." >&2
  exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
source "${SCRIPT_DIR}/read-stack-path.sh"
DATA_DIR=$(read_stack_value "${REPO_DIR}/.env" DATA_DIR)
TAILSCALE_FQDN=$(read_stack_value "${REPO_DIR}/.env" TAILSCALE_FQDN)
exec python3 "${SCRIPT_DIR}/collect-cockpit-status.py" \
  --status-file "${DATA_DIR}/monitoring/cockpit.json" --fqdn "${TAILSCALE_FQDN}"
