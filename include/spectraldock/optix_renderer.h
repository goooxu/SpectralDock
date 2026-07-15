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
  float clamp_direct = 64.0f;
  float clamp_indirect = 16.0f;
  bool denoise = false;
  bool validation = false;
  bool capture_linear = false;
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
  std::string direct_light_sampling;
  float clamp_direct = 64.0f;
  float clamp_indirect = 16.0f;
  double bvh_build_ms = 0.0;
  double render_ms = 0.0;
  double denoise_ms = 0.0;
  double total_ms = 0.0;
  std::size_t peak_device_bytes = 0;
  std::size_t peak_tracked_device_bytes = 0;
  std::uint64_t traced_rays = 0;
  double rays_per_second = 0.0;
  std::uint64_t firefly_direct_clamped_contributions = 0;
  std::uint64_t firefly_indirect_clamped_contributions = 0;
  std::uint64_t volume_density_evaluations = 0;
  std::uint64_t volume_real_collisions = 0;
  std::uint64_t volume_light_samples = 0;
  std::uint64_t volume_majorant_violations = 0;
  std::uint64_t volume_tracking_overflows = 0;
  std::uint64_t water_height_evaluations = 0;
  std::uint64_t water_tile_tests = 0;
  std::uint64_t water_roots_reported = 0;
  std::uint64_t water_medium_segments = 0;
  std::uint64_t water_solver_overflows = 0;
  std::uint64_t water_medium_errors = 0;
  std::uint64_t water_rough_nee_attempts = 0;
  std::uint64_t water_rough_nee_contributions = 0;
  std::uint64_t water_delta_splits = 0;
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
  std::vector<float> linear_rgb;
  RenderStats stats;
};

RenderResult render_optix(const Scene& scene, const RenderSettings& settings);

}  // namespace spectraldock
