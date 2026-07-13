#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
SCENE="${1:-tests/scenes/mesh-composite-smoke.json}"
OUT="${2:-output/sanitizer-mesh-composite.png}"

require_file "${ROOT}/build/Debug/spectraldock"
require_file "${ROOT}/${SCENE}"
mkdir -p "${ROOT}/$(dirname "${OUT}")"

COMMON=(
  build/Debug/spectraldock
  --scene "${SCENE}" --output "${OUT}"
  --width 64 --height 64 --spp 1 --max-depth 6 --seed 1
  --no-denoise
)
for tool in memcheck initcheck racecheck; do
  echo "== compute-sanitizer ${tool} =="
  gpu_container compute-sanitizer --tool "${tool}" \
    --report-api-errors explicit --error-exitcode 99 "${COMMON[@]}"
done

WATER_SCENE="tests/scenes/water-smoke.json"
WATER_OUT="output/sanitizer-water-smoke.png"
require_file "${ROOT}/${WATER_SCENE}"
WATER_COMMON=(
  build/Debug/spectraldock
  --scene "${WATER_SCENE}" --output "${WATER_OUT}"
  --width 64 --height 64 --spp 1 --max-depth 8 --seed 83
  --no-denoise
)
for tool in memcheck initcheck racecheck; do
  echo "== compute-sanitizer ${tool} (water) =="
  gpu_container compute-sanitizer --tool "${tool}" \
    --report-api-errors explicit --error-exitcode 99 "${WATER_COMMON[@]}"
done

gpu_container python3 tests/check_mesh_smoke.py \
  "${SCENE}" tests/assets/uv-quad.obj "${OUT}" \
  "${OUT%.png}.stats.json" \
  tests/golden/mesh-composite-smoke-64x64-spp1-depth6-seed1.sha256

FLAME_SCENE="tests/scenes/flame-smoke.json"
FLAME_OUT="output/sanitizer-flame-smoke.png"
require_file "${ROOT}/${FLAME_SCENE}"
FLAME_COMMON=(
  build/Debug/spectraldock
  --scene "${FLAME_SCENE}" --output "${FLAME_OUT}"
  --width 64 --height 64 --spp 1 --max-depth 3 --seed 71
  --no-denoise
)
for tool in memcheck initcheck racecheck; do
  echo "== compute-sanitizer ${tool} (flame) =="
  gpu_container compute-sanitizer --tool "${tool}" \
    --report-api-errors explicit --error-exitcode 99 "${FLAME_COMMON[@]}"
done
