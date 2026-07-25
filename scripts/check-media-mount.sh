#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env
# shellcheck source=scripts/read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

MEDIA_DIR=$(read_stack_value "${STACK_ENV}" MEDIA_DIR)
if [[ ${MEDIA_DIR} != /* || ${MEDIA_DIR} == "/" ]]; then
  echo "MEDIA_DIR must be a non-root absolute path." >&2
  exit 1
fi
if ! mountpoint -q "${MEDIA_DIR}"; then
  echo "${MEDIA_DIR} is not a mount point; refusing to start media services." >&2
  exit 1
fi
if [[ ! -f ${MEDIA_DIR}/.piserver-media ]]; then
  echo "Missing ${MEDIA_DIR}/.piserver-media marker; refusing to use an unexpected share." >&2
  exit 1
fi
for directory in immich jellyfin nextcloud; do
  if [[ ! -d ${MEDIA_DIR}/${directory} ]]; then
    echo "Missing ${MEDIA_DIR}/${directory}; see docs/storage.md." >&2
    exit 1
  fi
done

echo "Verified media mount: ${MEDIA_DIR}"
