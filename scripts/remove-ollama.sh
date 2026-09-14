#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/remove-ollama.sh --confirm" >&2
  exit 1
fi
if [[ ${1:-} != --confirm ]]; then
  echo "This permanently removes the Ollama containers, image and every local model." >&2
  echo "Re-run with --confirm to continue." >&2
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
ENV_FILE=${REPO_DIR}/.env
[[ -r ${ENV_FILE} ]] || { echo "Missing readable ${ENV_FILE}" >&2; exit 1; }

read_env_value() {
  local key=${1:?missing key}
  local line value
  line=$(grep -m1 -E "^[[:space:]]*${key}=" "${ENV_FILE}" || true)
  [[ -n ${line} ]] || return 1
  value=${line#*=}
  value=${value#"${value%%[![:space:]]*}"}
  value=${value%"${value##*[![:space:]]}"}
  if [[ (${value:0:1} == '"' && ${value: -1} == '"') || \
        (${value:0:1} == "'" && ${value: -1} == "'") ]]; then
    value=${value:1:-1}
  fi
  printf '%s' "${value}"
}

DATA_DIR=$(read_env_value DATA_DIR) || { echo "Set DATA_DIR in .env" >&2; exit 1; }
OLLAMA_IMAGE=$(read_env_value OLLAMA_IMAGE || true)
data_root=$(realpath -m -- "${DATA_DIR}")
model_dir=$(realpath -m -- "${DATA_DIR}/ollama")
if [[ ${model_dir} != "${data_root}/ollama" || ${data_root} == / ]]; then
  echo "Refusing unsafe model path: ${model_dir}" >&2
  exit 1
fi

legacy_services=(ollama ollama-model-init ai-ops-bridge ai-ops-telegram)
containers=()
for service in "${legacy_services[@]}"; do
  while IFS= read -r container; do
    [[ -n ${container} ]] && containers+=("${container}")
  done < <(
    docker container ls -aq \
      --filter label=com.docker.compose.project=raspberry-server \
      --filter label=com.docker.compose.service="${service}"
  )
done
if ((${#containers[@]})); then
  docker container rm --force "${containers[@]}"
fi

if [[ -d ${model_dir} ]]; then
  find "${model_dir}" -xdev -mindepth 1 -delete
  rmdir -- "${model_dir}"
fi

if [[ -n ${OLLAMA_IMAGE} ]] && docker image inspect "${OLLAMA_IMAGE}" >/dev/null 2>&1; then
  docker image rm "${OLLAMA_IMAGE}" || \
    echo "Ollama image is still referenced elsewhere and was left in place." >&2
fi

systemctl disable --now ai-ops-gateway.service >/dev/null 2>&1 || true
legacy_unit=/etc/systemd/system/ai-ops-gateway.service
if [[ -f ${legacy_unit} ]]; then
  rm -f -- "${legacy_unit}"
  systemctl daemon-reload
fi

echo "Ollama, local model data and legacy local-AI runtime removed."
