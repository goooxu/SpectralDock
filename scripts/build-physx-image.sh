#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

docker build \
  --pull \
  --file "${ROOT}/Dockerfile.physx" \
  --tag "${PHYSX_IMAGE}" \
  "${ROOT}"
