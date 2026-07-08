#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker build -t "${SPECTRALDOCK_IMAGE:-spectraldock-dev:cuda13.3}" "${ROOT}"
