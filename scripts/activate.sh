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
  _spectraldock_physx_lib="${PHYSX_ROOT}/bin/linux.x86_64/${PHYSX_BUILD_TYPE:-checked}"
  export LD_LIBRARY_PATH="${_spectraldock_physx_lib}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

unset _spectraldock_root _spectraldock_build_type
unset _spectraldock_python_paths _spectraldock_joined _spectraldock_physx_lib
