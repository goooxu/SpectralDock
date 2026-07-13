#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

usage() {
  printf '%s\n' \
    'Usage: ./scripts/render-examples.sh --preset preview|final [scene ...]' \
    '' \
    'Scene arguments may be bare names (for example material-cathedral) or JSON' \
    'paths. With no scene arguments all seven teaching scenes are rendered.' \
    '' \
    'preview: 960x540, 64 spp, depth 8, AI denoising' \
    'final:   1920x1080, 512 spp, depth 12, AI denoising' \
    'ember-forge:       256/2048 spp, depth 12, no denoising' \
    'moonlit-stepwell:   256/2048 spp, depth 16, no denoising' \
    'Warning: --preset final writes version-controlled files in docs/gallery.'
}

preset=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --preset)
      [[ $# -ge 2 ]] || { echo "error: --preset needs a value" >&2; exit 2; }
      preset="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "error: unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

case "${preset}" in
  preview)
    width=960
    height=540
    spp=64
    depth=8
    output_dir="output/examples"
    suffix="-preview"
    ;;
  final)
    width=1920
    height=1080
    spp=512
    depth=12
    output_dir="docs/gallery"
    suffix=""
    ;;
  *)
    echo "error: --preset must be preview or final" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ $# -eq 0 ]]; then
  scenes=(
    material-cathedral
    neon-koi
    celestial-archive
    reflector-laboratory
    benchmark-harbor
    ember-forge
    moonlit-stepwell
  )
else
  scenes=("$@")
fi

mkdir -p "${ROOT}/${output_dir}"
for requested in "${scenes[@]}"; do
  if [[ "${requested}" == *.json || "${requested}" == */* ]]; then
    scene_path="${requested}"
  else
    scene_path="scenes/${requested}.json"
  fi
  if [[ ! -f "${ROOT}/${scene_path}" ]]; then
    echo "error: scene not found: ${scene_path}" >&2
    exit 2
  fi
  stem="$(basename "${scene_path}" .json)"
  output_path="${output_dir}/${stem}${suffix}.png"
  scene_spp="${spp}"
  scene_depth="${depth}"
  denoise_option="--denoise"
  if [[ "${stem}" == "ember-forge" ]]; then
    scene_depth=12
    denoise_option="--no-denoise"
    if [[ "${preset}" == "preview" ]]; then
      scene_spp=256
    else
      scene_spp=2048
    fi
  fi
  if [[ "${stem}" == "moonlit-stepwell" ]]; then
    scene_depth=16
    denoise_option="--no-denoise"
    if [[ "${preset}" == "preview" ]]; then
      scene_spp=256
    else
      scene_spp=2048
    fi
  fi
  echo "rendering ${stem} (${preset}, ${scene_spp} spp) -> ${output_path}"
  gpu_container "build/${BUILD_TYPE}/spectraldock" \
    --scene "${scene_path}" --output "${output_path}" \
    --width "${width}" --height "${height}" --spp "${scene_spp}" \
    --max-depth "${scene_depth}" "${denoise_option}"
done
