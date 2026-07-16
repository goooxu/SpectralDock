#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

[[ $# -eq 0 ]] || die "render-examples.sh accepts no arguments; each example owns its render parameters and output path"

for example in "${STATIC_EXAMPLES[@]}" "${PHYSX_EXAMPLES[@]}"; do
  scene="${ROOT}/scenes/${example}.py"
  require_file "${scene}"
  echo "running ${scene}"
  run_python "${scene}"
done
