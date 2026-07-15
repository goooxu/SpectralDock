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
gpu_container python3 tests/check_rough_dielectric_nee.py \
  build/Release/spectraldock tests/scenes/water-smoke.json
gpu_container python3 tests/check_environment_importance.py \
  build/Release/spectraldock tests/scenes/environment-smoke.json
gpu_container python3 tests/check_radiance_pavilion_importance.py \
  build/Release/spectraldock scenes/radiance-pavilion.json
gpu_container python3 tests/check_light_importance.py \
  build/Release/spectraldock
gpu_container python3 tests/check_delta_lights_and_firefly.py \
  build/Release/spectraldock
"$(dirname "$0")/configure.sh" Debug
gpu_container cmake --build build/Debug --clean-first --parallel

COVER_SCENE="scenes/generated/lava-temple-oracle.json"
COVER_METADATA="scenes/generated/lava-temple-oracle.physics.json"
COVER_SANITIZER_OUT="output/sanitizer-lava-temple-oracle.png"
cleanup_physx_cover() {
  rm -f "${ROOT}/${COVER_SCENE}" "${ROOT}/${COVER_METADATA}"
}
trap cleanup_physx_cover EXIT
"$(dirname "$0")/generate-physx-scene.sh" \
  --scene lava-temple-oracle --output "${COVER_SCENE}" \
  --metadata "${COVER_METADATA}" --verify
require_file "${ROOT}/${COVER_SCENE}"
require_file "${ROOT}/${COVER_METADATA}"
COVER_SANITIZER_COMMON=(
  build/Debug/spectraldock
  --scene "${COVER_SCENE}" --output "${COVER_SANITIZER_OUT}"
  --width 64 --height 36 --spp 1 --max-depth 12 --seed 909
  --no-denoise
)
for tool in memcheck initcheck racecheck; do
  echo "== compute-sanitizer ${tool} (PhysX lava temple cover) =="
  gpu_container compute-sanitizer --tool "${tool}" \
    --report-api-errors explicit --error-exitcode 99 \
    "${COVER_SANITIZER_COMMON[@]}"
done
cleanup_physx_cover
trap - EXIT

"$(dirname "$0")/test.sh"
"$(dirname "$0")/sanitizers.sh"

"$(dirname "$0")/render-physx-scene.sh" \
  --scene kinetic-foundry --preset preview
"$(dirname "$0")/render-physx-scene.sh" \
  --scene lava-temple-oracle --preset preview

echo "GPU renderer and PhysX scene acceptance completed"
