#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${SPECTRALDOCK_IMAGE:-spectraldock-dev:cuda13.3}"
PHYSX_IMAGE="${SPECTRALDOCK_PHYSX_IMAGE:-spectraldock-physx:5.8.0-cuda12.8}"
PHYSX_GPU_DEVICE="${PHYSX_GPU_DEVICE:-0}"
OPTIX_ROOT="${OPTIX_ROOT:-}"
BUILD_TYPE="${BUILD_TYPE:-Release}"

die() {
  echo "error: $*" >&2
  exit 2
}

require_file() {
  [[ -f "$1" ]] || die "required file is missing: $1"
}

require_optix_root() {
  [[ -n "${OPTIX_ROOT}" ]] ||
    die "OPTIX_ROOT must be set to the extracted NVIDIA OptiX SDK directory"
  require_file "${OPTIX_ROOT}/include/optix.h"
}

run_container() {
  local mode="$1"
  shift
  local image="${IMAGE}"
  local args=(
    run --rm
    --user "$(id -u):$(id -g)"
    -e HOME=/tmp
    -v "${ROOT}:/workspace"
    -w /workspace
    --entrypoint /usr/bin/env
  )

  case "${mode}" in
    cpu)
      ;;
    gpu)
      require_optix_root
      args+=(
        --gpus all
        -e "NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics"
        -v "${OPTIX_ROOT}:/opt/optix:ro"
      )
      if [[ -f /usr/share/nvidia/nvoptix.bin ]]; then
        args+=(-v /usr/share/nvidia/nvoptix.bin:/usr/share/nvidia/nvoptix.bin:ro)
      fi
      ;;
    physx)
      image="${PHYSX_IMAGE}"
      args+=(
        --gpus all
        -e "NVIDIA_DRIVER_CAPABILITIES=compute,utility"
        -e "PHYSX_ROOT=/opt/physx"
        -e "PHYSX_BUILD_TYPE=checked"
        -e "PHYSX_GPU_DEVICE=${PHYSX_GPU_DEVICE}"
      )
      ;;
    *)
      die "unknown container mode: ${mode}"
      ;;
  esac

  docker "${args[@]}" "${image}" "$@"
}

cpu_container() {
  run_container cpu "$@"
}

gpu_container() {
  run_container gpu "$@"
}

physx_container() {
  run_container physx "$@"
}
