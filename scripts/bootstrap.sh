#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run this once with sudo: sudo ./scripts/bootstrap.sh" >&2
  exit 1
fi

if [[ $(dpkg --print-architecture) != "arm64" ]]; then
  echo "This setup requires 64-bit Raspberry Pi OS (arm64)." >&2
  exit 1
fi

TARGET_USER=${SUDO_USER:-${RPI_USER:-}}
if [[ -z ${TARGET_USER} || ${TARGET_USER} == "root" ]]; then
  echo "Run through sudo from the normal Raspberry Pi user, or set RPI_USER." >&2
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

# Raspberry Pi OS 64-bit follows Debian arm64 packages. Do not use Docker's
# convenience script: the apt repository keeps upgrades visible and reviewable.
. /etc/os-release
CODENAME=${VERSION_CODENAME:?Cannot determine the Debian/Raspberry Pi OS codename}

apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git gnupg jq openssh-client restic rsync

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.list <<EOF
deb [arch=arm64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${CODENAME} stable
EOF

curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.noarmor.gpg" \
  -o /usr/share/keyrings/tailscale-archive-keyring.gpg
curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.tailscale-keyring.list" \
  -o /etc/apt/sources.list.d/tailscale.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin tailscale
systemctl enable --now docker tailscaled
usermod -aG docker "${TARGET_USER}"

# Put state on the SSD mounted at /srv. Configuration remains in Git; state does not.
install -d -m 0750 /srv/raspberry-server/data
install -d -m 0750 /srv/raspberry-server/staging
install -d -m 0755 -o "${TARGET_USER}" -g "${TARGET_GROUP}" /srv/raspberry-server/sites
install -d -m 0755 /etc/raspberry-server/sites

bash "${SCRIPT_DIR}/install-systemd.sh" "${TARGET_USER}" "${TARGET_GROUP}"

cat <<EOF

Base installation complete.

1. Log out and back in so '${TARGET_USER}' receives the docker group.
2. Copy ${REPO_DIR}/.env.example to ${REPO_DIR}/.env, set values, then chmod 600 it.
3. Authenticate Tailscale: sudo tailscale up --ssh --hostname=rpi-server
4. Follow docs/first-boot.md before starting the containers or enabling site deployment.
EOF
