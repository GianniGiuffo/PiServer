#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo after Tailscale is authenticated." >&2
  exit 1
fi

if [[ $(tailscale status --json | jq -r '.BackendState // empty') != "Running" ]]; then
  echo "Tailscale is not connected. Run: sudo tailscale up --ssh --hostname=mini-pc" >&2
  exit 1
fi

# Each application gets a dedicated Tailnet-only HTTPS port because most of
# these applications do not support being hosted below a URL subpath.
tailscale serve reset
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:3000
tailscale serve --bg --https=8443 --set-path=/ http://127.0.0.1:8083
tailscale serve --bg --https=8444 --set-path=/ http://127.0.0.1:8081
tailscale serve --bg --https=8445 --set-path=/ http://127.0.0.1:8082
tailscale serve --bg --https=8446 --set-path=/ http://127.0.0.1:8096
tailscale serve --bg --https=8447 --set-path=/ http://127.0.0.1:2283
tailscale serve --bg --https=8448 --set-path=/ http://127.0.0.1:3001
tailscale serve --bg --https=8449 --set-path=/ http://127.0.0.1:5678
tailscale serve --bg --https=8450 --set-path=/ http://127.0.0.1:8000

echo
echo "Private services configured:"
echo "  443  Homepage"
echo "  8443 private website"
echo "  8444 Pi-hole"
echo "  8445 Nextcloud"
echo "  8446 Jellyfin"
echo "  8447 Immich"
echo "  8448 Uptime Kuma"
echo "  8449 n8n"
echo "  8450 StreamingCommunity downloader"
echo
echo "Confirm with: tailscale serve status"
