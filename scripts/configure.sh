#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
BUILD_TYPE="${1:-${BUILD_TYPE}}"
require_optix_root
validation=OFF
[[ "${BUILD_TYPE}" == Debug ]] && validation=ON
gpu_container cmake -S . -B "build/${BUILD_TYPE}" -GNinja \
  -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
  -DOptiX_ROOT=/opt/optix \
  -DSPECTRALDOCK_ENABLE_GPU=ON \
  -DSPECTRALDOCK_ENABLE_VALIDATION="${validation}"
