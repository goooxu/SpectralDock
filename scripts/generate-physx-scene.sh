#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

output="scenes/generated/kinetic-foundry.json"
metadata=""
device=0
seed=20260711
verify=0
max_attempts=8

usage() {
  printf '%s\n' \
    'Usage: ./scripts/generate-physx-scene.sh [options]' \
    '' \
    'Options:' \
    '  --output PATH    Scene JSON under scenes/generated/' \
    '  --metadata PATH  Physics metadata JSON under scenes/generated/' \
    '  --device N       Required CUDA device ordinal (default: 0)' \
    '  --seed N         Simulation seed (default: 20260711)' \
    '  --verify         Produce two independently validated GPU samples'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output|--metadata|--device|--seed)
      [[ $# -ge 2 ]] || die "$1 needs a value"
      case "$1" in
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
export PHYSX_GPU_DEVICE="${device}"

physx_container cmake -S . -B build/PhysX -GNinja \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_TESTING=OFF \
  -DSPECTRALDOCK_ENABLE_GPU=OFF \
  -DSPECTRALDOCK_ENABLE_PHYSX_SCENE=ON \
  -DPHYSX_ROOT=/opt/physx \
  -DPHYSX_BUILD_TYPE=checked
physx_container cmake --build build/PhysX \
  --target spectraldock_physx_scene --parallel

run_simulation() {
  local scene_path="$1"
  local metadata_path="$2"
  rm -f "${ROOT}/${scene_path}" "${ROOT}/${metadata_path}"
  physx_container build/PhysX/spectraldock_physx_scene \
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
       physx_container python3 tools/check_physx_scene.py \
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
  cleanup_verify() {
    rm -f "${ROOT}/${verify_output}" "${ROOT}/${verify_metadata}"
  }
  trap cleanup_verify EXIT
  generate_valid "${verify_output}" "${verify_metadata}"
  cleanup_verify
  trap - EXIT
  printf 'verified two independent GPU simulations against the scene contract\n'
fi

printf 'generated %s and %s with GPU PhysX\n' "${output}" "${metadata}"
