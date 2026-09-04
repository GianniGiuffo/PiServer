#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=${RACK_DIR}/.env
[[ -r ${ENV_FILE} ]] || { echo "Missing ${ENV_FILE}." >&2; exit 1; }
if grep -Eq 'CHANGE_ME|example-tailnet' "${ENV_FILE}"; then
  echo "rack-pi/.env still contains placeholders." >&2
  exit 1
fi
[[ $(dpkg --print-architecture) == arm64 ]] || {
  echo "rack-pi requires the 64-bit arm64 OS image." >&2
  exit 1
}
[[ $(hostnamectl --static) == rack-pi ]] || {
  echo "Set the operating-system hostname to rack-pi before continuing." >&2
  exit 1
}
for command_name in docker tailscale restic findmnt flock timeout jq ssh python3 curl; do
  command -v "${command_name}" >/dev/null || {
    echo "Missing command: ${command_name}" >&2
    exit 1
  }
done

docker compose --project-directory "${RACK_DIR}" \
  -f "${RACK_DIR}/compose.yaml" config --quiet
if ss -H -lntu '( sport = :53 )' 2>/dev/null | grep -q .; then
  if docker compose --project-directory "${RACK_DIR}" \
      -f "${RACK_DIR}/compose.yaml" ps --services --status running | \
      grep -qx pihole; then
    echo "Port 53 is occupied by the expected running Pi-hole container."
  else
    echo "WARNING: port 53 is occupied by a process other than this running Pi-hole."
  fi
fi

configured_ip=$(grep -m1 '^RACK_PI_TAILSCALE_IP=' "${ENV_FILE}" | cut -d= -f2- | tr -d '\r')
actual_ip=$(tailscale ip -4 2>/dev/null || true)
if [[ -n ${actual_ip} && ${configured_ip} != "${actual_ip}" ]]; then
  echo "RACK_PI_TAILSCALE_IP=${configured_ip}, but Tailscale reports ${actual_ip}." >&2
  exit 1
fi

if [[ -r /etc/rack-pi/backup.env ]]; then
  bash "${SCRIPT_DIR}/check-backup-disk.sh" || \
    echo "WARNING: backup disk is not ready; core services can still start."
fi
echo "rack-pi preflight completed."
