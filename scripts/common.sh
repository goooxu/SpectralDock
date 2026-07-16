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
SPECTRALDOCK_PHYSX_WORKER="${SPECTRALDOCK_PHYSX_WORKER:-${PHYSX_BUILD}/spectraldock_physx_worker}"
COMPUTE_SANITIZER="${COMPUTE_SANITIZER:-${SPECTRALDOCK_CUDA_ROOT:+${SPECTRALDOCK_CUDA_ROOT}/bin/compute-sanitizer}}"
export SPECTRALDOCK_PHYSX_WORKER

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
    die "SPECTRALDOCK_CUDA_ROOT must name the CUDA 13.3 toolkit"
  require_file "${SPECTRALDOCK_CUDA_ROOT}/bin/nvcc"
}

require_compute_sanitizer() {
  require_cuda_root
  [[ -n "${COMPUTE_SANITIZER}" ]] ||
    die "COMPUTE_SANITIZER must name the CUDA Compute Sanitizer executable"
  require_file "${COMPUTE_SANITIZER}"
  [[ -x "${COMPUTE_SANITIZER}" ]] ||
    die "Compute Sanitizer is not executable: ${COMPUTE_SANITIZER}"
}

require_physx_roots() {
  [[ -n "${SPECTRALDOCK_PHYSX_CUDA_ROOT}" ]] ||
    die "SPECTRALDOCK_PHYSX_CUDA_ROOT must name the CUDA 12.8 toolkit"
  require_file "${SPECTRALDOCK_PHYSX_CUDA_ROOT}/bin/nvcc"
  [[ -n "${PHYSX_ROOT}" ]] ||
    die "PHYSX_ROOT must name the installed NVIDIA PhysX 5.8 SDK"
  require_file "${PHYSX_ROOT}/include/PxPhysicsAPI.h"
}

python_path=(
  "${ROOT}/python"
  "${RENDER_BUILD}/python"
  "${PHYSX_BUILD}/python"
)
joined_python_path="$(IFS=:; echo "${python_path[*]}")"
export PYTHONPATH="${joined_python_path}${PYTHONPATH:+:${PYTHONPATH}}"

if [[ -n "${PHYSX_ROOT}" ]]; then
  physx_library_path="${PHYSX_ROOT}/bin/linux.x86_64/${PHYSX_BUILD_TYPE:-checked}"
  export LD_LIBRARY_PATH="${physx_library_path}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

run_python() {
  "${PYTHON}" "$@"
}
