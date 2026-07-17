#!/usr/bin/env bash
set -euo pipefail
export BUILD_TYPE=Release
source "$(dirname "$0")/common.sh"

[[ $# -eq 0 ]] || die "acceptance.sh does not accept arguments"
require_optix_root
require_cuda_root
[[ -d "${ROOT}/assets/examples" ]] ||
  die "local asset directory is missing: assets/examples"

if [[ "${SPECTRALDOCK_BUILD_PHYSX:-ON}" == ON ]]; then
  require_physx_roots
else
  echo "== PhysX disabled: skipping SDK checks, worker build, and PhysX previews =="
fi

"$(dirname "$0")/configure.sh" Release
"$(dirname "$0")/build.sh" Release
source "$(dirname "$0")/activate.sh" Release

smoke_scenes=(
  tests/scenes/smoke.py
  tests/scenes/geometry-smoke.py
  tests/scenes/mesh-composite-smoke.py
  tests/scenes/multi-material-mesh-smoke.py
  tests/scenes/environment-smoke.py
  tests/scenes/flame-smoke.py
  tests/scenes/water-smoke.py
  tests/scenes/delta-light-smoke.py
)
for scene in "${smoke_scenes[@]}"; do
  echo "== Python smoke scene: ${scene} =="
  run_python "${ROOT}/${scene}"
  if [[ "${scene}" == tests/scenes/mesh-composite-smoke.py ]]; then
    run_python "${ROOT}/tests/check_mesh_smoke.py"
  elif [[ "${scene}" == tests/scenes/multi-material-mesh-smoke.py ]]; then
    run_python "${ROOT}/tests/check_multi_material_mesh_smoke.py"
  fi
done

run_gpu_check() {
  local script="$1"
  shift
  echo "== Advanced GPU check: ${script} =="
  run_python "${ROOT}/tests/${script}" "$@"
}

# These budgets keep the routine acceptance pass practical while retaining
# deterministic, transport-branch, and statistical A/B coverage.
run_gpu_check check_integrator_mis.py --spp 4
run_gpu_check check_delta_lights_and_firefly.py
run_gpu_check check_shading_normals.py
run_gpu_check check_ray_spawning.py
run_gpu_check check_pbr_materials.py
run_gpu_check check_flame_transport.py --spp 32
run_gpu_check check_environment_importance.py \
  --deterministic-spp 4 --rotation-spp 32 \
  --reference-spp 256 --high-spp 256 --low-spp 8
run_gpu_check check_light_importance.py
run_gpu_check check_water_transport.py
run_gpu_check check_rough_dielectric_nee.py

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
for scene in "${STATIC_EXAMPLES[@]}"; do
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
if [[ "${SPECTRALDOCK_BUILD_PHYSX:-ON}" == ON ]]; then
  for scene in "${PHYSX_EXAMPLES[@]}"; do
    echo "== Python PhysX smoke scene: ${scene} =="
    run_python -c "${PHYSX_SMOKE_CODE}" \
      "${ROOT}/scenes/${scene}.py" \
      "${ROOT}/output/acceptance-${scene}.png"
  done
else
  echo "== PhysX disabled: two PhysX example previews were not run =="
fi

"$(dirname "$0")/test.sh"

if [[ "${SPECTRALDOCK_BUILD_PHYSX:-ON}" == ON ]]; then
  echo "GPU renderer and PhysX scene acceptance completed"
else
  echo "GPU renderer acceptance completed without PhysX"
fi
