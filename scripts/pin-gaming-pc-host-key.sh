#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on the mini PC." >&2
  exit 1
fi

HOST=${1:?Usage: sudo bash scripts/pin-gaming-pc-host-key.sh <windows-tailscale-ip> <SHA256:fingerprint> [port]}
EXPECTED=${2:?Usage: sudo bash scripts/pin-gaming-pc-host-key.sh <windows-tailscale-ip> <SHA256:fingerprint> [port]}
PORT=${3:-22}

if [[ ! ${HOST} =~ ^100\.([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})$ ]] ||
   (( 10#${BASH_REMATCH[1]:-0} < 64 || 10#${BASH_REMATCH[1]:-0} > 127 ||
      10#${BASH_REMATCH[2]:-0} > 255 || 10#${BASH_REMATCH[3]:-0} > 255 )); then
  echo "Expected the Windows PC Tailscale IPv4 address." >&2
  exit 1
fi
if [[ ! ${EXPECTED} =~ ^SHA256:[A-Za-z0-9+/]{40,44}$ ]]; then
  echo "Expected an SHA256 OpenSSH fingerprint." >&2
  exit 1
fi
if [[ ! ${PORT} =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  echo "Invalid SSH port." >&2
  exit 1
fi

CONFIG_DIR=/etc/raspberry-server/gaming
if [[ ! -d ${CONFIG_DIR} ]]; then
  echo "Run setup-gaming-controller.sh first." >&2
  exit 1
fi
TARGET_GROUP=$(stat -c '%G' "${CONFIG_DIR}")
temporary=$(mktemp)
trap 'rm -f -- "${temporary}"' EXIT

ssh-keyscan -T 8 -p "${PORT}" -t ed25519 "${HOST}" 2>/dev/null > "${temporary}"
if [[ ! -s ${temporary} ]]; then
  echo "No Ed25519 host key received from ${HOST}:${PORT}." >&2
  exit 1
fi
ACTUAL=$(ssh-keygen -lf "${temporary}" -E sha256 | awk 'NR == 1 { print $2 }')
if [[ ${ACTUAL} != "${EXPECTED}" ]]; then
  echo "Host key mismatch: expected ${EXPECTED}, received ${ACTUAL}." >&2
  exit 1
fi

install -m 0640 -o root -g "${TARGET_GROUP}" \
  "${temporary}" "${CONFIG_DIR}/known_hosts"
echo "Pinned ${HOST}:${PORT} with fingerprint ${ACTUAL}."
