#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run once with sudo from the normal Raspberry administrator." >&2
  exit 1
fi
[[ $(dpkg --print-architecture) == arm64 ]] || {
  echo "Install Raspberry Pi OS Lite 64 bit (arm64)." >&2
  exit 1
}
TARGET_USER=${SUDO_USER:-}
[[ -n ${TARGET_USER} && ${TARGET_USER} != root ]] || {
  echo "Run through sudo from a non-root administrator." >&2
  exit 1
}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
chmod 0755 "${SCRIPT_DIR}"/*.sh
. /etc/os-release
CODENAME=${VERSION_CODENAME:?Cannot determine Debian codename}
ARCH=$(dpkg --print-architecture)
TAILSCALE_DIST=${ID:-debian}
case "${TAILSCALE_DIST}" in
  debian|raspbian) ;;
  *) TAILSCALE_DIST=debian ;;
esac

apt-get update
apt-get install -y --no-install-recommends \
  apache2-utils ca-certificates curl dnsutils e2fsprogs git gnupg jq \
  openssh-client parted python3 restic rsync smartmontools

install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg \
  -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian %s stable\n' \
  "${ARCH}" "${CODENAME}" > /etc/apt/sources.list.d/docker.list
curl -fsSL "https://pkgs.tailscale.com/stable/${TAILSCALE_DIST}/${CODENAME}.noarmor.gpg" \
  -o /usr/share/keyrings/tailscale-archive-keyring.gpg
curl -fsSL "https://pkgs.tailscale.com/stable/${TAILSCALE_DIST}/${CODENAME}.tailscale-keyring.list" \
  -o /etc/apt/sources.list.d/tailscale.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin tailscale
systemctl enable --now docker tailscaled
usermod -aG docker "${TARGET_USER}"

install -d -m 0750 /srv/rack-pi/data
install -d -m 0755 -o root -g root /srv/rack-pi/data/monitoring
install -d -m 0750 -o root -g root /srv/rack-pi/data/pihole
install -d -m 0750 -o 1000 -g 1000 /srv/rack-pi/data/uptime-kuma
install -d -m 0700 -o root -g root /etc/rack-pi /etc/rack-pi/ssh
install -d -m 0755 /mnt/rack-backup
install -d -m 0755 /etc/systemd/journald.conf.d
install -m 0644 "${RACK_DIR}/config/journald/10-rack-pi.conf" \
  /etc/systemd/journald.conf.d/10-rack-pi.conf
systemctl restart systemd-journald

if [[ ! -e /etc/rack-pi/backup.env ]]; then
  install -m 0600 -o root -g root "${RACK_DIR}/config/backup.env.example" \
    /etc/rack-pi/backup.env
fi
if [[ ! -e /etc/rack-pi/orchestrator.env ]]; then
  install -m 0600 -o root -g root "${RACK_DIR}/config/orchestrator.env.example" \
    /etc/rack-pi/orchestrator.env
fi

if [[ ! -s /etc/rack-pi/ssh/minipc-backup ]]; then
  ssh-keygen -q -t ed25519 -N '' -C rack-pi-backup \
    -f /etc/rack-pi/ssh/minipc-backup
fi
chmod 0600 /etc/rack-pi/ssh/minipc-backup
chmod 0644 /etc/rack-pi/ssh/minipc-backup.pub

bash "${SCRIPT_DIR}/install-systemd.sh"
cat <<EOF

rack-pi base installation completed.
1. Copy rack-pi/.env.example to rack-pi/.env and fill it.
2. Authenticate: sudo tailscale up --ssh --hostname=rack-pi
3. Run rack-pi/scripts/preflight.sh and follow docs/rack-pi.md.
4. The public backup key is /etc/rack-pi/ssh/minipc-backup.pub.
EOF
