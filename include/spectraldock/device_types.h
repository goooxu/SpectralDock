#pragma once

#include <cstdint>

#include <cuda_runtime.h>
#include <optix.h>

namespace spectraldock {

enum RayType : std::uint32_t {
  kRayRadiance = 0,
  kRayShadow = 1,
  kRayTypeCount = 2,
};

enum DeviceMaterialType : std::uint32_t {
  kMaterialLambertian = 0,
  kMaterialMetal = 1,
  kMaterialDielectric = 2,
  kMaterialEmitter = 3,
  kMaterialWater = 4,
};

enum PrimitiveType : std::uint32_t {
  kPrimitiveTriangle = 0,
  kPrimitiveSphere = 1,
  kPrimitiveDisk = 2,
  kPrimitiveCylinder = 3,
  kPrimitiveParabola = 4,
  kPrimitiveMesh = 5,
  kPrimitiveWaterSurface = 6,
  kPrimitiveSolidSphere = 7,
};

enum DeviceBackgroundType : std::uint32_t {
  kBackgroundConstant = 0,
  kBackgroundSky = 1,
};

enum DeviceLightType : std::uint32_t {
  kLightRectangle = 0,
  kLightDisk = 1,
  kLightSphere = 2,
  kLightFlame = 3,
};

enum TextureFlags : std::uint32_t {
  kTextureSrgb = 1u << 0,
};

constexpr std::int32_t kInvalidIndex = -1;

// CUDA texture objects are expected to use normalized coordinates. Image row
// zero is the top row; device code flips the scene's bottom-left-origin v.
struct TextureData {
  std::uint64_t object = 0;
  std::uint32_t flags = kTextureSrgb;
};

struct MaterialData {
  float3 base_color = {0.8f, 0.8f, 0.8f};
  float roughness = 0.5f;
  float3 emission = {0.0f, 0.0f, 0.0f};
  float ior = 1.5f;
  float metallic = 1.0f;
  std::int32_t texture_index = kInvalidIndex;
  std::uint32_t type = kMaterialLambertian;
  float3 absorption = {0.0f, 0.0f, 0.0f};
  std::uint32_t reserved = 0;
};

struct DeviceWaterWave {
  float2 direction = {1.0f, 0.0f};
  float amplitude = 0.0f;
  float wave_number = 0.0f;
  float phase = 0.0f;
  float reserved = 0.0f;
};

// DeviceGeometryData is copied inline into every hit-group SBT record.
//  * triangle: p0,p1,p2 are three consecutive parallelogram corners. The two
//    indexed triangles must be (p0,p1,p2) and (p0,p2,p0+p2-p1).
//  * sphere: p0=center, radius=radius.
//  * disk: p0=center, p1=normal, p2=optional in-plane +u direction.
//  * cylinder: p0=axis origin, p1=axis direction, radius=radius. A positive
//    height clips the axis coordinate to [0,height]; otherwise aabb is the only
//    clip and the side remains open.
//  * parabola: p0=vertex, p1=extrusion axis, p2=focus. It is the parabolic
//    cylinder x^2=4*f*y, clipped by aabb.
struct DeviceGeometryData {
  float3 p0 = {0.0f, 0.0f, 0.0f};
  float radius = 0.0f;
  float3 p1 = {0.0f, 1.0f, 0.0f};
  float height = 0.0f;
  float3 p2 = {1.0f, 0.0f, 0.0f};
  float alpha_cutoff = 0.5f;
  float3 aabb_min = {-1.0e16f, -1.0e16f, -1.0e16f};
  std::int32_t primitive_type = kPrimitiveTriangle;
  float3 aabb_max = {1.0e16f, 1.0e16f, 1.0e16f};
  std::int32_t material_front = kInvalidIndex;
  std::int32_t material_back = kInvalidIndex;
  std::int32_t alpha_texture = kInvalidIndex;
  std::int32_t light_index = kInvalidIndex;
  std::uint32_t primitive_index_base = 0;

