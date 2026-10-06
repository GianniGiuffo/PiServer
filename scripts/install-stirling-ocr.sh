#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_DIR=$(cd -- "${SCRIPT_DIR}/.." && pwd)

# Run as the administrator with Docker access. The language data is independent
# of user documents; use upstream's fixed 4.1.0 tessdata_fast release.
docker compose --project-directory "${REPO_DIR}" -f "${REPO_DIR}/compose.yaml" \
  run --rm --no-deps --user 0 --entrypoint /bin/sh stirling-pdf -ec '
    for language in eng ita osd; do
      curl --fail --location --retry 3 \
        "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/4.1.0/${language}.traineddata" \
        --output "/usr/share/tessdata/${language}.traineddata.tmp"
      mv "/usr/share/tessdata/${language}.traineddata.tmp" \
         "/usr/share/tessdata/${language}.traineddata"
      chmod 0644 "/usr/share/tessdata/${language}.traineddata"
    done
    tesseract --list-langs --tessdata-dir /usr/share/tessdata
  '
