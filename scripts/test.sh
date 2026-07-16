#!/usr/bin/env bash
set -euo pipefail
exec "$(dirname "$0")/test-host.sh" "${1:-build/host-test}"
