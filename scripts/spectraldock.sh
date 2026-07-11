#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"
mkdir -p "${ROOT}/output"
gpu_container "build/${BUILD_TYPE}/spectraldock" "$@"
