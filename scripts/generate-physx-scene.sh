#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

scene_name="kinetic-foundry"
output=""
metadata=""
device=0
seed=""
verify=0
max_attempts=8

usage() {
  printf '%s\n' \
    'Usage: ./scripts/generate-physx-scene.sh [options]' \
    '' \
    'Options:' \
    '  --scene NAME     kinetic-foundry (default) or lava-temple-oracle' \
    '  --output PATH    Scene JSON under scenes/generated/' \
    '  --metadata PATH  Physics metadata JSON under scenes/generated/' \
    '  --device N       Required CUDA device ordinal (default: 0)' \
    '  --seed N         Simulation seed (scene default when omitted)' \
    '  --verify         Validate a second independent GPU sample' \
    '' \
    'Every invocation runs GPU PhysX immediately; reuse and CPU fallback are unavailable.'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scene|--output|--metadata|--device|--seed)
      [[ $# -ge 2 ]] || die "$1 needs a value"
      case "$1" in
        --scene) scene_name="$2" ;;
        --output) output="$2" ;;
        --metadata) metadata="$2" ;;
        --device) device="$2" ;;
        --seed) seed="$2" ;;
      esac
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --verify)
      verify=1
      shift
      ;;
    *)
      die "unknown option: $1"
      ;;
  esac
done

case "${scene_name}" in
  kinetic-foundry)
    target="spectraldock_physx_scene"
    executable="build/PhysX/spectraldock_physx_scene"
    checker="tools/check_physx_scene.py"
    default_seed=20260711
    ;;
  lava-temple-oracle)
    target="spectraldock_physx_lava_temple_oracle"
    executable="build/PhysX/spectraldock_physx_lava_temple_oracle"
    checker="tools/check_physx_lava_temple_oracle.py"
    default_seed=909
    ;;
  *)
    die "--scene must be kinetic-foundry or lava-temple-oracle"
    ;;
esac

if [[ -z "${output}" ]]; then
  output="scenes/generated/${scene_name}.json"
fi
if [[ -z "${seed}" ]]; then
  seed="${default_seed}"
fi

[[ "${device}" =~ ^[0-9]+$ ]] || die "--device must be a non-negative integer"
[[ "${seed}" =~ ^[0-9]+$ ]] || die "--seed must be a non-negative integer"
[[ "${output}" == scenes/generated/*.json ]] ||
  die "--output must be a JSON path under scenes/generated/"
if [[ -z "${metadata}" ]]; then
  metadata="${output%.json}.physics.json"
fi
[[ "${metadata}" == scenes/generated/*.json ]] ||
  die "--metadata must be a JSON path under scenes/generated/"
[[ "${output}" != *'/../'* && "${metadata}" != *'/../'* ]] ||
  die "generated paths must not contain parent-directory traversal"

mkdir -p "${ROOT}/$(dirname "${output}")" \
  "${ROOT}/$(dirname "${metadata}")"
rm -f "${ROOT}/${output}" "${ROOT}/${metadata}"
export PHYSX_GPU_DEVICE="${device}"

physx_container cmake -S . -B build/PhysX -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=OFF \
  -DSPECTRALDOCK_ENABLE_GPU=OFF \
  -DSPECTRALDOCK_ENABLE_PHYSX_SCENE=ON \
  -DPHYSX_ROOT=/opt/physx \
  -DPHYSX_BUILD_TYPE=checked
physx_container cmake --build build/PhysX \
  --target "${target}" --parallel

run_simulation() {
  local scene_path="$1"
  local metadata_path="$2"
  rm -f "${ROOT}/${scene_path}" "${ROOT}/${metadata_path}"
  physx_container "${executable}" \
    --output "${scene_path}" --metadata "${metadata_path}" \
    --device "${device}" --seed "${seed}" &&
    [[ -f "${ROOT}/${scene_path}" && -f "${ROOT}/${metadata_path}" ]]
}

generate_valid() {
  local scene_path="$1"
  local metadata_path="$2"
  local attempt
  for ((attempt = 1; attempt <= max_attempts; ++attempt)); do
    if run_simulation "${scene_path}" "${metadata_path}" &&
       physx_container python3 "${checker}" \
        "${scene_path}" "${metadata_path}"; then
      printf 'accepted GPU sample on attempt %d/%d\n' \
        "${attempt}" "${max_attempts}"
      return 0
    fi
    printf 'retrying failed or rejected GPU sample (%d/%d)\n' \
      "${attempt}" "${max_attempts}" >&2
  done
  rm -f "${ROOT}/${scene_path}" "${ROOT}/${metadata_path}"
  die "PhysX GPU produced no valid scene after ${max_attempts} attempts"
}

generate_valid "${output}" "${metadata}"

if [[ "${verify}" -eq 1 ]]; then
  verify_output="${output%.json}.verify.$$.json"
  verify_metadata="${metadata%.json}.verify.$$.json"
  verify_succeeded=0
  cleanup_verify() {
    rm -f "${ROOT}/${verify_output}" "${ROOT}/${verify_metadata}"
    if [[ "${verify_succeeded}" -ne 1 ]]; then
      rm -f "${ROOT}/${output}" "${ROOT}/${metadata}"
    fi
  }
  trap cleanup_verify EXIT
  generate_valid "${verify_output}" "${verify_metadata}"
  verify_succeeded=1
  cleanup_verify
  trap - EXIT
  printf 'verified two independent GPU simulations against the %s contract\n' \
    "${scene_name}"
fi

printf 'generated %s and %s with GPU PhysX for %s\n' \
  "${output}" "${metadata}" "${scene_name}"
