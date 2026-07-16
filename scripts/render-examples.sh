#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

[[ $# -eq 0 ]] || die "render-examples.sh accepts no arguments; each example owns its render parameters and output path"

examples=(
  material-cathedral
  neon-koi
  celestial-archive
  reflector-laboratory
  benchmark-harbor
  ember-forge
  moonlit-stepwell
  radiance-pavilion
  kinetic-foundry
  lava-temple-oracle
)

for example in "${examples[@]}"; do
  scene="${ROOT}/scenes/${example}.py"
  require_file "${scene}"
  echo "running ${scene}"
  run_python "${scene}"
done
