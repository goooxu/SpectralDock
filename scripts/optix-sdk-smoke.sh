#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_optix_root

mkdir -p "${ROOT}/build/optix-sdk" "${ROOT}/output"
gpu_container cmake -G Ninja -S /opt/optix/SDK -B build/optix-sdk \
  -DCMAKE_BUILD_TYPE=Release
gpu_container cmake --build build/optix-sdk --target optixHello -j2
gpu_container build/optix-sdk/bin/optixHello \
  --file output/optixHello.ppm --dim=64x48

test -s "${ROOT}/output/optixHello.ppm"
echo "OptiX SDK optixHello smoke test passed"
