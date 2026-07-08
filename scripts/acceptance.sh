#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_optix_root
[[ -d "${ROOT}/assets/examples" ]] || die "local asset directory is missing: assets/examples"

"$(dirname "$0")/environment-smoke.sh"
"$(dirname "$0")/optix-sdk-smoke.sh"

BUILD_TYPE=Release "$(dirname "$0")/configure.sh" Release
gpu_container cmake --build build/Release --clean-first --parallel
gpu_container python3 tests/check_integrator_mis.py \
  build/Release/spectraldock tests/scenes/smoke.json
BUILD_TYPE=Debug "$(dirname "$0")/configure.sh" Debug
gpu_container cmake --build build/Debug --clean-first --parallel

"$(dirname "$0")/test.sh"
BUILD_TYPE=Debug "$(dirname "$0")/sanitizers.sh"

echo "RTX 5090 core renderer acceptance completed"
