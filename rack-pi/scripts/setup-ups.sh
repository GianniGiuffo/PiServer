#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on rack-pi." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RACK_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=/etc/rack-pi/ups.env
[[ -r ${ENV_FILE} ]] || {
  echo "Install and fill ${RACK_DIR}/config/ups.env.example as ${ENV_FILE}." >&2
  exit 1
}
# shellcheck disable=SC1090
source "${ENV_FILE}"

: "${UPS_NAME:?Set UPS_NAME}"
: "${UPS_RACK_SHUTDOWN_PERCENT:?Set UPS_RACK_SHUTDOWN_PERCENT}"
: "${MINIPC_POWER_SSH_KEY:?Set MINIPC_POWER_SSH_KEY}"
: "${MINIPC_POWER_KNOWN_HOSTS:?Set MINIPC_POWER_KNOWN_HOSTS}"
: "${MINIPC_LAN_MAC:?Set MINIPC_LAN_MAC}"
: "${MINIPC_LAN_BROADCAST:?Set MINIPC_LAN_BROADCAST}"
UPS_CRITICAL_CONFIRM_SECONDS=${UPS_CRITICAL_CONFIRM_SECONDS:-30}
[[ ${UPS_NAME} =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Invalid UPS_NAME." >&2; exit 1; }
[[ ${UPS_RACK_SHUTDOWN_PERCENT} =~ ^[0-9]+$ ]] &&
  (( UPS_RACK_SHUTDOWN_PERCENT >= 5 && UPS_RACK_SHUTDOWN_PERCENT <= 50 )) || {
  echo "UPS_RACK_SHUTDOWN_PERCENT must be between 5 and 50." >&2
  exit 1
}
[[ -s ${MINIPC_POWER_SSH_KEY} && -s ${MINIPC_POWER_KNOWN_HOSTS} ]] || {
  echo "Install the dedicated mini-PC power key and pin its host key first." >&2
  exit 1
}
bash "${SCRIPT_DIR}/ups-orchestrator.sh" --check

apt-get update
apt-get install -y --no-install-recommends \
  iputils-ping nut nut-client nut-server usbutils wakeonlan

sed "s|__RACK_DIR__|${RACK_DIR}|g" \
  "${RACK_DIR}/systemd/rack-ups-orchestrator.service" > \
  /etc/systemd/system/rack-ups-orchestrator.service
systemctl daemon-reload

monitor_password=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
install -d -m 0750 -o root -g nut /etc/nut
cat > /etc/nut/nut.conf <<'EOF'
MODE=standalone
EOF
cat > /etc/nut/ups.conf <<EOF
[${UPS_NAME}]
    driver = usbhid-ups
    port = auto
    vendorid = 0463
    desc = "Eaton UPS del rack"
    ignorelb
    override.battery.charge.low = ${UPS_RACK_SHUTDOWN_PERCENT}
    override.battery.runtime.low = -1
    offdelay = 30
    ondelay = 60
EOF
cat > /etc/nut/upsd.conf <<'EOF'
LISTEN 127.0.0.1 3493
EOF
cat > /etc/nut/upsd.users <<EOF
[rackmon]
    password = ${monitor_password}
    upsmon primary
EOF
cat > /etc/nut/upsmon.conf <<EOF
MONITOR ${UPS_NAME}@localhost 1 rackmon ${monitor_password} primary
MINSUPPLIES 1
SHUTDOWNCMD "/usr/bin/bash ${RACK_DIR}/scripts/ups-orchestrator.sh --final-shutdown"
POWERDOWNFLAG /etc/killpower
FINALDELAY 5
DEADTIME 25
HOSTSYNC 15
EOF
chown root:nut /etc/nut/nut.conf /etc/nut/ups.conf /etc/nut/upsd.conf \
  /etc/nut/upsd.users /etc/nut/upsmon.conf
chmod 0640 /etc/nut/nut.conf /etc/nut/ups.conf /etc/nut/upsd.conf \
  /etc/nut/upsd.users /etc/nut/upsmon.conf

# The UPS is normally already plugged in while NUT is installed. Re-apply the
# package's USB permissions now so the first driver start does not require a
# physical unplug/replug cycle.
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --attr-match=idVendor=0463 --action=change
udevadm settle
systemctl restart nut-driver@"${UPS_NAME}".service 2>/dev/null || true
systemctl restart nut-server.service nut-monitor.service
ups_ready=false
for _attempt in {1..15}; do
  if upsc "${UPS_NAME}@localhost" battery.charge >/dev/null 2>&1; then
    ups_ready=true
    break
  fi
  sleep 2
done
[[ ${ups_ready} == true ]] || {
  echo "NUT did not reconnect to ${UPS_NAME} within 30 seconds." >&2
  exit 1
}
systemctl enable rack-ups-orchestrator.service
systemctl restart rack-ups-orchestrator.service

echo "Eaton UPS monitoring enabled. Current values:"
upsc "${UPS_NAME}@localhost" | grep -E '^(battery\.charge|battery\.runtime|ups\.load|ups\.status):' || true
