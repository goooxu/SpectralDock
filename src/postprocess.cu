#include <cstdint>

#include <cuda_runtime.h>

namespace spectraldock {
namespace {

// Krzysztof Narkowicz's CC0/MIT ACES-inspired fitted curve, used here under
// CC0-1.0. See THIRD_PARTY_NOTICES.md.
static __forceinline__ __device__ float aces_fitted(float value) {
  const float x = fmaxf(value, 0.0f);
  return fminf(fmaxf((x * (2.51f * x + 0.03f)) /
                         (x * (2.43f * x + 0.59f) + 0.14f),
                     0.0f),
               1.0f);
}

static __forceinline__ __device__ float linear_to_srgb(float value) {
  const float x = fminf(fmaxf(value, 0.0f), 1.0f);
  return x <= 0.0031308f ? 12.92f * x
                         : 1.055f * powf(x, 1.0f / 2.4f) - 0.055f;
}

static __forceinline__ __device__ unsigned char to_byte(float value) {
  return static_cast<unsigned char>(
      fminf(fmaxf(floorf(value * 255.0f + 0.5f), 0.0f), 255.0f));
}

__global__ void postprocess_kernel(const float4* linear_beauty,
                                   uchar4* output,
                                   std::uint32_t pixel_count,
                                   float exposure) {
  const std::uint32_t index =
      blockIdx.x * static_cast<std::uint32_t>(blockDim.x) + threadIdx.x;
  if (index >= pixel_count) {
    return;
  }
  const float4 source = linear_beauty[index];
  const float multiplier = exp2f(exposure);
  float r = isfinite(source.x) ? source.x * multiplier : 0.0f;
  float g = isfinite(source.y) ? source.y * multiplier : 0.0f;
  float b = isfinite(source.z) ? source.z * multiplier : 0.0f;
  r = linear_to_srgb(aces_fitted(r));
  g = linear_to_srgb(aces_fitted(g));
  b = linear_to_srgb(aces_fitted(b));
  output[index] = make_uchar4(to_byte(r), to_byte(g), to_byte(b), 255u);
}

}  // namespace

extern "C" cudaError_t spectraldockLaunchPostprocess(
    const float4* linear_beauty, uchar4* output, std::uint32_t width,
    std::uint32_t height, float exposure, cudaStream_t stream) {
  if (linear_beauty == nullptr || output == nullptr) {
    return cudaErrorInvalidValue;
  }
  if (width == 0 || height == 0) {
    return cudaSuccess;
  }
  const unsigned long long count64 =
      static_cast<unsigned long long>(width) * height;
  if (count64 > 0xffffffffull) {
    return cudaErrorInvalidValue;
  }
  const std::uint32_t count = static_cast<std::uint32_t>(count64);
  constexpr std::uint32_t kBlockSize = 256;
  const std::uint32_t block_count = (count + kBlockSize - 1u) / kBlockSize;
  postprocess_kernel<<<block_count, kBlockSize, 0, stream>>>(
      linear_beauty, output, count, exposure);
  return cudaGetLastError();
}

}  // namespace spectraldock
