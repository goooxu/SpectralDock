#pragma once

#include "spectraldock/math.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <type_traits>
#include <variant>
#include <vector>

namespace spectraldock {

constexpr std::int32_t kInvalidId = -1;
// Exposure is evaluated as 2^EV by the HDR AVIF encoder. Keeping the public
// range explicit prevents callers from relying on an undocumented saturation
// step at extreme finite values.
constexpr float kMinimumExposureEv = -128.0f;
constexpr float kMaximumExposureEv = 128.0f;
// Shared AVIF input/output bounds. The total-pixel cap keeps pixel-buffer
// allocations bounded independently of image aspect ratio.
constexpr std::uint32_t kMaximumAvifDimension = 16384;
constexpr std::uint32_t kMaximumAvifPixels = std::uint32_t{1} << 25;

enum class TextureType : std::uint32_t { Constant, Image };
enum class TextureColorSpace : std::uint32_t { Linear, Srgb, Hdr };
enum class TextureWrap : std::uint32_t {
  ClampToEdge,
  Repeat,
  MirroredRepeat,
};
enum class MaterialType : std::uint32_t {
  Lambertian,
  Metal,
  Dielectric,
  Emitter,
  Water,
  Pbr,
};
enum class GeometryType : std::uint32_t {
  Sphere,
  Rectangle,
  Disk,
  Cylinder,
  Parabola,
  Mesh,
  WaterSurface,
};
enum class BackgroundType : std::uint32_t { Constant, Sky, Environment };
enum class DirectLightSampling : std::uint32_t { Uniform, Importance };
// Keep the original values stable: device-side records and existing fixtures
// rely on Sphere..Flame occupying values 0..3.
enum class LightType : std::uint32_t {
  Sphere,
  Rectangle,
  Disk,
  Flame,
  Point,
  Directional,
};

struct Camera {
  Vec3 look_from{0.0f, 0.0f, 5.0f};
  Vec3 look_at{0.0f, 0.0f, 0.0f};
  Vec3 up{0.0f, 1.0f, 0.0f};
  float vertical_fov_degrees = 45.0f;
  float aperture = 0.0f;
  float focus_distance = 0.0f;
};

struct Background {
  BackgroundType type = BackgroundType::Constant;
  Vec3 color{0.0f};
  Vec3 sky_bottom{1.0f};
  Vec3 sky_top{0.5f, 0.7f, 1.0f};
  Vec3 sun_direction{1.0f, 0.0f, 0.0f};
  Vec3 sun_color{0.0f};
  float sun_cos_angle = 2.0f;  // Values > 1 disable the sun lobe.
  std::filesystem::path environment_path;
  float environment_intensity = 1.0f;
  float environment_rotation_degrees = 0.0f;
  // Exposure value in stops (EV), constrained to
  // [kMinimumExposureEv, kMaximumExposureEv].
  float exposure = 0.0f;
};

struct Integrator {
  DirectLightSampling direct_light_sampling =
      DirectLightSampling::Importance;
  // A value of zero disables the corresponding (biased) contribution clamp.
  float clamp_direct = 64.0f;
  float clamp_indirect = 16.0f;
};

struct Texture {
  TextureType type = TextureType::Constant;
  Vec3 color{1.0f};
  std::filesystem::path image_path;
  TextureColorSpace color_space = TextureColorSpace::Srgb;
  TextureWrap wrap_u = TextureWrap::ClampToEdge;
  TextureWrap wrap_v = TextureWrap::ClampToEdge;
};

struct Material {
  MaterialType type = MaterialType::Lambertian;
  std::int32_t texture_id = kInvalidId;
  Vec3 base_color{1.0f};
  Vec3 emission{0.0f};
  float roughness = 0.5f;
  float ior = 1.5f;
  Vec3 absorption{0.0f};
  float metallic = 0.0f;
  std::int32_t metallic_roughness_texture_id = kInvalidId;
  std::int32_t normal_texture_id = kInvalidId;
  float normal_scale = 1.0f;
};

struct Transform {
  Vec3 translate{0.0f};
  Vec3 rotate_degrees{0.0f};
  Vec3 scale{1.0f};
};

// Row-major object-to-world affine transform accepted by OptixInstance.
// Composition order is T * Rz * Ry * Rx * S.
using TransformMatrix3x4 = std::array<float, 12>;
TransformMatrix3x4 compose_transform(const Transform& transform);

struct MeshTriangle {
  std::uint32_t x = 0;
  std::uint32_t y = 0;
  std::uint32_t z = 0;
};

// MikkTSpace produces one tangent per face corner, not per indexed vertex.
// The sign reconstructs the bitangent as sign * cross(normal, direction).
// A zero direction/sign is deliberately retained for an unresolved corner.
struct MeshTangent {
  Vec3 direction{};
  float sign = 0.0f;
};

static_assert(sizeof(MeshTangent) == 4 * sizeof(float),
              "MeshTangent must match CUDA float4 layout");
static_assert(std::is_standard_layout<MeshTangent>::value,
              "MeshTangent must remain standard-layout");
static_assert(std::is_trivially_copyable<MeshTangent>::value,
              "MeshTangent must be device-copyable");

struct TriangleMesh {
  std::vector<Vec3> positions;
  std::vector<Vec3> normals;
  std::vector<Vec2> texcoords;
  std::vector<MeshTriangle> indices;
  // Unindexed face-corner order: three consecutive entries per triangle.
  std::vector<MeshTangent> tangents;

