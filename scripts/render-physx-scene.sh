#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

preset=""
scene="scenes/generated/kinetic-foundry.json"
device=0
seed=20260711

usage() {
  printf '%s\n' \
    'Usage: ./scripts/render-physx-scene.sh --preset preview|final [options]' \
    '' \
    'Options:' \
    '  --device N  Required CUDA device for PhysX generation (default: 0)' \
    '  --seed N    Simulation seed (default: 20260711)' \
    '' \
    'preview writes output/examples/kinetic-foundry-preview.png' \
    'final writes docs/gallery/kinetic-foundry.png, stats, and physics metadata'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preset|--device|--seed)
      [[ $# -ge 2 ]] || die "$1 needs a value"
      case "$1" in
        --preset) preset="$2" ;;
        --device) device="$2" ;;
        --seed) seed="$2" ;;
      esac
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

case "${preset}" in
  preview)
    metadata="scenes/generated/kinetic-foundry.physics.json"
    expected="output/examples/kinetic-foundry-preview.png"
    publish_metadata=""
    ;;
  final)
    metadata="scenes/generated/kinetic-foundry.physics.json"
    expected="docs/gallery/kinetic-foundry.png"
    publish_metadata="docs/gallery/kinetic-foundry.physics.json"
    ;;
  *)
    die "--preset must be preview or final"
    ;;
esac

require_optix_root
"$(dirname "$0")/generate-physx-scene.sh" \
  --output "${scene}" --metadata "${metadata}" \
  --device "${device}" --seed "${seed}" --verify

export BUILD_TYPE=Release
"$(dirname "$0")/configure.sh" Release
"$(dirname "$0")/build.sh" Release
"$(dirname "$0")/render-examples.sh" --preset "${preset}" "${scene}"

require_file "${ROOT}/${expected}"
require_file "${ROOT}/${expected%.png}.stats.json"
if [[ -n "${publish_metadata}" ]]; then
  metadata_temporary="${ROOT}/docs/gallery/.kinetic-foundry.physics.json.tmp"
  cleanup_metadata() {
    rm -f "${metadata_temporary}"
  }
  trap cleanup_metadata EXIT
  cp "${ROOT}/${metadata}" "${metadata_temporary}"
  mv -f "${metadata_temporary}" "${ROOT}/${publish_metadata}"
  trap - EXIT
fi
printf 'rendered %s preset -> %s\n' "${preset}" "${expected}"
