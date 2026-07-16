#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

BUILD_TYPE="${1:-${BUILD_TYPE}}"
RENDER_BUILD="${ROOT}/build/${BUILD_TYPE}"
require_file "${RENDER_BUILD}/CMakeCache.txt"
cmake --build "${RENDER_BUILD}" --parallel

if [[ "${SPECTRALDOCK_BUILD_PHYSX:-ON}" == ON ]]; then
  require_file "${PHYSX_BUILD}/CMakeCache.txt"
  cmake --build "${PHYSX_BUILD}" --parallel
fi
