#include "spectraldock/scene_builder.h"

#include "spectraldock/obj_loader.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <unordered_set>
#include <utility>

namespace spectraldock {
namespace {

[[noreturn]] void fail(const std::string& where,
                       const std::string& message) {
  throw std::runtime_error("scene " + where + ": " + message);
}

void require_name(const std::string& value, const std::string& where) {
  if (value.empty()) fail(where, "must not be empty");
}

void require_finite(float value, const std::string& where) {
  if (!finite(value)) fail(where, "must be a finite float32 value");
}

void require_exposure(float value, const std::string& where) {
  require_finite(value, where);
  if (value < kMinimumExposureEv || value > kMaximumExposureEv)
    fail(where, "must be in [-128, 128] EV");
}

void require_finite(Vec2 value, const std::string& where) {
  require_finite(value.x, where + "[0]");
  require_finite(value.y, where + "[1]");
}

void require_finite(Vec3 value, const std::string& where) {
  if (!finite(value)) fail(where, "must contain finite float32 values");
}

void require_nonnegative(Vec3 value, const std::string& where) {
  require_finite(value, where);
  if (value.x < 0.0f || value.y < 0.0f || value.z < 0.0f)
    fail(where, "components must be non-negative");
}

Vec3 unit_vector(Vec3 value, const std::string& where) {
  require_finite(value, where);
  const double norm = std::hypot(static_cast<double>(value.x),
                                 static_cast<double>(value.y),
                                 static_cast<double>(value.z));
  if (norm < 1.0e-6) fail(where, "must be non-zero");
  return {static_cast<float>(static_cast<double>(value.x) / norm),
          static_cast<float>(static_cast<double>(value.y) / norm),
          static_cast<float>(static_cast<double>(value.z) / norm)};
}

void validate_rectangle(Vec3 p1, Vec3 p2, Vec3 p3,
                        const std::string& where) {
  require_finite(p1, where + ".p1");
  require_finite(p2, where + ".p2");
  require_finite(p3, where + ".p3");
  if (length_squared(cross(p2 - p1, p3 - p2)) < 1.0e-12f)
    fail(where, "rectangle points are degenerate");
}

bool approximately_equal(float a, float b) {
  return std::fabs(a - b) <=
         1.0e-5f * std::max(1.0f, std::max(std::fabs(a), std::fabs(b)));
}

bool approximately_equal(Vec3 a, Vec3 b) {
  return approximately_equal(a.x, b.x) && approximately_equal(a.y, b.y) &&
         approximately_equal(a.z, b.z);
}

bool same_rectangle(const RectangleData& geometry, const Light& light) {
  const std::array<Vec3, 4> geometry_points = {
      geometry.p1, geometry.p2, geometry.p3,
      geometry.p1 + (geometry.p3 - geometry.p2)};
  const std::array<Vec3, 4> light_points = {
      light.position, light.position + light.edge_u,
      light.position + light.edge_u + light.edge_v,
      light.position + light.edge_v};
  std::array<bool, 4> matched = {false, false, false, false};
  for (Vec3 point : light_points) {
    bool found = false;
    for (std::size_t i = 0; i < geometry_points.size(); ++i) {
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

template <typename Map>
std::int32_t insert_unique(Map& ids, const std::string& name,
                           std::size_t index, const std::string& where) {
  require_name(name, where + ".name");
  if (index > static_cast<std::size_t>(
                  std::numeric_limits<std::int32_t>::max()))
    fail(where, "resource count exceeds signed 32-bit ids");
  const auto id = static_cast<std::int32_t>(index);
  if (!ids.emplace(name, id).second)
    fail(where + ".name", "duplicate name '" + name + "'");
  return id;
}

void require_id(std::int32_t id, std::size_t size, const std::string& where,
                bool optional = false) {
  if (optional && id == kInvalidId) return;
  if (id < 0 || static_cast<std::size_t>(id) >= size)
    fail(where, "references an invalid typed handle");
}

bool material_uses_texture(const Scene& scene, std::int32_t material_id) {
  if (material_id == kInvalidId) return false;
  const Material& material =
      scene.materials[static_cast<std::size_t>(material_id)];
  return material.texture_id != kInvalidId ||
         material.metallic_roughness_texture_id != kInvalidId ||
         material.normal_texture_id != kInvalidId;
}

bool material_uses_normal_texture(const Scene& scene,
                                  std::int32_t material_id) {
  return material_id != kInvalidId &&
         scene.materials[static_cast<std::size_t>(material_id)]
                 .normal_texture_id != kInvalidId;
}

const MeshResource* mesh_resource_for_object(const Scene& scene,
                                             const Object& object) {
  if (object.type != GeometryType::Mesh) return nullptr;
  const auto& instance = std::get<MeshInstanceData>(object.geometry);
  if (instance.mesh_id < 0 ||
      static_cast<std::size_t>(instance.mesh_id) >= scene.meshes.size())
    return nullptr;
  return &scene.meshes[static_cast<std::size_t>(instance.mesh_id)];
}

bool object_requires_uvs(const Scene& scene, const Object& object) {
  if (object.alpha_texture != kInvalidId ||
      material_uses_texture(scene, object.front_material) ||
      material_uses_texture(scene, object.back_material))
    return true;
  const MeshResource* resource = mesh_resource_for_object(scene, object);
  if (resource == nullptr) return false;
  return std::any_of(
      resource->material_ids.begin(), resource->material_ids.end(),
      [&](std::int32_t id) { return material_uses_texture(scene, id); });
}

bool object_uses_normal_texture(const Scene& scene, const Object& object) {
  if (material_uses_normal_texture(scene, object.front_material) ||
      material_uses_normal_texture(scene, object.back_material))
    return true;
  const MeshResource* resource = mesh_resource_for_object(scene, object);
  if (resource == nullptr) return false;
  return std::any_of(
      resource->material_ids.begin(), resource->material_ids.end(),
      [&](std::int32_t id) { return material_uses_normal_texture(scene, id); });
}

bool binds_material_type(const Scene& scene, std::int32_t material_id,
                         MaterialType type) {
  return material_id != kInvalidId &&
         scene.materials[static_cast<std::size_t>(material_id)].type == type;
}

bool object_binds_material_type(const Scene& scene, const Object& object,
                                MaterialType type) {
  if (binds_material_type(scene, object.front_material, type) ||
      binds_material_type(scene, object.back_material, type))
    return true;
  const MeshResource* resource = mesh_resource_for_object(scene, object);
  if (resource == nullptr) return false;
  return std::any_of(
      resource->material_ids.begin(), resource->material_ids.end(),
      [&](std::int32_t id) { return binds_material_type(scene, id, type); });
}

}  // namespace

void SceneBuilder::require_open() const {
  if (finished_)
    throw std::runtime_error("scene builder has already been finalized");
}

void SceneBuilder::set_camera(Vec3 look_from, Vec3 look_at, Vec3 up,
                              float vertical_fov_degrees, float aperture,
                              float focus_distance) {
  require_open();
  require_finite(look_from, "camera.look_from");
  require_finite(look_at, "camera.look_at");
  up = unit_vector(up, "camera.up");
  require_finite(vertical_fov_degrees, "camera.vertical_fov_degrees");
  require_finite(aperture, "camera.aperture");
  require_finite(focus_distance, "camera.focus_distance");
  if (length_squared(look_from - look_at) < 1.0e-12f)
    fail("camera", "look_from and look_at must differ");
  if (length_squared(cross(look_at - look_from, up)) < 1.0e-12f)
    fail("camera", "up must not be parallel to the view direction");
  if (!(vertical_fov_degrees > 0.0f && vertical_fov_degrees < 179.0f))
    fail("camera.vertical_fov_degrees", "must be in (0, 179)");
  if (aperture < 0.0f) fail("camera.aperture", "must be non-negative");
  if (!(focus_distance > 0.0f))
    fail("camera.focus_distance", "must be positive");
  scene_.camera =
      {look_from, look_at, up, vertical_fov_degrees, aperture, focus_distance};
  camera_set_ = true;
}

void SceneBuilder::set_integrator(DirectLightSampling direct_light_sampling,
                                  float clamp_direct,
                                  float clamp_indirect) {
  require_open();
  require_finite(clamp_direct, "integrator.clamp_direct");
  require_finite(clamp_indirect, "integrator.clamp_indirect");
  if (clamp_direct < 0.0f)
    fail("integrator.clamp_direct", "must be non-negative");
  if (clamp_indirect < 0.0f)
    fail("integrator.clamp_indirect", "must be non-negative");
  scene_.integrator =
      {direct_light_sampling, clamp_direct, clamp_indirect};
}

void SceneBuilder::set_constant_background(Vec3 color, float exposure) {
  require_open();
  require_nonnegative(color, "background.color");
  require_exposure(exposure, "background.exposure");
  Background result;
  result.type = BackgroundType::Constant;
  result.color = color;
  result.exposure = exposure;
  scene_.background = std::move(result);
  background_set_ = true;
}

void SceneBuilder::set_sky_background(Vec3 bottom, Vec3 top,
                                      Vec3 sun_direction, Vec3 sun_color,
                                      float sun_cos_angle, float exposure) {
  require_open();
  require_nonnegative(bottom, "background.bottom");
  require_nonnegative(top, "background.top");
  require_nonnegative(sun_color, "background.sun_color");
  sun_direction = unit_vector(sun_direction, "background.sun_direction");
  require_finite(sun_cos_angle, "background.sun_cos_angle");
  require_exposure(exposure, "background.exposure");
  if (sun_cos_angle < -1.0f || sun_cos_angle > 2.0f)
    fail("background.sun_cos_angle", "must be in [-1, 2]");
  Background result;
  result.type = BackgroundType::Sky;
  result.sky_bottom = bottom;
  result.sky_top = top;
  result.sun_direction = sun_direction;
  result.sun_color = sun_color;
  result.sun_cos_angle = sun_cos_angle;
  result.exposure = exposure;
  scene_.background = std::move(result);
  background_set_ = true;
}

void SceneBuilder::set_environment_background(
    const std::filesystem::path& path, float intensity, float rotation_degrees,
    float exposure) {
  require_open();
  require_finite(intensity, "background.intensity");
  require_finite(rotation_degrees, "background.rotation_degrees");
  require_exposure(exposure, "background.exposure");
  if (intensity < 0.0f)
    fail("background.intensity", "must be non-negative");
  const auto absolute = std::filesystem::absolute(path).lexically_normal();
  if (absolute.extension() != ".hdr")
    fail("background.path",
         "environment backgrounds must use the lowercase .hdr extension");
  if (!std::filesystem::is_regular_file(absolute))
    fail("background.path", "asset not found: " + absolute.string());
  Background result;
  result.type = BackgroundType::Environment;
  result.environment_path = absolute;
  result.environment_intensity = intensity;
  result.environment_rotation_degrees = rotation_degrees;
  result.exposure = exposure;
  scene_.background = std::move(result);
  background_set_ = true;
}

std::int32_t SceneBuilder::add_constant_texture(const std::string& name,
                                                Vec3 color) {
  require_open();
  const std::string where = "textures[" +
                            std::to_string(scene_.textures.size()) + "]";
  require_nonnegative(color, where + ".color");
  const auto id = insert_unique(texture_ids_, name, scene_.textures.size(),
                                where);
  Texture texture;
  texture.type = TextureType::Constant;
  texture.color = color;
  texture.color_space = TextureColorSpace::Linear;
  scene_.textures.push_back(std::move(texture));
  return id;
}

std::int32_t SceneBuilder::add_image_texture(
    const std::string& name, const std::filesystem::path& path,
    TextureColorSpace color_space, TextureWrap wrap_u, TextureWrap wrap_v) {
  require_open();
  const std::string where = "textures[" +
                            std::to_string(scene_.textures.size()) + "]";
  const auto absolute = std::filesystem::absolute(path).lexically_normal();
  if (absolute.extension() != ".avif")
    fail(where + ".path", "image textures must use the lowercase .avif extension");
  if (!std::filesystem::is_regular_file(absolute))
    fail(where + ".path", "asset not found: " + absolute.string());
  const auto id = insert_unique(texture_ids_, name, scene_.textures.size(),
                                where);
  Texture texture;
  texture.type = TextureType::Image;
  texture.image_path = absolute;
  texture.color_space = color_space;
  texture.wrap_u = wrap_u;
  texture.wrap_v = wrap_v;
  scene_.textures.push_back(std::move(texture));
  return id;
}

std::int32_t SceneBuilder::add_material(
    const std::string& name, MaterialType type, std::int32_t texture_id,
    Vec3 base_color, Vec3 emission, float roughness, float ior,
    Vec3 absorption) {
  require_open();
  const std::string where = "materials[" +
                            std::to_string(scene_.materials.size()) + "]";
  require_id(texture_id, scene_.textures.size(), where + ".texture", true);
  require_nonnegative(base_color, where + ".base_color");
  require_nonnegative(emission, where + ".emission");
  require_nonnegative(absorption, where + ".absorption");
  require_finite(roughness, where + ".roughness");
  require_finite(ior, where + ".ior");
  if (type == MaterialType::Pbr)
    fail(where + ".type", "PBR materials require add_pbr_material");
  if (texture_id != kInvalidId) {
    const Texture& texture =
        scene_.textures[static_cast<std::size_t>(texture_id)];
    if (texture.type == TextureType::Image &&
        texture.color_space == TextureColorSpace::Hdr &&
        type != MaterialType::Emitter) {
      fail(where + ".texture",
           "HDR textures are supported only by emitter materials");
    }
  }
  if (roughness < 0.0f || roughness > 1.0f)
    fail(where + ".roughness", "must be in [0, 1]");
  if (type == MaterialType::Water) {
    if (texture_id != kInvalidId)
      fail(where + ".texture", "is not supported by water materials");
    if (!(ior > 1.0f && ior <= 3.0f))
      fail(where + ".ior", "water IOR must be in (1, 3]");
  } else if (type == MaterialType::Dielectric && !(ior > 1.0f)) {
    fail(where + ".ior", "dielectric IOR must be greater than 1");
  }
  if (type == MaterialType::Emitter && max_component(emission) <= 0.0f &&
      texture_id == kInvalidId)
    fail(where, "emitter needs positive emission or a texture");
  const auto id = insert_unique(material_ids_, name, scene_.materials.size(),
                                where);
  Material material;
  material.type = type;
  material.texture_id = texture_id;
  material.base_color = base_color;
  material.emission = emission;
  material.roughness = roughness;
  material.ior = ior;
  material.absorption = absorption;
  scene_.materials.push_back(std::move(material));
  return id;
}

std::int32_t SceneBuilder::add_pbr_material(
    const std::string& name, std::int32_t base_color_texture_id,
    std::int32_t metallic_roughness_texture_id,
    std::int32_t normal_texture_id, Vec3 base_color, float metallic,
    float roughness, float normal_scale) {
  require_open();
  const std::string where = "materials[" +
                            std::to_string(scene_.materials.size()) + "]";
  require_id(base_color_texture_id, scene_.textures.size(),
             where + ".base_color_texture", true);
  require_id(metallic_roughness_texture_id, scene_.textures.size(),
             where + ".metallic_roughness_texture", true);
  require_id(normal_texture_id, scene_.textures.size(),
             where + ".normal_texture", true);
  require_finite(base_color, where + ".base_color");
  if (base_color.x < 0.0f || base_color.x > 1.0f ||
      base_color.y < 0.0f || base_color.y > 1.0f ||
      base_color.z < 0.0f || base_color.z > 1.0f)
    fail(where + ".base_color", "components must be in [0, 1]");
  require_finite(metallic, where + ".metallic");
  require_finite(roughness, where + ".roughness");
  require_finite(normal_scale, where + ".normal_scale");
  if (metallic < 0.0f || metallic > 1.0f)
    fail(where + ".metallic", "must be in [0, 1]");
  if (roughness < 0.0f || roughness > 1.0f)
    fail(where + ".roughness", "must be in [0, 1]");
  if (base_color_texture_id != kInvalidId) {
    const Texture& texture =
        scene_.textures[static_cast<std::size_t>(base_color_texture_id)];
    if (texture.type == TextureType::Image &&
        texture.color_space == TextureColorSpace::Hdr) {
      fail(where + ".base_color_texture",
           "HDR textures are supported only by emitter materials");
    }
    if (texture.type == TextureType::Constant &&
        (texture.color.x > 1.0f || texture.color.y > 1.0f ||
         texture.color.z > 1.0f))
      fail(where + ".base_color_texture",
           "constant texture components must be in [0, 1]");
  }
  const auto require_linear_data_texture = [&](std::int32_t texture_id,
                                                const std::string& field) {
    if (texture_id == kInvalidId) return;
    const Texture& texture =
        scene_.textures[static_cast<std::size_t>(texture_id)];
    if (texture.type == TextureType::Image &&
        texture.color_space != TextureColorSpace::Linear)
      fail(where + "." + field,
           "requires a texture with color_space='linear'");
  };
  require_linear_data_texture(metallic_roughness_texture_id,
                              "metallic_roughness_texture");
  require_linear_data_texture(normal_texture_id, "normal_texture");

  const auto id = insert_unique(material_ids_, name, scene_.materials.size(),
                                where);
  Material material;
  material.type = MaterialType::Pbr;
  material.texture_id = base_color_texture_id;
  material.metallic_roughness_texture_id =
      metallic_roughness_texture_id;
  material.normal_texture_id = normal_texture_id;
  material.base_color = base_color;
  material.metallic = metallic;
  material.roughness = roughness;
  material.normal_scale = normal_scale;
  scene_.materials.push_back(std::move(material));
  return id;
}

std::int32_t SceneBuilder::add_mesh(const std::string& name,
                                    const std::filesystem::path& path,
                                    const std::vector<std::pair<
                                        std::string, std::int32_t>>&
                                        material_bindings) {
  require_open();
  const std::string where = "meshes[" +
                            std::to_string(scene_.meshes.size()) + "]";
  const auto absolute = std::filesystem::absolute(path).lexically_normal();
  if (!std::filesystem::is_regular_file(absolute))
    fail(where + ".path", "asset not found: " + absolute.string());
  MeshResource resource;
  resource.name = name;
  std::unordered_map<std::string, std::int32_t> bindings;
  std::vector<std::string> triangle_slots;
  if (!material_bindings.empty()) {
    bindings.reserve(material_bindings.size());
    for (std::size_t i = 0; i < material_bindings.size(); ++i) {
      const auto& [slot, material_id] = material_bindings[i];
      const std::string binding_where =
          where + ".material_bindings[" + std::to_string(i) + "]";
      require_name(slot, binding_where + ".name");
      require_id(material_id, scene_.materials.size(),
                 binding_where + ".material");
      if (scene_.materials[static_cast<std::size_t>(material_id)].type ==
          MaterialType::Water)
        fail(binding_where + ".material",
             "water materials cannot be bound to OBJ material slots");
      if (!bindings.emplace(slot, material_id).second)
        fail(binding_where + ".name",
             "duplicate OBJ material slot '" + slot + "'");
    }
  }
  try {
    if (material_bindings.empty()) {
      resource.mesh = load_obj_mesh(absolute);
    } else {
      resource.mesh = load_obj_mesh(absolute, triangle_slots);
    }
  } catch (const std::exception& error) {
    fail(where + ".path", error.what());
  }
  if (!material_bindings.empty()) {
    if (triangle_slots.size() != resource.mesh.indices.size())
      fail(where + ".material_bindings",
           "OBJ triangle/material assignment count mismatch");

    std::unordered_set<std::string> used_slots;
    resource.material_ids.reserve(triangle_slots.size());
    for (const std::string& slot : triangle_slots) {
      const auto binding = bindings.find(slot);
      if (binding == bindings.end())
        fail(where + ".material_bindings",
             "missing binding for used OBJ material slot '" + slot + "'");
      used_slots.insert(slot);
      resource.material_ids.push_back(binding->second);
    }
    for (const auto& [slot, material_id] : bindings) {
      (void)material_id;
      if (used_slots.count(slot) == 0)
        fail(where + ".material_bindings",
             "binding for unused OBJ material slot '" + slot + "'");
    }

    if (!resource.mesh.has_complete_uvs()) {
      for (std::int32_t material_id : resource.material_ids) {
        if (material_uses_texture(scene_, material_id))
          fail(where + ".material_bindings",
               "textured OBJ material slots require complete UV coordinates");
      }
    }
    if (!resource.mesh.has_complete_tangents()) {
      for (std::int32_t material_id : resource.material_ids) {
        if (material_uses_normal_texture(scene_, material_id))
          fail(where + ".material_bindings",
               "normal-mapped OBJ material slots require a complete valid "
               "tangent frame");
      }
    }
  }
  const auto id = insert_unique(mesh_ids_, name, scene_.meshes.size(), where);
  scene_.meshes.push_back(std::move(resource));
  return id;
}

std::int32_t SceneBuilder::add_object(Object object) {
  require_open();
  const std::string where = "objects[" +
                            std::to_string(scene_.objects.size()) + "]";
  require_id(object.front_material, scene_.materials.size(),
             where + ".front_material", true);
  require_id(object.back_material, scene_.materials.size(),
             where + ".back_material", true);
  require_id(object.alpha_texture, scene_.textures.size(),
             where + ".alpha_texture", true);
  if (object.alpha_texture != kInvalidId) {
    const Texture& texture =
        scene_.textures[static_cast<std::size_t>(object.alpha_texture)];
    if (texture.type == TextureType::Image &&
        texture.color_space == TextureColorSpace::Hdr) {
      fail(where + ".alpha_texture",
           "HDR textures cannot be used as alpha masks");
    }
  }
  const MeshResource* mesh_resource =
      mesh_resource_for_object(scene_, object);
  const bool has_mapped_mesh_materials =
      mesh_resource != nullptr && !mesh_resource->material_ids.empty() &&
      mesh_resource->material_ids.size() == mesh_resource->mesh.indices.size();
  if (object.front_material == kInvalidId &&
      object.back_material == kInvalidId && !has_mapped_mesh_materials)
    fail(where, "at least one face material is required");
  require_finite(object.alpha_cutoff, where + ".alpha_cutoff");
  if (object.alpha_cutoff < 0.0f || object.alpha_cutoff > 1.0f)
    fail(where + ".alpha_cutoff", "must be in [0, 1]");
  if (object.type != GeometryType::WaterSurface &&
      (binds_material_type(scene_, object.front_material,
                           MaterialType::Water) ||
       binds_material_type(scene_, object.back_material,
                           MaterialType::Water)))
    fail(where, "water materials can only be bound to water_surface objects");
  if (object.type != GeometryType::Mesh &&
      object_uses_normal_texture(scene_, object))
    fail(where, "normal maps are supported only by mesh objects");
  const auto id =
      insert_unique(object_ids_, object.name, scene_.objects.size(), where);
  scene_.objects.push_back(std::move(object));
  return id;
}

std::int32_t SceneBuilder::add_sphere(
    const std::string& name, Vec3 center, float radius,
    std::int32_t front_material, std::int32_t back_material,
    std::int32_t alpha_texture, float alpha_cutoff) {
  require_finite(center, "sphere.center");
  require_finite(radius, "sphere.radius");
  if (!(radius > 0.0f)) fail("sphere.radius", "must be positive");
  Object object;
  object.name = name;
  object.type = GeometryType::Sphere;
  object.geometry = SphereData{center, radius};
  object.front_material = front_material;
  object.back_material = back_material;
  object.alpha_texture = alpha_texture;
  object.alpha_cutoff = alpha_cutoff;
  return add_object(std::move(object));
}

std::int32_t SceneBuilder::add_rectangle(
    const std::string& name, Vec3 p1, Vec3 p2, Vec3 p3,
    std::int32_t front_material, std::int32_t back_material,
    std::int32_t alpha_texture, float alpha_cutoff) {
  validate_rectangle(p1, p2, p3, "rectangle");
  Object object;
  object.name = name;
  object.type = GeometryType::Rectangle;
  object.geometry = RectangleData{p1, p2, p3};
  object.front_material = front_material;
  object.back_material = back_material;
  object.alpha_texture = alpha_texture;
  object.alpha_cutoff = alpha_cutoff;
  return add_object(std::move(object));
}

std::int32_t SceneBuilder::add_disk(
    const std::string& name, Vec3 center, Vec3 normal, float radius,
    std::int32_t front_material, std::int32_t back_material,
    std::int32_t alpha_texture, float alpha_cutoff) {
  require_finite(center, "disk.center");
  normal = unit_vector(normal, "disk.normal");
  require_finite(radius, "disk.radius");
  if (!(radius > 0.0f)) fail("disk.radius", "must be positive");
  Object object;
  object.name = name;
  object.type = GeometryType::Disk;
  object.geometry = DiskData{center, normal, radius};
  object.front_material = front_material;
  object.back_material = back_material;
  object.alpha_texture = alpha_texture;
  object.alpha_cutoff = alpha_cutoff;
  return add_object(std::move(object));
}

std::int32_t SceneBuilder::add_cylinder(
    const std::string& name, Vec3 base, Vec3 axis, float height, float radius,
    std::int32_t front_material, std::int32_t back_material,
    std::int32_t alpha_texture, float alpha_cutoff) {
  require_finite(base, "cylinder.base");
  axis = unit_vector(axis, "cylinder.axis");
  require_finite(height, "cylinder.height");
  require_finite(radius, "cylinder.radius");
  if (!(height > 0.0f)) fail("cylinder.height", "must be positive");
  if (!(radius > 0.0f)) fail("cylinder.radius", "must be positive");
  Object object;
  object.name = name;
  object.type = GeometryType::Cylinder;
  object.geometry = CylinderData{base, axis, height, radius};
  object.front_material = front_material;
  object.back_material = back_material;
  object.alpha_texture = alpha_texture;
  object.alpha_cutoff = alpha_cutoff;
  return add_object(std::move(object));
}

std::int32_t SceneBuilder::add_parabola(
    const std::string& name, Vec3 origin, Vec3 normal, Vec3 focus, Aabb clip,
    std::int32_t front_material, std::int32_t back_material,
    std::int32_t alpha_texture, float alpha_cutoff) {
  require_finite(origin, "parabola.origin");
  normal = unit_vector(normal, "parabola.normal");
  require_finite(focus, "parabola.focus");
  if (!clip.valid()) fail("parabola.clip", "must be a valid ordered AABB");
  if (!(clip.min.x < clip.max.x && clip.min.y < clip.max.y &&
        clip.min.z < clip.max.z))
    fail("parabola.clip", "must have positive extent on every axis");
  const Vec3 opening = focus - origin;
  if (length_squared(opening) < 1.0e-12f)
    fail("parabola.focus", "must differ from origin");
  if (std::fabs(dot(normalize(opening), normal)) > 1.0e-5f)
    fail("parabola", "normal must be perpendicular to focus-origin");
  Object object;
  object.name = name;
  object.type = GeometryType::Parabola;
  object.geometry = ParabolaData{origin, normal, focus, clip};
  object.front_material = front_material;
  object.back_material = back_material;
  object.alpha_texture = alpha_texture;
  object.alpha_cutoff = alpha_cutoff;
  return add_object(std::move(object));
}

std::int32_t SceneBuilder::add_mesh_instance(
    const std::string& name, std::int32_t mesh_id, const Transform& transform,
    std::int32_t front_material, std::int32_t back_material,
    std::int32_t alpha_texture, float alpha_cutoff) {
  require_id(mesh_id, scene_.meshes.size(), "mesh_instance.mesh");
  require_id(front_material, scene_.materials.size(),
             "mesh_instance.front_material", true);
  require_id(back_material, scene_.materials.size(),
             "mesh_instance.back_material", true);
  require_id(alpha_texture, scene_.textures.size(),
             "mesh_instance.alpha_texture", true);
  require_finite(transform.translate, "mesh_instance.transform.translate");
  require_finite(transform.rotate_degrees,
                 "mesh_instance.transform.rotate_degrees");
  require_finite(transform.scale, "mesh_instance.transform.scale");
  if (!(transform.scale.x > 0.0f) || !(transform.scale.y > 0.0f) ||
      !(transform.scale.z > 0.0f))
    fail("mesh_instance.transform.scale",
         "components must be greater than zero");
  Object object;
  object.name = name;
  object.type = GeometryType::Mesh;
  object.geometry = MeshInstanceData{mesh_id, transform};
  object.front_material = front_material;
  object.back_material = back_material;
  object.alpha_texture = alpha_texture;
  object.alpha_cutoff = alpha_cutoff;
  const MeshResource& resource =
      scene_.meshes[static_cast<std::size_t>(mesh_id)];
  if (!resource.material_ids.empty() &&
      (front_material != kInvalidId || back_material != kInvalidId))
    fail("mesh_instance",
         "material-mapped meshes do not accept front/back materials");
  if (!resource.mesh.empty() && !resource.mesh.has_complete_uvs() &&
      object_requires_uvs(scene_, object))
    fail("mesh_instance",
         "mesh '" + resource.name +
             "' has no complete UV coordinates but the object binds a "
             "material or alpha texture");
  if (!resource.mesh.empty() && !resource.mesh.has_complete_tangents() &&
      object_uses_normal_texture(scene_, object))
    fail("mesh_instance",
         "mesh '" + resource.name +
             "' has no complete valid tangent frame for its normal map");
  return add_object(std::move(object));
}

std::int32_t SceneBuilder::add_water_surface(
    const std::string& name, Vec3 center, Vec2 size, std::int32_t material,
    const std::vector<WaterWave>& waves) {
  require_open();
  const std::size_t existing = static_cast<std::size_t>(std::count_if(
      scene_.objects.begin(), scene_.objects.end(), [](const Object& object) {
        return object.type == GeometryType::WaterSurface;
      }));
  if (existing >= 4)
    fail("objects", "must contain at most 4 water_surface objects");
  require_id(material, scene_.materials.size(), "water_surface.material");
  if (scene_.materials[static_cast<std::size_t>(material)].type !=
      MaterialType::Water)
    fail("water_surface.material", "requires a water material");
  require_finite(center, "water_surface.center");
  require_finite(size, "water_surface.size");
  if (!(size.x > 0.0f) || !(size.y > 0.0f))
    fail("water_surface.size", "components must be positive");
  if (waves.empty() || waves.size() > 4)
    fail("water_surface.waves", "must contain 1 to 4 waves");

  WaterSurfaceData data;
  data.center = center;
  data.size = size;
  data.wave_count = static_cast<std::uint32_t>(waves.size());
  double total_slope = 0.0;
  double total_amplitude = 0.0;
  float shortest_wavelength = std::numeric_limits<float>::max();
  for (std::size_t i = 0; i < waves.size(); ++i) {
    WaterWave wave = waves[i];
    const std::string where =
        "water_surface.waves[" + std::to_string(i) + "]";
    require_finite(wave.direction, where + ".direction");
    const double direction_length_squared =
        static_cast<double>(wave.direction.x) * wave.direction.x +
        static_cast<double>(wave.direction.y) * wave.direction.y;
    if (!(direction_length_squared >= 1.0e-12))
      fail(where + ".direction", "must be non-zero");
    const double inverse_direction_length =
        1.0 / std::sqrt(direction_length_squared);
    wave.direction.x = static_cast<float>(
        static_cast<double>(wave.direction.x) * inverse_direction_length);
    wave.direction.y = static_cast<float>(
        static_cast<double>(wave.direction.y) * inverse_direction_length);
    require_finite(wave.amplitude, where + ".amplitude");
    require_finite(wave.wavelength, where + ".wavelength");
    require_finite(wave.phase_radians, where + ".phase_radians");
    if (!(wave.amplitude > 0.0f))
      fail(where + ".amplitude", "must be positive");
    if (!(wave.wavelength > 0.0f))
      fail(where + ".wavelength", "must be positive");
    const double wave_number = 2.0 * static_cast<double>(kPi) /
                               static_cast<double>(wave.wavelength);
    if (!std::isfinite(wave_number) ||
        wave_number > std::numeric_limits<float>::max())
      fail(where + ".wavelength",
           "produces a non-finite float32 wave number");
    wave.phase_radians = std::fmod(wave.phase_radians, 2.0f * kPi);
    if (wave.phase_radians < 0.0f) wave.phase_radians += 2.0f * kPi;
    total_slope += 2.0 * static_cast<double>(kPi) * wave.amplitude /
                   wave.wavelength;
    total_amplitude += wave.amplitude;
    shortest_wavelength = std::min(shortest_wavelength, wave.wavelength);
    data.waves[i] = wave;
  }
  if (!(total_slope <= 1.0))
    fail("water_surface.waves", "total wave slope must be at most 1");

  const double tile_extent = 0.5 * shortest_wavelength;
  const double tiles_x = std::ceil(static_cast<double>(size.x) / tile_extent);
  const double tiles_z = std::ceil(static_cast<double>(size.y) / tile_extent);
  if (!(tiles_x >= 1.0 && tiles_x <= 4096.0 && tiles_z >= 1.0 &&
        tiles_z <= 4096.0 && tiles_x * tiles_z <= 4096.0))
    fail("water_surface", "automatic water tile count must be at most 4096");
  data.tiles_x = static_cast<std::uint32_t>(tiles_x);
  data.tiles_z = static_cast<std::uint32_t>(tiles_z);
  if (!(size.x / static_cast<float>(data.tiles_x) > 0.0f) ||
      !(size.y / static_cast<float>(data.tiles_z) > 0.0f))
    fail("water_surface",
         "automatic water tile extent underflows float32");

  const auto finite_float32 = [](double value) {
    return std::isfinite(value) &&
           value >= -static_cast<double>(std::numeric_limits<float>::max()) &&
           value <= static_cast<double>(std::numeric_limits<float>::max());
  };
  const double minimum_x = static_cast<double>(center.x) - 0.5 * size.x;
  const double maximum_x = static_cast<double>(center.x) + 0.5 * size.x;
  const double minimum_y = static_cast<double>(center.y) - total_amplitude;
  const double maximum_y = static_cast<double>(center.y) + total_amplitude;
  const double minimum_z = static_cast<double>(center.z) - 0.5 * size.y;
  const double maximum_z = static_cast<double>(center.z) + 0.5 * size.y;
  if (!finite_float32(minimum_x) || !finite_float32(maximum_x) ||
      !finite_float32(minimum_y) || !finite_float32(maximum_y) ||
      !finite_float32(minimum_z) || !finite_float32(maximum_z) ||
      !(static_cast<float>(minimum_x) < static_cast<float>(maximum_x)) ||
      !(static_cast<float>(minimum_y) < static_cast<float>(maximum_y)) ||
      !(static_cast<float>(minimum_z) < static_cast<float>(maximum_z)))
    fail("water_surface",
         "derived water bounds must be finite non-degenerate float32");
  const auto boundaries_increase = [](float center_value, float extent,
                                      std::uint32_t tiles) {
    const float minimum = center_value - 0.5f * extent;
    const float width = extent / static_cast<float>(tiles);
    float previous = minimum;
    for (std::uint32_t tile = 1; tile <= tiles; ++tile) {
      const float boundary = minimum + width * static_cast<float>(tile);
      if (!(boundary > previous)) return false;
      previous = boundary;
    }
    return true;
  };
  if (!boundaries_increase(center.x, size.x, data.tiles_x) ||
      !boundaries_increase(center.z, size.y, data.tiles_z))
    fail("water_surface", "automatic water tile boundaries collapse in float32");

  Object object;
  object.name = name;
  object.type = GeometryType::WaterSurface;
  object.geometry = data;
  object.front_material = material;
  object.back_material = material;
  return add_object(std::move(object));
}

std::int32_t SceneBuilder::add_light(Light light) {
  require_open();
  if (scene_.lights.size() >= 4096)
    fail("lights", "must contain at most 4096 explicit lights");
  const std::string where =
      "lights[" + std::to_string(scene_.lights.size()) + "]";
  const auto id = insert_unique(light_ids_, light.name, scene_.lights.size(),
                                where);
  scene_.lights.push_back(std::move(light));
  return id;
}

std::int32_t SceneBuilder::add_sphere_light(
    const std::string& name, Vec3 position, float radius, Vec3 emission,
    std::int32_t object_id) {
  require_finite(position, "sphere_light.position");
  require_finite(radius, "sphere_light.radius");
  require_nonnegative(emission, "sphere_light.emission");
  require_id(object_id, scene_.objects.size(), "sphere_light.object", true);
  if (!(radius > 0.0f)) fail("sphere_light.radius", "must be positive");
  if (max_component(emission) <= 0.0f)
    fail("sphere_light.emission", "must contain positive energy");
  Light light;
  light.name = name;
  light.type = LightType::Sphere;
  light.position = position;
  light.radius = radius;
  light.emission = emission;
  light.object_id = object_id;
  return add_light(std::move(light));
}

std::int32_t SceneBuilder::add_rectangle_light(
    const std::string& name, Vec3 position, Vec3 edge_u, Vec3 edge_v,
    Vec3 emission, std::int32_t object_id) {
  require_finite(position, "rectangle_light.position");
  require_finite(edge_u, "rectangle_light.edge_u");
  require_finite(edge_v, "rectangle_light.edge_v");
  require_nonnegative(emission, "rectangle_light.emission");
  require_id(object_id, scene_.objects.size(), "rectangle_light.object", true);
  if (length_squared(cross(edge_u, edge_v)) < 1.0e-12f)
    fail("rectangle_light", "edges are degenerate");
  if (max_component(emission) <= 0.0f)
    fail("rectangle_light.emission", "must contain positive energy");
  Light light;
  light.name = name;
  light.type = LightType::Rectangle;
  light.position = position;
  light.edge_u = edge_u;
  light.edge_v = edge_v;
  light.emission = emission;
  light.object_id = object_id;
  return add_light(std::move(light));
}

std::int32_t SceneBuilder::add_disk_light(
    const std::string& name, Vec3 position, Vec3 normal, float radius,
    Vec3 emission, std::int32_t object_id) {
  require_finite(position, "disk_light.position");
  normal = unit_vector(normal, "disk_light.normal");
  require_finite(radius, "disk_light.radius");
  require_nonnegative(emission, "disk_light.emission");
  require_id(object_id, scene_.objects.size(), "disk_light.object", true);
  if (!(radius > 0.0f)) fail("disk_light.radius", "must be positive");
  if (max_component(emission) <= 0.0f)
    fail("disk_light.emission", "must contain positive energy");
  Light light;
  light.name = name;
  light.type = LightType::Disk;
  light.position = position;
  light.normal = normal;
  light.radius = radius;
  light.emission = emission;
  light.object_id = object_id;
  return add_light(std::move(light));
}

std::int32_t SceneBuilder::add_flame_light(
    const std::string& name, Vec3 position, Vec3 axis, float height,
    float radius_start, float radius_end, Vec3 emission_start,
    Vec3 emission_end, float extinction, float density_scale,
    float turbulence, float noise_scale, std::uint32_t seed) {
  require_finite(position, "flame.position");
  axis = unit_vector(axis, "flame.axis");
  for (const auto& item :
       std::array<std::pair<float, const char*>, 7>{
           std::pair<float, const char*>{height, "height"},
           {radius_start, "radius_start"}, {radius_end, "radius_end"},
           {extinction, "extinction"}, {density_scale, "density_scale"},
           {turbulence, "turbulence"}, {noise_scale, "noise_scale"}})
    require_finite(item.first, std::string("flame.") + item.second);
  require_nonnegative(emission_start, "flame.emission_start");
  require_nonnegative(emission_end, "flame.emission_end");
  if (!(height > 0.0f)) fail("flame.height", "must be positive");
  if (radius_start < 0.0f)
    fail("flame.radius_start", "must be non-negative");
  if (radius_end < 0.0f)
    fail("flame.radius_end", "must be non-negative");
  if (!(radius_start > 0.0f || radius_end > 0.0f))
    fail("flame", "radius_start and radius_end cannot both be zero");
  if (max_component(emission_start) <= 0.0f &&
      max_component(emission_end) <= 0.0f)
    fail("flame", "emission_start and emission_end cannot both be zero");
  if (!(extinction > 0.0f)) fail("flame.extinction", "must be positive");
  if (!(density_scale > 0.0f))
    fail("flame.density_scale", "must be positive");
  if (!(noise_scale > 0.0f))
    fail("flame.noise_scale", "must be positive");
  if (turbulence < 0.0f || turbulence > 1.0f)
    fail("flame.turbulence", "must be in [0, 1]");
  Light light;
  light.name = name;
  light.type = LightType::Flame;
  light.position = position;
  light.axis = axis;
  light.height = height;
  light.radius_start = radius_start;
  light.radius_end = radius_end;
  light.emission_start = emission_start;
  light.emission_end = emission_end;
  light.extinction = extinction;
  light.density_scale = density_scale;
  light.turbulence = turbulence;
  light.noise_scale = noise_scale;
  light.seed = seed;
  return add_light(std::move(light));
}

std::int32_t SceneBuilder::add_point_light(const std::string& name,
                                           Vec3 position, Vec3 intensity) {
  require_finite(position, "point_light.position");
  require_nonnegative(intensity, "point_light.intensity");
  if (max_component(intensity) <= 0.0f)
    fail("point_light.intensity", "must contain positive energy");
  Light light;
  light.name = name;
  light.type = LightType::Point;
  light.position = position;
  light.emission = intensity;
  return add_light(std::move(light));
}

std::int32_t SceneBuilder::add_directional_light(const std::string& name,
                                                 Vec3 direction,
                                                 Vec3 irradiance) {
  direction = unit_vector(direction, "directional_light.direction");
  require_nonnegative(irradiance, "directional_light.irradiance");
  if (max_component(irradiance) <= 0.0f)
    fail("directional_light.irradiance", "must contain positive energy");
  Light light;
  light.name = name;
  light.type = LightType::Directional;
  light.axis = direction;
  light.emission = irradiance;
  return add_light(std::move(light));
}

void SceneBuilder::validate_scene() const {
  if (!camera_set_) fail("camera", "must be configured");
  if (!background_set_) fail("background", "must be configured");
  if (scene_.objects.empty()) fail("objects", "must contain at least one object");

  std::size_t flame_count = 0;
  std::size_t delta_count = 0;
  double total_flame_optical_thickness = 0.0;
  std::unordered_set<std::int32_t> linked_objects;
  for (std::size_t i = 0; i < scene_.lights.size(); ++i) {
    const Light& light = scene_.lights[i];
    const std::string where = "lights[" + std::to_string(i) + "]";
    if (light.type == LightType::Flame) {
      if (++flame_count > 8)
        fail("lights", "must contain at most 8 flame lights");
      const double half_height = 0.5 * light.height;
      const double max_radius = std::max(light.radius_start, light.radius_end);
      const double bounds_radius =
          std::sqrt(half_height * half_height + max_radius * max_radius);
      total_flame_optical_thickness +=
          2.0 * bounds_radius * light.extinction * light.density_scale;
      if (!(total_flame_optical_thickness <= 64.0))
        fail("lights",
             "total conservative flame optical thickness must be at most 64");
    }
    if (light.type == LightType::Point ||
        light.type == LightType::Directional) {
      if (++delta_count > 32)
        fail("lights", "must contain at most 32 point and directional lights");
    }
    if (light.object_id == kInvalidId) continue;
    require_id(light.object_id, scene_.objects.size(), where + ".object");
    if (!linked_objects.insert(light.object_id).second)
      fail(where + ".object", "object is already linked to another light");
    const Object& object =
        scene_.objects[static_cast<std::size_t>(light.object_id)];
    if (object.alpha_texture != kInvalidId)
      fail(where + ".object",
           "alpha-cutout emitters cannot be explicitly sampled");
    const bool type_matches =
        (light.type == LightType::Sphere &&
         object.type == GeometryType::Sphere) ||
        (light.type == LightType::Rectangle &&
         object.type == GeometryType::Rectangle) ||
        (light.type == LightType::Disk && object.type == GeometryType::Disk);
    if (!type_matches)
      fail(where + ".object",
           "linked object geometry type does not match light type");
    std::int32_t emitting_material = object.front_material;
    if (light.type == LightType::Sphere) {
      const auto& geometry = std::get<SphereData>(object.geometry);
      if (!approximately_equal(light.position, geometry.center) ||
          !approximately_equal(light.radius, geometry.radius))
        fail(where + ".object",
             "sphere light does not match linked geometry");
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
        fail(where + ".object",
             "rectangle light does not match linked geometry");
      const Vec3 front_normal = normalize(
          cross(geometry.p3 - geometry.p2, geometry.p2 - geometry.p1));
      const Vec3 light_normal = normalize(cross(light.edge_u, light.edge_v));
      if (dot(light_normal, front_normal) < 0.0f)
        emitting_material = object.back_material;
    }
    if (emitting_material == kInvalidId ||
        scene_.materials[static_cast<std::size_t>(emitting_material)].type !=
            MaterialType::Emitter)
      fail(where + ".object", "sampled side of linked object must be emissive");
    const Material& material =
        scene_.materials[static_cast<std::size_t>(emitting_material)];
    if (material.texture_id != kInvalidId)
      fail(where + ".object",
           "textured emitters cannot be explicitly sampled");
    if (!approximately_equal(material.emission, light.emission))
      fail(where + ".emission", "must match linked emitter material");
  }

  struct DielectricSphereBoundary {
    std::size_t object_index;
    SphereData sphere;
  };
  struct WaterSurfaceBounds {
    std::size_t object_index;
    double minimum_x, maximum_x, minimum_y, maximum_y, minimum_z, maximum_z;
  };
  std::vector<WaterSurfaceBounds> water_bounds;
  for (std::size_t i = 0; i < scene_.objects.size(); ++i) {
    const Object& object = scene_.objects[i];
    if (object.type == GeometryType::WaterSurface) {
      const auto& water = std::get<WaterSurfaceData>(object.geometry);
      double amplitude = 0.0;
      for (std::uint32_t wave = 0; wave < water.wave_count; ++wave)
        amplitude += water.waves[wave].amplitude;
      water_bounds.push_back(
          {i, water.center.x - 0.5 * water.size.x,
           water.center.x + 0.5 * water.size.x, water.center.y - amplitude,
           water.center.y + amplitude, water.center.z - 0.5 * water.size.y,
           water.center.z + 0.5 * water.size.y});
    }
  }
  if (water_bounds.empty()) return;

  std::vector<DielectricSphereBoundary> dielectric_spheres;
  for (std::size_t i = 0; i < scene_.objects.size(); ++i) {
    const Object& object = scene_.objects[i];
    if (object.type == GeometryType::WaterSurface) continue;
    const bool front_dielectric = binds_material_type(
        scene_, object.front_material, MaterialType::Dielectric);
    const bool back_dielectric = binds_material_type(
        scene_, object.back_material, MaterialType::Dielectric);
    const bool mapped_dielectric =
        object_binds_material_type(scene_, object, MaterialType::Dielectric) &&
        !front_dielectric && !back_dielectric;
    if (object.type == GeometryType::Sphere) {
      if (front_dielectric || back_dielectric) {
        if (object.front_material != object.back_material ||
            !front_dielectric)
          fail("objects[" + std::to_string(i) + "]",
               "dielectric sphere boundaries in water scenes require one "
               "shared dielectric material on both faces");
        if (object.alpha_texture != kInvalidId)
          fail("objects[" + std::to_string(i) + "]",
               "dielectric sphere boundaries in water scenes cannot use "
               "alpha textures");
        dielectric_spheres.push_back(
            {i, std::get<SphereData>(object.geometry)});
      }
    } else if (front_dielectric || back_dielectric || mapped_dielectric) {
      fail("objects[" + std::to_string(i) + "]",
           "dielectric materials in water scenes require closed sphere "
           "geometry; open dielectric boundaries are not supported");
    }
  }

  const auto distance_between = [](Vec3 a, Vec3 b) {
    return std::hypot(static_cast<double>(a.x) - b.x,
                      static_cast<double>(a.y) - b.y,
                      static_cast<double>(a.z) - b.z);
  };
  const double lens_radius = 0.5 * scene_.camera.aperture;
  for (const auto& boundary : dielectric_spheres) {
    if (distance_between(scene_.camera.look_from, boundary.sphere.center) <=
        boundary.sphere.radius + lens_radius)
      fail("camera.look_from",
           "camera aperture must start outside every dielectric sphere");
  }
  for (std::size_t i = 0; i < dielectric_spheres.size(); ++i) {
    const auto& first = dielectric_spheres[i];
    unsigned int layers = 1;
    for (std::size_t j = 0; j < dielectric_spheres.size(); ++j) {
      if (i == j) continue;
      const auto& second = dielectric_spheres[j];
      const double distance =
          distance_between(first.sphere.center, second.sphere.center);
      if (i < j) {
        const bool separate =
            distance > first.sphere.radius + second.sphere.radius;
        const bool first_contains =
            distance + second.sphere.radius < first.sphere.radius;
        const bool second_contains =
            distance + first.sphere.radius < second.sphere.radius;
        if (!separate && !first_contains && !second_contains)
          fail("objects[" + std::to_string(second.object_index) + "]",
               "dielectric sphere boundaries in water scenes must be "
               "strictly separate or strictly nested");
      }
      if (distance + first.sphere.radius < second.sphere.radius) ++layers;
    }
    if (layers + 1 > 4)
      fail("objects[" + std::to_string(first.object_index) + "]",
           "nested dielectric spheres exceed the four-layer medium stack "
           "including water");
  }
  for (std::size_t i = 0; i < water_bounds.size(); ++i) {
    const auto& first = water_bounds[i];
    if (scene_.camera.look_from.x + lens_radius >= first.minimum_x &&
        scene_.camera.look_from.x - lens_radius <= first.maximum_x &&
        scene_.camera.look_from.z + lens_radius >= first.minimum_z &&
        scene_.camera.look_from.z - lens_radius <= first.maximum_z &&
        scene_.camera.look_from.y - lens_radius <= first.maximum_y)
      fail("camera.look_from",
           "camera aperture must start outside and above every water surface");
    for (std::size_t j = i + 1; j < water_bounds.size(); ++j) {
      const auto& second = water_bounds[j];
      const bool separate = first.maximum_x < second.minimum_x ||
                            second.maximum_x < first.minimum_x ||
                            first.maximum_z < second.minimum_z ||
                            second.maximum_z < first.minimum_z;
      if (!separate)
        fail("objects[" + std::to_string(second.object_index) + "]",
             "water_surface footprints must be strictly separate");
    }
    for (const auto& boundary : dielectric_spheres) {
      const double x = std::min(
          std::max(static_cast<double>(boundary.sphere.center.x),
                   first.minimum_x),
          first.maximum_x);
      const double z = std::min(
          std::max(static_cast<double>(boundary.sphere.center.z),
                   first.minimum_z),
          first.maximum_z);
      const double dx = boundary.sphere.center.x - x;
      const double dz = boundary.sphere.center.z - z;
      const double radius = boundary.sphere.radius;
      const bool overlaps = dx * dx + dz * dz <= radius * radius;
      const bool vertically_separate =
          boundary.sphere.center.y + radius < first.minimum_y ||
          boundary.sphere.center.y - radius > first.maximum_y;
      if (overlaps && !vertically_separate)
        fail("objects[" + std::to_string(boundary.object_index) + "]",
             "dielectric sphere boundary may intersect a water_surface");
    }
  }
}

std::shared_ptr<const Scene> SceneBuilder::finish() {
  require_open();
  validate_scene();
  finished_ = true;
  return std::make_shared<const Scene>(std::move(scene_));
}

}  // namespace spectraldock
