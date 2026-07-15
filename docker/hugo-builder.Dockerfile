# syntax=docker/dockerfile:1
#
# Reproducible builder for the first website. It combines the exact Hugo
# extended release required by the project with Node 24 for Tailwind CSS 4.
# The image is built natively on the Raspberry Pi (arm64).
FROM node:24-bookworm-slim

ARG HUGO_VERSION=0.163.3
ARG TARGETARCH

RUN set -eux; \
    case "${TARGETARCH}" in \
      arm64) hugo_arch=arm64 ;; \
      amd64) hugo_arch=amd64 ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl git; \
    curl --fail --location --silent --show-error \
      --output /tmp/hugo.deb \
      "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_extended_${HUGO_VERSION}_linux-${hugo_arch}.deb"; \
    dpkg --install /tmp/hugo.deb; \
    rm -f /tmp/hugo.deb; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /work
