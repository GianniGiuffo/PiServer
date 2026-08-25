#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo after authenticating Tailscale." >&2
  exit 1
fi
if [[ $(tailscale status --json | jq -r '.BackendState // empty') != Running ]]; then
  echo "Authenticate first: sudo tailscale up --ssh --hostname=rack-pi" >&2
  exit 1
fi

tailscale set --accept-dns=false
tailscale serve reset
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:3000
tailscale serve --bg --https=8444 --set-path=/ http://127.0.0.1:8081
tailscale serve --bg --https=8448 --set-path=/ http://127.0.0.1:3001

echo "Tailnet-only services: Homepage 443, Pi-hole 8444, Uptime Kuma 8448."
echo "Rest Server is not proxied: it binds directly to the rack-pi Tailscale IP."
