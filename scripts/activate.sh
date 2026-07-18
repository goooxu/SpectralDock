#!/usr/bin/env bash

_spectraldock_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_spectraldock_build_type="${1:-${BUILD_TYPE:-Release}}"
_spectraldock_python_paths=(
  "${_spectraldock_root}/python"
  "${_spectraldock_root}/build/${_spectraldock_build_type}/python"
  "${_spectraldock_root}/build/PhysX/python"
)
_spectraldock_joined="$(IFS=:; echo "${_spectraldock_python_paths[*]}")"
export PYTHONPATH="${_spectraldock_joined}${PYTHONPATH:+:${PYTHONPATH}}"
export SPECTRALDOCK_PHYSX_WORKER="${SPECTRALDOCK_PHYSX_WORKER:-${_spectraldock_root}/build/PhysX/spectraldock_physx_worker}"

if [[ -n "${PHYSX_ROOT:-}" ]]; then
  case "$(uname -m)" in
    x86_64|amd64) _spectraldock_physx_platform=linux.x86_64 ;;
    aarch64|arm64) _spectraldock_physx_platform=linux.aarch64 ;;
    *) _spectraldock_physx_platform="linux.$(uname -m)" ;;
  esac
  _spectraldock_physx_candidates=(
    "${PHYSX_RUNTIME_DIR:-}"
    "${PHYSX_ROOT}/bin"
    "${PHYSX_ROOT}/bin/${_spectraldock_physx_platform}/${PHYSX_BUILD_TYPE:-checked}"
    "${PHYSX_ROOT}/bin/${_spectraldock_physx_platform}"
    "${PHYSX_ROOT}/bin/${PHYSX_BUILD_TYPE:-checked}"
    "${PHYSX_LIBRARY_DIR:-}"
    "${PHYSX_ROOT}/lib"
    "${PHYSX_ROOT}/lib/${_spectraldock_physx_platform}/${PHYSX_BUILD_TYPE:-checked}"
    "${PHYSX_ROOT}/lib/${_spectraldock_physx_platform}"
  )
  for _spectraldock_physx_candidate in "${_spectraldock_physx_candidates[@]}"; do
    if [[ -n "${_spectraldock_physx_candidate}" &&
          -f "${_spectraldock_physx_candidate}/libPhysXGpu_64.so" ]]; then
      export LD_LIBRARY_PATH="${_spectraldock_physx_candidate}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
      break
    fi
  done
fi
if [[ -n "${SPECTRALDOCK_PHYSX_CUDA_ROOT:-}" &&
      -d "${SPECTRALDOCK_PHYSX_CUDA_ROOT}/lib64" ]]; then
  export LD_LIBRARY_PATH="${SPECTRALDOCK_PHYSX_CUDA_ROOT}/lib64${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

unset _spectraldock_root _spectraldock_build_type
unset _spectraldock_python_paths _spectraldock_joined
unset _spectraldock_physx_platform _spectraldock_physx_candidates
unset _spectraldock_physx_candidate
