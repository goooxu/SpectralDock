#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${1:-build/host-test}"

cd "${ROOT}"
bash -n scripts/*.sh
cmake -S . -B "${BUILD_DIR}" -GNinja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DBUILD_TESTING=ON \
  -DSPECTRALDOCK_ENABLE_GPU=OFF \
  -DSPECTRALDOCK_ENABLE_PHYSX_SCENE=OFF
cmake --build "${BUILD_DIR}" --parallel
ctest --test-dir "${BUILD_DIR}" --output-on-failure
PYTHONDONTWRITEBYTECODE="${PYTHONDONTWRITEBYTECODE:-1}" \
  python3 -m pytest -q -p no:cacheprovider \
    tests/test_technical_report_snippets.py \
    tests/test_hdr_environment_generator.py
