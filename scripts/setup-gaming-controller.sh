#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo on the mini PC." >&2
  exit 1
fi

TARGET_USER=${1:?Usage: sudo bash scripts/setup-gaming-controller.sh <linux-user> [--enable]}
MODE=${2:-prepare}
if [[ ${MODE} != prepare && ${MODE} != --enable ]]; then
  echo "Second argument must be --enable when the Windows and host-key steps are complete." >&2
  exit 1
fi
if ! id "${TARGET_USER}" >/dev/null 2>&1; then
  echo "User '${TARGET_USER}' does not exist." >&2
  exit 1
fi
TARGET_GROUP=$(id -gn "${TARGET_USER}")

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
CONFIG_DIR=/etc/raspberry-server/gaming
CONFIG_FILE=${CONFIG_DIR}/gaming.env
STATE_DIR=/var/lib/raspberry-server/gaming-controller
UNIT=gaming-pc-controller.service

install -d -m 0750 -o root -g "${TARGET_GROUP}" "${CONFIG_DIR}"
install -d -m 0750 -o "${TARGET_USER}" -g "${TARGET_GROUP}" "${STATE_DIR}"

if [[ ! -e ${CONFIG_FILE} ]]; then
  install -m 0640 -o root -g "${TARGET_GROUP}" \
    "${REPO_DIR}/config/gaming/gaming.env.example" "${CONFIG_FILE}"
  echo "Created ${CONFIG_FILE}; replace every example value before enabling."
fi

if [[ ! -s ${CONFIG_DIR}/id_ed25519 ]]; then
  ssh-keygen -q -t ed25519 -N '' \
    -C 'piserver-gaming-controller' -f "${CONFIG_DIR}/id_ed25519"
fi
if [[ ! -s ${CONFIG_DIR}/session-token ]]; then
  umask 0027
  openssl rand -hex 32 > "${CONFIG_DIR}/session-token"
fi

chown root:"${TARGET_GROUP}" \
  "${CONFIG_FILE}" "${CONFIG_DIR}/id_ed25519" \
  "${CONFIG_DIR}/id_ed25519.pub" "${CONFIG_DIR}/session-token"
chmod 0640 "${CONFIG_FILE}" "${CONFIG_DIR}/id_ed25519" "${CONFIG_DIR}/session-token"
chmod 0644 "${CONFIG_DIR}/id_ed25519.pub"

sed \
  -e "s|__RPI_USER__|${TARGET_USER}|g" \
  -e "s|__RPI_GROUP__|${TARGET_GROUP}|g" \
  -e "s|__REPO_DIR__|${REPO_DIR}|g" \
  "${REPO_DIR}/systemd/${UNIT}" > "/etc/systemd/system/${UNIT}"
chmod 0644 "/etc/systemd/system/${UNIT}"
systemctl daemon-reload

if [[ ${MODE} == --enable ]]; then
  if [[ ! -s ${CONFIG_DIR}/known_hosts ]]; then
    echo "Pin the Windows OpenSSH host key before enabling the controller." >&2
    exit 1
  fi
  runuser -u "${TARGET_USER}" -- \
    /usr/bin/python3 "${REPO_DIR}/scripts/gaming-pc-controller.py" \
    --check-config "${CONFIG_FILE}"
  systemctl enable --now "${UNIT}"
  echo "${UNIT} enabled and started."
else
  cat <<EOF

Gaming controller material prepared. It is not enabled yet.

1. Edit ${CONFIG_FILE}.
2. Copy these two files securely to the Windows PC:
   ${CONFIG_DIR}/id_ed25519.pub
   ${CONFIG_DIR}/session-token
3. Complete the Windows setup in docs/cloud-gaming.md.
4. Pin the Windows host key with scripts/pin-gaming-pc-host-key.sh.
5. Re-run: sudo bash scripts/setup-gaming-controller.sh ${TARGET_USER} --enable
EOF
fi
