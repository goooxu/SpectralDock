#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_TYPE="${BUILD_TYPE:-Release}"
PYTHON="${PYTHON:-python3}"
RENDER_BUILD="${ROOT}/build/${BUILD_TYPE}"
PHYSX_BUILD="${ROOT}/build/PhysX"
OPTIX_ROOT="${OPTIX_ROOT:-}"
SPECTRALDOCK_CUDA_ROOT="${SPECTRALDOCK_CUDA_ROOT:-}"
SPECTRALDOCK_PHYSX_CUDA_ROOT="${SPECTRALDOCK_PHYSX_CUDA_ROOT:-}"
PHYSX_ROOT="${PHYSX_ROOT:-}"
PHYSX_LIBRARY_DIR="${PHYSX_LIBRARY_DIR:-}"
PHYSX_RUNTIME_DIR="${PHYSX_RUNTIME_DIR:-}"
SPECTRALDOCK_PHYSX_WORKER="${SPECTRALDOCK_PHYSX_WORKER:-${PHYSX_BUILD}/spectraldock_physx_worker}"
export SPECTRALDOCK_PHYSX_WORKER

STATIC_EXAMPLES=(
  material-cathedral
  neon-koi
  celestial-archive
  reflector-laboratory
  benchmark-harbor
  ember-forge
  moonlit-stepwell
  radiance-pavilion
)
PHYSX_EXAMPLES=(
  kinetic-foundry
  lava-temple-oracle
)
GALLERY_PROGRAMS=(
  tidal-observatory
  compare-light-transport
  compare-hdr-sampling
  compare-normal-mapping
  compare-water-absorption
)
PHYSX_GALLERY_PROGRAMS=(
  atelier
  assembly-hall
)

die() {
  echo "error: $*" >&2
  exit 2
}

require_file() {
  [[ -f "$1" ]] || die "required file is missing: $1"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

require_optix_root() {
  [[ -n "${OPTIX_ROOT}" ]] ||
    die "OPTIX_ROOT must name the extracted NVIDIA OptiX SDK"
  require_file "${OPTIX_ROOT}/include/optix.h"
}

require_cuda_root() {
  [[ -n "${SPECTRALDOCK_CUDA_ROOT}" ]] ||
    die "SPECTRALDOCK_CUDA_ROOT must name a CUDA 13.x toolkit"
  require_file "${SPECTRALDOCK_CUDA_ROOT}/bin/nvcc"
}

physx_platform_dir() {
  local machine
  machine="$(uname -m)"
  case "${machine}" in
    x86_64|amd64) echo "linux.x86_64" ;;
    aarch64|arm64) echo "linux.aarch64" ;;
    *) echo "linux.${machine}" ;;
  esac
}

resolve_physx_library_dir() {
  local platform candidate
  platform="$(physx_platform_dir)"
  if [[ -n "${PHYSX_LIBRARY_DIR}" ]]; then
    [[ -f "${PHYSX_LIBRARY_DIR}/libPhysX_static_64.a" ]] || return 1
    echo "${PHYSX_LIBRARY_DIR}"
    return 0
  fi
  for candidate in \
    "${PHYSX_ROOT}/lib" \
    "${PHYSX_ROOT}/lib/${platform}/${PHYSX_BUILD_TYPE:-checked}" \
    "${PHYSX_ROOT}/lib/${platform}" \
    "${PHYSX_ROOT}/lib/${PHYSX_BUILD_TYPE:-checked}" \
    "${PHYSX_ROOT}/bin/${platform}/${PHYSX_BUILD_TYPE:-checked}" \
    "${PHYSX_ROOT}/bin/${platform}" \
    "${PHYSX_ROOT}/bin/${PHYSX_BUILD_TYPE:-checked}" \
    "${PHYSX_ROOT}/bin"; do
    if [[ -f "${candidate}/libPhysX_static_64.a" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

resolve_physx_runtime_dir() {
  local platform library_dir candidate
  platform="$(physx_platform_dir)"
  if [[ -n "${PHYSX_RUNTIME_DIR}" ]]; then
    [[ -f "${PHYSX_RUNTIME_DIR}/libPhysXGpu_64.so" ]] || return 1
    echo "${PHYSX_RUNTIME_DIR}"
    return 0
  fi
  library_dir="$(resolve_physx_library_dir 2>/dev/null || true)"
  for candidate in \
    "${PHYSX_ROOT}/bin" \
    "${PHYSX_ROOT}/bin/${platform}/${PHYSX_BUILD_TYPE:-checked}" \
    "${PHYSX_ROOT}/bin/${platform}" \
    "${PHYSX_ROOT}/bin/${PHYSX_BUILD_TYPE:-checked}" \
    "${library_dir}"; do
    if [[ -n "${candidate}" && -f "${candidate}/libPhysXGpu_64.so" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

require_physx_roots() {
  [[ -n "${SPECTRALDOCK_PHYSX_CUDA_ROOT}" ]] ||
    die "SPECTRALDOCK_PHYSX_CUDA_ROOT must name the CUDA 12.8 toolkit"
  require_file "${SPECTRALDOCK_PHYSX_CUDA_ROOT}/bin/nvcc"
  [[ -n "${PHYSX_ROOT}" ]] ||
    die "PHYSX_ROOT must name the installed NVIDIA PhysX 5.8 SDK"
  require_file "${PHYSX_ROOT}/include/PxPhysicsAPI.h"
  PHYSX_LIBRARY_DIR="$(resolve_physx_library_dir)" ||
    die "cannot locate PhysX static libraries; set PHYSX_LIBRARY_DIR"
  PHYSX_RUNTIME_DIR="$(resolve_physx_runtime_dir)" ||
    die "cannot locate libPhysXGpu_64.so; set PHYSX_RUNTIME_DIR"
  export PHYSX_LIBRARY_DIR PHYSX_RUNTIME_DIR
}

python_path=(
  "${ROOT}/python"
  "${RENDER_BUILD}/python"
  "${PHYSX_BUILD}/python"
)
joined_python_path="$(IFS=:; echo "${python_path[*]}")"
export PYTHONPATH="${joined_python_path}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -n "${PHYSX_ROOT}" ]]; then
  if resolved_physx_runtime="$(resolve_physx_runtime_dir 2>/dev/null)"; then
    PHYSX_RUNTIME_DIR="${resolved_physx_runtime}"
    export PHYSX_RUNTIME_DIR
    export LD_LIBRARY_PATH="${PHYSX_RUNTIME_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
  fi
fi
if [[ -n "${SPECTRALDOCK_PHYSX_CUDA_ROOT}" &&
      -d "${SPECTRALDOCK_PHYSX_CUDA_ROOT}/lib64" ]]; then
  export LD_LIBRARY_PATH="${SPECTRALDOCK_PHYSX_CUDA_ROOT}/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

run_python() {
  "${PYTHON}" "$@"
}
