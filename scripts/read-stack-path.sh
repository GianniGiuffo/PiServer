#!/usr/bin/env bash
# This file is sourced by other scripts. It deliberately reads only one
# non-secret value instead of sourcing the Compose .env file.

read_stack_value() {
  local env_file=${1:?env file is required}
  local key=${2:?key is required}
  local line value

  line=$(grep -m 1 -E "^${key}=" "${env_file}" || true)
  value=${line#*=}
  value=${value%$'\r'}

  if [[ ${value} == \"*\" && ${value} == *\" ]]; then
    value=${value:1:-1}
  elif [[ ${value} == \'*\' && ${value} == *\' ]]; then
    value=${value:1:-1}
  fi

  if [[ -z ${value} ]]; then
    echo "Missing ${key} in ${env_file}." >&2
    return 1
  fi
  printf '%s\n' "${value}"
}
