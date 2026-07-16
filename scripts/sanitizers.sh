#!/usr/bin/env bash
set -euo pipefail
export BUILD_TYPE=Debug
source "$(dirname "$0")/common.sh"

[[ $# -eq 0 ]] || die "sanitizers.sh does not accept arguments"
require_compute_sanitizer
[[ -d "${ROOT}/build/Debug/python/spectraldock" ]] ||
  die "Debug Python extension is missing; configure and build Debug first"
mkdir -p "${ROOT}/output"

# Import a fixture by file path and render through the public Python API.  The
# numeric arguments are sanitizer-only reductions; the fixture's normal main()
# retains its canonical smoke settings.
PYTHON_RENDER_CODE='import runpy, sys
from pathlib import Path
module = runpy.run_path(sys.argv[1])
output = Path(sys.argv[2])
renderer = module["create_renderer"]()
renderer.render(
    output=output,
    stats_output=output.with_suffix(".stats.json"),
    width=int(sys.argv[3]),
    height=int(sys.argv[4]),
    spp=int(sys.argv[5]),
    depth=int(sys.argv[6]),
    seed=int(sys.argv[7]),
    denoise=False,
    clamp_direct=float(sys.argv[8]),
    clamp_indirect=float(sys.argv[9]),
    validation=False,
)'

sanitize_scene() {
  local label="$1"
  local scene="$2"
  local output="$3"
  local width="$4"
  local height="$5"
  local spp="$6"
  local depth="$7"
  local seed="$8"
  local clamp_direct="$9"
  local clamp_indirect="${10}"
  local tool
  local -a tool_options
  require_file "${ROOT}/${scene}"
  for tool in memcheck initcheck racecheck; do
    tool_options=()
    if [[ "${tool}" == initcheck ]]; then
      # Initcheck ignores OptiX launches unless this flag is explicit.
      tool_options+=(--check-optix)
    fi
    echo "== compute-sanitizer ${tool} (${label}) =="
    "${COMPUTE_SANITIZER}" --tool "${tool}" \
      --target-processes application-only \
      "${tool_options[@]}" \
      --report-api-errors explicit --error-exitcode 99 \
      "${PYTHON}" -c "${PYTHON_RENDER_CODE}" \
      "${ROOT}/${scene}" "${ROOT}/${output}" \
      "${width}" "${height}" "${spp}" "${depth}" "${seed}" \
      "${clamp_direct}" "${clamp_indirect}"
  done
}

sanitize_scene \
  "mesh composite" tests/scenes/mesh-composite-smoke.py \
  output/sanitizer-mesh-composite.png 64 64 1 6 1 0.0 0.0

require_file "${ROOT}/assets/examples/environments/radiance-pavilion.hdr"
sanitize_scene \
  "HDR environment" tests/scenes/environment-smoke.py \
  output/sanitizer-environment-smoke.png 64 64 1 4 109 0.0 0.0

sanitize_scene \
  "water" tests/scenes/water-smoke.py \
  output/sanitizer-water-smoke.png 64 64 1 8 83 0.0 0.0

sanitize_scene \
  "delta lights and clamp" tests/scenes/delta-light-smoke.py \
  output/sanitizer-delta-light-smoke.png 64 64 1 6 313 0.01 0.01

sanitize_scene \
  "flame" tests/scenes/flame-smoke.py \
  output/sanitizer-flame-smoke.png 64 64 1 3 71 0.0 0.0
