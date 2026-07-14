#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_optix_root
[[ -d "${ROOT}/assets/examples" ]] || die "local asset directory is missing: assets/examples"

"$(dirname "$0")/configure.sh" Release
gpu_container cmake --build build/Release --clean-first --parallel
gpu_container python3 tests/check_integrator_mis.py \
  build/Release/spectraldock tests/scenes/smoke.json
gpu_container python3 tests/check_flame_transport.py \
  build/Release/spectraldock tests/scenes/flame-smoke.json
gpu_container python3 tests/check_water_transport.py \
  build/Release/spectraldock tests/scenes/water-smoke.json
gpu_container python3 tests/check_environment_importance.py \
  build/Release/spectraldock tests/scenes/environment-smoke.json
gpu_container python3 tests/check_radiance_pavilion_importance.py \
  build/Release/spectraldock scenes/radiance-pavilion.json
gpu_container python3 tests/check_light_importance.py \
  build/Release/spectraldock
"$(dirname "$0")/configure.sh" Debug
gpu_container cmake --build build/Debug --clean-first --parallel

"$(dirname "$0")/test.sh"
"$(dirname "$0")/sanitizers.sh"

echo "GPU core renderer acceptance completed"
