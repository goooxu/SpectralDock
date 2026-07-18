#include "spectraldock/scene_builder.h"
#include "spectraldock/scene_types.h"

#if SPECTRALDOCK_ENABLE_GPU
#include "spectraldock/optix_renderer.h"
#endif

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <pybind11/stl/filesystem.h>

#include <array>
#include <chrono>
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
  if (value == "pbr") return MaterialType::Pbr;
  throw std::invalid_argument("unsupported material type: " + value);
}

TextureWrap texture_wrap(const std::string& value) {
  if (value == "clamp_to_edge") return TextureWrap::ClampToEdge;
  if (value == "repeat") return TextureWrap::Repeat;
  if (value == "mirrored_repeat") return TextureWrap::MirroredRepeat;
  throw std::invalid_argument("unsupported texture wrap mode: " + value);
}

TextureColorSpace texture_color_space(const std::string& value) {
  if (value == "linear") return TextureColorSpace::Linear;
  if (value == "srgb") return TextureColorSpace::Srgb;
  if (value == "hdr") return TextureColorSpace::Hdr;
  throw std::invalid_argument("unsupported texture color space: " + value);
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
  timings["avif_encode"] = stats.avif_encode_ms;
  timings["total"] = stats.total_ms;

  py::dict hdr_avif;
  hdr_avif["bit_depth"] = 10;
  hdr_avif["yuv_format"] = "4:4:4";
  hdr_avif["full_range"] = true;
  hdr_avif["cicp"] = py::make_tuple(9, 16, 9);
  hdr_avif["diffuse_white_nits"] = 203;
  hdr_avif["peak_nits"] = 1000;
  hdr_avif["lossless"] = true;
  hdr_avif["max_cll"] = stats.avif_max_cll;
  hdr_avif["max_pall"] = stats.avif_max_pall;

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
  result["schema_version"] = 2;
  result["hardware"] = std::move(hardware);
  result["versions"] = std::move(versions);
  result["render"] = std::move(render);
  result["timings_ms"] = std::move(timings);
  result["hdr_avif"] = std::move(hdr_avif);
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
      .def(
          "add_image_texture",
          [](SceneBuilder& self, const std::string& name,
             const std::filesystem::path& path,
             const std::string& color_space,
             const std::string& wrap_u, const std::string& wrap_v) {
            return self.add_image_texture(name, path,
                                          texture_color_space(color_space),
                                          texture_wrap(wrap_u),
                                          texture_wrap(wrap_v));
          },
          py::arg("name"), py::arg("path"), py::arg("color_space"),
          py::arg("wrap_u"), py::arg("wrap_v"))
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
      .def(
          "add_pbr_material",
          [](SceneBuilder& self, const std::string& name,
             std::int32_t base_color_texture_id,
             std::int32_t metallic_roughness_texture_id,
             std::int32_t normal_texture_id,
             const std::array<float, 3>& base_color, float metallic,
             float roughness, float normal_scale) {
            return self.add_pbr_material(
                name, base_color_texture_id,
                metallic_roughness_texture_id, normal_texture_id,
                vec3(base_color), metallic, roughness, normal_scale);
          },
          py::arg("name"), py::arg("base_color_texture_id"),
          py::arg("metallic_roughness_texture_id"),
          py::arg("normal_texture_id"), py::arg("base_color"),
          py::arg("metallic"), py::arg("roughness"),
          py::arg("normal_scale"))
      .def("add_mesh", &SceneBuilder::add_mesh, py::arg("name"),
           py::arg("path"),
           py::arg("material_bindings") =
               std::vector<std::pair<std::string, std::int32_t>>{})
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
      "write_texture_avif",
      [](const std::filesystem::path& path, std::uint32_t width,
         std::uint32_t height, const py::bytes& rgba, bool srgb) {
        const std::string pixels = rgba;
        const std::vector<std::uint8_t> pixel_bytes(
            reinterpret_cast<const std::uint8_t*>(pixels.data()),
            reinterpret_cast<const std::uint8_t*>(pixels.data()) +
                pixels.size());
        py::gil_scoped_release release;
        write_texture_avif_rgba8(path, width, height, pixel_bytes, srgb);
      },
      py::arg("path"), py::arg("width"), py::arg("height"),
      py::arg("rgba_bytes"), py::arg("srgb"));

  module.def(
      "read_avif",
      [](const std::filesystem::path& path) {
        DecodedAvif decoded;
        {
          py::gil_scoped_release release;
          decoded = read_avif_rgba8(path);
        }
        py::dict metadata;
        metadata["bit_depth"] = decoded.info.bit_depth;
        metadata["yuv_format"] = decoded.info.yuv_format;
        metadata["full_range"] = decoded.info.full_range;
        metadata["cicp"] = py::make_tuple(
            decoded.info.color_primaries,
            decoded.info.transfer_characteristics,
            decoded.info.matrix_coefficients);
        metadata["premultiplied"] = decoded.info.premultiplied;
        metadata["animated"] = decoded.info.animated;
        metadata["has_alpha"] = decoded.info.has_alpha;
        metadata["max_cll"] = decoded.info.max_cll;
        metadata["max_pall"] = decoded.info.max_pall;
        return py::make_tuple(
            decoded.image.width, decoded.image.height,
            py::bytes(reinterpret_cast<const char*>(decoded.image.pixels.data()),
                      decoded.image.pixels.size()),
            std::move(metadata));
      },
      py::arg("path"));

  module.def(
      "render_to_files",
      [](const NativeScene& native_scene, const std::string& output,
         int device, std::uint32_t width, std::uint32_t height,
         std::uint32_t spp, std::uint32_t max_depth, std::uint32_t seed,
         std::optional<float> clamp_direct,
         std::optional<float> clamp_indirect,
         bool denoise, bool validation, bool test_capture_linear) -> py::dict {
#if SPECTRALDOCK_ENABLE_GPU
        if (!native_scene.value)
          throw std::runtime_error("native scene handle is empty");
        const std::filesystem::path output_path(output);
        if (output_path.extension() != ".avif")
          throw std::runtime_error("output must use the lowercase .avif extension");
        if (!output_path.parent_path().empty())
          std::filesystem::create_directories(output_path.parent_path());

        RenderSettings settings;
        settings.device = device;
        settings.width = width;
        settings.height = height;
        settings.spp = spp;
        settings.max_depth = max_depth;
        settings.seed = seed;
        settings.clamp_direct = clamp_direct;
        settings.clamp_indirect = clamp_indirect;
        settings.denoise = denoise;
        settings.validation = validation;

        RenderResult result;
        {
          py::gil_scoped_release release;
          result = render_optix(*native_scene.value, settings);
          const auto encode_begin = std::chrono::steady_clock::now();
          const HdrAvifInfo info = write_hdr_avif_rgb32f(
              output_path, result.width, result.height, result.linear_rgb,
              native_scene.value->background.exposure);
          result.stats.avif_encode_ms =
              std::chrono::duration<double, std::milli>(
                  std::chrono::steady_clock::now() - encode_begin).count();
          result.stats.total_ms += result.stats.avif_encode_ms;
          result.stats.avif_max_cll = info.max_cll;
          result.stats.avif_max_pall = info.max_pall;
        }
        py::dict stats = stats_dictionary(result.stats);
        if (test_capture_linear) {
          py::tuple capture(result.linear_rgb.size());
          for (std::size_t i = 0; i < result.linear_rgb.size(); ++i)
            capture[i] = result.linear_rgb[i];
          stats["_test_linear_rgb"] = std::move(capture);
        }
        return stats;
#else
        (void)native_scene;
        (void)output;
        (void)device;
        (void)width;
        (void)height;
        (void)spp;
        (void)max_depth;
        (void)seed;
        (void)clamp_direct;
        (void)clamp_indirect;
        (void)denoise;
        (void)validation;
        (void)test_capture_linear;
        throw std::runtime_error(
            "SpectralDock was built without CUDA/OptiX rendering support");
#endif
      },
      py::arg("scene"), py::arg("output"), py::arg("device"),
      py::arg("width"), py::arg("height"), py::arg("spp"),
      py::arg("max_depth"), py::arg("seed"),
      py::arg("clamp_direct"), py::arg("clamp_indirect"),
      py::arg("denoise"), py::arg("validation") = false,
      py::arg("test_capture_linear") = false);
}
