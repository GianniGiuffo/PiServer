#!/usr/bin/env bash
set -euo pipefail

ENV_FILE=${UPS_ENV_FILE:-/etc/rack-pi/ups.env}
STATUS_FILE=${UPS_STATUS_FILE:-/srv/rack-pi/data/monitoring/ups.json}
STATE_DIR=${UPS_STATE_DIR:-/var/lib/rack-pi-ups}
[[ -r ${ENV_FILE} ]] || { echo "Missing ${ENV_FILE}." >&2; exit 1; }
# shellcheck disable=SC1090
source "${ENV_FILE}"

: "${UPS_NAME:?Set UPS_NAME}"
: "${UPS_MINIPC_SHUTDOWN_PERCENT:?Set UPS_MINIPC_SHUTDOWN_PERCENT}"
: "${UPS_RACK_SHUTDOWN_PERCENT:?Set UPS_RACK_SHUTDOWN_PERCENT}"
: "${MINIPC_POWER_SSH_HOST:?Set MINIPC_POWER_SSH_HOST}"
: "${MINIPC_POWER_SSH_PORT:?Set MINIPC_POWER_SSH_PORT}"
: "${MINIPC_POWER_SSH_USER:?Set MINIPC_POWER_SSH_USER}"
: "${MINIPC_POWER_SSH_KEY:?Set MINIPC_POWER_SSH_KEY}"
: "${MINIPC_POWER_KNOWN_HOSTS:?Set MINIPC_POWER_KNOWN_HOSTS}"
: "${MINIPC_LAN_MAC:?Set MINIPC_LAN_MAC}"
: "${MINIPC_LAN_BROADCAST:?Set MINIPC_LAN_BROADCAST}"
UPS_POLL_SECONDS=${UPS_POLL_SECONDS:-10}
UPS_CRITICAL_CONFIRM_SECONDS=${UPS_CRITICAL_CONFIRM_SECONDS:-30}
UPS_MINIPC_GRACE_SECONDS=${UPS_MINIPC_GRACE_SECONDS:-90}

for value in UPS_MINIPC_SHUTDOWN_PERCENT UPS_RACK_SHUTDOWN_PERCENT UPS_POLL_SECONDS UPS_CRITICAL_CONFIRM_SECONDS UPS_MINIPC_GRACE_SECONDS MINIPC_POWER_SSH_PORT; do
  [[ ${!value} =~ ^[0-9]+$ ]] || { echo "${value} must be numeric." >&2; exit 1; }
