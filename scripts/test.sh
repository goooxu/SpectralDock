#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

cpu_container bash -n scripts/*.sh
cpu_container cmake -S . -B build/cpu-test -GNinja \
  -DCMAKE_BUILD_TYPE=Debug \
  -DBUILD_TESTING=ON \
  -DSPECTRALDOCK_ENABLE_GPU=OFF
cpu_container cmake --build build/cpu-test --parallel
cpu_container ctest --test-dir build/cpu-test --output-on-failure
cpu_container python3 -m pytest -q -p no:cacheprovider tests
