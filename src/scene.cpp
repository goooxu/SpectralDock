#include "spectraldock/scene_types.h"
#include "spectraldock/obj_loader.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <initializer_list>
#include <limits>
#include <stdexcept>
#include <string_view>
#include <unordered_map>
#include <unordered_set>

namespace spectraldock {
namespace {

using json = nlohmann::json;
using IdMap = std::unordered_map<std::string, std::int32_t>;

[[noreturn]] void fail(const std::string& where, const std::string& message) {
  throw std::runtime_error("scene " + where + ": " + message);
}

const json& member(const json& object, const char* key, std::string_view where) {
  const std::string context(where);
  if (!object.is_object()) fail(context, "expected an object");
  const auto it = object.find(key);
  if (it == object.end()) fail(context, "missing required key '" + std::string(key) + "'");
  return *it;
}

float number(const json& value, const std::string& where) {
  if (!value.is_number()) fail(where, "expected a number");
  const double x = value.get<double>();
  if (!std::isfinite(x) || x < -std::numeric_limits<float>::max() ||
      x > std::numeric_limits<float>::max()) {
    fail(where, "number is not finite float32");
  }
  return static_cast<float>(x);
}

float optional_number(const json& object, const char* key, float fallback, const std::string& where) {
  const auto it = object.find(key);
  return it == object.end() ? fallback : number(*it, where + "." + key);
}

Vec3 vec3(const json& value, const std::string& where) {
  if (!value.is_array() || value.size() != 3) fail(where, "expected [x, y, z]");
  return {number(value[0], where + "[0]"),
          number(value[1], where + "[1]"),
          number(value[2], where + "[2]")};
}

Vec3 optional_vec3(const json& object, const char* key, Vec3 fallback, const std::string& where) {
  const auto it = object.find(key);
  return it == object.end() ? fallback : vec3(*it, where + "." + key);
}

Vec2 vec2(const json& value, const std::string& where) {
  if (!value.is_array() || value.size() != 2) fail(where, "expected [x, y]");
  return {number(value[0], where + "[0]"),
          number(value[1], where + "[1]")};
}

std::string text(const json& value, const std::string& where) {
  if (!value.is_string()) fail(where, "expected a string");
  const std::string result = value.get<std::string>();
  if (result.empty()) fail(where, "must not be empty");
  return result;
}

bool optional_bool(const json& object, const char* key, bool fallback, const std::string& where) {
  const auto it = object.find(key);
  if (it == object.end()) return fallback;
  if (!it->is_boolean()) fail(where + "." + key, "expected true or false");
  return it->get<bool>();
}

std::uint32_t optional_u32(const json& object,
                           const char* key,
                           std::uint32_t fallback,
                           std::uint32_t minimum,
                           std::uint32_t maximum,
                           const std::string& where) {
  const auto it = object.find(key);
  if (it == object.end()) return fallback;
  if (!it->is_number_unsigned() && !it->is_number_integer())
    fail(where + "." + key, "expected an integer");
  const auto value = it->get<std::int64_t>();
  if (value < static_cast<std::int64_t>(minimum) ||
      value > static_cast<std::int64_t>(maximum)) {
    fail(where + "." + key,
         "must be in [" + std::to_string(minimum) + ", " + std::to_string(maximum) + "]");
  }
  return static_cast<std::uint32_t>(value);
}

void nonnegative(Vec3 value, const std::string& where) {
  if (!finite(value) || value.x < 0.0f || value.y < 0.0f || value.z < 0.0f)
    fail(where, "components must be finite and non-negative");
}

void require_only_members(
    const json& object,
    std::initializer_list<std::string_view> allowed,
    const std::string& where) {
  if (!object.is_object()) fail(where, "expected an object");
  for (auto it = object.begin(); it != object.end(); ++it) {
    const std::string& key = it.key();
    const bool accepted = std::any_of(
        allowed.begin(), allowed.end(), [&](std::string_view candidate) {
          return std::string_view(key) == candidate;
        });
    if (!accepted) fail(where + "." + key, "key is not valid for this light type");
  }
}

Vec3 unit_vector(const json& value, const std::string& where) {
  const Vec3 v = vec3(value, where);
  // Compute the norm in double precision. Squaring a valid float32 component
  // near FLT_MAX overflows in float and would otherwise normalize to zero.
  const double norm = std::hypot(
      static_cast<double>(v.x), static_cast<double>(v.y),
      static_cast<double>(v.z));
  if (norm < 1.0e-6) fail(where, "must be non-zero");
  return {static_cast<float>(static_cast<double>(v.x) / norm),
          static_cast<float>(static_cast<double>(v.y) / norm),
          static_cast<float>(static_cast<double>(v.z) / norm)};
}

std::filesystem::path resolve_path(const std::filesystem::path& scene_path,
                                   const std::string& value) {
  std::filesystem::path result(value);
  if (result.is_relative()) result = scene_path.parent_path() / result;
  return std::filesystem::absolute(result).lexically_normal();
}

void insert_unique(IdMap& ids, const std::string& name, std::int32_t id, const std::string& where) {
  if (!ids.emplace(name, id).second) fail(where, "duplicate name '" + name + "'");
}

std::int32_t lookup(const IdMap& ids, const std::string& name, const std::string& where) {
  const auto it = ids.find(name);
  if (it == ids.end()) fail(where, "unknown reference '" + name + "'");
  return it->second;
}

std::int32_t optional_reference(const json& object,
                                const char* key,
                                const IdMap& ids,
                                const std::string& where) {
  const auto it = object.find(key);
  if (it == object.end() || it->is_null()) return kInvalidId;
  return lookup(ids, text(*it, where + "." + key), where + "." + key);
}

Aabb parse_aabb(const json& value, const std::string& where) {
  Aabb box{vec3(member(value, "min", where), where + ".min"),
           vec3(member(value, "max", where), where + ".max")};
  if (!box.valid()) fail(where, "bounds must be finite and ordered");
  if (box.min.x == box.max.x || box.min.y == box.max.y || box.min.z == box.max.z)
    fail(where, "bounds must have positive extent on every axis");
  return box;
}

void validate_rectangle(Vec3 p1, Vec3 p2, Vec3 p3, const std::string& where) {
  const Vec3 edge1 = p2 - p1;
  const Vec3 edge2 = p3 - p2;
  if (length_squared(edge1) < 1.0e-12f || length_squared(edge2) < 1.0e-12f ||
      length_squared(cross(edge1, edge2)) < 1.0e-12f) {
    fail(where, "rectangle corners are degenerate");
  }
}

bool approximately_equal(float a, float b) {
  const float scale = std::max(1.0f, std::max(std::fabs(a), std::fabs(b)));
  return std::fabs(a - b) <= 1.0e-5f * scale;
}

bool approximately_equal(Vec3 a, Vec3 b) {
  return approximately_equal(a.x, b.x) &&
         approximately_equal(a.y, b.y) &&
         approximately_equal(a.z, b.z);
}

bool same_rectangle(const RectangleData& geometry, const Light& light) {
  const Vec3 geometry_points[4] = {
      geometry.p1, geometry.p2, geometry.p3,
      geometry.p1 + geometry.p3 - geometry.p2};
  const Vec3 light_points[4] = {
      light.position, light.position + light.edge_u,
      light.position + light.edge_v,
      light.position + light.edge_u + light.edge_v};
  bool matched[4] = {false, false, false, false};
  for (const Vec3 point : light_points) {
    bool found = false;
    for (int i = 0; i < 4; ++i) {
      if (!matched[i] && approximately_equal(point, geometry_points[i])) {
        matched[i] = true;
        found = true;
        break;
      }
    }
    if (!found) return false;
  }
  return true;
}

Camera parse_camera(const json& value) {
  const std::string where = "camera";
  Camera camera;
  camera.look_from = vec3(member(value, "look_from", where), where + ".look_from");
  camera.look_at = vec3(member(value, "look_at", where), where + ".look_at");
  camera.up = unit_vector(member(value, "up", where), where + ".up");
  const auto vfov = value.find("vertical_fov_degrees");
  camera.vertical_fov_degrees = vfov == value.end()
                                    ? optional_number(value, "vfov", camera.vertical_fov_degrees, where)
                                    : number(*vfov, where + ".vertical_fov_degrees");
  camera.aperture = optional_number(value, "aperture", camera.aperture, where);
  camera.focus_distance = optional_number(value, "focus_distance", length(camera.look_from - camera.look_at), where);
  if (length_squared(camera.look_from - camera.look_at) < 1.0e-12f)
    fail(where, "look_from and look_at must differ");
  if (length_squared(cross(camera.look_at - camera.look_from, camera.up)) < 1.0e-12f)
    fail(where, "up must not be parallel to the view direction");
  if (!(camera.vertical_fov_degrees > 0.0f && camera.vertical_fov_degrees < 179.0f))
    fail(where + ".vertical_fov_degrees", "must be in (0, 179)");
  if (camera.aperture < 0.0f) fail(where + ".aperture", "must be non-negative");
  if (!(camera.focus_distance > 0.0f)) fail(where + ".focus_distance", "must be positive");
  return camera;
}

Background parse_background(const json& value,
                            const std::filesystem::path& scene_path,
                            const SceneLoadOptions& options) {
  const std::string where = "background";
  Background background;
  const std::string type = text(member(value, "type", where), where + ".type");
  background.exposure = optional_number(value, "exposure", 0.0f, where);
  if (type == "constant") {
    background.type = BackgroundType::Constant;
    background.color = vec3(member(value, "color", where), where + ".color");
    nonnegative(background.color, where + ".color");
  } else if (type == "sky") {
    background.type = BackgroundType::Sky;
    background.sky_bottom = optional_vec3(value, "bottom", background.sky_bottom, where);
    background.sky_top = optional_vec3(value, "top", background.sky_top, where);
    background.sun_color = optional_vec3(value, "sun_color", background.sun_color, where);
    background.sun_cos_angle = optional_number(value, "sun_cos_angle", background.sun_cos_angle, where);
    if (value.contains("sun_direction"))
      background.sun_direction = unit_vector(value.at("sun_direction"), where + ".sun_direction");
    nonnegative(background.sky_bottom, where + ".bottom");
    nonnegative(background.sky_top, where + ".top");
    nonnegative(background.sun_color, where + ".sun_color");
    if (background.sun_cos_angle < -1.0f || background.sun_cos_angle > 2.0f)
      fail(where + ".sun_cos_angle", "must be in [-1, 2]");
  } else if (type == "environment") {
    background.type = BackgroundType::Environment;
    background.environment_path = resolve_path(
        scene_path, text(member(value, "path", where), where + ".path"));
    background.environment_intensity = optional_number(
        value, "intensity", background.environment_intensity, where);
    background.environment_rotation_degrees = optional_number(
        value, "rotation_degrees", background.environment_rotation_degrees,
        where);
    if (background.environment_intensity < 0.0f)
      fail(where + ".intensity", "must be non-negative");
    if (options.require_assets &&
        !std::filesystem::is_regular_file(background.environment_path)) {
      fail(where + ".path",
           "asset not found: " + background.environment_path.string());
    }
  } else {
    fail(where + ".type", "unsupported type '" + type + "'");
  }
  return background;
}

Integrator parse_integrator(const json& value) {
  const std::string where = "integrator";
  if (!value.is_object()) fail(where, "expected an object");
  Integrator integrator;
  const auto sampling = value.find("direct_light_sampling");
  if (sampling != value.end()) {
    const std::string mode = text(*sampling, where + ".direct_light_sampling");
    if (mode == "uniform") {
      integrator.direct_light_sampling = DirectLightSampling::Uniform;
    } else if (mode == "importance") {
      integrator.direct_light_sampling = DirectLightSampling::Importance;
    } else {
      fail(where + ".direct_light_sampling",
           "expected 'uniform' or 'importance'");
    }
  }
  integrator.clamp_direct =
      optional_number(value, "clamp_direct", integrator.clamp_direct, where);
  integrator.clamp_indirect = optional_number(
      value, "clamp_indirect", integrator.clamp_indirect, where);
  if (integrator.clamp_direct < 0.0f)
    fail(where + ".clamp_direct", "must be non-negative");
  if (integrator.clamp_indirect < 0.0f)
    fail(where + ".clamp_indirect", "must be non-negative");
  return integrator;
}

RenderDefaults parse_render(const json& value) {
  const std::string where = "render";
  RenderDefaults render;
  render.width = optional_u32(value, "width", render.width, 1, 16384, where);
  render.height = optional_u32(value, "height", render.height, 1, 16384, where);
  render.spp = optional_u32(value, "spp", render.spp, 1, 1000000, where);
  render.max_depth = optional_u32(value, "max_depth", render.max_depth, 1, 64, where);
  render.denoise = optional_bool(value, "denoise", render.denoise, where);
  const auto seed = value.find("seed");
  if (seed != value.end()) {
    if (!seed->is_number_unsigned() && !seed->is_number_integer()) fail(where + ".seed", "expected an integer");
    const auto signed_seed = seed->get<std::int64_t>();
    if (signed_seed < 0) fail(where + ".seed", "must be non-negative");
    render.seed = static_cast<std::uint64_t>(signed_seed);
  }
  return render;
}

Transform parse_transform(const json& value, const std::string& where) {
  if (!value.is_object()) fail(where, "expected an object");
  Transform transform;
  transform.translate =
      optional_vec3(value, "translate", transform.translate, where);
  transform.rotate_degrees =
      optional_vec3(value, "rotate_degrees", transform.rotate_degrees, where);
  transform.scale = optional_vec3(value, "scale", transform.scale, where);
  if (!(transform.scale.x > 0.0f) || !(transform.scale.y > 0.0f) ||
      !(transform.scale.z > 0.0f))
    fail(where + ".scale", "components must be greater than zero");
  return transform;
}

bool material_uses_texture(const Scene& scene, std::int32_t material_id) {
  return material_id != kInvalidId &&
         scene.materials[static_cast<std::size_t>(material_id)].texture_id !=
             kInvalidId;
}

bool object_requires_uvs(const Scene& scene, const Object& object) {
  return object.alpha_texture != kInvalidId ||
         material_uses_texture(scene, object.front_material) ||
         material_uses_texture(scene, object.back_material);
}

void require_schema_version_6(const json& root) {
  const json& value = member(root, "schema_version", "root");
  if (!value.is_number_unsigned() && !value.is_number_integer())
    fail("root.schema_version", "expected the integer 6");
  if (value != 6)
    fail("root.schema_version", "unsupported schema version; expected 6");
}

}  // namespace

TransformMatrix3x4 compose_transform(const Transform& transform) {
  const float radians = kPi / 180.0f;
  const float cx = std::cos(transform.rotate_degrees.x * radians);
  const float sx = std::sin(transform.rotate_degrees.x * radians);
  const float cy = std::cos(transform.rotate_degrees.y * radians);
  const float sy = std::sin(transform.rotate_degrees.y * radians);
  const float cz = std::cos(transform.rotate_degrees.z * radians);
  const float sz = std::sin(transform.rotate_degrees.z * radians);

  // Rz * Ry * Rx, followed by column-wise scale and affine translation.
  return {
      cz * cy * transform.scale.x,
      (cz * sy * sx - sz * cx) * transform.scale.y,
      (cz * sy * cx + sz * sx) * transform.scale.z,
      transform.translate.x,
      sz * cy * transform.scale.x,
      (sz * sy * sx + cz * cx) * transform.scale.y,
      (sz * sy * cx - cz * sx) * transform.scale.z,
      transform.translate.y,
      -sy * transform.scale.x,
      cy * sx * transform.scale.y,
      cy * cx * transform.scale.z,
      transform.translate.z,
  };
}

Scene load_scene(const std::filesystem::path& input_path, const SceneLoadOptions& options) {
  const std::filesystem::path path = std::filesystem::absolute(input_path).lexically_normal();
  std::ifstream input(path);
  if (!input) throw std::runtime_error("cannot open scene file: " + path.string());
  json root;
  try {
    input >> root;
  } catch (const json::exception& error) {
    throw std::runtime_error("cannot parse scene file " + path.string() + ": " + error.what());
  }
  if (!root.is_object()) fail("root", "expected an object");
  require_schema_version_6(root);

  Scene scene;
  scene.camera = parse_camera(member(root, "camera", "root"));
  scene.background =
      parse_background(member(root, "background", "root"), path, options);
  if (root.contains("integrator"))
    scene.integrator = parse_integrator(root.at("integrator"));
  if (root.contains("render")) scene.render = parse_render(root.at("render"));

  IdMap mesh_ids;
  if (root.contains("meshes")) {
    const json& meshes = root.at("meshes");
    if (!meshes.is_array()) fail("meshes", "expected an array");
    for (std::size_t i = 0; i < meshes.size(); ++i) {
      const json& value = meshes[i];
      const std::string where = "meshes[" + std::to_string(i) + "]";
      MeshResource resource;
      resource.name = text(member(value, "name", where), where + ".name");
      resource.path = resolve_path(
          path, text(member(value, "path", where), where + ".path"));
      insert_unique(mesh_ids, resource.name,
                    static_cast<std::int32_t>(scene.meshes.size()), where);
      if (std::filesystem::is_regular_file(resource.path)) {
        try {
          resource.mesh = load_obj_mesh(resource.path);
        } catch (const std::exception& error) {
          fail(where + ".path", error.what());
        }
      } else if (options.require_assets) {
        fail(where + ".path", "asset not found: " + resource.path.string());
      }
      scene.meshes.push_back(std::move(resource));
    }
  }

  IdMap texture_ids;
  const json& textures = member(root, "textures", "root");
  if (!textures.is_array()) fail("textures", "expected an array");
  for (std::size_t i = 0; i < textures.size(); ++i) {
    const json& value = textures[i];
    const std::string where = "textures[" + std::to_string(i) + "]";
    Texture texture;
    texture.name = text(member(value, "name", where), where + ".name");
    const std::string type = text(member(value, "type", where), where + ".type");
    if (type == "constant") {
      texture.type = TextureType::Constant;
      texture.color = vec3(member(value, "color", where), where + ".color");
      nonnegative(texture.color, where + ".color");
      texture.srgb = false;
    } else if (type == "image") {
      texture.type = TextureType::Image;
      const std::string asset = text(member(value, "path", where), where + ".path");
      texture.image_path = resolve_path(path, asset);
      const std::string color_space = value.value("color_space", std::string("srgb"));
      if (color_space != "srgb" && color_space != "linear")
        fail(where + ".color_space", "expected 'srgb' or 'linear'");
      texture.srgb = color_space == "srgb";
      if (options.require_assets && !std::filesystem::is_regular_file(texture.image_path))
        fail(where + ".path", "asset not found: " + texture.image_path.string());
    } else {
      fail(where + ".type", "unsupported type '" + type + "'");
    }
    insert_unique(texture_ids, texture.name, static_cast<std::int32_t>(scene.textures.size()), where);
    scene.textures.push_back(std::move(texture));
  }

  IdMap material_ids;
  const json& materials = member(root, "materials", "root");
  if (!materials.is_array()) fail("materials", "expected an array");
  for (std::size_t i = 0; i < materials.size(); ++i) {
    const json& value = materials[i];
    const std::string where = "materials[" + std::to_string(i) + "]";
    Material material;
    material.name = text(member(value, "name", where), where + ".name");
    const std::string type = text(member(value, "type", where), where + ".type");
    if (type == "lambertian") material.type = MaterialType::Lambertian;
    else if (type == "metal") material.type = MaterialType::Metal;
    else if (type == "dielectric") material.type = MaterialType::Dielectric;
    else if (type == "emitter") material.type = MaterialType::Emitter;
    else if (type == "water") material.type = MaterialType::Water;
    else {
      fail(where + ".type", "unsupported type '" + type + "'");
    }
    if (material.type == MaterialType::Water) {
      for (const char* key : {"texture", "base_color", "emission"}) {
        if (value.contains(key))
          fail(where + "." + key, "is not supported by water materials");
      }
      material.roughness = optional_number(value, "roughness", 0.0f, where);
      material.ior = optional_number(value, "ior", 1.333f, where);
      material.absorption =
          optional_vec3(value, "absorption", {0.35f, 0.08f, 0.025f}, where);
      nonnegative(material.absorption, where + ".absorption");
      if (!(material.ior > 1.0f && material.ior <= 3.0f))
        fail(where + ".ior", "water IOR must be in (1, 3]");
    } else {
      material.texture_id = optional_reference(value, "texture", texture_ids, where);
      material.base_color = optional_vec3(value, "base_color", material.base_color, where);
      material.emission = optional_vec3(value, "emission", material.emission, where);
      const float default_roughness =
          material.type == MaterialType::Dielectric ? 0.0f : 0.5f;
      material.roughness =
          optional_number(value, "roughness", default_roughness, where);
      material.ior = optional_number(value, "ior", material.ior, where);
    }
    nonnegative(material.base_color, where + ".base_color");
    nonnegative(material.emission, where + ".emission");
    if (material.roughness < 0.0f || material.roughness > 1.0f)
      fail(where + ".roughness", "must be in [0, 1]");
    if (material.type == MaterialType::Dielectric && !(material.ior > 1.0f))
      fail(where + ".ior", "dielectric IOR must be greater than 1");
    if (material.type == MaterialType::Emitter && max_component(material.emission) <= 0.0f &&
        material.texture_id == kInvalidId)
      fail(where, "emitter needs positive emission or a texture");
    insert_unique(material_ids, material.name, static_cast<std::int32_t>(scene.materials.size()), where);
    scene.materials.push_back(std::move(material));
  }

  IdMap object_ids;
  const json& objects = member(root, "objects", "root");
  if (!objects.is_array()) fail("objects", "expected an array");
  std::size_t water_surface_count = 0;
  for (std::size_t i = 0; i < objects.size(); ++i) {
    const json& value = objects[i];
    const std::string where = "objects[" + std::to_string(i) + "]";
    Object object;
    object.name = text(member(value, "name", where), where + ".name");
    insert_unique(object_ids, object.name,
                  static_cast<std::int32_t>(scene.objects.size()), where);
    if (value.contains("material")) {
      const std::int32_t id = lookup(material_ids, text(value.at("material"), where + ".material"), where + ".material");
      object.front_material = id;
      object.back_material = id;
    }
    if (value.contains("front_material"))
      object.front_material = optional_reference(value, "front_material", material_ids, where);
    if (value.contains("back_material"))
      object.back_material = optional_reference(value, "back_material", material_ids, where);
    if (object.front_material == kInvalidId && object.back_material == kInvalidId)
      fail(where, "at least one face material is required");
    object.alpha_texture = optional_reference(value, "alpha_texture", texture_ids, where);
    object.alpha_cutoff = optional_number(value, "alpha_cutoff", object.alpha_cutoff, where);
    if (object.alpha_cutoff < 0.0f || object.alpha_cutoff > 1.0f)
      fail(where + ".alpha_cutoff", "must be in [0, 1]");

    const std::string type = text(member(value, "type", where), where + ".type");
    if (type != "mesh" && value.contains("transform"))
      fail(where + ".transform", "is supported only for mesh objects");
    if (type == "mesh") {
      object.type = GeometryType::Mesh;
      MeshInstanceData data;
      data.mesh_id = lookup(
          mesh_ids, text(member(value, "mesh", where), where + ".mesh"),
          where + ".mesh");
      if (value.contains("transform"))
        data.transform = parse_transform(value.at("transform"),
                                         where + ".transform");
      const MeshResource& resource =
          scene.meshes[static_cast<std::size_t>(data.mesh_id)];
      if (!resource.mesh.empty() && !resource.mesh.has_complete_uvs() &&
          object_requires_uvs(scene, object)) {
        fail(where,
             "mesh '" + resource.name + "' has no complete UV coordinates "
             "but the object binds a material or alpha texture");
      }
      object.geometry = data;
    } else if (type == "sphere") {
      object.type = GeometryType::Sphere;
      SphereData data{vec3(member(value, "center", where), where + ".center"),
                      number(member(value, "radius", where), where + ".radius")};
      if (!(data.radius > 0.0f)) fail(where + ".radius", "must be positive");
      object.geometry = data;
    } else if (type == "rectangle" || type == "sketch") {
      const Vec3 p1 = vec3(member(value, "p1", where), where + ".p1");
      const Vec3 p2 = vec3(member(value, "p2", where), where + ".p2");
      const Vec3 p3 = vec3(member(value, "p3", where), where + ".p3");
      validate_rectangle(p1, p2, p3, where);
      if (type == "rectangle") {
        object.type = GeometryType::Rectangle;
        object.geometry = RectangleData{p1, p2, p3};
      } else {
        if (object.alpha_texture == kInvalidId) fail(where, "sketch requires alpha_texture");
        object.type = GeometryType::Sketch;
        object.geometry = SketchData{p1, p2, p3};
      }
    } else if (type == "disk") {
      object.type = GeometryType::Disk;
      DiskData data;
      data.center = vec3(member(value, "center", where), where + ".center");
      data.normal = unit_vector(member(value, "normal", where), where + ".normal");
      data.radius = number(member(value, "radius", where), where + ".radius");
      if (!(data.radius > 0.0f)) fail(where + ".radius", "must be positive");
      object.geometry = data;
    } else if (type == "cylinder") {
      object.type = GeometryType::Cylinder;
      CylinderData data;
      data.base = vec3(member(value, "base", where), where + ".base");
      data.axis = unit_vector(member(value, "axis", where), where + ".axis");
      data.height = number(member(value, "height", where), where + ".height");
      data.radius = number(member(value, "radius", where), where + ".radius");
      if (!(data.height > 0.0f)) fail(where + ".height", "must be positive");
      if (!(data.radius > 0.0f)) fail(where + ".radius", "must be positive");
      object.geometry = data;
    } else if (type == "parabola") {
      object.type = GeometryType::Parabola;
      ParabolaData data;
      data.origin = vec3(member(value, "origin", where), where + ".origin");
      data.normal = unit_vector(member(value, "normal", where), where + ".normal");
      data.focus = vec3(member(value, "focus", where), where + ".focus");
      data.clip = parse_aabb(member(value, "clip", where), where + ".clip");
      const Vec3 opening = data.focus - data.origin;
      if (length_squared(opening) < 1.0e-12f) fail(where + ".focus", "must differ from origin");
      if (std::fabs(dot(normalize(opening), data.normal)) > 1.0e-5f)
        fail(where, "normal must be perpendicular to focus-origin");
      object.geometry = data;
    } else if (type == "water_surface") {
      if (++water_surface_count > 4)
        fail("objects", "must contain at most 4 water_surface objects");
      if (!value.contains("material") || value.contains("front_material") ||
          value.contains("back_material"))
        fail(where, "water_surface requires one shared 'material'");
      if (object.alpha_texture != kInvalidId || value.contains("alpha_cutoff"))
        fail(where, "water_surface does not support alpha");
      if (object.front_material != object.back_material ||
          scene.materials[static_cast<std::size_t>(object.front_material)].type !=
              MaterialType::Water)
        fail(where + ".material", "water_surface requires a water material");

      object.type = GeometryType::WaterSurface;
      WaterSurfaceData data;
      data.center = vec3(member(value, "center", where), where + ".center");
      data.size = vec2(member(value, "size", where), where + ".size");
      if (!(data.size.x > 0.0f) || !(data.size.y > 0.0f))
        fail(where + ".size", "components must be positive");

      const json& waves = member(value, "waves", where);
      if (!waves.is_array() || waves.empty() || waves.size() > data.waves.size())
        fail(where + ".waves", "must contain 1 to 4 waves");
      data.wave_count = static_cast<std::uint32_t>(waves.size());
      double total_slope = 0.0;
      double total_amplitude = 0.0;
      float shortest_wavelength = std::numeric_limits<float>::max();
      for (std::size_t wave_index = 0; wave_index < waves.size(); ++wave_index) {
        const json& wave_value = waves[wave_index];
        const std::string wave_where =
            where + ".waves[" + std::to_string(wave_index) + "]";
        if (!wave_value.is_object()) fail(wave_where, "expected an object");
        WaterWave wave;
        wave.direction =
            vec2(member(wave_value, "direction", wave_where),
                 wave_where + ".direction");
        const double direction_length_squared =
            static_cast<double>(wave.direction.x) * wave.direction.x +
            static_cast<double>(wave.direction.y) * wave.direction.y;
        if (!(direction_length_squared >= 1.0e-12))
          fail(wave_where + ".direction", "must be non-zero");
        const double inverse_direction_length =
            1.0 / std::sqrt(direction_length_squared);
        wave.direction.x = static_cast<float>(
            static_cast<double>(wave.direction.x) * inverse_direction_length);
        wave.direction.y = static_cast<float>(
            static_cast<double>(wave.direction.y) * inverse_direction_length);
        wave.amplitude =
            number(member(wave_value, "amplitude", wave_where),
                   wave_where + ".amplitude");
        wave.wavelength =
            number(member(wave_value, "wavelength", wave_where),
                   wave_where + ".wavelength");
        wave.phase_radians =
            number(member(wave_value, "phase_radians", wave_where),
                   wave_where + ".phase_radians");
        if (!(wave.amplitude > 0.0f))
          fail(wave_where + ".amplitude", "must be positive");
        if (!(wave.wavelength > 0.0f))
          fail(wave_where + ".wavelength", "must be positive");
        const double wave_number =
            2.0 * static_cast<double>(kPi) /
            static_cast<double>(wave.wavelength);
        if (!std::isfinite(wave_number) ||
            wave_number > std::numeric_limits<float>::max()) {
          fail(wave_where + ".wavelength",
               "produces a non-finite float32 wave number");
        }
        wave.phase_radians = std::fmod(wave.phase_radians, 2.0f * kPi);
        if (wave.phase_radians < 0.0f) wave.phase_radians += 2.0f * kPi;
        total_slope += 2.0 * static_cast<double>(kPi) *
                       static_cast<double>(wave.amplitude) /
                       static_cast<double>(wave.wavelength);
        total_amplitude += static_cast<double>(wave.amplitude);
        shortest_wavelength = std::min(shortest_wavelength, wave.wavelength);
        data.waves[wave_index] = wave;
      }
      if (!(total_slope <= 1.0))
        fail(where + ".waves", "total wave slope must be at most 1");

      const double tile_extent = 0.5 * static_cast<double>(shortest_wavelength);
      const double tiles_x =
          std::ceil(static_cast<double>(data.size.x) / tile_extent);
      const double tiles_z =
          std::ceil(static_cast<double>(data.size.y) / tile_extent);
      if (!(tiles_x >= 1.0 && tiles_x <= 4096.0 &&
            tiles_z >= 1.0 && tiles_z <= 4096.0 &&
            tiles_x * tiles_z <= 4096.0))
        fail(where, "automatic water tile count must be at most 4096");
      data.tiles_x = static_cast<std::uint32_t>(tiles_x);
      data.tiles_z = static_cast<std::uint32_t>(tiles_z);
      if (!(data.size.x / static_cast<float>(data.tiles_x) > 0.0f) ||
          !(data.size.y / static_cast<float>(data.tiles_z) > 0.0f)) {
        fail(where, "automatic water tile extent underflows float32");
      }
      const auto finite_float32 = [](double value) {
        return std::isfinite(value) &&
               value >= -static_cast<double>(
                            std::numeric_limits<float>::max()) &&
               value <= static_cast<double>(
                            std::numeric_limits<float>::max());
      };
      const double minimum_x = static_cast<double>(data.center.x) -
                               0.5 * static_cast<double>(data.size.x);
      const double maximum_x = static_cast<double>(data.center.x) +
                               0.5 * static_cast<double>(data.size.x);
      const double minimum_y =
          static_cast<double>(data.center.y) - total_amplitude;
      const double maximum_y =
          static_cast<double>(data.center.y) + total_amplitude;
      const double minimum_z = static_cast<double>(data.center.z) -
                               0.5 * static_cast<double>(data.size.y);
      const double maximum_z = static_cast<double>(data.center.z) +
                               0.5 * static_cast<double>(data.size.y);
      if (!finite_float32(minimum_x) || !finite_float32(maximum_x) ||
          !finite_float32(minimum_y) || !finite_float32(maximum_y) ||
          !finite_float32(minimum_z) || !finite_float32(maximum_z) ||
          !(static_cast<float>(minimum_x) < static_cast<float>(maximum_x)) ||
          !(static_cast<float>(minimum_y) < static_cast<float>(maximum_y)) ||
          !(static_cast<float>(minimum_z) < static_cast<float>(maximum_z))) {
        fail(where, "derived water bounds must be finite non-degenerate float32");
      }
      const auto tile_boundaries_increase = [](
          float center, float size, std::uint32_t tiles) {
        const float minimum = center - 0.5f * size;
        const float width = size / static_cast<float>(tiles);
        float previous = minimum;
        for (std::uint32_t tile = 1u; tile <= tiles; ++tile) {
          const float boundary =
              minimum + width * static_cast<float>(tile);
          if (!(boundary > previous)) return false;
          previous = boundary;
        }
        return true;
      };
      if (!tile_boundaries_increase(
              data.center.x, data.size.x, data.tiles_x) ||
          !tile_boundaries_increase(
              data.center.z, data.size.y, data.tiles_z)) {
        fail(where,
             "automatic water tile boundaries collapse in float32");
      }
      object.geometry = data;
    } else {
      fail(where + ".type", "unsupported type '" + type + "'");
    }
    if (type != "water_surface") {
      const auto binds_water = [&](std::int32_t material_id) {
        return material_id != kInvalidId &&
               scene.materials[static_cast<std::size_t>(material_id)].type ==
                   MaterialType::Water;
      };
      if (binds_water(object.front_material) || binds_water(object.back_material))
        fail(where, "water materials can only be bound to water_surface objects");
    }
    scene.objects.push_back(std::move(object));
  }

  if (water_surface_count != 0) {
    struct DielectricSphereBoundary {
      std::size_t object_index;
      SphereData sphere;
    };
    struct WaterSurfaceBounds {
      std::size_t object_index;
      double minimum_x;
      double maximum_x;
      double minimum_y;
      double maximum_y;
      double minimum_z;
      double maximum_z;
    };
    std::vector<DielectricSphereBoundary> dielectric_spheres;
    std::vector<WaterSurfaceBounds> water_bounds;
    const auto binds_dielectric = [&](std::int32_t material_id) {
      return material_id != kInvalidId &&
             scene.materials[static_cast<std::size_t>(material_id)].type ==
                 MaterialType::Dielectric;
    };
    for (std::size_t i = 0; i < scene.objects.size(); ++i) {
      const Object& object = scene.objects[i];
      if (object.type == GeometryType::WaterSurface) {
        const WaterSurfaceData& water =
            std::get<WaterSurfaceData>(object.geometry);
        double amplitude = 0.0;
        for (std::uint32_t wave = 0; wave < water.wave_count; ++wave) {
          amplitude += static_cast<double>(water.waves[wave].amplitude);
        }
        water_bounds.push_back(
            {i,
             static_cast<double>(water.center.x) -
                 0.5 * static_cast<double>(water.size.x),
             static_cast<double>(water.center.x) +
                 0.5 * static_cast<double>(water.size.x),
             static_cast<double>(water.center.y) - amplitude,
             static_cast<double>(water.center.y) + amplitude,
             static_cast<double>(water.center.z) -
                 0.5 * static_cast<double>(water.size.y),
             static_cast<double>(water.center.z) +
                 0.5 * static_cast<double>(water.size.y)});
        continue;
      }
      if (object.type == GeometryType::Sphere) {
        const bool has_dielectric = binds_dielectric(object.front_material) ||
                                    binds_dielectric(object.back_material);
        if (has_dielectric &&
            (object.front_material != object.back_material ||
             !binds_dielectric(object.front_material))) {
          fail("objects[" + std::to_string(i) + "]",
               "dielectric sphere boundaries in water scenes require one "
               "shared dielectric material on both faces");
        }
        if (has_dielectric && object.alpha_texture != kInvalidId) {
          fail("objects[" + std::to_string(i) + "]",
               "dielectric sphere boundaries in water scenes cannot use "
               "alpha textures");
        }
        if (has_dielectric) {
          dielectric_spheres.push_back(
              {i, std::get<SphereData>(object.geometry)});
        }
        continue;
      }
      if (binds_dielectric(object.front_material) ||
          binds_dielectric(object.back_material)) {
        fail("objects[" + std::to_string(i) + "]",
             "dielectric materials in water scenes require closed sphere "
             "geometry; open dielectric boundaries are not supported");
      }
    }

    const auto distance_between = [](Vec3 a, Vec3 b) {
      const double x = static_cast<double>(a.x) - b.x;
      const double y = static_cast<double>(a.y) - b.y;
      const double z = static_cast<double>(a.z) - b.z;
      return std::sqrt(x * x + y * y + z * z);
    };
    const double lens_radius = 0.5 * static_cast<double>(scene.camera.aperture);
    for (const DielectricSphereBoundary& boundary : dielectric_spheres) {
      if (distance_between(scene.camera.look_from, boundary.sphere.center) <=
          static_cast<double>(boundary.sphere.radius) + lens_radius) {
        fail("camera.look_from",
             "camera aperture must start outside every dielectric sphere");
      }
    }
    for (std::size_t i = 0; i < dielectric_spheres.size(); ++i) {
      const DielectricSphereBoundary& first = dielectric_spheres[i];
      unsigned int active_sphere_layers = 1u;
      for (std::size_t j = 0; j < dielectric_spheres.size(); ++j) {
        if (i == j) continue;
        const DielectricSphereBoundary& second = dielectric_spheres[j];
        const double distance =
            distance_between(first.sphere.center, second.sphere.center);
        const double first_radius = first.sphere.radius;
        const double second_radius = second.sphere.radius;
        if (i < j) {
          const bool strictly_separate =
              distance > first_radius + second_radius;
          const bool first_strictly_contains_second =
              distance + second_radius < first_radius;
          const bool second_strictly_contains_first =
              distance + first_radius < second_radius;
          if (!strictly_separate && !first_strictly_contains_second &&
              !second_strictly_contains_first) {
            fail("objects[" + std::to_string(second.object_index) + "]",
                 "dielectric sphere boundaries in water scenes must be "
                 "strictly separate or strictly nested");
          }
        }
        if (distance + first_radius < second_radius) {
          ++active_sphere_layers;
        }
      }
      // One slot is reserved for the water medium itself.
      if (active_sphere_layers + 1u > 4u) {
        fail("objects[" + std::to_string(first.object_index) + "]",
             "nested dielectric spheres exceed the four-layer medium stack "
             "including water");
      }
    }

    for (std::size_t i = 0; i < water_bounds.size(); ++i) {
      const WaterSurfaceBounds& first = water_bounds[i];
      if (static_cast<double>(scene.camera.look_from.x) + lens_radius >=
              first.minimum_x &&
          static_cast<double>(scene.camera.look_from.x) - lens_radius <=
              first.maximum_x &&
          static_cast<double>(scene.camera.look_from.z) + lens_radius >=
              first.minimum_z &&
          static_cast<double>(scene.camera.look_from.z) - lens_radius <=
              first.maximum_z &&
          static_cast<double>(scene.camera.look_from.y) - lens_radius <=
              first.maximum_y) {
        fail("camera.look_from",
             "camera aperture must start outside and above every water surface");
      }
      for (std::size_t j = i + 1; j < water_bounds.size(); ++j) {
        const WaterSurfaceBounds& second = water_bounds[j];
        const bool footprints_are_strictly_separate =
            first.maximum_x < second.minimum_x ||
            second.maximum_x < first.minimum_x ||
            first.maximum_z < second.minimum_z ||
            second.maximum_z < first.minimum_z;
        if (!footprints_are_strictly_separate) {
          fail("objects[" + std::to_string(second.object_index) + "]",
               "water_surface footprints must be strictly separate");
        }
      }
      for (const DielectricSphereBoundary& boundary : dielectric_spheres) {
        const double x = std::min(
            std::max(static_cast<double>(boundary.sphere.center.x),
                     first.minimum_x),
            first.maximum_x);
        const double z = std::min(
            std::max(static_cast<double>(boundary.sphere.center.z),
                     first.minimum_z),
            first.maximum_z);
        const double dx = static_cast<double>(boundary.sphere.center.x) - x;
        const double dz = static_cast<double>(boundary.sphere.center.z) - z;
        const double radius = boundary.sphere.radius;
        const bool overlaps_footprint = dx * dx + dz * dz <= radius * radius;
        const double sphere_minimum_y =
            static_cast<double>(boundary.sphere.center.y) - radius;
        const double sphere_maximum_y =
            static_cast<double>(boundary.sphere.center.y) + radius;
        const bool vertically_separate =
            sphere_maximum_y < first.minimum_y ||
            sphere_minimum_y > first.maximum_y;
        if (overlaps_footprint && !vertically_separate) {
          fail("objects[" + std::to_string(boundary.object_index) + "]",
               "dielectric sphere boundary may intersect a water_surface");
        }
      }
    }
  }

  if (root.contains("lights")) {
    const json& lights = root.at("lights");
    if (!lights.is_array()) fail("lights", "expected an array");
    if (lights.size() > 4096)
      fail("lights", "must contain at most 4096 explicit lights");
    std::unordered_set<std::string> light_names;
    std::unordered_set<std::int32_t> linked_objects;
    std::size_t flame_count = 0;
    std::size_t delta_count = 0;
    double total_flame_optical_thickness = 0.0;
    for (std::size_t i = 0; i < lights.size(); ++i) {
      const json& value = lights[i];
      const std::string where = "lights[" + std::to_string(i) + "]";
      Light light;
      light.name = text(member(value, "name", where), where + ".name");
      if (!light_names.insert(light.name).second) fail(where, "duplicate name '" + light.name + "'");
      const std::string type = text(member(value, "type", where), where + ".type");

      if (type == "point") {
        require_only_members(value, {"name", "type", "position", "intensity"},
                             where);
        if (++delta_count > 32)
          fail("lights", "must contain at most 32 point and directional lights");
        light.type = LightType::Point;
        light.position =
            vec3(member(value, "position", where), where + ".position");
        light.emission =
            vec3(member(value, "intensity", where), where + ".intensity");
        nonnegative(light.emission, where + ".intensity");
        if (max_component(light.emission) <= 0.0f)
          fail(where + ".intensity", "must contain positive energy");
        scene.lights.push_back(std::move(light));
        continue;
      }

      if (type == "directional") {
        require_only_members(
            value, {"name", "type", "direction", "irradiance"}, where);
        if (++delta_count > 32)
          fail("lights", "must contain at most 32 point and directional lights");
        light.type = LightType::Directional;
        light.axis =
            unit_vector(member(value, "direction", where), where + ".direction");
        light.emission =
            vec3(member(value, "irradiance", where), where + ".irradiance");
        nonnegative(light.emission, where + ".irradiance");
        if (max_component(light.emission) <= 0.0f)
          fail(where + ".irradiance", "must contain positive energy");
        scene.lights.push_back(std::move(light));
        continue;
      }

      light.position = vec3(member(value, "position", where), where + ".position");

      if (type == "flame") {
        if (value.contains("object"))
          fail(where + ".object", "flame lights cannot be bound to objects");
        if (++flame_count > 8)
          fail("lights", "must contain at most 8 flame lights");

        light.type = LightType::Flame;
        light.axis = unit_vector(member(value, "axis", where), where + ".axis");
        light.height = number(member(value, "height", where), where + ".height");
        light.radius_start =
            number(member(value, "radius_start", where), where + ".radius_start");
        light.radius_end =
            number(member(value, "radius_end", where), where + ".radius_end");
        light.emission_start =
            vec3(member(value, "emission_start", where), where + ".emission_start");
        light.emission_end =
            vec3(member(value, "emission_end", where), where + ".emission_end");
        light.extinction =
            number(member(value, "extinction", where), where + ".extinction");
        light.density_scale =
            optional_number(value, "density_scale", light.density_scale, where);
        light.turbulence =
            optional_number(value, "turbulence", light.turbulence, where);
        light.noise_scale =
            optional_number(value, "noise_scale", light.noise_scale, where);
        light.seed = optional_u32(
            value, "seed", light.seed, 0,
            std::numeric_limits<std::uint32_t>::max(), where);

        if (!(light.height > 0.0f))
          fail(where + ".height", "must be positive");
        if (light.radius_start < 0.0f)
          fail(where + ".radius_start", "must be non-negative");
        if (light.radius_end < 0.0f)
          fail(where + ".radius_end", "must be non-negative");
        if (!(light.radius_start > 0.0f || light.radius_end > 0.0f))
          fail(where, "radius_start and radius_end cannot both be zero");
        nonnegative(light.emission_start, where + ".emission_start");
        nonnegative(light.emission_end, where + ".emission_end");
        if (max_component(light.emission_start) <= 0.0f &&
            max_component(light.emission_end) <= 0.0f)
          fail(where, "emission_start and emission_end cannot both be zero");
        if (!(light.extinction > 0.0f))
          fail(where + ".extinction", "must be positive");
        if (!(light.density_scale > 0.0f))
          fail(where + ".density_scale", "must be positive");
        if (!(light.noise_scale > 0.0f))
          fail(where + ".noise_scale", "must be positive");
        if (light.turbulence < 0.0f || light.turbulence > 1.0f)
          fail(where + ".turbulence", "must be in [0, 1]");

        const double half_height = 0.5 * static_cast<double>(light.height);
        const double max_radius =
            static_cast<double>(std::max(light.radius_start, light.radius_end));
        const double bounds_radius =
            std::sqrt(half_height * half_height + max_radius * max_radius);
        total_flame_optical_thickness +=
            2.0 * bounds_radius * static_cast<double>(light.extinction) *
            static_cast<double>(light.density_scale);
        if (!(total_flame_optical_thickness <= 64.0))
          fail("lights", "total conservative flame optical thickness must be at most 64");

        scene.lights.push_back(std::move(light));
        continue;
      }

      light.object_id = optional_reference(value, "object", object_ids, where);
      if (light.object_id != kInvalidId &&
          !linked_objects.insert(light.object_id).second)
        fail(where + ".object", "object is already linked to another light");
      light.emission = vec3(member(value, "emission", where), where + ".emission");
      nonnegative(light.emission, where + ".emission");
      if (max_component(light.emission) <= 0.0f) fail(where + ".emission", "must contain positive energy");
      if (type == "sphere") {
        light.type = LightType::Sphere;
        light.radius = number(member(value, "radius", where), where + ".radius");
        if (!(light.radius > 0.0f)) fail(where + ".radius", "must be positive");
      } else if (type == "rectangle") {
        light.type = LightType::Rectangle;
        light.edge_u = vec3(member(value, "edge_u", where), where + ".edge_u");
        light.edge_v = vec3(member(value, "edge_v", where), where + ".edge_v");
        if (length_squared(cross(light.edge_u, light.edge_v)) < 1.0e-12f)
          fail(where, "rectangle light edges are degenerate");
      } else if (type == "disk") {
        light.type = LightType::Disk;
        light.normal = unit_vector(member(value, "normal", where), where + ".normal");
        light.radius = number(member(value, "radius", where), where + ".radius");
        if (!(light.radius > 0.0f)) fail(where + ".radius", "must be positive");
      } else {
        fail(where + ".type", "unsupported type '" + type + "'");
      }
      if (light.object_id != kInvalidId) {
        const Object& object = scene.objects[light.object_id];
        if (object.alpha_texture != kInvalidId)
          fail(where + ".object",
               "alpha-cutout emitters cannot be explicitly sampled");
        const bool type_matches =
            (light.type == LightType::Sphere && object.type == GeometryType::Sphere) ||
            (light.type == LightType::Rectangle && object.type == GeometryType::Rectangle) ||
            (light.type == LightType::Disk && object.type == GeometryType::Disk);
        if (!type_matches)
          fail(where + ".object", "linked object geometry type does not match light type");
        std::int32_t emitting_material = object.front_material;
        if (light.type == LightType::Sphere) {
          const auto& geometry = std::get<SphereData>(object.geometry);
          if (!approximately_equal(light.position, geometry.center) ||
              !approximately_equal(light.radius, geometry.radius))
            fail(where + ".object", "sphere light does not match linked geometry");
        } else if (light.type == LightType::Disk) {
          const auto& geometry = std::get<DiskData>(object.geometry);
          if (!approximately_equal(light.position, geometry.center) ||
              !approximately_equal(light.radius, geometry.radius) ||
              std::fabs(dot(light.normal, geometry.normal)) < 1.0f - 1.0e-5f)
            fail(where + ".object", "disk light does not match linked geometry");
          if (dot(light.normal, geometry.normal) < 0.0f)
            emitting_material = object.back_material;
        } else {
          const auto& geometry = std::get<RectangleData>(object.geometry);
          if (!same_rectangle(geometry, light))
            fail(where + ".object", "rectangle light does not match linked geometry");
          const Vec3 front_normal = normalize(
              cross(geometry.p3 - geometry.p2, geometry.p2 - geometry.p1));
          const Vec3 light_normal = normalize(cross(light.edge_u, light.edge_v));
          if (dot(light_normal, front_normal) < 0.0f)
            emitting_material = object.back_material;
        }
        if (emitting_material == kInvalidId ||
            scene.materials[emitting_material].type != MaterialType::Emitter)
          fail(where + ".object", "sampled side of linked object must be emissive");
        const Material& material = scene.materials[emitting_material];
        if (material.texture_id != kInvalidId)
          fail(where + ".object", "textured emitters cannot be explicitly sampled");
        if (!approximately_equal(material.emission, light.emission))
          fail(where + ".emission", "must match linked emitter material");
      }
      scene.lights.push_back(std::move(light));
    }
  }
  if (scene.objects.empty()) fail("objects", "must contain at least one object");
  return scene;
}

}  // namespace spectraldock
