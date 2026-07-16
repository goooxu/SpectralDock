#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${1:-build/host-test}"
PYTHON="${PYTHON:-python3}"

cd "${ROOT}"
bash -n scripts/*.sh
cmake -S . -B "${BUILD_DIR}" -GNinja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DBUILD_TESTING=ON \
  -DSPECTRALDOCK_ENABLE_GPU=OFF \
  -DSPECTRALDOCK_ENABLE_PHYSX_SCENE=OFF
cmake --build "${BUILD_DIR}" --parallel
ctest --test-dir "${BUILD_DIR}" --output-on-failure

export PYTHONPATH="${ROOT}/python:${ROOT}/${BUILD_DIR}/python${PYTHONPATH:+:${PYTHONPATH}}"
PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}" \
  "${PYTHON}" -m pytest -q -p no:cacheprovider tests
