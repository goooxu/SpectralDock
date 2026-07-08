#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

mkdir -p "${ROOT}/build"
gpu_container nvcc --std=c++17 \
  -gencode arch=compute_75,code=sm_75 \
  -gencode arch=compute_86,code=sm_86 \
  -gencode arch=compute_89,code=sm_89 \
  -gencode arch=compute_120,code=sm_120 \
  tests/cuda_device_query.cu -o build/cuda-device-query
gpu_container build/cuda-device-query
gpu_container nvidia-smi \
  --query-gpu=name,driver_version,memory.total,compute_cap \
  --format=csv,noheader