  bool empty() const noexcept { return positions.empty() || indices.empty(); }
  bool has_complete_uvs() const noexcept {
    return !texcoords.empty() && texcoords.size() == positions.size();
  }
  bool has_complete_tangents() const noexcept {
    if (tangents.empty() || tangents.size() != indices.size() * 3)
      return false;
    for (const MeshTangent& tangent : tangents) {
      const float tangent_length_squared = length_squared(tangent.direction);
      if (!finite(tangent.direction) || !finite(tangent_length_squared) ||
          tangent_length_squared <= 0.0f ||
          (tangent.sign != -1.0f && tangent.sign != 1.0f))
        return false;
    }
    return true;
  }
};

struct MeshResource {
  std::string name;
  TriangleMesh mesh;
  // Empty preserves the legacy per-instance front/back material path. When
  // populated, each entry is the global Scene material id for the matching
  // triangle in mesh.indices.
  std::vector<std::int32_t> material_ids;
};

struct SphereData {
  Vec3 center{};
  float radius = 1.0f;
};

// p1, p2 and p3 are consecutive corners of a parallelogram.
struct RectangleData {
  Vec3 p1{};
  Vec3 p2{0.0f, 1.0f, 0.0f};
  Vec3 p3{1.0f, 1.0f, 0.0f};
};

struct DiskData {
  Vec3 center{};
  Vec3 normal{0.0f, 1.0f, 0.0f};
  float radius = 1.0f;
};

// The open finite cylinder spans base .. base + axis * height.
struct CylinderData {
  Vec3 base{};
  Vec3 axis{0.0f, 1.0f, 0.0f};
  float height = 1.0f;
  float radius = 1.0f;
};

struct ParabolaData {
  Vec3 origin{};
  Vec3 normal{0.0f, 1.0f, 0.0f};
  Vec3 focus{0.0f, 0.0f, 1.0f};
  Aabb clip{{-1.0f, -1.0f, -1.0f}, {1.0f, 1.0f, 1.0f}};
};

struct MeshInstanceData {
  std::int32_t mesh_id = kInvalidId;
  Transform transform{};
};

struct WaterWave {
  Vec2 direction{1.0f, 0.0f};
  float amplitude = 0.1f;
  float wavelength = 1.0f;
  float phase_radians = 0.0f;
};

struct WaterSurfaceData {
  Vec3 center{};
  Vec2 size{1.0f, 1.0f};
  std::array<WaterWave, 4> waves{};
  std::uint32_t wave_count = 0;
  std::uint32_t tiles_x = 1;
  std::uint32_t tiles_z = 1;
};

using GeometryData = std::variant<SphereData,
                                  RectangleData,
                                  DiskData,
                                  CylinderData,
                                  ParabolaData,
                                  MeshInstanceData,
                                  WaterSurfaceData>;

struct Object {
  std::string name;
  GeometryType type = GeometryType::Sphere;
  GeometryData geometry = SphereData{};
  std::int32_t front_material = kInvalidId;
  std::int32_t back_material = kInvalidId;
  std::int32_t alpha_texture = kInvalidId;
  float alpha_cutoff = 0.5f;
};

struct Light {
  std::string name;
  LightType type = LightType::Sphere;
  std::int32_t object_id = kInvalidId;
  Vec3 position{};
  Vec3 edge_u{1.0f, 0.0f, 0.0f};
  Vec3 edge_v{0.0f, 0.0f, 1.0f};
  Vec3 normal{0.0f, -1.0f, 0.0f};
  // Radiance for finite surface lights; intensity for point lights; and
  // irradiance for directional lights.
  Vec3 emission{1.0f};
  float radius = 0.01f;