  // water_surface is a world-space XZ height field. p0 is its center and
  // water_size is its X/Z extent. Each custom primitive is one conservative
  // tile AABB; its primitive index identifies the tile in row-major order.
  float2 water_size = {0.0f, 0.0f};
  std::uint32_t water_wave_count = 0;
  std::uint32_t water_tiles_x = 0;
  std::uint32_t water_tiles_z = 0;
  std::uint32_t water_reserved = 0;
  DeviceWaterWave water_waves[4]{};
};

enum MeshFlags : std::uint32_t {
  kMeshHasNormals = 1u << 0,
  kMeshHasTexcoords = 1u << 1,
};

struct DeviceMeshData {
  const float3* positions = nullptr;
  const float3* normals = nullptr;
  const float2* texcoords = nullptr;
  const uint3* indices = nullptr;
  std::uint32_t vertex_count = 0;
  std::uint32_t triangle_count = 0;
  std::uint32_t flags = 0;
  std::uint32_t reserved = 0;
};

struct HitgroupData {
  DeviceGeometryData geometry;
  DeviceMeshData mesh;
};

struct LightData {
  float3 p0 = {0.0f, 0.0f, 0.0f};
  float area = 0.0f;
  float3 edge_u = {1.0f, 0.0f, 0.0f};
  std::int32_t two_sided = 0;
  float3 edge_v = {0.0f, 1.0f, 0.0f};
  std::int32_t geometry_index = kInvalidIndex;
  float3 emission = {1.0f, 1.0f, 1.0f};
  std::uint32_t type = kLightRectangle;
  float3 normal = {0.0f, 1.0f, 0.0f};
  float radius = 0.0f;

  // A flame is an oriented, finite, procedural absorption-emission volume.
  // Existing area-light fields remain valid for the three surface types.
  float3 axis = {0.0f, 1.0f, 0.0f};
  float height = 0.0f;
  float3 emission_start = {0.0f, 0.0f, 0.0f};
  float radius_start = 0.0f;
  float3 emission_end = {0.0f, 0.0f, 0.0f};
  float radius_end = 0.0f;
  float extinction = 0.0f;
  float density_scale = 0.0f;
  float turbulence = 0.0f;
  float noise_scale = 0.0f;
  std::uint32_t seed = 0;
  std::uint32_t reserved0 = 0;
  std::uint32_t reserved1 = 0;
  std::uint32_t reserved2 = 0;
};

struct VolumeCounters {
  unsigned long long density_evaluations = 0;
  unsigned long long real_collisions = 0;
  unsigned long long light_samples = 0;
  unsigned long long majorant_violations = 0;
  unsigned long long tracking_overflows = 0;
};

struct WaterCounters {
  unsigned long long height_evaluations = 0;
  unsigned long long tile_tests = 0;
  unsigned long long roots_reported = 0;
  unsigned long long shadow_transmissions = 0;
  unsigned long long medium_segments = 0;
  unsigned long long solver_overflows = 0;
  unsigned long long medium_errors = 0;
  unsigned long long shadow_boundary_overflows = 0;
};

// Camera basis uses w pointing backwards (look-from minus look-at), with u to
// the right and v up. tan_half_fov is the vertical half-angle tangent.
struct CameraData {
  float3 origin = {0.0f, 0.0f, 0.0f};
  float tan_half_fov = 0.41421356f;
  float3 u = {1.0f, 0.0f, 0.0f};
  float aspect = 1.0f;
  float3 v = {0.0f, 1.0f, 0.0f};
  float lens_radius = 0.0f;
  float3 w = {0.0f, 0.0f, 1.0f};
  float focus_distance = 1.0f;
};

struct LaunchParams {
  OptixTraversableHandle traversable = 0;

  float4* beauty = nullptr;
  float4* albedo = nullptr;
  float3* normal = nullptr;

  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::uint32_t spp = 1;
  std::uint32_t max_depth = 12;
  std::uint32_t seed = 1;
  float scene_epsilon = 1.0e-4f;
  std::uint32_t background_type = kBackgroundConstant;

  CameraData camera;
  float3 background_color = {0.0f, 0.0f, 0.0f};
  std::uint32_t reserved0 = 0;
  float3 sky_bottom = {1.0f, 1.0f, 1.0f};
  std::uint32_t reserved1 = 0;
  float3 sky_top = {0.5f, 0.7f, 1.0f};
  std::uint32_t reserved2 = 0;
  float3 sun_direction = {1.0f, 0.0f, 0.0f};
  float sun_cos_angle = 2.0f;
  float3 sun_color = {0.0f, 0.0f, 0.0f};
  std::uint32_t reserved_sun = 0;

  const MaterialData* materials = nullptr;
  const TextureData* textures = nullptr;
  const LightData* lights = nullptr;
  std::uint32_t material_count = 0;
  std::uint32_t texture_count = 0;
  std::uint32_t light_count = 0;
  std::uint32_t flame_count = 0;
  std::uint32_t water_surface_count = 0;

  // Optional global counter. Every radiance and shadow optixTrace increments
  // it once, allowing rays/s reporting without estimating bounce counts.
  unsigned long long* traced_rays = nullptr;
  VolumeCounters* volume_counters = nullptr;
  WaterCounters* water_counters = nullptr;
};

extern "C" cudaError_t spectraldockLaunchPostprocess(
    const float4* linear_beauty, uchar4* output, std::uint32_t width,
    std::uint32_t height, float exposure, cudaStream_t stream);

}  // namespace spectraldock
