#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo after copying the historical repository." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
set -a
# shellcheck disable=SC1090
source /etc/rack-pi/backup.env
set +a

bash "${SCRIPT_DIR}/check-backup-disk.sh" --initialize-marker
umask 077
install -d -m 0700 -o root -g root \
  "${BACKUP_MOUNTPOINT}/repositories/minipc" \
  "${BACKUP_MOUNTPOINT}/repositories/rack-pi" \
  /etc/rack-pi

if [[ ! -f ${MINIPC_STATE_REPOSITORY}/config ]]; then
  echo "Historical repository missing at ${MINIPC_STATE_REPOSITORY}." >&2
  echo "Copy it from the old USB device before running this script." >&2
  exit 1
fi
if [[ ! -r ${MINIPC_STATE_PASSWORD_FILE} ]]; then
  echo "Copy the historical Restic password to ${MINIPC_STATE_PASSWORD_FILE}." >&2
  exit 1
fi
restic -r "${MINIPC_STATE_REPOSITORY}" \
  --password-file "${MINIPC_STATE_PASSWORD_FILE}" snapshots --latest 1 >/dev/null

generate_password() {
  local path=${1:?path}
  if [[ ! -s ${path} ]]; then
    openssl rand -base64 48 > "${path}"
  fi
  chown root:root "${path}"
  chmod 0600 "${path}"
}
generate_password "${PHOTOS_PASSWORD_FILE}"
generate_password "${RACK_PI_PASSWORD_FILE}"

if [[ ! -f ${PHOTOS_REPOSITORY}/config ]]; then
  install -d -m 0700 "${PHOTOS_REPOSITORY}"
  restic -r "${PHOTOS_REPOSITORY}" \
    --password-file "${PHOTOS_PASSWORD_FILE}" init
fi
if [[ ! -f ${RACK_PI_REPOSITORY}/config ]]; then
  install -d -m 0700 "${RACK_PI_REPOSITORY}"
  restic -r "${RACK_PI_REPOSITORY}" \
    --password-file "${RACK_PI_PASSWORD_FILE}" init
fi

server_password_file=/etc/rack-pi/rest-server-minipc-password
if [[ ! -s ${server_password_file} ]]; then
  openssl rand -hex 32 > "${server_password_file}"
fi
chmod 0600 "${server_password_file}"
chown root:root "${server_password_file}"
printf '%s\n' "$(<"${server_password_file}")" | \
  htpasswd -B -i -c /etc/rack-pi/rest-server.htpasswd minipc >/dev/null
chmod 0600 /etc/rack-pi/rest-server.htpasswd
chown root:root /etc/rack-pi/rest-server.htpasswd

echo "Repositories verified/initialized."
echo "Use ${server_password_file} only when building the mini-PC REST URLs."
echo "Keep all three Restic password files in an independent password manager."
