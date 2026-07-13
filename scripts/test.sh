#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

cpu_container bash scripts/test-host.sh build/host-test
