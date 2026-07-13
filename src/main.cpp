#include "spectraldock/optix_renderer.h"
#include "spectraldock/scene_types.h"

#include <nlohmann/json.hpp>

#include <charconv>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

#ifndef SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT
#define SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT 0
#endif

namespace {

using spectraldock::RenderSettings;

struct Cli {
  std::filesystem::path scene;
  std::filesystem::path output;
  std::optional<std::uint32_t> width;
  std::optional<std::uint32_t> height;
  std::optional<std::uint32_t> spp;
  std::optional<std::uint32_t> max_depth;
  std::optional<std::uint32_t> seed;
  std::optional<float> exposure;
  std::optional<bool> denoise;
  bool help = false;
};

[[noreturn]] void usage_error(const std::string& message) {
  throw std::invalid_argument(message + "\nRun spectraldock --help for usage.");
}

void print_usage(std::ostream& out) {
  out << "Usage:\n"
      << "  spectraldock --scene SCENE.json --output OUTPUT.png"
         " [--width N] [--height N] [--spp N] [--max-depth N]"
         " [--seed N] [--exposure EV] [--denoise|--no-denoise]\n\n"
      << "CLI values override scene render defaults. Rendering is deterministic"
         " for a fixed scene, GPU, build, and seed.\n";
}

std::uint32_t parse_u32(std::string_view text, const char* option, bool allow_zero = false) {
  std::uint64_t value = 0;
  const auto result = std::from_chars(text.data(), text.data() + text.size(), value);
  if (result.ec != std::errc{} || result.ptr != text.data() + text.size() ||
      value > std::numeric_limits<std::uint32_t>::max() || (!allow_zero && value == 0)) {
    usage_error(std::string("invalid value for ") + option + ": " + std::string(text));
  }
  return static_cast<std::uint32_t>(value);
}

float parse_float(std::string_view text, const char* option) {
  std::string owned(text);
  std::size_t used = 0;
  float value = 0.0f;
  try {
    value = std::stof(owned, &used);
  } catch (const std::exception&) {
    usage_error(std::string("invalid value for ") + option + ": " + owned);
  }
  if (used != owned.size() || !std::isfinite(value)) {
    usage_error(std::string("invalid value for ") + option + ": " + owned);
  }
  return value;
}

Cli parse_cli(int argc, char** argv) {
  Cli cli;
  auto next = [&](int& index, const char* option) -> std::string_view {
    if (index + 1 >= argc) usage_error(std::string("missing value for ") + option);
    return argv[++index];
  };

  for (int i = 1; i < argc; ++i) {
    const std::string_view arg(argv[i]);
    if (arg == "--help" || arg == "-h") {
      cli.help = true;
    } else if (arg == "--scene") {
      cli.scene = next(i, "--scene");
    } else if (arg == "--output") {
      cli.output = next(i, "--output");
    } else if (arg == "--width") {
      cli.width = parse_u32(next(i, "--width"), "--width");
    } else if (arg == "--height") {
      cli.height = parse_u32(next(i, "--height"), "--height");
    } else if (arg == "--spp") {
      cli.spp = parse_u32(next(i, "--spp"), "--spp");
    } else if (arg == "--max-depth") {
      cli.max_depth = parse_u32(next(i, "--max-depth"), "--max-depth");
    } else if (arg == "--seed") {
      cli.seed = parse_u32(next(i, "--seed"), "--seed", true);
    } else if (arg == "--exposure") {
      cli.exposure = parse_float(next(i, "--exposure"), "--exposure");
    } else if (arg == "--denoise") {
      if (cli.denoise.has_value() && !*cli.denoise) {
        usage_error("--denoise and --no-denoise are mutually exclusive");
      }
      cli.denoise = true;
    } else if (arg == "--no-denoise") {
      if (cli.denoise.has_value() && *cli.denoise) {
        usage_error("--denoise and --no-denoise are mutually exclusive");
      }
      cli.denoise = false;
    } else {
      usage_error("unknown argument: " + std::string(arg));
    }
  }

  if (!cli.help && cli.scene.empty()) usage_error("--scene is required");
  if (!cli.help && cli.output.empty()) usage_error("--output is required");
  return cli;
}

std::filesystem::path stats_path_for(std::filesystem::path output) {
  output.replace_extension(".stats.json");
  return output;
}

nlohmann::ordered_json stats_json(const spectraldock::RenderStats& s,
                                  const std::filesystem::path& scene,
                                  const std::filesystem::path& output) {
  return {
      {"scene", scene.string()},
      {"output", output.string()},
      {"hardware",
       {{"gpu", s.gpu_name},
        {"compute_capability", std::to_string(s.compute_major) + "." + std::to_string(s.compute_minor)}}},
      {"versions",
       {{"driver", s.driver_version},
        {"cuda_driver_api", s.cuda_driver_api_version},
        {"cuda_runtime", s.cuda_runtime_version},
        {"optix", s.optix_version}}},
      {"render",
       {{"width", s.width},
        {"height", s.height},
        {"spp", s.spp},
        {"max_depth", s.max_depth},
        {"seed", s.seed},
        {"denoised", s.denoised}}},
      {"timings_ms",
       {{"bvh_build", s.bvh_build_ms},
        {"render", s.render_ms},
        {"denoise", s.denoise_ms},
        {"total", s.total_ms}}},
      {"memory",
       {{"peak_device_bytes", s.peak_device_bytes},
        {"peak_tracked_device_bytes", s.peak_tracked_device_bytes}}},
      {"geometry",
       {{"objects", s.objects},
        {"instances", s.instances},
        {"unique_meshes", s.unique_meshes},
        {"mesh_triangles", s.mesh_triangles},
        {"gas_count", s.gas_count}}},
      {"performance",
       {{"traced_rays", s.traced_rays},
        {"rays_per_second", s.rays_per_second}}},
      {"volume",
       {{"volume_density_evaluations", s.volume_density_evaluations},
        {"volume_real_collisions", s.volume_real_collisions},
        {"volume_light_samples", s.volume_light_samples},
        {"volume_majorant_violations", s.volume_majorant_violations},
        {"volume_tracking_overflows", s.volume_tracking_overflows}}},
      {"water",
       {{"water_height_evaluations", s.water_height_evaluations},
        {"water_tile_tests", s.water_tile_tests},
        {"water_roots_reported", s.water_roots_reported},
        {"water_shadow_transmissions", s.water_shadow_transmissions},
        {"water_medium_segments", s.water_medium_segments},
        {"water_solver_overflows", s.water_solver_overflows},
        {"water_medium_errors", s.water_medium_errors},
        {"water_shadow_boundary_overflows",
         s.water_shadow_boundary_overflows}}}};
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Cli cli = parse_cli(argc, argv);
    if (cli.help) {
      print_usage(std::cout);
      return 0;
    }

    spectraldock::Scene scene = spectraldock::load_scene(cli.scene);
    RenderSettings settings;
    settings.width = cli.width.value_or(scene.render.width);
    settings.height = cli.height.value_or(scene.render.height);
    settings.spp = cli.spp.value_or(scene.render.spp);
    settings.max_depth = cli.max_depth.value_or(scene.render.max_depth);
    if (scene.render.seed > std::numeric_limits<std::uint32_t>::max()) {
      throw std::runtime_error("scene render.seed exceeds the supported 32-bit range");
    }
    settings.seed = cli.seed.value_or(static_cast<std::uint32_t>(scene.render.seed));
    settings.exposure = cli.exposure.value_or(scene.background.exposure);
    settings.denoise = cli.denoise.value_or(scene.render.denoise);
    settings.validation = SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT != 0;

    if (cli.output.extension() != ".png") {
      throw std::runtime_error("output must use the .png extension");
    }
    if (!cli.output.parent_path().empty()) {
      std::filesystem::create_directories(cli.output.parent_path());
    }

    const spectraldock::RenderResult result = spectraldock::render_optix(scene, settings);
    spectraldock::write_png_rgba8(cli.output, result.width, result.height, result.rgba);

    const auto stats_path = stats_path_for(cli.output);
    std::ofstream stats_stream(stats_path);
    if (!stats_stream) {
      throw std::runtime_error("cannot open stats file for writing: " + stats_path.string());
    }
    stats_stream << std::setw(2) << stats_json(result.stats, cli.scene, cli.output) << '\n';

    std::cout << "rendered " << result.width << 'x' << result.height
              << ", " << result.stats.spp << " spp in "
              << std::fixed << std::setprecision(3) << result.stats.render_ms << " ms"
              << " (" << std::setprecision(3) << result.stats.rays_per_second / 1.0e6
              << " Mrays/s)\n"
              << "image: " << cli.output << "\nstats: " << stats_path << '\n';
    return 0;
  } catch (const std::invalid_argument& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 2;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 1;
  }
}
