#include "spectraldock/scene_builder.h"
#include "spectraldock/scene_types.h"

#if SPECTRALDOCK_ENABLE_GPU
#include "spectraldock/optix_renderer.h"
#endif

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/stl/filesystem.h>

#include <array>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace py = pybind11;

#ifndef SPECTRALDOCK_ENABLE_GPU
#define SPECTRALDOCK_ENABLE_GPU 0
#endif

#ifndef SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT
#define SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT 0
#endif

namespace spectraldock {
namespace {

Vec2 vec2(const std::array<float, 2>& value) {
  return {value[0], value[1]};
}

Vec3 vec3(const std::array<float, 3>& value) {
  return {value[0], value[1], value[2]};
}

MaterialType material_type(const std::string& value) {
  if (value == "lambertian") return MaterialType::Lambertian;
  if (value == "metal") return MaterialType::Metal;
  if (value == "dielectric") return MaterialType::Dielectric;
  if (value == "emitter") return MaterialType::Emitter;
  if (value == "water") return MaterialType::Water;
  throw std::invalid_argument("unsupported material type: " + value);
}

DirectLightSampling light_sampling(const std::string& value) {
  if (value == "uniform") return DirectLightSampling::Uniform;
  if (value == "importance") return DirectLightSampling::Importance;
  throw std::invalid_argument(
      "direct_light_sampling must be 'uniform' or 'importance'");
}

struct NativeScene {
  std::shared_ptr<const Scene> value;
};

#if SPECTRALDOCK_ENABLE_GPU
py::dict stats_dictionary(const RenderStats& stats) {
  py::dict hardware;
  hardware["gpu"] = stats.gpu_name;
  hardware["compute_capability"] =
      std::to_string(stats.compute_major) + "." +
      std::to_string(stats.compute_minor);

  py::dict versions;
  versions["driver"] = stats.driver_version;
  versions["cuda_driver_api"] = stats.cuda_driver_api_version;
  versions["cuda_runtime"] = stats.cuda_runtime_version;
  versions["optix"] = stats.optix_version;

  py::dict render;
  render["width"] = stats.width;
  render["height"] = stats.height;
  render["spp"] = stats.spp;
  render["max_depth"] = stats.max_depth;
  render["seed"] = stats.seed;
  render["denoised"] = stats.denoised;
  render["direct_light_sampling"] = stats.direct_light_sampling;
  render["clamp_direct"] = stats.clamp_direct;
  render["clamp_indirect"] = stats.clamp_indirect;

  py::dict timings;
  timings["bvh_build"] = stats.bvh_build_ms;
  timings["render"] = stats.render_ms;
  timings["denoise"] = stats.denoise_ms;
  timings["total"] = stats.total_ms;

  py::dict memory;
  memory["peak_device_bytes"] = stats.peak_device_bytes;
  memory["peak_tracked_device_bytes"] = stats.peak_tracked_device_bytes;

  py::dict geometry;
  geometry["objects"] = stats.objects;
  geometry["instances"] = stats.instances;
  geometry["unique_meshes"] = stats.unique_meshes;
  geometry["mesh_triangles"] = stats.mesh_triangles;
  geometry["gas_count"] = stats.gas_count;

  py::dict performance;
  performance["traced_rays"] = stats.traced_rays;
  performance["rays_per_second"] = stats.rays_per_second;

  py::dict firefly;
  firefly["direct_clamped_contributions"] =
      stats.firefly_direct_clamped_contributions;
  firefly["indirect_clamped_contributions"] =
      stats.firefly_indirect_clamped_contributions;

  py::dict volume;
  volume["volume_density_evaluations"] = stats.volume_density_evaluations;
  volume["volume_real_collisions"] = stats.volume_real_collisions;
  volume["volume_light_samples"] = stats.volume_light_samples;
  volume["volume_majorant_violations"] = stats.volume_majorant_violations;
  volume["volume_tracking_overflows"] = stats.volume_tracking_overflows;

  py::dict water;
  water["water_height_evaluations"] = stats.water_height_evaluations;
  water["water_tile_tests"] = stats.water_tile_tests;
  water["water_roots_reported"] = stats.water_roots_reported;
  water["water_medium_segments"] = stats.water_medium_segments;
  water["water_solver_overflows"] = stats.water_solver_overflows;
  water["water_medium_errors"] = stats.water_medium_errors;
  water["water_rough_nee_attempts"] = stats.water_rough_nee_attempts;
  water["water_rough_nee_contributions"] =
      stats.water_rough_nee_contributions;
  water["water_delta_splits"] = stats.water_delta_splits;

  py::dict result;
  result["hardware"] = std::move(hardware);
  result["versions"] = std::move(versions);
  result["render"] = std::move(render);
  result["timings_ms"] = std::move(timings);
  result["memory"] = std::move(memory);
  result["geometry"] = std::move(geometry);
  result["performance"] = std::move(performance);
  result["firefly"] = std::move(firefly);
  result["volume"] = std::move(volume);
  result["water"] = std::move(water);
  return result;
}
#endif

}  // namespace
}  // namespace spectraldock

