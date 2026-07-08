#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
BUILD_TYPE="${1:-${BUILD_TYPE}}"
gpu_container cmake --build "build/${BUILD_TYPE}" --parallel
