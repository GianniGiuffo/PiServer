#!/usr/bin/env bash
set -euo pipefail

# Keep the plugin artifact reproducible and verify both the strong digest and
# Jellyfin catalog checksum before installing it.
PLUGIN_VERSION=3.0.0.2
PLUGIN_URL="https://github.com/JellyPlugins/jellyfin-helper/releases/download/${PLUGIN_VERSION}/JellyfinHelper_${PLUGIN_VERSION}.zip"
PLUGIN_SHA256=692d108b71e3755471aa6d2ffa0f475bbc93f21dd069270b648105e9fecdf025
PLUGIN_MD5=974ff1d2c486431f2cac0b9a79e9d2e6
PLUGIN_SOURCE_URL="https://github.com/JellyPlugins/jellyfin-helper/archive/refs/tags/${PLUGIN_VERSION}.tar.gz"
PLUGIN_SOURCE_SHA256=cfb9c2daf321590cf924eeba6922c342e5d3647cbf32d62f2dea8bade8a8e4c8
PATCH_LEVEL=italian-react-discovery-4
# Jellyfin Helper uses File Transformation to expose its Discovery entry in
# the read-only jellyfin-web image. Pin the Jellyfin 12.1 build as a runtime
# support dependency instead of allowing a catalog update to select an ABI.
TRANSFORMATION_VERSION=3.0.1.0
TRANSFORMATION_URL="https://github.com/IAmParadox27/jellyfin-plugin-file-transformation/releases/download/${TRANSFORMATION_VERSION}/Release-12.1.0.zip"
TRANSFORMATION_SHA256=c1318b2438f4c0dbfd46850bcbd3a5c18ecaf6f873a4790318693e0d3dbaa7b3
TRANSFORMATION_MD5=1451642c8dc6f036cb00aa703a9f0834
# The 12.1 File Transformation release declares Newtonsoft.Json but omits the
# DLL from its archive. Install the exact NuGet dependency declared in its
# deps.json so Jellyfin Helper can register the index.html transformation.
NEWTONSOFT_VERSION=13.0.1
NEWTONSOFT_URL="https://api.nuget.org/v3-flatcontainer/newtonsoft.json/${NEWTONSOFT_VERSION}/newtonsoft.json.${NEWTONSOFT_VERSION}.nupkg"
NEWTONSOFT_SHA256=2b6b52556e27e1b7913f33eedeb95568110c746bd64afff74357f1683878323a

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)
STACK_ENV=${REPO_DIR}/.env
# shellcheck source=scripts/read-stack-path.sh
source "${SCRIPT_DIR}/read-stack-path.sh"

for command in curl docker python3 sha256sum md5sum tar; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "Missing required command: ${command}" >&2
    exit 1
  fi
done
if [[ ! -r ${STACK_ENV} ]]; then
  echo "Missing ${STACK_ENV}." >&2
  exit 1
fi

DATA_DIR=$(read_stack_value "${STACK_ENV}" DATA_DIR)
CONFIG_DIR=${DATA_DIR}/jellyfin/config
PLUGIN_ROOT=${CONFIG_DIR}/plugins
PLUGIN_DIR=${PLUGIN_ROOT}/JellyfinHelper_${PLUGIN_VERSION}
TRANSFORMATION_DIR=${PLUGIN_ROOT}/FileTransformation_${TRANSFORMATION_VERSION}
BACKUP_ROOT=${CONFIG_DIR}/plugin-backups
BASE=(docker compose --project-directory "${REPO_DIR}" -f "${REPO_DIR}/compose.yaml")
MEDIA=("${BASE[@]}" -f "${REPO_DIR}/compose.media.yaml")

