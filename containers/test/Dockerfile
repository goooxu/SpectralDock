# syntax=docker/dockerfile:1.7

# Both NVIDIA images are multi-architecture. Docker therefore selects the
# native target layer without hard-coding the host ISA.
ARG PHYSX_CUDA_IMAGE=nvidia/cuda:12.8.1-devel-ubuntu24.04
ARG RENDER_CUDA_IMAGE=nvidia/cuda:13.0.1-devel-ubuntu24.04

FROM ${PHYSX_CUDA_IMAGE} AS physx-cuda

FROM ${RENDER_CUDA_IMAGE} AS spectraldock-test

ARG DEBIAN_FRONTEND=noninteractive

# PhysX and the renderer deliberately use separate CUDA toolkits and separate
# processes. The unversioned /usr/local/cuda link remains owned by CUDA 13.0.
COPY --from=physx-cuda /usr/local/cuda-12.8 /usr/local/cuda-12.8

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        git \
        nasm \
        ninja-build \
        perl \
        pkg-config \
        pybind11-dev \
        python3 \
        python3-dev \
        python3-pytest \
    && rm -rf /var/lib/apt/lists/*

ENV SPECTRALDOCK_CUDA_ROOT=/usr/local/cuda-13.0 \
    SPECTRALDOCK_PHYSX_CUDA_ROOT=/usr/local/cuda-12.8 \
    OPTIX_ROOT=/opt/optix \
    PHYSX_ROOT=/opt/physx \
    PYTHONDONTWRITEBYTECODE=1

# Mount the repository at /workspace, OptiX 9.1 headers at /opt/optix, and the
# matching native PhysX 5.8 GPU SDK at /opt/physx. The SDK mounts may be
# read-only; all build and test output stays below the repository staging copy.
WORKDIR /workspace
