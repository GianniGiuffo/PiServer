#!/usr/bin/env bash
set -euo pipefail

SITE=${1:?Usage: deploy-site.sh <site-1|site-2>}
case "${SITE}" in
  site-1|site-2) ;;
  *) echo "Unknown site '${SITE}'." >&2; exit 1 ;;
esac

CONFIG="/etc/raspberry-server/sites/${SITE}.env"
if [[ ! -r ${CONFIG} ]]; then
  echo "Skipping ${SITE}: ${CONFIG} does not exist or is unreadable." >&2
  exit 0
fi

# Site configuration is administrator-owned. It intentionally holds BUILD_COMMAND,
# which executes only code from the repository owner selected in this file.
# shellcheck disable=SC1090
source "${CONFIG}"
: "${REPOSITORY:?Missing REPOSITORY in ${CONFIG}}"
: "${BRANCH:?Missing BRANCH in ${CONFIG}}"
: "${BUILD_IMAGE:?Missing BUILD_IMAGE in ${CONFIG}}"
: "${BUILD_COMMAND:?Missing BUILD_COMMAND in ${CONFIG}}"
: "${PUBLISH_DIR:?Missing PUBLISH_DIR in ${CONFIG}}"

if [[ ${PUBLISH_DIR} = /* || ${PUBLISH_DIR} == *".."* ]]; then
  echo "PUBLISH_DIR must be a relative path without '..'." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/.env"
set +a

SITE_ROOT="${SITES_DIR:?SITES_DIR is missing from .env}/${SITE}"
CHECKOUT="${SITE_ROOT}/checkout"
RELEASES="${SITE_ROOT}/releases"
LOCK="/tmp/raspberry-server-${SITE}.lock"

exec 9>"${LOCK}"
flock -n 9 || exit 0

mkdir -p "${RELEASES}"

if [[ ! -d ${CHECKOUT}/.git ]]; then
  rm -rf "${CHECKOUT}"
  git clone --single-branch --branch "${BRANCH}" "${REPOSITORY}" "${CHECKOUT}"
else
  git -C "${CHECKOUT}" fetch --prune origin "${BRANCH}"
  git -C "${CHECKOUT}" reset --hard FETCH_HEAD
fi

REVISION=$(git -C "${CHECKOUT}" rev-parse --short=12 HEAD)
RELEASE="${RELEASES}/${REVISION}"
rm -rf "${RELEASE}"
mkdir -p "${RELEASE}"

# The build runs in a disposable multi-architecture image; Node/Hugo/etc. do not
# need to be installed on the Pi host. Images and commands are chosen per site.
docker run --rm --init \
  --user "$(id -u):$(id -g)" \
  --volume "${CHECKOUT}:/work" \
  --workdir /work \
  "${BUILD_IMAGE}" /bin/sh -lc "${BUILD_COMMAND}"

if [[ ! -d ${CHECKOUT}/${PUBLISH_DIR} ]]; then
  echo "Build succeeded but ${PUBLISH_DIR} was not produced." >&2
  exit 1
fi

rsync -a --delete "${CHECKOUT}/${PUBLISH_DIR}/" "${RELEASE}/"
ln -sfn "releases/${REVISION}" "${SITE_ROOT}/current.next"
mv -Tf "${SITE_ROOT}/current.next" "${SITE_ROOT}/current"

# Keep the currently served release and the three previous ones for a quick rollback.
find "${RELEASES}" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
  | sort -nr | tail -n +5 | cut -d' ' -f2- | xargs -r rm -rf --

echo "${SITE} deployed at ${REVISION}."
