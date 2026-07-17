#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

BUILD_TYPE="${1:-${BUILD_TYPE}}"
RENDER_BUILD="${ROOT}/build/${BUILD_TYPE}"
validation=OFF
[[ "${BUILD_TYPE}" == Debug ]] && validation=ON

require_command cmake
require_command ninja
require_cuda_root
require_optix_root

cmake -S "${ROOT}" -B "${RENDER_BUILD}" -GNinja \
  -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
  -DCMAKE_CUDA_COMPILER="${SPECTRALDOCK_CUDA_ROOT}/bin/nvcc" \
  -DCUDAToolkit_ROOT="${SPECTRALDOCK_CUDA_ROOT}" \
  -DOptiX_ROOT="${OPTIX_ROOT}" \
  -DBUILD_TESTING=OFF \
  -DSPECTRALDOCK_ENABLE_GPU=ON \
  -DSPECTRALDOCK_ENABLE_PHYSX_SCENE=OFF \
  -DSPECTRALDOCK_OPTIX_MODULE_FORMAT="${SPECTRALDOCK_OPTIX_MODULE_FORMAT:-optixir}" \
  -DSPECTRALDOCK_ENABLE_VALIDATION="${validation}"

if [[ "${SPECTRALDOCK_BUILD_PHYSX:-ON}" == ON ]]; then
  require_physx_roots
  cmake -S "${ROOT}" -B "${PHYSX_BUILD}" -GNinja \
    -DCMAKE_BUILD_TYPE=Release \
    -DCUDAToolkit_ROOT="${SPECTRALDOCK_PHYSX_CUDA_ROOT}" \
    -DPHYSX_ROOT="${PHYSX_ROOT}" \
    -DPHYSX_BUILD_TYPE="${PHYSX_BUILD_TYPE:-checked}" \
    -DBUILD_TESTING=OFF \
    -DSPECTRALDOCK_ENABLE_GPU=OFF \
    -DSPECTRALDOCK_ENABLE_PHYSX_SCENE=ON
fi
