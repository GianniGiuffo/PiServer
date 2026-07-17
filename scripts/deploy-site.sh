#!/usr/bin/env bash
set -euo pipefail

SITE=${1:?Usage: deploy-site.sh <site-1|site-2>}
case "${SITE}" in
  site-1|site-2) ;;
  *) echo "Unknown site '${SITE}'." >&2; exit 1 ;;
esac

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env
CONFIG="/etc/raspberry-server/sites/${SITE}.env"
if [[ ! -r ${CONFIG} ]]; then
  echo "Skipping ${SITE}: ${CONFIG} does not exist or is unreadable." >&2
  exit 0
fi
if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}." >&2
  exit 1
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

# Docker Compose accepts values which are not valid Bash assignments. The
# deploy only needs SITES_DIR, so never source passwords and tokens from the
# whole stack .env file.
read_stack_path() {
  local key=${1:?key is required}
  local line value
  line=$(grep -m 1 -E "^${key}=" "${STACK_ENV}" || true)
  value=${line#*=}
  value=${value%$'\r'}

  if [[ ${value} == \"*\" && ${value} == *\" ]]; then
    value=${value:1:-1}
  elif [[ ${value} == \'*\' && ${value} == *\' ]]; then
    value=${value:1:-1}
  fi

  if [[ -z ${value} ]]; then
    echo "Missing ${key} in ${STACK_ENV}." >&2
    exit 1
  fi
  printf '%s\n' "${value}"
}

SITES_DIR=$(read_stack_path SITES_DIR)
SITE_ROOT="${SITES_DIR}/${SITE}"
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

# The timer polls GitHub frequently, but a build is needed only for a new
# commit. This keeps the Pi idle between pushes instead of rebuilding on every
# timer run.
CURRENT_RELEASE=$(readlink -f -- "${SITE_ROOT}/current" 2>/dev/null || true)
if [[ ${CURRENT_RELEASE} == "${RELEASE}" && -d ${RELEASE} ]]; then
  echo "${SITE} is already deployed at ${REVISION}."
  exit 0
fi

rm -rf "${RELEASE}"
mkdir -p "${RELEASE}"

# The build runs in a disposable multi-architecture image; Node/Hugo/etc. do not
# need to be installed on the Pi host. Images and commands are chosen per site.
docker run --rm --init \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp \
  --env npm_config_cache=/tmp/npm-cache \
  --volume "${CHECKOUT}:/work" \
  --workdir /work \
  --entrypoint /bin/sh \
  "${BUILD_IMAGE}" -lc "${BUILD_COMMAND}"

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
