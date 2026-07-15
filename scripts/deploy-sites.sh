#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
"${SCRIPT_DIR}/deploy-site.sh" site-1
"${SCRIPT_DIR}/deploy-site.sh" site-2