done
[[ ${UPS_NAME} =~ ^[A-Za-z0-9_-]+$ ]] || { echo "Invalid UPS_NAME." >&2; exit 1; }
[[ ${MINIPC_POWER_SSH_USER} =~ ^[a-z_][a-z0-9_-]*$ ]] || {
  echo "Invalid MINIPC_POWER_SSH_USER." >&2; exit 1;
}
[[ ${MINIPC_POWER_SSH_HOST} =~ ^100\.([0-9]{1,3}\.){2}[0-9]{1,3}$ ]] || {
  echo "MINIPC_POWER_SSH_HOST must be a Tailscale IPv4 address." >&2; exit 1;
}
[[ ${MINIPC_LAN_MAC} =~ ^([[:xdigit:]]{2}:){5}[[:xdigit:]]{2}$ ]] || {
  echo "Invalid MINIPC_LAN_MAC." >&2; exit 1;
}
[[ ${MINIPC_LAN_BROADCAST} =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || {
  echo "Invalid MINIPC_LAN_BROADCAST." >&2; exit 1;
}
[[ ${MINIPC_POWER_SSH_KEY} == /etc/rack-pi/ssh/* &&
   ${MINIPC_POWER_KNOWN_HOSTS} == /etc/rack-pi/ssh/* ]] || {
  echo "UPS SSH files must stay under /etc/rack-pi/ssh." >&2; exit 1;
}
(( UPS_MINIPC_SHUTDOWN_PERCENT <= 100 && UPS_RACK_SHUTDOWN_PERCENT >= 5 &&
   UPS_POLL_SECONDS >= 5 && UPS_CRITICAL_CONFIRM_SECONDS >= 20 &&
   UPS_MINIPC_GRACE_SECONDS >= 30 &&
   MINIPC_POWER_SSH_PORT >= 1 && MINIPC_POWER_SSH_PORT <= 65535 )) || {
  echo "UPS thresholds, timing or SSH port are outside safe limits." >&2; exit 1;
}
(( UPS_RACK_SHUTDOWN_PERCENT < UPS_MINIPC_SHUTDOWN_PERCENT )) || {
  echo "The Raspberry shutdown threshold must be lower than the mini-PC threshold." >&2
  exit 1
}

install -d -m 0755 "$(dirname -- "${STATUS_FILE}")"
install -d -m 0700 "${STATE_DIR}"
shutdown_marker=${STATE_DIR}/minipc-shutdown
final_lock=${STATE_DIR}/final-shutdown.lock

if [[ ${1:-} == --check ]]; then
  exit 0
fi

ssh_poweroff() {
  ssh -n -T -o BatchMode=yes -o ConnectTimeout=10 -o ConnectionAttempts=1 \
    -o StrictHostKeyChecking=yes -o UserKnownHostsFile="${MINIPC_POWER_KNOWN_HOSTS}" \
    -i "${MINIPC_POWER_SSH_KEY}" -p "${MINIPC_POWER_SSH_PORT}" \
    "${MINIPC_POWER_SSH_USER}@${MINIPC_POWER_SSH_HOST}" shutdown
}

shutdown_minipc() {
  [[ -e ${shutdown_marker} ]] && return 0
  if ssh_poweroff; then
    touch "${shutdown_marker}"
    logger -t rack-ups "Mini PC shutdown requested at UPS battery threshold."
    return 0
  fi
  logger -t rack-ups "WARNING: mini PC shutdown request failed; it will be retried."
  return 1
}

wake_minipc() {
  wakeonlan -i "${MINIPC_LAN_BROADCAST}" "${MINIPC_LAN_MAC}" >/dev/null
  logger -t rack-ups "Wake-on-LAN sent to mini PC after mains restoration."
}

write_status() {
  local charge=$1 ups_status=$2 runtime=$3 load=$4 state power temporary
  if [[ " ${ups_status} " == *" OB "* ]]; then power=Batteria; else power=Rete; fi
  if [[ " ${ups_status} " == *" LB "* ]]; then
    state="Batteria critica"
  elif [[ ${power} == Batteria ]]; then
    state="Blackout"
  elif [[ " ${ups_status} " == *" CHRG "* ]]; then
    state="In carica"
  else
    state="Online"
  fi
  temporary=${STATUS_FILE}.tmp
  printf '{"charge_percent":%s,"power":"%s","state":"%s","runtime_seconds":%s,"load_percent":%s,"updated_at":"%s"}\n' \
    "${charge:-null}" "${power}" "${state}" "${runtime:-null}" "${load:-null}" \
    "$(date --iso-8601=seconds)" > "${temporary}"
  chmod 0644 "${temporary}"
  mv -f "${temporary}" "${STATUS_FILE}"
}

write_unavailable_status() {
  local temporary=${STATUS_FILE}.tmp
  printf '{"charge_percent":null,"power":"Non disponibile","state":"Non disponibile","runtime_seconds":null,"load_percent":null,"updated_at":"%s"}\n' \
    "$(date --iso-8601=seconds)" > "${temporary}"
  chmod 0644 "${temporary}"
  mv -f "${temporary}" "${STATUS_FILE}"
}

final_shutdown() {
  local requested_at elapsed remaining
  exec 9>"${final_lock}"
  flock -n 9 || exit 0
  shutdown_minipc || true
  requested_at=$(stat -c %Y "${shutdown_marker}" 2>/dev/null || date +%s)
  elapsed=$(( $(date +%s) - requested_at ))
  remaining=$(( UPS_MINIPC_GRACE_SECONDS - elapsed ))
  if (( remaining > 0 )); then
    logger -t rack-ups "Waiting ${remaining}s for the mini PC before shutting down rack-pi."
    sleep "${remaining}"
  fi
  logger -t rack-ups "UPS critical: shutting down rack-pi; NUT will turn off the UPS output."
  systemctl poweroff
}

if [[ ${1:-} == --final-shutdown ]]; then
  final_shutdown
  exit 0
fi

wake_counter=0
critical_since=0
fsd_requested=0
last_ups_status=
last_logged_charge=
while true; do
  if snapshot=$(upsc "${UPS_NAME}@localhost" 2>/dev/null); then
    charge=$(awk -F': ' '$1 == "battery.charge" {print int($2); exit}' <<<"${snapshot}")
    ups_status=$(awk -F': ' '$1 == "ups.status" {print $2; exit}' <<<"${snapshot}")
    runtime=$(awk -F': ' '$1 == "battery.runtime" {print int($2); exit}' <<<"${snapshot}")
    load=$(awk -F': ' '$1 == "ups.load" {print $2 + 0; exit}' <<<"${snapshot}")
    [[ ${charge} =~ ^[0-9]+$ ]] || charge=
    [[ ${runtime} =~ ^[0-9]+$ ]] || runtime=
    [[ ${load} =~ ^[0-9]+([.][0-9]+)?$ ]] || load=
    if [[ -n ${ups_status} ]]; then
      write_status "${charge}" "${ups_status}" "${runtime}" "${load}"
    else
      write_unavailable_status
    fi

    if [[ ${ups_status} != "${last_ups_status}" ]]; then
      logger -t rack-ups "UPS status changed: status=${ups_status:-unknown} charge=${charge:-unknown}% runtime=${runtime:-unknown}s load=${load:-unknown}%."
      last_ups_status=${ups_status}
    fi
    if [[ " ${ups_status} " == *" OB "* && ${charge:-} != "${last_logged_charge}" ]]; then
      logger -t rack-ups "UPS on battery: charge=${charge:-unknown}% runtime=${runtime:-unknown}s load=${load:-unknown}%."
      last_logged_charge=${charge:-unknown}
    fi

    if [[ " ${ups_status} " == *" OB "* && -n ${charge} ]] &&
       (( charge <= UPS_MINIPC_SHUTDOWN_PERCENT )); then
      shutdown_minipc || true
    fi
    if [[ " ${ups_status} " == *" OB "* && -n ${charge} ]] &&
       (( charge <= UPS_RACK_SHUTDOWN_PERCENT )); then
      current_time=$(date +%s)
      if (( critical_since == 0 )); then
        critical_since=${current_time}
        logger -t rack-ups "UPS critical candidate: charge=${charge}%; waiting ${UPS_CRITICAL_CONFIRM_SECONDS}s for confirmation."
      elif (( current_time - critical_since >= UPS_CRITICAL_CONFIRM_SECONDS && fsd_requested == 0 )); then
        logger -t rack-ups "UPS remained at or below ${UPS_RACK_SHUTDOWN_PERCENT}% for ${UPS_CRITICAL_CONFIRM_SECONDS}s; requesting NUT forced shutdown."
        fsd_requested=1
        upsmon -c fsd
      fi
    else
      if (( critical_since != 0 && fsd_requested == 0 )); then
        logger -t rack-ups "UPS critical candidate cleared before confirmation: status=${ups_status:-unknown} charge=${charge:-unknown}%."
      fi
      critical_since=0
      fsd_requested=0
    fi
    if [[ " ${ups_status} " == *" OL "* && -e ${shutdown_marker} ]]; then
      if (( wake_counter % 6 == 0 )); then wake_minipc || true; fi
      ((wake_counter+=1))
      if ping -c 1 -W 2 "${MINIPC_POWER_SSH_HOST}" >/dev/null 2>&1; then
        rm -f "${shutdown_marker}"
        wake_counter=0
        logger -t rack-ups "Mini PC is online again."
      fi
    else
      wake_counter=0
    fi
  else
    write_unavailable_status
    logger -t rack-ups "WARNING: NUT data unavailable for ${UPS_NAME}."
  fi
  sleep "${UPS_POLL_SECONDS}"
done