  // Procedural absorption-emission volume. The finite support runs
  // from position to position + axis * height and is conservatively enclosed
  // by a cylinder whose radius is max(radius_start, radius_end).
  // Flame axis, or the surface-to-light unit direction of a directional
  // light.
  Vec3 axis{0.0f, 1.0f, 0.0f};
  Vec3 emission_start{1.0f};
  Vec3 emission_end{1.0f};
  float height = 1.0f;
  float radius_start = 0.1f;
  float radius_end = 0.1f;
  float extinction = 1.0f;
  float density_scale = 1.0f;
  float turbulence = 0.35f;
  float noise_scale = 2.0f;
  std::uint32_t seed = 0;
};

struct Scene {
  Camera camera{};
  Background background{};
  Integrator integrator{};
  std::vector<Texture> textures;
  std::vector<Material> materials;
  std::vector<MeshResource> meshes;
  std::vector<Object> objects;
  std::vector<Light> lights;
};

struct ImageRgba8 {
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::vector<std::uint8_t> pixels;

  bool empty() const noexcept { return width == 0 || height == 0 || pixels.empty(); }
};

struct ImageRgba32f {
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::vector<float> pixels;

  bool empty() const noexcept {
    return width == 0 || height == 0 || pixels.empty();
  }
};

struct AvifImageInfo {
  std::uint32_t bit_depth = 0;
  std::string yuv_format;
  bool full_range = false;
  std::uint16_t color_primaries = 0;
  std::uint16_t transfer_characteristics = 0;
  std::uint16_t matrix_coefficients = 0;
  bool premultiplied = false;
  bool animated = false;
  bool has_alpha = false;
  std::uint16_t max_cll = 0;
  std::uint16_t max_pall = 0;
};

struct DecodedAvif {
  ImageRgba8 image;
  AvifImageInfo info;
};

// SDR AVIF texture pixels use top-to-bottom RGBA byte order. The color-space
// value is part of the file contract, not a request to reinterpret sample
// codes. TextureColorSpace::Hdr is rejected by this byte-oriented loader.
ImageRgba8 load_avif_rgba8(const std::filesystem::path& path,
                           TextureColorSpace color_space);
// HDR AVIF input is decoded to top-to-bottom, scene-linear Rec.709 RGBA.
// The renderer's diffuse white convention is 203 cd/m2 == 1.0. Image inputs
// are limited to 16384 pixels per dimension and 2^25 pixels in total.
ImageRgba32f load_hdr_avif_rgba32f(const std::filesystem::path& path);
DecodedAvif read_avif_rgba8(const std::filesystem::path& path);
void write_texture_avif_rgba8(const std::filesystem::path& path,
                              std::uint32_t width,
                              std::uint32_t height,
                              const std::uint8_t* pixels,
                              bool srgb,
                              std::size_t row_stride = 0);
void write_texture_avif_rgba8(const std::filesystem::path& path,
                              std::uint32_t width,
                              std::uint32_t height,
                              const std::vector<std::uint8_t>& pixels,
                              bool srgb);

struct HdrAvifInfo {
  std::uint16_t max_cll = 0;
  std::uint16_t max_pall = 0;
};

// Maps top-to-bottom linear Rec.709 RGB floats to the renderer's fixed
// 10-bit Rec.2020/PQ, 4:4:4, full-range, lossless AVIF output profile.
// Exposure must be finite and in [kMinimumExposureEv, kMaximumExposureEv].
HdrAvifInfo write_hdr_avif_rgb32f(const std::filesystem::path& path,
                                  std::uint32_t width,
                                  std::uint32_t height,
                                  const std::vector<float>& pixels,
                                  float exposure);

}  // namespace spectraldock
