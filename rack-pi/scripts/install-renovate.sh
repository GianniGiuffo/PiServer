#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID} -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
[[ $(dpkg --print-architecture) == arm64 ]] || {
  echo "Use the documented 64-bit Raspberry installation." >&2
  exit 1
}
command -v docker >/dev/null
command -v python3 >/dev/null
install -d -m 0700 -o root -g root /etc/rack-pi
install -d -m 0750 -o 1000 -g 1000 /var/lib/rack-pi-renovate
if [[ ! -e /etc/rack-pi/renovate.env ]]; then
  install -m 0600 -o root -g root "${RACK_DIR}/config/renovate.env.example" \
    /etc/rack-pi/renovate.env
fi
for unit in rack-renovate.service rack-renovate.timer; do
  sed "s|__RACK_DIR__|${RACK_DIR}|g" "${RACK_DIR}/systemd/${unit}" \
    > "/etc/systemd/system/${unit}"
done
python3 "${RACK_DIR}/scripts/run-renovate.py" --init-status
systemctl daemon-reload
echo "Renovate installed. Fill /etc/rack-pi/renovate.env, run --dry-run, then"
echo "test the service manually before enabling rack-renovate.timer."