server_info=$(curl -fsS http://127.0.0.1:8096/System/Info/Public)
server_version=$(printf '%s' "${server_info}" | python3 -c \
  'import json,sys; print(json.load(sys.stdin).get("Version", ""))')
if [[ ${server_version} != 12.* ]]; then
  echo "Jellyfin Helper ${PLUGIN_VERSION} requires Jellyfin 12.x; found '${server_version}'." >&2
  exit 1
fi

helper_current=false
transformation_current=false
if [[ -r ${PLUGIN_DIR}/meta.json ]] \
  && grep -q "\"version\"[[:space:]]*:[[:space:]]*\"${PLUGIN_VERSION}\"" "${PLUGIN_DIR}/meta.json" \
  && [[ -r ${PLUGIN_DIR}/.piserver-discovery-patch ]] \
  && grep -qx "${PATCH_LEVEL}" "${PLUGIN_DIR}/.piserver-discovery-patch"; then
  helper_current=true
fi
if [[ -r ${TRANSFORMATION_DIR}/Jellyfin.Plugin.FileTransformation.dll \
  && -r ${TRANSFORMATION_DIR}/Newtonsoft.Json.dll ]]; then
  transformation_current=true
fi
if [[ ${helper_current} == true && ${transformation_current} == true ]]; then
  echo "Jellyfin Helper ${PLUGIN_VERSION} and File Transformation ${TRANSFORMATION_VERSION} are already installed."
  exit 0
fi

work_dir=$(mktemp -d)
was_running=false
backup_dir=
transformation_backup_dir=
cleanup() {
  rm -rf -- "${work_dir}"
}
trap cleanup EXIT

archive=${work_dir}/JellyfinHelper.zip
extracted=${work_dir}/helper
source_archive=${work_dir}/JellyfinHelper-source.tar.gz
source_dir=${work_dir}/source
transformation_archive=${work_dir}/FileTransformation.zip
transformation_extracted=${work_dir}/transformation
newtonsoft_archive=${work_dir}/Newtonsoft.Json.nupkg
newtonsoft_extracted=${work_dir}/newtonsoft
if [[ ${helper_current} == false ]]; then
  curl --proto '=https' --tlsv1.2 -fsSL "${PLUGIN_URL}" -o "${archive}"
  printf '%s  %s\n' "${PLUGIN_SHA256}" "${archive}" | sha256sum --check --status
  printf '%s  %s\n' "${PLUGIN_MD5}" "${archive}" | md5sum --check --status
  mkdir -p "${extracted}"
  python3 -m zipfile -e "${archive}" "${extracted}"
  for required in Jellyfin.Plugin.JellyfinHelper.dll meta.json logo.png; do
    if [[ ! -f ${extracted}/${required} ]]; then
      echo "Plugin archive is missing ${required}." >&2
      exit 1
    fi
  done

  # Helper 3.0.0.2 does not map Italian Jellyfin genres to TMDb and its web
  # integration still depends on Custom Tabs, which has no Jellyfin 12 build.
  # Build the pinned source with the audited PiServer compatibility files.
  curl --proto '=https' --tlsv1.2 -fsSL "${PLUGIN_SOURCE_URL}" -o "${source_archive}"
  printf '%s  %s\n' "${PLUGIN_SOURCE_SHA256}" "${source_archive}" | sha256sum --check --status
  mkdir -p "${source_dir}"
  tar -xzf "${source_archive}" -C "${source_dir}"
  source_root=${source_dir}/jellyfin-helper-${PLUGIN_VERSION}
  cp -- "${REPO_DIR}/patches/jellyfin-helper/TmdbGenreMap-${PLUGIN_VERSION}.cs" \
    "${source_root}/Jellyfin.Plugin.JellyfinHelper/Services/Seerr/Discovery/TmdbGenreMap.cs"
  cp -- "${REPO_DIR}/patches/jellyfin-helper/discovery-sidebar-${PLUGIN_VERSION}.js" \
    "${source_root}/Jellyfin.Plugin.JellyfinHelper/js/discovery-sidebar.js"
  cp -- "${REPO_DIR}/patches/jellyfin-helper/Plugin-${PLUGIN_VERSION}.cs" \
    "${source_root}/Jellyfin.Plugin.JellyfinHelper/Plugin.cs"
  # Upstream 3.0.0.2 hard-codes a 10-item visible list, a 20-item persisted
  # pool and a 20-item enrichment budget. Keep all three aligned so Discovery
  # can generate and display the requested 40 useful recommendations.
  python3 - "${source_root}/Jellyfin.Plugin.JellyfinHelper/Services/Seerr/Discovery/SeerrDiscoveryService.cs" <<'PY'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
source = path.read_text(encoding="utf-8")
replacements = {
    "internal const int MaxVisiblePerUser = 10;": "internal const int MaxVisiblePerUser = 40;",
    "private const int MaxPoolPerUser = 20;": "private const int MaxPoolPerUser = 40;",
    "private const int CreditsEnrichmentBudget = 20;": "private const int CreditsEnrichmentBudget = 40;",
}
for old, new in replacements.items():
    if source.count(old) != 1:
        raise SystemExit(f"Expected exactly one pinned Helper constant: {old}")
    source = source.replace(old, new)
path.write_text(source, encoding="utf-8")
PY
  docker run --rm \
    -v "${source_root}:/src" \
    -w /src \
    mcr.microsoft.com/dotnet/sdk:10.0 \
    sh -lc 'dotnet restore Jellyfin.Plugin.JellyfinHelper/Jellyfin.Plugin.JellyfinHelper.csproj && dotnet build Jellyfin.Plugin.JellyfinHelper/Jellyfin.Plugin.JellyfinHelper.csproj -c Release --no-restore'
  cp -- "${source_root}/Jellyfin.Plugin.JellyfinHelper/bin/Release/net10.0/Jellyfin.Plugin.JellyfinHelper.dll" \
    "${extracted}/Jellyfin.Plugin.JellyfinHelper.dll"
  printf '%s\n' "${PATCH_LEVEL}" > "${extracted}/.piserver-discovery-patch"
fi
if [[ ${transformation_current} == false ]]; then
  curl --proto '=https' --tlsv1.2 -fsSL "${TRANSFORMATION_URL}" -o "${transformation_archive}"
  printf '%s  %s\n' "${TRANSFORMATION_SHA256}" "${transformation_archive}" | sha256sum --check --status
  printf '%s  %s\n' "${TRANSFORMATION_MD5}" "${transformation_archive}" | md5sum --check --status
  mkdir -p "${transformation_extracted}"
  python3 -m zipfile -e "${transformation_archive}" "${transformation_extracted}"
  if [[ ! -f ${transformation_extracted}/Jellyfin.Plugin.FileTransformation.dll ]]; then
    echo "File Transformation archive is missing its plugin assembly." >&2
    exit 1
  fi
  curl --proto '=https' --tlsv1.2 -fsSL "${NEWTONSOFT_URL}" -o "${newtonsoft_archive}"
  printf '%s  %s\n' "${NEWTONSOFT_SHA256}" "${newtonsoft_archive}" | sha256sum --check --status
  mkdir -p "${newtonsoft_extracted}"
  python3 -m zipfile -e "${newtonsoft_archive}" "${newtonsoft_extracted}"
  if [[ ! -f ${newtonsoft_extracted}/lib/netstandard2.0/Newtonsoft.Json.dll ]]; then
    echo "Newtonsoft.Json package is missing its netstandard2.0 assembly." >&2
    exit 1
  fi
  cp -- "${newtonsoft_extracted}/lib/netstandard2.0/Newtonsoft.Json.dll" \
    "${transformation_extracted}/Newtonsoft.Json.dll"
fi

if "${MEDIA[@]}" ps --services --status running | grep -qx jellyfin; then
  was_running=true
  "${MEDIA[@]}" stop jellyfin
fi

mkdir -p "${PLUGIN_ROOT}" "${BACKUP_ROOT}"
if [[ ${helper_current} == false ]]; then
  if [[ -e ${PLUGIN_DIR} ]]; then
    backup_dir=${BACKUP_ROOT}/JellyfinHelper-${PLUGIN_VERSION}-$(date -u +%Y%m%dT%H%M%SZ)
    mv -- "${PLUGIN_DIR}" "${backup_dir}"
  fi
  mkdir "${PLUGIN_DIR}"
  cp -a -- "${extracted}/." "${PLUGIN_DIR}/"
fi
if [[ ${transformation_current} == false ]]; then
  if [[ -e ${TRANSFORMATION_DIR} ]]; then
    transformation_backup_dir=${BACKUP_ROOT}/FileTransformation-${TRANSFORMATION_VERSION}-$(date -u +%Y%m%dT%H%M%SZ)
    mv -- "${TRANSFORMATION_DIR}" "${transformation_backup_dir}"
  fi
  mkdir "${TRANSFORMATION_DIR}"
  cp -a -- "${transformation_extracted}/." "${TRANSFORMATION_DIR}/"
fi

# Match the ownership of the persistent Jellyfin configuration. This works for
# both the normal administrator and a root-run recovery.
config_owner=$(stat -c '%u:%g' "${CONFIG_DIR}")
chown -R "${config_owner}" "${PLUGIN_DIR}" "${TRANSFORMATION_DIR}"

if [[ ${was_running} == true ]]; then
  "${MEDIA[@]}" start jellyfin
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8096/health >/dev/null 2>&1; then
      echo "Jellyfin Helper ${PLUGIN_VERSION} and File Transformation ${TRANSFORMATION_VERSION} installed; Jellyfin is healthy."
      exit 0
    fi
    sleep 5
  done

  echo "Jellyfin did not become healthy; rolling back the plugin installation." >&2
  "${MEDIA[@]}" stop jellyfin || true
  if [[ ${helper_current} == false ]]; then
    rm -rf -- "${PLUGIN_DIR}"
    if [[ -n ${backup_dir} && -d ${backup_dir} ]]; then
      mv -- "${backup_dir}" "${PLUGIN_DIR}"
    fi
  fi
  if [[ ${transformation_current} == false ]]; then
    rm -rf -- "${TRANSFORMATION_DIR}"
    if [[ -n ${transformation_backup_dir} && -d ${transformation_backup_dir} ]]; then
      mv -- "${transformation_backup_dir}" "${TRANSFORMATION_DIR}"
    fi
  fi
  "${MEDIA[@]}" start jellyfin || true
  exit 1
fi

echo "Jellyfin Helper ${PLUGIN_VERSION} and File Transformation ${TRANSFORMATION_VERSION} installed. Jellyfin was already stopped."
