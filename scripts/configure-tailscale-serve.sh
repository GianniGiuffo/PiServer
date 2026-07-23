#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo after Tailscale is authenticated." >&2
  exit 1
fi

if ! tailscale status --json >/dev/null; then
  echo "Tailscale is not connected. Run: sudo tailscale up --ssh --hostname=rpi-server" >&2
  exit 1
fi

# Tailscale Serve uses a separate virtual network interface, so it does not
# collide with Caddy's public port 443. The longest matching path wins.
tailscale serve reset
tailscale serve --bg --https=443 --set-path=/ http://127.0.0.1:8082
# Pi-hole uses root-relative /admin/ links, so it needs its own HTTPS port
# rather than a subpath alongside Nextcloud.
tailscale serve --bg --https=8444 --set-path=/ http://127.0.0.1:8081
# Hugo generates root-relative links such as /posts/... and /css/.... Serving
# the static site on its own HTTPS port keeps all of those links on Caddy
# instead of falling through to Nextcloud on port 443.
tailscale serve --bg --https=8443 --set-path=/ http://127.0.0.1:8083

echo
echo "Private services configured. Confirm with: tailscale serve status"
