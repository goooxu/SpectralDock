#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

preset=""
scene_name="kinetic-foundry"
device=0
seed=""

usage() {
  printf '%s\n' \
    'Usage: ./scripts/render-physx-scene.sh --preset preview|final [options]' \
    '' \
    'Options:' \
    '  --scene NAME  kinetic-foundry (default) or lava-temple-oracle' \
    '  --device N   Required CUDA device for PhysX generation (default: 0)' \
    '  --seed N     Simulation seed (scene default when omitted)' \
    '' \
    'preview writes output/examples/<scene>-preview.png' \
    'final writes docs/gallery/<scene>.png, stats, and same-run physics metadata' \
    '' \
    'Every render performs a fresh GPU PhysX simulation before optixLaunch.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scene|--preset|--device|--seed)
      [[ $# -ge 2 ]] || die "$1 needs a value"
      case "$1" in
        --scene) scene_name="$2" ;;
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

case "${scene_name}" in
  kinetic-foundry)
    default_seed=20260711
    ;;
  lava-temple-oracle)
    default_seed=909
    ;;
  *)
    die "--scene must be kinetic-foundry or lava-temple-oracle"
    ;;
esac
if [[ -z "${seed}" ]]; then
  seed="${default_seed}"
fi

scene="scenes/generated/${scene_name}.json"
metadata="scenes/generated/${scene_name}.physics.json"

case "${preset}" in
  preview)
    expected="output/examples/${scene_name}-preview.png"
    publish_metadata=""
    ;;
  final)
    expected="docs/gallery/${scene_name}.png"
    publish_metadata="docs/gallery/${scene_name}.physics.json"
    ;;
  *)
    die "--preset must be preview or final"
    ;;
esac

require_optix_root
cleanup_generated() {
  rm -f "${ROOT}/${scene}" "${ROOT}/${metadata}"
}
trap cleanup_generated EXIT
"$(dirname "$0")/generate-physx-scene.sh" \
  --scene "${scene_name}" \
  --output "${scene}" --metadata "${metadata}" \
  --device "${device}" --seed "${seed}" --verify

export BUILD_TYPE=Release
"$(dirname "$0")/configure.sh" Release
"$(dirname "$0")/build.sh" Release
"$(dirname "$0")/render-examples.sh" --preset "${preset}" "${scene}"

require_file "${ROOT}/${expected}"
require_file "${ROOT}/${expected%.png}.stats.json"
if [[ -n "${publish_metadata}" ]]; then
  metadata_temporary="${ROOT}/docs/gallery/.${scene_name}.physics.json.tmp"
  cleanup_metadata() {
    rm -f "${metadata_temporary}"
  }
  trap 'cleanup_metadata; cleanup_generated' EXIT
  cp "${ROOT}/${metadata}" "${metadata_temporary}"
  mv -f "${metadata_temporary}" "${ROOT}/${publish_metadata}"
fi
cleanup_generated
trap - EXIT
printf 'rendered %s %s preset -> %s\n' \
  "${scene_name}" "${preset}" "${expected}"
