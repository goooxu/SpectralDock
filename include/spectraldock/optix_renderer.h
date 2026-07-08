#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace spectraldock {

struct Scene;

struct RenderSettings {
  std::uint32_t width = 1024;
  std::uint32_t height = 1024;
  std::uint32_t spp = 256;
  std::uint32_t max_depth = 12;
  std::uint32_t seed = 1;
  float exposure = 0.0f;
  bool denoise = false;
  bool validation = false;
};

struct RenderStats {
  std::string gpu_name;
  int compute_major = 0;
  int compute_minor = 0;
  std::string driver_version;
  int cuda_driver_api_version = 0;
  int cuda_runtime_version = 0;
  int optix_version = 0;
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::uint32_t spp = 0;
  std::uint32_t max_depth = 0;
  std::uint32_t seed = 0;
  bool denoised = false;
  double bvh_build_ms = 0.0;
  double render_ms = 0.0;
  double denoise_ms = 0.0;
  double total_ms = 0.0;
  std::size_t peak_device_bytes = 0;
  std::size_t peak_tracked_device_bytes = 0;
  std::uint64_t traced_rays = 0;
  double rays_per_second = 0.0;
  std::uint64_t objects = 0;
  std::uint64_t instances = 0;
  std::uint64_t unique_meshes = 0;
  std::uint64_t mesh_triangles = 0;
  std::uint64_t gas_count = 0;
};

struct RenderResult {
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::vector<std::uint8_t> rgba;
  RenderStats stats;
};

RenderResult render_optix(const Scene& scene, const RenderSettings& settings);

}  // namespace spectraldock
