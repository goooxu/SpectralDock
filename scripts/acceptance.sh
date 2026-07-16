#!/usr/bin/env bash
set -euo pipefail
export BUILD_TYPE=Release
source "$(dirname "$0")/common.sh"

[[ $# -eq 0 ]] || die "acceptance.sh does not accept arguments"
require_optix_root
require_cuda_root
require_physx_roots
[[ -d "${ROOT}/assets/examples" ]] ||
  die "local asset directory is missing: assets/examples"

"$(dirname "$0")/configure.sh" Release
"$(dirname "$0")/build.sh" Release
source "$(dirname "$0")/activate.sh" Release

smoke_scenes=(
  tests/scenes/smoke.py
  tests/scenes/geometry-smoke.py
  tests/scenes/mesh-composite-smoke.py
  tests/scenes/environment-smoke.py
  tests/scenes/flame-smoke.py
  tests/scenes/water-smoke.py
  tests/scenes/delta-light-smoke.py
)
for scene in "${smoke_scenes[@]}"; do
  echo "== Python smoke scene: ${scene} =="
  run_python "${ROOT}/${scene}"
  if [[ "${scene}" == tests/scenes/mesh-composite-smoke.py ]]; then
    run_python "${ROOT}/tests/check_mesh_smoke.py" \
      "${ROOT}/${scene}" \
      "${ROOT}/tests/assets/uv-quad.obj" \
      "${ROOT}/output/tests/mesh-composite-smoke.png" \
      "${ROOT}/output/tests/mesh-composite-smoke.stats.json" \
      "${ROOT}/tests/golden/mesh-composite-smoke-64x64-spp1-depth6-seed1.sha256"
  fi
done

run_gpu_check() {
  local script="$1"
  shift
  echo "== Advanced GPU check: ${script} =="
  run_python "${ROOT}/tests/${script}" "$@"
}

# These budgets keep the routine acceptance pass practical while retaining
# deterministic, transport-branch, and statistical A/B coverage.  Invoking a
# check directly still uses its full/default convergence budget.  The much
# heavier water time-to-error benchmark intentionally remains maintainer-only.
run_gpu_check check_integrator_mis.py --spp 4
run_gpu_check check_delta_lights_and_firefly.py
run_gpu_check check_flame_transport.py --spp 32
run_gpu_check check_environment_importance.py \
  --deterministic-spp 4 --rotation-spp 32 \
  --reference-spp 256 --high-spp 256 --low-spp 8
run_gpu_check check_light_importance.py
run_gpu_check check_radiance_pavilion_importance.py \
  --low-spp 8 --high-spp 128 --reference-spp 256
run_gpu_check check_water_transport.py
run_gpu_check check_rough_dielectric_nee.py --profile acceptance

# Build every shipped static example through its public factory and render a
# tiny frame. Their ordinary __main__ blocks retain the canonical quality and
# output paths; this harness only keeps acceptance practical while proving that
# each standalone program still constructs a complete current-API scene.
STATIC_PREVIEW_CODE='import runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1])
output = Path(sys.argv[2])
renderer = module["create_renderer"]()
renderer.render(
    output=output,
    stats_output=output.with_suffix(".stats.json"),
    width=160,
    height=90,
    spp=1,
    depth=12,
    seed=1,
    denoise=False,
)'
for scene in \
  material-cathedral neon-koi celestial-archive reflector-laboratory \
  benchmark-harbor ember-forge moonlit-stepwell radiance-pavilion; do
  echo "== Python static example preview: ${scene} =="
  run_python -c "${STATIC_PREVIEW_CODE}" \
    "${ROOT}/scenes/${scene}.py" \
    "${ROOT}/output/acceptance-${scene}.png"
done

# PhysX scenes expose ordinary constructor functions because their fresh
# fixed-step simulation must run immediately before the OptiX render. Acceptance imports
# each file directly and asks for a small diagnostic frame; no scene document
# or generated scene file sits between PhysX and the renderer.
PHYSX_SMOKE_CODE='import runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1])
output = Path(sys.argv[2])
physics = module["create_physics_world"]()
renderer = module["create_renderer"](
    physics,
    metadata_output=output.with_suffix(".physics.json"),
    verify=True,
)
renderer.render(
    output=output,
    stats_output=output.with_suffix(".stats.json"),
    width=320,
    height=180,
    spp=4,
    depth=12,
    seed=int(module["SEED"]),
    denoise=False,
)'
for scene in kinetic-foundry lava-temple-oracle; do
  echo "== Python PhysX smoke scene: ${scene} =="
  run_python -c "${PHYSX_SMOKE_CODE}" \
    "${ROOT}/scenes/${scene}.py" \
    "${ROOT}/output/acceptance-${scene}.png"
done

"$(dirname "$0")/configure.sh" Debug
cmake --build "${ROOT}/build/Debug" --clean-first --parallel
source "$(dirname "$0")/activate.sh" Debug

# Exercise OptiX validation once on the compact smoke scene. Compute
# Sanitizer is run separately with validation disabled: stacking both tools
# makes OptiX module compilation prohibitively slow and does not improve their
# independent diagnostics.
echo "== Debug OptiX validation smoke =="
run_python "${ROOT}/tests/scenes/smoke.py"

require_compute_sanitizer
COVER_SANITIZER_CODE='import runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1])
output = Path(sys.argv[2])
physics = module["create_physics_world"]()
renderer = module["create_renderer"](
    physics,
    metadata_output=output.with_suffix(".physics.json"),
    verify=True,
)
renderer.render(
    output=output,
    stats_output=output.with_suffix(".stats.json"),
    width=64,
    height=36,
    spp=1,
    depth=12,
    seed=int(module["SEED"]),
    denoise=False,
    validation=False,
)'
# One explicit all-process memcheck covers both the CUDA-13.x OptiX root process
# and its CUDA-12.8 PhysX workers. PhysX initcheck is deliberately not claimed:
# PhysX 5.8's internal buffer-capacity copies emit upstream diagnostics, while
# OptiX initcheck and ordinary-CUDA racecheck are covered by focused fixtures.
echo "== compute-sanitizer memcheck (PhysX lava temple cover) =="
"${COMPUTE_SANITIZER}" --tool memcheck \
  --target-processes all \
  --report-api-errors explicit --error-exitcode 99 \
  "${PYTHON}" -c "${COVER_SANITIZER_CODE}" \
  "${ROOT}/scenes/lava-temple-oracle.py" \
  "${ROOT}/output/sanitizer-lava-temple-oracle.png"

"$(dirname "$0")/test.sh"
BUILD_TYPE=Debug "$(dirname "$0")/sanitizers.sh"

echo "GPU renderer and PhysX scene acceptance completed"
