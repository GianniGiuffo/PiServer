#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this once with sudo: sudo ./scripts/bootstrap.sh" >&2
  exit 1
fi

ARCH=$(dpkg --print-architecture)
if [[ ${ARCH} != "arm64" && ${ARCH} != "amd64" ]]; then
  echo "This setup supports only Debian-family arm64 or amd64 hosts." >&2
  exit 1
fi

TARGET_USER=${SUDO_USER:-${SERVER_USER:-${RPI_USER:-}}}
if [[ -z ${TARGET_USER} || ${TARGET_USER} == "root" ]]; then
  echo "Run through sudo from the normal administrator user, or set SERVER_USER." >&2
  exit 1
fi

if ! id "${TARGET_USER}" >/dev/null 2>&1; then
  echo "User '${TARGET_USER}' does not exist." >&2
  exit 1
fi
TARGET_GROUP=$(id -gn "${TARGET_USER}")

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
chmod 0755 "${SCRIPT_DIR}"/*.sh

# Use Docker's Debian apt repository rather than the convenience script so host
# upgrades remain visible and reviewable.
. /etc/os-release
CODENAME=${VERSION_CODENAME:?Cannot determine the Debian codename}

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates cifs-utils curl git gnupg intel-gpu-tools jq \
  nfs-common openssh-client restic rsync

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.list <<EOF
deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${CODENAME} stable
EOF

curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.noarmor.gpg" \
  -o /usr/share/keyrings/tailscale-archive-keyring.gpg
curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.tailscale-keyring.list" \
  -o /etc/apt/sources.list.d/tailscale.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin tailscale
systemctl enable --now docker tailscaled
usermod -aG docker "${TARGET_USER}"

# Application state stays on the local SSD. User media is mounted separately at
# /srv/media and is never created here: doing so could hide a failed NAS mount.
install -d -m 0750 /srv/raspberry-server/data
install -d -m 0750 /srv/raspberry-server/staging
install -d -m 0750 -o 1000 -g 1000 /srv/raspberry-server/data/n8n/n8n
install -d -m 0755 -o "${TARGET_USER}" -g "${TARGET_GROUP}" /srv/raspberry-server/sites
install -d -m 0750 -o "${TARGET_USER}" -g "${TARGET_GROUP}" \
  /srv/raspberry-server/data/jellyfin/config \
  /srv/raspberry-server/data/jellyfin/cache
install -d -m 0750 /srv/raspberry-server/data/uptime-kuma
install -d -m 0755 /srv/media
install -d -m 0755 /etc/raspberry-server/sites

bash "${SCRIPT_DIR}/install-systemd.sh" "${TARGET_USER}" "${TARGET_GROUP}"

cat <<EOF

Base installation complete.

1. Log out and back in so '${TARGET_USER}' receives the docker group.
2. Copy ${REPO_DIR}/.env.example to ${REPO_DIR}/.env, set values, then chmod 600 it.
3. Authenticate Tailscale: sudo tailscale up --ssh --hostname=mini-pc
4. Run scripts/preflight.sh and follow docs/first-boot.md.
5. Do not enable media-stack.service until /srv/media is a verified network mount.
EOF
