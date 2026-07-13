ARG CUDA_IMAGE=nvidia/cuda:13.3.0-devel-ubuntu24.04
FROM ${CUDA_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      cmake \
      libpng-dev \
      ninja-build \
      nlohmann-json3-dev \
      python3 \
      python3-pil \
      python3-pytest \
    && rm -rf /var/lib/apt/lists/*

ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics
WORKDIR /workspace
