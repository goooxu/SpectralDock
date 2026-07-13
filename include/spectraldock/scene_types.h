#pragma once

#include "spectraldock/math.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>
#include <variant>
#include <vector>

namespace spectraldock {

constexpr std::int32_t kInvalidId = -1;

enum class TextureType : std::uint32_t { Constant, Image };
enum class MaterialType : std::uint32_t { Lambertian, Metal, Dielectric, Emitter };
enum class GeometryType : std::uint32_t {
  Sphere,
  Rectangle,
  Sketch,
  Disk,
  Cylinder,
  Parabola,
  Mesh,
};
enum class BackgroundType : std::uint32_t { Constant, Sky };
enum class LightType : std::uint32_t { Sphere, Rectangle, Disk, Flame };

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
  float exposure = 0.0f;       // Exposure value in stops (EV).
};

struct RenderDefaults {
  std::uint32_t width = 1024;
  std::uint32_t height = 1024;
  std::uint32_t spp = 256;
  std::uint32_t max_depth = 12;
  std::uint64_t seed = 1;
  bool denoise = false;
};

struct Texture {
  std::string name;
  TextureType type = TextureType::Constant;
  Vec3 color{1.0f};
  std::filesystem::path image_path;
  bool srgb = true;
};

struct Material {
  std::string name;
  MaterialType type = MaterialType::Lambertian;
  std::int32_t texture_id = kInvalidId;
  Vec3 base_color{1.0f};
  Vec3 emission{0.0f};
  float roughness = 0.5f;
  float ior = 1.5f;
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

struct TriangleMesh {
  std::vector<Vec3> positions;
  std::vector<Vec3> normals;
  std::vector<Vec2> texcoords;
  std::vector<MeshTriangle> indices;

  bool empty() const noexcept { return positions.empty() || indices.empty(); }
  bool has_complete_uvs() const noexcept {
    return !texcoords.empty() && texcoords.size() == positions.size();
  }
};

struct MeshResource {
  std::string name;
  std::filesystem::path path;
  TriangleMesh mesh;
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

struct SketchData {
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

using GeometryData = std::variant<SphereData,
                                  RectangleData,
                                  SketchData,
                                  DiskData,
                                  CylinderData,
                                  ParabolaData,
                                  MeshInstanceData>;

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
  Vec3 emission{1.0f};
  float radius = 0.01f;

  // Schema v3 procedural absorption-emission volume. The finite support runs
  // from position to position + axis * height and is conservatively enclosed
  // by a cylinder whose radius is max(radius_start, radius_end).
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
  std::uint32_t schema_version = 1;
  Camera camera{};
  Background background{};
  RenderDefaults render{};
  std::vector<Texture> textures;
  std::vector<Material> materials;
  std::vector<MeshResource> meshes;
  std::vector<Object> objects;
  std::vector<Light> lights;
};

struct SceneLoadOptions {
  bool require_assets = true;
};

Scene load_scene(const std::filesystem::path& path,
                 const SceneLoadOptions& options = SceneLoadOptions{});

struct ImageRgba8 {
  std::uint32_t width = 0;
  std::uint32_t height = 0;
  std::vector<std::uint8_t> pixels;

  bool empty() const noexcept { return width == 0 || height == 0 || pixels.empty(); }
};

ImageRgba8 load_png_rgba8(const std::filesystem::path& path);
void write_png_rgba8(const std::filesystem::path& path,
                     std::uint32_t width,
                     std::uint32_t height,
                     const std::uint8_t* pixels,
                     std::size_t row_stride = 0);
void write_png_rgba8(const std::filesystem::path& path,
                     std::uint32_t width,
                     std::uint32_t height,
                     const std::vector<std::uint8_t>& pixels);

}  // namespace spectraldock