PYBIND11_MODULE(_native, module) {
  using namespace spectraldock;
  module.doc() = "SpectralDock native scene builder and OptiX renderer";
  module.attr("gpu_enabled") = py::bool_(SPECTRALDOCK_ENABLE_GPU != 0);
  module.attr("validation_default") =
      py::bool_(SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT != 0);

  py::class_<NativeScene>(module, "NativeScene");

  py::class_<SceneBuilder>(module, "SceneBuilder")
      .def(py::init<>())
      .def(
          "set_camera",
          [](SceneBuilder& self, const std::array<float, 3>& look_from,
             const std::array<float, 3>& look_at,
             const std::array<float, 3>& up, float vfov, float aperture,
             float focus_distance) {
            self.set_camera(vec3(look_from), vec3(look_at), vec3(up), vfov,
                            aperture, focus_distance);
          },
          py::arg("look_from"), py::arg("look_at"), py::arg("up"),
          py::arg("vfov"), py::arg("aperture"),
          py::arg("focus_distance"))
      .def(
          "set_integrator",
          [](SceneBuilder& self, const std::string& sampling,
             float clamp_direct, float clamp_indirect) {
            self.set_integrator(light_sampling(sampling), clamp_direct,
                                clamp_indirect);
          },
          py::arg("direct_light_sampling"), py::arg("clamp_direct"),
          py::arg("clamp_indirect"))
      .def(
          "set_constant_background",
          [](SceneBuilder& self, const std::array<float, 3>& color,
             float exposure) {
            self.set_constant_background(vec3(color), exposure);
          },
          py::arg("color"), py::arg("exposure"))
      .def(
          "set_sky_background",
          [](SceneBuilder& self, const std::array<float, 3>& bottom,
             const std::array<float, 3>& top,
             const std::array<float, 3>& sun_direction,
             const std::array<float, 3>& sun_color, float sun_cos_angle,
             float exposure) {
            self.set_sky_background(vec3(bottom), vec3(top),
                                    vec3(sun_direction), vec3(sun_color),
                                    sun_cos_angle, exposure);
          },
          py::arg("bottom"), py::arg("top"), py::arg("sun_direction"),
          py::arg("sun_color"), py::arg("sun_cos_angle"),
          py::arg("exposure"))
      .def("set_environment_background",
           &SceneBuilder::set_environment_background, py::arg("path"),
           py::arg("intensity"), py::arg("rotation_degrees"),
           py::arg("exposure"))
      .def(
          "add_constant_texture",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& color) {
            return self.add_constant_texture(name, vec3(color));
          },
          py::arg("name"), py::arg("color"))
      .def("add_image_texture", &SceneBuilder::add_image_texture,
           py::arg("name"), py::arg("path"), py::arg("srgb"))
      .def(
          "add_material",
          [](SceneBuilder& self, const std::string& name,
             const std::string& type, std::int32_t texture_id,
             const std::array<float, 3>& base_color,
             const std::array<float, 3>& emission, float roughness, float ior,
             const std::array<float, 3>& absorption) {
            return self.add_material(name, material_type(type), texture_id,
                                     vec3(base_color), vec3(emission), roughness,
                                     ior, vec3(absorption));
          },
          py::arg("name"), py::arg("type"), py::arg("texture_id"),
          py::arg("base_color"), py::arg("emission"), py::arg("roughness"),
          py::arg("ior"), py::arg("absorption"))
      .def("add_mesh", &SceneBuilder::add_mesh, py::arg("name"),
           py::arg("path"))
      .def(
          "add_sphere",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& center, float radius,
             std::int32_t front_material, std::int32_t back_material,
             std::int32_t alpha_texture, float alpha_cutoff) {
            return self.add_sphere(name, vec3(center), radius, front_material,
                                   back_material, alpha_texture, alpha_cutoff);
          })
      .def(
          "add_rectangle",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& p1, const std::array<float, 3>& p2,
             const std::array<float, 3>& p3, std::int32_t front_material,
             std::int32_t back_material, std::int32_t alpha_texture,
             float alpha_cutoff) {
            return self.add_rectangle(name, vec3(p1), vec3(p2), vec3(p3),
                                      front_material, back_material,
                                      alpha_texture, alpha_cutoff);
          })
      .def(
          "add_sketch",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& p1, const std::array<float, 3>& p2,
             const std::array<float, 3>& p3, std::int32_t front_material,
             std::int32_t back_material, std::int32_t alpha_texture,
             float alpha_cutoff) {
            return self.add_sketch(name, vec3(p1), vec3(p2), vec3(p3),
                                   front_material, back_material,
                                   alpha_texture, alpha_cutoff);
          })
      .def(
          "add_disk",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& center,
             const std::array<float, 3>& normal, float radius,
             std::int32_t front_material, std::int32_t back_material,
             std::int32_t alpha_texture, float alpha_cutoff) {
            return self.add_disk(name, vec3(center), vec3(normal), radius,
                                 front_material, back_material, alpha_texture,
                                 alpha_cutoff);
          })
      .def(
          "add_cylinder",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& base,
             const std::array<float, 3>& axis, float height, float radius,
             std::int32_t front_material, std::int32_t back_material,
             std::int32_t alpha_texture, float alpha_cutoff) {
            return self.add_cylinder(name, vec3(base), vec3(axis), height,
                                     radius, front_material, back_material,
                                     alpha_texture, alpha_cutoff);
          })
      .def(
          "add_parabola",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& origin,
             const std::array<float, 3>& normal,
             const std::array<float, 3>& focus,
             const std::array<float, 3>& clip_min,
             const std::array<float, 3>& clip_max,
             std::int32_t front_material, std::int32_t back_material,
             std::int32_t alpha_texture, float alpha_cutoff) {
            return self.add_parabola(
                name, vec3(origin), vec3(normal), vec3(focus),
                Aabb{vec3(clip_min), vec3(clip_max)}, front_material,
                back_material, alpha_texture, alpha_cutoff);
          })
      .def(
          "add_mesh_instance",
          [](SceneBuilder& self, const std::string& name, std::int32_t mesh_id,
             const std::array<float, 3>& translate,
             const std::array<float, 3>& rotate_degrees,
             const std::array<float, 3>& scale, std::int32_t front_material,
             std::int32_t back_material, std::int32_t alpha_texture,
             float alpha_cutoff) {
            return self.add_mesh_instance(
                name, mesh_id,
                Transform{vec3(translate), vec3(rotate_degrees), vec3(scale)},
                front_material, back_material, alpha_texture, alpha_cutoff);
          })
      .def(
          "add_water_surface",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& center,
             const std::array<float, 2>& size, std::int32_t material,
             const std::vector<std::tuple<std::array<float, 2>, float, float,
                                          float>>& input_waves) {
            std::vector<WaterWave> waves;
            waves.reserve(input_waves.size());
            for (const auto& [direction, amplitude, wavelength, phase] :
                 input_waves)
              waves.push_back(
                  {vec2(direction), amplitude, wavelength, phase});
            return self.add_water_surface(name, vec3(center), vec2(size),
                                          material, waves);
          })
      .def(
          "add_sphere_light",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& position, float radius,
             const std::array<float, 3>& emission, std::int32_t object_id) {
            return self.add_sphere_light(name, vec3(position), radius,
                                         vec3(emission), object_id);
          })
      .def(
          "add_rectangle_light",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& position,
             const std::array<float, 3>& edge_u,
             const std::array<float, 3>& edge_v,
             const std::array<float, 3>& emission, std::int32_t object_id) {
            return self.add_rectangle_light(name, vec3(position), vec3(edge_u),
                                            vec3(edge_v), vec3(emission),
                                            object_id);
          })
      .def(
          "add_disk_light",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& position,
             const std::array<float, 3>& normal, float radius,
             const std::array<float, 3>& emission, std::int32_t object_id) {
            return self.add_disk_light(name, vec3(position), vec3(normal),
                                       radius, vec3(emission), object_id);
          })
      .def(
          "add_flame_light",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& position,
             const std::array<float, 3>& axis, float height,
             float radius_start, float radius_end,
             const std::array<float, 3>& emission_start,
             const std::array<float, 3>& emission_end, float extinction,
             float density_scale, float turbulence, float noise_scale,
             std::uint32_t seed) {
            return self.add_flame_light(
                name, vec3(position), vec3(axis), height, radius_start,
                radius_end, vec3(emission_start), vec3(emission_end),
                extinction, density_scale, turbulence, noise_scale, seed);
          })
      .def(
          "add_point_light",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& position,
             const std::array<float, 3>& intensity) {
            return self.add_point_light(name, vec3(position), vec3(intensity));
          })
      .def(
          "add_directional_light",
          [](SceneBuilder& self, const std::string& name,
             const std::array<float, 3>& direction,
             const std::array<float, 3>& irradiance) {
            return self.add_directional_light(name, vec3(direction),
                                              vec3(irradiance));
          })
      .def("finish", [](SceneBuilder& self) {
        return NativeScene{self.finish()};
      });

  module.def(
      "render_to_files",
      [](const NativeScene& native_scene, const std::string& output,
         int device, std::uint32_t width, std::uint32_t height,
         std::uint32_t spp, std::uint32_t max_depth, std::uint32_t seed,
         float exposure, float clamp_direct, float clamp_indirect,
         bool denoise, bool validation,
         const std::optional<std::string>& linear_output) -> py::dict {
#if SPECTRALDOCK_ENABLE_GPU
        if (!native_scene.value)
          throw std::runtime_error("native scene handle is empty");
        const std::filesystem::path output_path(output);
        if (output_path.extension() != ".png")
          throw std::runtime_error("output must use the .png extension");
        std::optional<std::filesystem::path> linear_path;
        if (linear_output.has_value()) {
          linear_path = std::filesystem::path(*linear_output);
          if (linear_path->extension() != ".pfm")
            throw std::runtime_error(
                "linear_output must use the .pfm extension");
        }
        if (!output_path.parent_path().empty())
          std::filesystem::create_directories(output_path.parent_path());
        if (linear_path.has_value() && !linear_path->parent_path().empty())
          std::filesystem::create_directories(linear_path->parent_path());

        RenderSettings settings;
        settings.device = device;
        settings.width = width;
        settings.height = height;
        settings.spp = spp;
        settings.max_depth = max_depth;
        settings.seed = seed;
        settings.exposure = exposure;
        settings.clamp_direct = clamp_direct;
        settings.clamp_indirect = clamp_indirect;
        settings.denoise = denoise;
        settings.validation = validation;
        settings.capture_linear = linear_path.has_value();

        RenderResult result;
        {
          py::gil_scoped_release release;
          result = render_optix(*native_scene.value, settings);
          write_png_rgba8(output_path, result.width, result.height,
                          result.rgba);
          if (linear_path.has_value())
            write_pfm_rgb32f(*linear_path, result.width, result.height,
                             result.linear_rgb);
        }
        return stats_dictionary(result.stats);
#else
        (void)native_scene;
        (void)output;
        (void)device;
        (void)width;
        (void)height;
        (void)spp;
        (void)max_depth;
        (void)seed;
        (void)exposure;
        (void)clamp_direct;
        (void)clamp_indirect;
        (void)denoise;
        (void)validation;
        (void)linear_output;
        throw std::runtime_error(
            "SpectralDock was built without CUDA/OptiX rendering support");
#endif
      },
      py::arg("scene"), py::arg("output"), py::arg("device"),
      py::arg("width"), py::arg("height"), py::arg("spp"),
      py::arg("max_depth"), py::arg("seed"), py::arg("exposure"),
      py::arg("clamp_direct"), py::arg("clamp_indirect"),
      py::arg("denoise"), py::arg("validation") = false,
      py::arg("linear_output") = std::nullopt);
}
