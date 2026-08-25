#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on rack-pi." >&2
  exit 1
fi
HOST=${1:?Usage: pin-minipc-host-key.sh <mini-pc-tailscale-ip> <SHA256:fingerprint> [port]}
EXPECTED=${2:?Usage: pin-minipc-host-key.sh <mini-pc-tailscale-ip> <SHA256:fingerprint> [port]}
PORT=${3:-2222}
[[ ${HOST} =~ ^100\.([0-9]{1,3}\.){2}[0-9]{1,3}$ ]] || {
  echo "Expected a Tailscale IPv4 address." >&2
  exit 1
}
[[ ${EXPECTED} == SHA256:* ]] || { echo "Expected SHA256 fingerprint." >&2; exit 1; }
[[ ${PORT} =~ ^[0-9]+$ ]] && (( PORT >= 1 && PORT <= 65535 )) || {
  echo "Invalid SSH port." >&2
  exit 1
}

temporary=$(mktemp /tmp/minipc-known-host.XXXXXX)
trap 'rm -f -- "${temporary}"' EXIT
ssh-keyscan -T 10 -p "${PORT}" -t ed25519 "${HOST}" > "${temporary}" 2>/dev/null
[[ -s ${temporary} ]] || { echo "No Ed25519 SSH host key received." >&2; exit 1; }
actual=$(ssh-keygen -lf "${temporary}" -E sha256 | awk '{print $2}')
if [[ ${actual} != "${EXPECTED}" ]]; then
  echo "Host key mismatch: expected ${EXPECTED}, received ${actual}." >&2
  exit 1
fi
install -d -m 0700 -o root -g root /etc/rack-pi/ssh
install -m 0600 -o root -g root "${temporary}" /etc/rack-pi/ssh/known_hosts
echo "Pinned mini-PC host key ${actual}."
