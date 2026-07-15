#pragma once

#include "spectraldock/scene_types.h"

#include <cstdint>
#include <filesystem>
#include <vector>

namespace spectraldock {

struct ImageRgb32f {
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::vector<float> pixels;

  bool empty() const noexcept {
    return width == 0 || height == 0 || pixels.empty();
  }
};

// Reads a Radiance RGBE image with FORMAT=32-bit_rle_rgbe and the conventional
// -Y height +X width orientation. Both modern per-channel RLE and raw RGBE
// scanlines are accepted. Returned samples are linear Rec.709 RGB values.
ImageRgb32f load_radiance_hdr(const std::filesystem::path& path);

struct FiniteLightDistribution {
  // Original Scene::lights indices for the non-delta lights represented by
  // this distribution. Point and directional lights are evaluated in their
  // own deterministic domain and never appear here.
  std::vector<std::uint32_t> indices;
  // CDF boundaries, including exactly 0 and 1.
  std::vector<float> cdf;
  // Actual float interval widths cdf[i + 1] - cdf[i]. These values, rather
  // than the original double-precision weights, are the sampler/PDF contract.
  std::vector<float> probabilities;
};

FiniteLightDistribution build_finite_light_distribution(
    const std::vector<Light>& lights,
    DirectLightSampling mode);

struct EnvironmentDistribution {
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::vector<float> row_cdf;
  std::vector<float> row_probabilities;
  // Row-major H x (W + 1) conditional CDFs.
  std::vector<float> conditional_cdf;
  // Row-major H x W actual conditional interval widths.
  std::vector<float> conditional_probabilities;
  bool black = false;
};

EnvironmentDistribution build_environment_distribution(
    const ImageRgb32f& image,
    DirectLightSampling mode);

}  // namespace spectraldock
