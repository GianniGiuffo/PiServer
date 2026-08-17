#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env
# shellcheck source=scripts/read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

# A disabled media stack is an explicit administrator choice. The recovery
# timer must never override it while storage is being replaced or maintained.
if ! systemctl is-enabled --quiet media-stack.service; then
  echo "Media stack is disabled; automatic recovery skipped."
  exit 0
fi

if systemctl is-active --quiet media-stack.service; then
  echo "Media stack is already active."
  exit 0
fi

if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}; automatic recovery skipped." >&2
  exit 0
fi

MEDIA_DIR=$(read_stack_value "${STACK_ENV}" MEDIA_DIR)
if [[ ${MEDIA_DIR} != /* || ${MEDIA_DIR} == "/" ]]; then
  echo "Invalid MEDIA_DIR; automatic recovery skipped." >&2
  exit 0
fi

# Accessing the marker activates x-systemd.automount. If no automount unit is
# present, try the matching /etc/fstab entry explicitly. Expected storage
# absence is not a timer failure and will be retried at the next interval.
if ! timeout 30s stat -- "${MEDIA_DIR}/.piserver-media" >/dev/null 2>&1; then
  timeout 30s mount "${MEDIA_DIR}" >/dev/null 2>&1 || true
fi
if ! timeout 30s bash "${SCRIPT_DIR}/check-media-mount.sh"; then
  bash "${SCRIPT_DIR}/refresh-media-status.sh" || true
  echo "Media storage is not ready; automatic recovery will retry."
  exit 0
fi

bash "${SCRIPT_DIR}/refresh-media-status.sh"
systemctl reset-failed media-stack.service
systemctl start media-stack.service
echo "Media stack recovered."
