#pragma once

#include "spectraldock/scene_types.h"

#include <cstdint>
#include <filesystem>
#include <memory>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace spectraldock {

// SceneBuilder is the sole public construction boundary for renderer scenes.
// It accepts typed values from the Python extension, resolves resource names
// to stable integer ids, and applies all renderer-side invariants before a
// Scene can be rendered.
class SceneBuilder {
 public:
  SceneBuilder() = default;

  void set_camera(Vec3 look_from, Vec3 look_at, Vec3 up,
                  float vertical_fov_degrees, float aperture,
                  float focus_distance);
  void set_integrator(DirectLightSampling direct_light_sampling,
                      float clamp_direct, float clamp_indirect);
  void set_constant_background(Vec3 color, float exposure);
  void set_sky_background(Vec3 bottom, Vec3 top, Vec3 sun_direction,
                          Vec3 sun_color, float sun_cos_angle,
                          float exposure);
  void set_environment_background(const std::filesystem::path& path,
                                  float intensity,
                                  float rotation_degrees,
                                  float exposure);

  std::int32_t add_constant_texture(const std::string& name, Vec3 color);
  std::int32_t add_image_texture(const std::string& name,
                                 const std::filesystem::path& path,
                                 bool srgb);
  std::int32_t add_material(const std::string& name, MaterialType type,
                            std::int32_t texture_id, Vec3 base_color,
                            Vec3 emission, float roughness, float ior,
                            Vec3 absorption);
  std::int32_t add_mesh(const std::string& name,
                        const std::filesystem::path& path,
                        const std::vector<std::pair<std::string, std::int32_t>>&
                            material_bindings = {});

  std::int32_t add_sphere(const std::string& name, Vec3 center, float radius,
                          std::int32_t front_material,
                          std::int32_t back_material,
                          std::int32_t alpha_texture, float alpha_cutoff);
  std::int32_t add_rectangle(const std::string& name, Vec3 p1, Vec3 p2,
                             Vec3 p3, std::int32_t front_material,
                             std::int32_t back_material,
                             std::int32_t alpha_texture, float alpha_cutoff);
  std::int32_t add_sketch(const std::string& name, Vec3 p1, Vec3 p2,
                          Vec3 p3, std::int32_t front_material,
                          std::int32_t back_material,
                          std::int32_t alpha_texture, float alpha_cutoff);
  std::int32_t add_disk(const std::string& name, Vec3 center, Vec3 normal,
                        float radius, std::int32_t front_material,
                        std::int32_t back_material,
                        std::int32_t alpha_texture, float alpha_cutoff);
  std::int32_t add_cylinder(const std::string& name, Vec3 base, Vec3 axis,
                            float height, float radius,
                            std::int32_t front_material,
                            std::int32_t back_material,
                            std::int32_t alpha_texture, float alpha_cutoff);
  std::int32_t add_parabola(const std::string& name, Vec3 origin,
                            Vec3 normal, Vec3 focus, Aabb clip,
                            std::int32_t front_material,
                            std::int32_t back_material,
                            std::int32_t alpha_texture, float alpha_cutoff);
  std::int32_t add_mesh_instance(const std::string& name,
                                 std::int32_t mesh_id,
                                 const Transform& transform,
                                 std::int32_t front_material,
                                 std::int32_t back_material,
                                 std::int32_t alpha_texture,
                                 float alpha_cutoff);
  std::int32_t add_water_surface(const std::string& name, Vec3 center,
                                 Vec2 size, std::int32_t material,
                                 const std::vector<WaterWave>& waves);

  std::int32_t add_sphere_light(const std::string& name, Vec3 position,
                                float radius, Vec3 emission,
                                std::int32_t object_id);
  std::int32_t add_rectangle_light(const std::string& name, Vec3 position,
                                   Vec3 edge_u, Vec3 edge_v, Vec3 emission,
                                   std::int32_t object_id);
  std::int32_t add_disk_light(const std::string& name, Vec3 position,
                              Vec3 normal, float radius, Vec3 emission,
                              std::int32_t object_id);
  std::int32_t add_flame_light(const std::string& name, Vec3 position,
                               Vec3 axis, float height, float radius_start,
                               float radius_end, Vec3 emission_start,
                               Vec3 emission_end, float extinction,
                               float density_scale, float turbulence,
                               float noise_scale, std::uint32_t seed);
  std::int32_t add_point_light(const std::string& name, Vec3 position,
                               Vec3 intensity);
  std::int32_t add_directional_light(const std::string& name, Vec3 direction,
                                     Vec3 irradiance);

  std::shared_ptr<const Scene> finish();

 private:
  void require_open() const;
  std::int32_t add_object(Object object);
  std::int32_t add_light(Light light);
  void validate_scene() const;

  Scene scene_;
  std::unordered_map<std::string, std::int32_t> texture_ids_;
  std::unordered_map<std::string, std::int32_t> material_ids_;
  std::unordered_map<std::string, std::int32_t> mesh_ids_;
  std::unordered_map<std::string, std::int32_t> object_ids_;
  std::unordered_map<std::string, std::int32_t> light_ids_;
  bool camera_set_ = false;
  bool background_set_ = false;
  bool finished_ = false;
};

}  // namespace spectraldock
