#include "spectraldock/math.h"
#include "spectraldock/obj_loader.h"
#include "spectraldock/sampling.h"
#include "spectraldock/scene_types.h"

#include <chrono>
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace spectraldock;

void check(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

void near(float actual, float expected, float epsilon, const std::string& message) {
  if (std::fabs(actual - expected) > epsilon)
    throw std::runtime_error(message + ": expected " + std::to_string(expected) +
                             ", got " + std::to_string(actual));
}

std::filesystem::path temporary(const char* suffix) {
  const auto stamp = std::chrono::high_resolution_clock::now().time_since_epoch().count();
  return std::filesystem::temp_directory_path() /
         ("spectraldock-test-" + std::to_string(stamp) + suffix);
}

struct TemporaryDirectory {
  std::filesystem::path path;

  TemporaryDirectory() : path(temporary("")) {
    std::filesystem::create_directories(path);
  }
  ~TemporaryDirectory() { std::filesystem::remove_all(path); }
};

void write_text(const std::filesystem::path& path, const std::string& contents) {
  std::ofstream output(path);
  if (!output) throw std::runtime_error("cannot create test file: " + path.string());
  output << contents;
  if (!output) throw std::runtime_error("cannot write test file: " + path.string());
}

void write_binary(const std::filesystem::path& path,
                  const std::vector<std::uint8_t>& contents) {
  std::ofstream output(path, std::ios::binary);
  if (!output) throw std::runtime_error("cannot create test file: " + path.string());
  output.write(reinterpret_cast<const char*>(contents.data()),
               static_cast<std::streamsize>(contents.size()));
  if (!output) throw std::runtime_error("cannot write test file: " + path.string());
}

void expect_error(const std::function<void()>& action,
                  const std::string& expected,
                  const std::string& message) {
  try {
    action();
  } catch (const std::exception& error) {
    if (std::string(error.what()).find(expected) != std::string::npos) return;
    throw std::runtime_error(message + ": unexpected error: " + error.what());
  }
  throw std::runtime_error(message + ": expected an exception");
}

Vec3 apply_transform(const TransformMatrix3x4& matrix, Vec3 point) {
  return {
      matrix[0] * point.x + matrix[1] * point.y +
          matrix[2] * point.z + matrix[3],
      matrix[4] * point.x + matrix[5] * point.y +
          matrix[6] * point.z + matrix[7],
      matrix[8] * point.x + matrix[9] * point.y +
          matrix[10] * point.z + matrix[11],
  };
}

void test_vectors() {
  const Vec3 x{1.0f, 0.0f, 0.0f};
  const Vec3 y{0.0f, 1.0f, 0.0f};
  check(length_squared(cross(x, y) - Vec3{0.0f, 0.0f, 1.0f}) < 1.0e-12f, "cross product");
  near(dot(x, y), 0.0f, 1.0e-7f, "dot product");
  near(length(normalize(Vec3{2.0f, 3.0f, 4.0f})), 1.0f, 1.0e-6f, "normalize");
}

void test_png() {
  const auto path = temporary(".png");
  const std::vector<std::uint8_t> expected = {
      255, 0, 0, 255, 0, 255, 0, 128,
      0, 0, 255, 64, 255, 255, 255, 0};
  write_png_rgba8(path, 2, 2, expected);
  const ImageRgba8 actual = load_png_rgba8(path);
  std::filesystem::remove(path);
  check(actual.width == 2 && actual.height == 2, "PNG dimensions");
  check(actual.pixels == expected, "PNG lossless RGBA round trip");
}

void test_pfm() {
  const auto path = temporary(".pfm");
  const std::vector<float> top_to_bottom = {
      1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f,
      7.0f, 8.0f, 9.0f, 10.0f, 11.0f, 12.0f};
  write_pfm_rgb32f(path, 2, 2, top_to_bottom);

  std::ifstream input(path, std::ios::binary);
  check(static_cast<bool>(input), "PFM output opens");
  std::string line;
  std::getline(input, line);
  check(line == "PF", "PFM RGB magic");
  std::getline(input, line);
  check(line == "2 2", "PFM dimensions");
  std::getline(input, line);
  check(line == "-1.0", "PFM little-endian scale");
  const auto read_little_endian_float = [&] {
    unsigned char bytes[4]{};
    input.read(reinterpret_cast<char*>(bytes), sizeof(bytes));
    check(input.gcount() == static_cast<std::streamsize>(sizeof(bytes)),
          "PFM float payload length");
    const std::uint32_t bits =
        static_cast<std::uint32_t>(bytes[0]) |
        (static_cast<std::uint32_t>(bytes[1]) << 8u) |
        (static_cast<std::uint32_t>(bytes[2]) << 16u) |
        (static_cast<std::uint32_t>(bytes[3]) << 24u);
    float value = 0.0f;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
  };
  const std::vector<float> bottom_to_top = {
      7.0f, 8.0f, 9.0f, 10.0f, 11.0f, 12.0f,
      1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f};
  for (const float expected : bottom_to_top)
    near(read_little_endian_float(), expected, 0.0f,
         "PFM bottom-up RGB payload");
  check(input.get() == std::char_traits<char>::eof(),
        "PFM has no trailing payload");
  input.close();
  std::filesystem::remove(path);

  expect_error([&] { write_pfm_rgb32f(path, 0, 1, {}); }, "non-zero",
               "PFM zero dimension rejection");
  expect_error([&] { write_pfm_rgb32f(path, 1, 1, {1.0f, 2.0f}); },
               "expected 3 RGB floats", "PFM channel count rejection");
  expect_error(
      [&] {
        write_pfm_rgb32f(
            path, 1, 1,
            {1.0f, std::numeric_limits<float>::infinity(), 3.0f});
      },
      "samples must be finite", "PFM non-finite sample rejection");
}

void test_hdr_and_sampling_distributions() {
  TemporaryDirectory directory;
  const std::string raw_header =
      "#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 2\n";
  std::vector<std::uint8_t> raw(raw_header.begin(), raw_header.end());
  raw.insert(raw.end(), {128, 64, 32, 129, 0, 0, 0, 0});
  const auto raw_path = directory.path / "raw.hdr";
  write_binary(raw_path, raw);
  const ImageRgb32f raw_image = load_radiance_hdr(raw_path);
  check(raw_image.width == 2 && raw_image.height == 1,
        "raw RGBE dimensions");
  near(raw_image.pixels[0], 1.0f, 1.0e-6f, "raw RGBE red");
  near(raw_image.pixels[1], 0.5f, 1.0e-6f, "raw RGBE green");
  near(raw_image.pixels[2], 0.25f, 1.0e-6f, "raw RGBE blue");
  near(raw_image.pixels[3], 0.0f, 0.0f, "zero-exponent RGBE");

  const std::string rle_header =
      "#?RGBE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 128\n";
  std::vector<std::uint8_t> rle(rle_header.begin(), rle_header.end());
  rle.insert(rle.end(), {2, 2, 0, 128});
  for (const std::uint8_t value : {std::uint8_t{128}, std::uint8_t{64},
                                   std::uint8_t{32}, std::uint8_t{129}}) {
    rle.push_back(128);  // A legal 128-byte literal packet.
    rle.insert(rle.end(), 128, value);
  }
  const auto rle_path = directory.path / "modern-rle.hdr";
  write_binary(rle_path, rle);
  const ImageRgb32f rle_image = load_radiance_hdr(rle_path);
  check(rle_image.width == 128 && rle_image.height == 1,
        "modern RLE dimensions");
  near(rle_image.pixels[127 * 3], 1.0f, 1.0e-6f,
       "128-byte RLE literal");

  std::vector<std::uint8_t> malformed(rle_header.begin(), rle_header.end());
  malformed.insert(malformed.end(), {2, 2, 0, 128, 0});
  const auto malformed_path = directory.path / "malformed.hdr";
  write_binary(malformed_path, malformed);
  expect_error([&] { (void)load_radiance_hdr(malformed_path); },
               "zero-length RLE packet", "zero-length HDR RLE rejection");

  std::vector<std::uint8_t> trailing(raw);
  trailing.push_back(0);
  const auto trailing_path = directory.path / "trailing.hdr";
  write_binary(trailing_path, trailing);
  expect_error([&] { (void)load_radiance_hdr(trailing_path); },
               "unexpected trailing data", "trailing HDR payload rejection");

  const auto oversized_path = directory.path / "oversized.hdr";
  write_text(oversized_path,
             "#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 8193\n");
  expect_error([&] { (void)load_radiance_hdr(oversized_path); },
               "width must be in", "oversized HDR rejection");

  Light small;
  small.type = LightType::Sphere;
  small.radius = 0.1f;
  small.emission = {1.0f, 1.0f, 1.0f};
  Light large;
  large.type = LightType::Rectangle;
  large.edge_u = {10.0f, 0.0f, 0.0f};
  large.edge_v = {0.0f, 0.0f, 10.0f};
  large.emission = {10.0f, 10.0f, 10.0f};
  const std::vector<Light> lights{small, large};
  const FiniteLightDistribution uniform_lights =
      build_finite_light_distribution(lights, DirectLightSampling::Uniform);
  const FiniteLightDistribution important_lights =
      build_finite_light_distribution(lights, DirectLightSampling::Importance);
  check(uniform_lights.cdf.size() == 3 &&
            uniform_lights.probabilities.size() == 2,
        "finite-light distribution dimensions");
  near(uniform_lights.probabilities[0], 0.5f, 1.0e-6f,
       "uniform finite-light probability");
  check(important_lights.probabilities[1] > 0.98f &&
            important_lights.probabilities[0] > 0.0f,
        "finite-light importance and support floor");
  for (std::size_t i = 0; i < important_lights.probabilities.size(); ++i) {
    near(important_lights.probabilities[i],
         important_lights.cdf[i + 1] - important_lights.cdf[i], 0.0f,
         "finite-light CDF interval source of truth");
  }

  ImageRgb32f black;
  black.width = 2;
  black.height = 2;
  black.pixels.assign(12, 0.0f);
  const EnvironmentDistribution black_distribution =
      build_environment_distribution(black, DirectLightSampling::Importance);
  check(black_distribution.black, "black environment fallback flag");
  near(black_distribution.row_probabilities[0], 0.5f, 1.0e-6f,
       "black environment uniform-sphere row");
  near(black_distribution.conditional_probabilities[0], 0.5f, 1.0e-6f,
       "black environment uniform longitude");

  ImageRgb32f bright = black;
  bright.pixels[0] = bright.pixels[1] = bright.pixels[2] = 100.0f;
  const EnvironmentDistribution important_environment =
      build_environment_distribution(bright, DirectLightSampling::Importance);
  const EnvironmentDistribution uniform_environment =
      build_environment_distribution(bright, DirectLightSampling::Uniform);
  check(!important_environment.black, "non-black environment flag");
  const float bright_mass = important_environment.row_probabilities[0] *
                            important_environment.conditional_probabilities[0];
  check(bright_mass > 0.98f &&
            important_environment.conditional_probabilities[1] > 0.0f,
        "environment importance and sphere support floor");
  near(uniform_environment.row_probabilities[0], 0.5f, 1.0e-6f,
       "uniform environment sphere row");
  near(uniform_environment.conditional_probabilities[0], 0.5f, 1.0e-6f,
       "uniform environment longitude");
}

void test_obj_loader() {
  TemporaryDirectory directory;
  const auto quad = directory.path / "quad.obj";
  write_text(quad, R"obj(
mtllib ignored.mtl
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 -2
usemtl ignored
s 7
f -4/-4/1 -3/-3/1 -2/-2/1 -1/-1/1
)obj");
  const TriangleMesh triangulated = load_obj_mesh(quad);
  check(triangulated.indices.size() == 2, "OBJ polygon triangulation");
  check(triangulated.positions.size() == 6 &&
            triangulated.normals.size() == 6,
        "OBJ expanded triangle corners");
  check(triangulated.has_complete_uvs(), "OBJ complete UVs");
  for (const Vec3 normal : triangulated.normals)
    near(normal.z, -1.0f, 1.0e-6f, "OBJ explicit normal interpolation data");
  bool found_top_right = false;
  for (const Vec2 uv : triangulated.texcoords)
    found_top_right = found_top_right ||
                      (std::fabs(uv.x - 1.0f) < 1.0e-6f &&
                       std::fabs(uv.y - 1.0f) < 1.0e-6f);
  check(found_top_right, "OBJ UV values");

  const auto smooth = directory.path / "smooth.obj";
  write_text(smooth, R"obj(
v 0 0 0
v 1 0 0
v 0 1 0
v 0 0 1
s 3
f 1 2 3
f 1 3 4
)obj");
  const TriangleMesh generated = load_obj_mesh(smooth);
  check(!generated.has_complete_uvs(), "OBJ missing UVs remain absent");
  const float expected = 1.0f / std::sqrt(2.0f);
  int shared_corners = 0;
  for (std::size_t i = 0; i < generated.positions.size(); ++i) {
    if (length_squared(generated.positions[i]) < 1.0e-12f) {
      near(generated.normals[i].x, expected, 1.0e-6f,
           "smoothing-group generated normal x");
      near(generated.normals[i].z, expected, 1.0e-6f,
           "smoothing-group generated normal z");
      ++shared_corners;
    }
  }
  check(shared_corners == 2, "shared smoothing-group corners");

  const auto invalid = directory.path / "invalid.obj";
  write_text(invalid, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 9\n");
  expect_error([&] { (void)load_obj_mesh(invalid); }, "out-of-range face index",
               "OBJ invalid index error");

  const auto invalid_negative_uv = directory.path / "invalid-negative-uv.obj";
  write_text(invalid_negative_uv,
             "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
             "vt 0 0\nf 1/-2 2/-1 3/-1\n");
  expect_error([&] { (void)load_obj_mesh(invalid_negative_uv); },
               "out-of-range face index",
               "OBJ invalid negative texture-coordinate index");

  const auto invalid_negative_normal =
      directory.path / "invalid-negative-normal.obj";
  write_text(invalid_negative_normal,
             "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
             "vn 0 0 1\nf 1//-2 2//-1 3//-1\n");
  expect_error([&] { (void)load_obj_mesh(invalid_negative_normal); },
               "out-of-range face index",
               "OBJ invalid negative normal index");

  const auto invalid_positive_uv = directory.path / "invalid-positive-uv.obj";
  write_text(invalid_positive_uv,
             "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
             "vt 0 0\nf 1/2 2/1 3/1\n");
  expect_error([&] { (void)load_obj_mesh(invalid_positive_uv); },
               "out-of-range face index",
               "OBJ invalid positive texture-coordinate index");

  const auto degenerate = directory.path / "degenerate.obj";
  write_text(degenerate, "v 0 0 0\nv 1 0 0\nv 2 0 0\nf 1 2 3\n");
  expect_error([&] { (void)load_obj_mesh(degenerate); }, "degenerate",
               "OBJ degenerate face error");
}

void test_transform_order() {
  Transform transform;
  transform.translate = {10.0f, 20.0f, 30.0f};
  transform.rotate_degrees = {90.0f, 90.0f, 90.0f};
  transform.scale = {2.0f, 3.0f, 4.0f};
  const Vec3 result =
      apply_transform(compose_transform(transform), {1.0f, 2.0f, 3.0f});
  near(result.x, 22.0f, 2.0e-5f, "transform T*Rz*Ry*Rx*S x");
  near(result.y, 26.0f, 2.0e-5f, "transform T*Rz*Ry*Rx*S y");
  near(result.z, 28.0f, 2.0e-5f, "transform T*Rz*Ry*Rx*S z");
}

void test_meshes() {
  TemporaryDirectory directory;
  write_text(directory.path / "mesh.obj", R"obj(
v 0 0 0
v 1 0 0
v 0 1 0
vt 0 0
vt 1 0
vt 0 1
f 1/1 2/2 3/3
)obj");
  const auto scene_path = directory.path / "scene.json";
  write_text(scene_path, R"json({
    "schema_version": 5,
    "camera": {"look_from":[0,1,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
    "background": {"type":"constant","color":[0,0,0]},
    "textures": [],
    "materials": [{"name":"front","type":"lambertian"},
                  {"name":"back","type":"metal","roughness":0.2}],
    "meshes": [{"name":"triangle","path":"mesh.obj"}],
    "objects": [{"name":"instance","type":"mesh","mesh":"triangle",
      "front_material":"front","back_material":"back",
      "transform":{"translate":[1,2,3],"rotate_degrees":[10,20,30],"scale":[2,3,4]}}]
  })json");
  const Scene scene = load_scene(scene_path);
  check(scene.meshes.size() == 1, "mesh declaration");
  check(scene.meshes[0].mesh.indices.size() == 1 &&
            scene.meshes[0].mesh.has_complete_uvs(),
        "loaded mesh data");
  check(scene.objects.size() == 1 &&
            scene.objects[0].type == GeometryType::Mesh,
        "mesh object");
  const auto& instance = std::get<MeshInstanceData>(scene.objects[0].geometry);
  check(instance.mesh_id == 0, "mesh reference");
  near(instance.transform.translate.y, 2.0f, 1.0e-6f,
       "mesh translation");
  near(instance.transform.rotate_degrees.z, 30.0f, 1.0e-6f,
       "mesh rotation");
  near(instance.transform.scale.x, 2.0f, 1.0e-6f,
       "mesh scale");

  write_text(directory.path / "no-uv.obj",
             "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
  const auto textured = directory.path / "textured-no-uv.json";
  write_text(textured, R"json({
    "schema_version": 5,
    "camera": {"look_from":[0,1,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
    "background": {"type":"constant","color":[0,0,0]},
    "textures": [{"name":"paint","type":"constant","color":[1,1,1]}],
    "materials": [{"name":"textured","type":"lambertian","texture":"paint"}],
    "meshes": [{"name":"plain","path":"no-uv.obj"}],
    "objects": [{"name":"bad","type":"mesh","mesh":"plain","material":"textured"}]
  })json");
  expect_error([&] { (void)load_scene(textured); }, "no complete UV coordinates",
               "textured mesh without UVs");

  const auto bad_scale = directory.path / "bad-scale.json";
  write_text(bad_scale, R"json({
    "schema_version": 5,
    "camera": {"look_from":[0,1,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
    "background": {"type":"constant","color":[0,0,0]},
    "textures": [], "materials": [{"name":"m","type":"lambertian"}],
    "meshes": [{"name":"triangle","path":"mesh.obj"}],
    "objects": [{"name":"bad","type":"mesh","mesh":"triangle","material":"m",
                 "transform":{"scale":[1,0,1]}}]
  })json");
  expect_error([&] { (void)load_scene(bad_scale); },
               "components must be greater than zero", "invalid mesh scale");
}

void test_flame_lights() {
  TemporaryDirectory directory;
  const auto scene_path = directory.path / "flame.json";
  const std::string valid_flame = R"json({
    "name":"plume", "type":"flame", "position":[0,1,0],
    "axis":[0,-2,0], "height":1, "radius_start":0.4, "radius_end":0.8,
    "emission_start":[4,5,6], "emission_end":[1,0,0], "extinction":2
  })json";

  const auto document = [](const std::string& lights) {
    return std::string(R"json({"schema_version":5,
      "camera":{"look_from":[0,4,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
      "background":{"type":"constant","color":[0,0,0]},
      "textures":[], "materials":[{"name":"mat","type":"lambertian"}],
      "objects":[{"name":"anchor","type":"sphere","center":[0,0,0],
                  "radius":0.25,"material":"mat"}],
      "lights":)json") + lights + "}";
  };
  const auto replace = [](std::string source, const std::string& before,
                          const std::string& after) {
    const std::size_t offset = source.find(before);
    if (offset == std::string::npos)
      throw std::runtime_error("test flame fixture replacement did not match");
    source.replace(offset, before.size(), after);
    return source;
  };
  const auto reject = [&](const std::string& flame, const std::string& expected,
                          const std::string& message) {
    write_text(scene_path, document("[" + flame + "]"));
    expect_error([&] { (void)load_scene(scene_path); }, expected, message);
  };

  write_text(scene_path, document("[" + valid_flame + "]"));
  const Scene scene = load_scene(scene_path);
  check(scene.lights.size() == 1, "flame declaration");
  const Light& light = scene.lights.front();
  check(light.type == LightType::Flame && light.object_id == kInvalidId,
        "flame light type and no object binding");
  near(light.axis.y, -1.0f, 1.0e-6f, "flame normalized axis");
  near(light.height, 1.0f, 1.0e-6f, "flame height");
  near(light.radius_start, 0.4f, 1.0e-6f, "flame start radius");
  near(light.radius_end, 0.8f, 1.0e-6f, "flame end radius");
  near(light.extinction, 2.0f, 1.0e-6f, "flame extinction");
  near(light.density_scale, 1.0f, 1.0e-6f, "flame default density scale");
  near(light.turbulence, 0.35f, 1.0e-6f, "flame default turbulence");
  near(light.noise_scale, 2.0f, 1.0e-6f, "flame default noise scale");
  check(light.seed == 0, "flame default seed");

  reject(replace(valid_flame, "\"height\":1",
                 "\"height\":1,\"object\":\"anchor\""),
         "cannot be bound to objects", "flame object binding");
  reject(replace(valid_flame, "[0,-2,0]", "[0,0,0]"), "must be non-zero",
         "flame zero axis");
  reject(replace(valid_flame, "\"height\":1", "\"height\":0"),
         "must be positive", "flame zero height");
  reject(replace(valid_flame, "\"height\":1", "\"height\":1e100"),
         "number is not finite float32", "flame non-float32 input");
  reject(replace(valid_flame, "\"radius_start\":0.4",
                 "\"radius_start\":-0.1"),
         "must be non-negative", "flame negative radius");
  reject(replace(replace(valid_flame, "\"radius_start\":0.4",
                         "\"radius_start\":0"),
                 "\"radius_end\":0.8", "\"radius_end\":0"),
         "cannot both be zero", "flame zero radii");
  reject(replace(replace(valid_flame, "[4,5,6]", "[0,0,0]"),
                         "[1,0,0]", "[0,0,0]"),
         "cannot both be zero", "flame zero emission");
  reject(replace(valid_flame, "[4,5,6]", "[-1,5,6]"),
         "components must be finite and non-negative",
         "flame negative emission");
  reject(replace(valid_flame, "\"extinction\":2", "\"extinction\":0"),
         "must be positive", "flame zero extinction");
  reject(replace(valid_flame, "\"extinction\":2",
                 "\"extinction\":2,\"density_scale\":0"),
         "must be positive", "flame zero density scale");
  reject(replace(valid_flame, "\"extinction\":2",
                 "\"extinction\":2,\"noise_scale\":0"),
         "must be positive", "flame zero noise scale");
  reject(replace(valid_flame, "\"extinction\":2",
                 "\"extinction\":2,\"turbulence\":1.1"),
         "must be in [0, 1]", "flame turbulence range");
  reject(replace(valid_flame, "\"extinction\":2",
                 "\"extinction\":2,\"seed\":4294967296"),
         "must be in [0, 4294967295]", "flame seed range");
  reject(replace(valid_flame, "\"extinction\":2", "\"extinction\":100"),
         "optical thickness must be at most 64",
         "flame conservative optical thickness");

  const std::string optically_thick =
      replace(valid_flame, "\"extinction\":2", "\"extinction\":20");
  write_text(scene_path,
             document("[" + optically_thick + "," +
                      replace(optically_thick, "\"plume\"",
                              "\"plume-2\"") +
                      "]"));
  expect_error([&] { (void)load_scene(scene_path); },
               "optical thickness must be at most 64",
               "combined flame conservative optical thickness");

  std::string too_many = "[";
  for (int i = 0; i < 9; ++i) {
    if (i != 0) too_many += ',';
    too_many += replace(valid_flame, "\"plume\"",
                        "\"plume-" + std::to_string(i) + "\"");
  }
  too_many += ']';
  write_text(scene_path, document(too_many));
  expect_error([&] { (void)load_scene(scene_path); }, "at most 8 flame lights",
               "flame count limit");
}

void test_water_surfaces() {
  TemporaryDirectory directory;
  const auto scene_path = directory.path / "water.json";
  const std::string valid_material = R"json(
    {"name":"water","type":"water"})json";
  const std::string valid_surface = R"json(
    {"name":"pool","type":"water_surface","center":[1,2,3],
     "size":[8,6],"material":"water","waves":[
       {"direction":[2,0],"amplitude":0.05,"wavelength":2,"phase_radians":-0.5},
       {"direction":[0,1],"amplitude":0.02,"wavelength":1,"phase_radians":7}
     ]})json";
  const auto document = [](const std::string& materials,
                           const std::string& objects) {
    return std::string(R"json({"schema_version":5,
      "camera":{"look_from":[0,4,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
      "background":{"type":"constant","color":[0,0,0]},
      "textures":[],"materials":)json") + materials +
           ",\"objects\":" + objects + "}";
  };
  const auto replace = [](std::string source, const std::string& before,
                          const std::string& after) {
    const std::size_t offset = source.find(before);
    if (offset == std::string::npos)
      throw std::runtime_error("test water fixture replacement did not match");
    source.replace(offset, before.size(), after);
    return source;
  };
  const auto reject = [&](const std::string& materials,
                          const std::string& objects,
                          const std::string& expected,
                          const std::string& message) {
    write_text(scene_path, document(materials, objects));
    expect_error([&] { (void)load_scene(scene_path); }, expected, message);
  };

  write_text(scene_path,
             document("[" + valid_material + "]",
                      "[" + valid_surface + "]"));
  const Scene scene = load_scene(scene_path);
  check(scene.materials.size() == 1 && scene.objects.size() == 1,
        "water declaration");
  const Material& material = scene.materials.front();
  check(material.type == MaterialType::Water,
        "water material type");
  near(material.ior, 1.333f, 1.0e-6f, "water default IOR");
  near(material.absorption.x, 0.35f, 1.0e-6f,
       "water default absorption red");
  near(material.absorption.y, 0.08f, 1.0e-6f,
       "water default absorption green");
  near(material.absorption.z, 0.025f, 1.0e-6f,
       "water default absorption blue");
  near(material.roughness, 0.0f, 0.0f, "water default roughness");
  check(scene.objects.front().type == GeometryType::WaterSurface,
        "water_surface geometry type");
  const auto& surface =
      std::get<WaterSurfaceData>(scene.objects.front().geometry);
  check(surface.wave_count == 2 && surface.tiles_x == 16 &&
            surface.tiles_z == 12,
        "water wave and automatic tile counts");
  near(surface.waves[0].direction.x, 1.0f, 1.0e-6f,
       "water wave direction normalization");
  near(surface.waves[0].phase_radians, 2.0f * kPi - 0.5f, 1.0e-6f,
       "water negative phase wrapping");
  near(surface.waves[1].phase_radians, 7.0f - 2.0f * kPi, 1.0e-6f,
       "water positive phase wrapping");

  write_text(scene_path,
             document("[" + replace(valid_material, "\"water\"}",
                                      "\"water\",\"roughness\":0.12}") +
                          "]",
                      "[" + valid_surface + "]"));
  near(load_scene(scene_path).materials.front().roughness, 0.12f, 1.0e-6f,
       "water explicit roughness");

  reject("[" + replace(valid_material, "\"water\"}",
                       "\"water\",\"texture\":\"x\"}") + "]",
         "[" + valid_surface + "]", "not supported by water",
         "water texture rejection");
  reject("[" + replace(valid_material, "\"water\"}",
                       "\"water\",\"ior\":1.0}") + "]",
         "[" + valid_surface + "]", "water IOR must be in (1, 3]",
         "water IOR range");
  reject("[" + replace(valid_material, "\"water\"}",
                       "\"water\",\"absorption\":[-1,0,0]}") + "]",
         "[" + valid_surface + "]", "finite and non-negative",
         "water absorption range");
  reject("[" + replace(valid_material, "\"water\"}",
                       "\"water\",\"roughness\":-0.1}") + "]",
         "[" + valid_surface + "]", "must be in [0, 1]",
         "water negative roughness rejection");
  reject("[" + replace(valid_material, "\"water\"}",
                       "\"water\",\"roughness\":1.1}") + "]",
         "[" + valid_surface + "]", "must be in [0, 1]",
         "water roughness upper bound");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"water_surface\"",
                       "\"water_surface\",\"alpha_cutoff\":0.5") + "]",
         "does not support alpha", "water alpha rejection");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "[2,0]", "[0,0]") + "]",
         "must be non-zero", "water zero wave direction");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"size\":[8,6]",
                       "\"size\":[8,0]") + "]",
         "components must be positive", "water surface size range");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"amplitude\":0.05",
                       "\"amplitude\":0") + "]",
         "must be positive", "water wave amplitude range");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"wavelength\":2",
                       "\"wavelength\":0") + "]",
         "must be positive", "water wavelength range");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"wavelength\":2",
                       "\"wavelength\":1e-45") + "]",
         "non-finite float32 wave number",
         "water derived wave number range");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"phase_radians\":-0.5",
                       "\"phase_radians\":\"invalid\"") + "]",
         "expected a number", "water phase must be numeric");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"amplitude\":0.05",
                       "\"amplitude\":0.4") + "]",
         "total wave slope must be at most 1", "water slope limit");
  const std::size_t waves_key = valid_surface.find("\"waves\":");
  const std::size_t waves_begin =
      waves_key == std::string::npos
          ? std::string::npos
          : waves_key + std::string("\"waves\":").size();
  const std::size_t waves_end = valid_surface.rfind(']');
  check(waves_begin != std::string::npos && waves_end != std::string::npos &&
            waves_end > waves_begin,
        "water fixture wave array bounds");
  std::string no_waves = valid_surface;
  no_waves.replace(waves_begin, waves_end - waves_begin + 1, "[]");
  reject("[" + valid_material + "]", "[" + no_waves + "]",
         "must contain 1 to 4 waves", "water wave count lower bound");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"size\":[8,6]",
                       "\"size\":[100,100]") + "]",
         "tile count must be at most 4096", "water tile limit");
  reject("[" + valid_material + "]",
         "[" + replace(valid_surface, "\"center\":[1,2,3]",
                       "\"center\":[3.4e38,2,3]") + "]",
         "derived water bounds must be finite non-degenerate float32",
         "water derived bounds range");
  const std::string collapsed_tiles = replace(
      replace(valid_surface, "\"center\":[1,2,3]",
              "\"center\":[1e8,2,1e8]"),
      "\"size\":[8,6]", "\"size\":[32,32]");
  reject("[" + valid_material + "]", "[" + collapsed_tiles + "]",
         "tile boundaries collapse in float32",
         "water tile boundary representability");

  const std::string dry_material =
      R"json({"name":"dry","type":"lambertian"})json";
  reject("[" + valid_material + "," + dry_material + "]",
         "[" + replace(valid_surface, "\"material\":\"water\"",
                       "\"material\":\"dry\"") + "]",
         "requires a water material", "water_surface material type");
  const std::string dry_sphere =
      R"json({"name":"ball","type":"sphere","center":[0,0,0],"radius":1,"material":"water"})json";
  reject("[" + valid_material + "]", "[" + dry_sphere + "]",
         "only be bound to water_surface", "water material geometry binding");

  const std::string glass_material =
      R"json({"name":"glass","type":"dielectric","ior":1.52})json";
  const std::string glass_sphere =
      R"json({"name":"glass_ball","type":"sphere","center":[0,1,0],"radius":0.25,"material":"glass"})json";
  write_text(scene_path,
             document("[" + valid_material + "," + glass_material + "]",
                      "[" + valid_surface + "," + glass_sphere + "]"));
  const Scene glass_scene = load_scene(scene_path);
  check(glass_scene.objects.size() == 2,
        "closed dielectric sphere is accepted in a water scene");
  near(glass_scene.materials[1].roughness, 0.0f, 0.0f,
       "dielectric default roughness");
  const std::string split_glass_sphere =
      R"json({"name":"split_glass","type":"sphere","center":[0,1,0],"radius":0.25,"front_material":"glass","back_material":null})json";
  reject("[" + valid_material + "," + glass_material + "]",
         "[" + valid_surface + "," + split_glass_sphere + "]",
         "one shared dielectric material on both faces",
         "split dielectric sphere boundary rejection");
  const std::string alpha_glass_sphere = replace(
      glass_sphere, "\"material\":\"glass\"",
      "\"material\":\"glass\",\"alpha_texture\":\"mask\"");
  std::string alpha_document = document(
      "[" + valid_material + "," + glass_material + "]",
      "[" + valid_surface + "," + alpha_glass_sphere + "]");
  alpha_document = replace(
      alpha_document, "\"textures\":[]",
      R"json("textures":[{"name":"mask","type":"constant","color":[1,1,1]}])json");
  write_text(scene_path, alpha_document);
  expect_error([&] { (void)load_scene(scene_path); },
               "cannot use alpha textures",
               "alpha dielectric sphere boundary rejection");

  const std::string tangent_glass_sphere = replace(
      glass_sphere, "[0,1,0]", "[0.5,1,0]");
  reject("[" + valid_material + "," + glass_material + "]",
         "[" + valid_surface + "," + glass_sphere + "," +
             replace(tangent_glass_sphere, "glass_ball", "glass_ball_2") +
             "]",
         "strictly separate or strictly nested",
         "tangent dielectric sphere rejection");

  std::string nested_spheres;
  for (int i = 0; i < 4; ++i) {
    if (i != 0) nested_spheres += ',';
    const float radius = 0.8f - 0.2f * static_cast<float>(i);
    nested_spheres +=
        "{\"name\":\"nested_" + std::to_string(i) +
        "\",\"type\":\"sphere\",\"center\":[0,1,0],\"radius\":" +
        std::to_string(radius) + ",\"material\":\"glass\"}";
  }
  reject("[" + valid_material + "," + glass_material + "]",
         "[" + valid_surface + "," + nested_spheres + "]",
         "exceed the four-layer medium stack",
         "nested dielectric stack limit");

  const std::string crossing_glass_sphere =
      R"json({"name":"crossing_glass","type":"sphere","center":[1,2,3],"radius":0.1,"material":"glass"})json";
  reject("[" + valid_material + "," + glass_material + "]",
         "[" + valid_surface + "," + crossing_glass_sphere + "]",
         "may intersect a water_surface",
         "water and dielectric boundary intersection rejection");

  const std::string camera_glass_sphere =
      R"json({"name":"camera_glass","type":"sphere","center":[0,4,4],"radius":0.25,"material":"glass"})json";
  reject("[" + valid_material + "," + glass_material + "]",
         "[" + valid_surface + "," + camera_glass_sphere + "]",
         "outside every dielectric sphere",
         "camera inside dielectric rejection");

  std::string submerged_camera_document = document(
      "[" + valid_material + "]", "[" + valid_surface + "]");
  submerged_camera_document = replace(
      submerged_camera_document, "\"look_from\":[0,4,4]",
      "\"look_from\":[0,1,4]");
  write_text(scene_path, submerged_camera_document);
  expect_error([&] { (void)load_scene(scene_path); },
               "outside and above every water surface",
               "camera below water rejection");

  const std::string second_surface = replace(
      valid_surface, "\"pool\"", "\"pool-2\"");
  reject("[" + valid_material + "]",
         "[" + valid_surface + "," + second_surface + "]",
         "footprints must be strictly separate",
         "overlapping water surface rejection");
  const std::string open_glass =
      R"json({"name":"glass_panel","type":"rectangle","p1":[-1,0,0],"p2":[-1,1,0],"p3":[1,1,0],"material":"glass"})json";
  reject("[" + valid_material + "," + glass_material + "]",
         "[" + valid_surface + "," + open_glass + "]",
         "require closed sphere geometry",
         "open dielectric rejection in a water scene");

  std::string five_surfaces = "[";
  for (int i = 0; i < 5; ++i) {
    if (i != 0) five_surfaces += ',';
    five_surfaces += replace(valid_surface, "\"pool\"",
                             "\"pool-" + std::to_string(i) + "\"");
  }
  five_surfaces += ']';
  reject("[" + valid_material + "]", five_surfaces,
         "at most 4 water_surface", "water surface count limit");
}

void test_schema_version() {
  TemporaryDirectory directory;
  const auto path = directory.path / "schema.json";
  const std::string body = R"json(
    "camera":{"look_from":[0,1,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
    "background":{"type":"constant","color":[0,0,0]},
    "textures":[],
    "materials":[{"name":"mat","type":"lambertian"}],
    "objects":[{"name":"ball","type":"sphere","center":[0,0,0],
                 "radius":1,"material":"mat"}]
  })json";

  write_text(path, "{" + body);
  expect_error([&] { (void)load_scene(path); }, "schema_version",
               "missing schema version rejection");

  for (const std::uint32_t version : {1u, 2u, 3u, 4u, 6u}) {
    write_text(path, "{\"schema_version\":" + std::to_string(version) +
                         "," + body);
    expect_error([&] { (void)load_scene(path); }, "schema_version",
                 "non-v5 schema rejection");
  }

  write_text(path, "{\"schema_version\":\"5\"," + body);
  expect_error([&] { (void)load_scene(path); }, "expected the integer 5",
               "non-integer schema version rejection");
}

void test_environment_scene_parser() {
  TemporaryDirectory directory;
  const auto path = directory.path / "environment.json";
  const std::string tail = R"json(
    "camera":{"look_from":[0,1,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
    "render":{"width":16,"height":8,"spp":1,"max_depth":2,"seed":9},
    "textures":[],
    "materials":[{"name":"mat","type":"lambertian"}],
    "objects":[{"name":"ball","type":"sphere","center":[0,0,0],
                 "radius":1,"material":"mat"}],
    "lights":[]
  })json";
  const auto document = [&](const std::string& integrator,
                            const std::string& background) {
    return std::string("{\"schema_version\":5,") + integrator +
           "\"background\":" + background + "," + tail;
  };
  const std::string environment =
      R"json({"type":"environment","path":"studio.hdr","intensity":2.5,"rotation_degrees":-45,"exposure":1})json";
  write_text(path, document(
                       R"json("integrator":{"direct_light_sampling":"uniform"},)json",
                       environment));
  const Scene scene = load_scene(path, SceneLoadOptions{false});
  check(scene.background.type == BackgroundType::Environment,
        "environment background type");
  check(scene.background.environment_path.filename() == "studio.hdr",
        "environment path resolution");
  near(scene.background.environment_intensity, 2.5f, 1.0e-6f,
       "environment intensity");
  near(scene.background.environment_rotation_degrees, -45.0f, 1.0e-6f,
       "environment rotation");
  check(scene.integrator.direct_light_sampling == DirectLightSampling::Uniform,
        "uniform direct-light sampling parse");
  expect_error([&] { (void)load_scene(path); }, "asset not found",
               "missing environment asset rejection");

  write_text(path, document("", environment));
  const Scene default_scene = load_scene(path, SceneLoadOptions{false});
  check(default_scene.integrator.direct_light_sampling ==
            DirectLightSampling::Importance,
        "default direct-light importance sampling");

  write_text(path, document(
                       R"json("integrator":{"direct_light_sampling":"power"},)json",
                       environment));
  expect_error([&] { (void)load_scene(path, SceneLoadOptions{false}); },
               "expected 'uniform' or 'importance'",
               "invalid direct-light sampling rejection");

  write_text(path, document(
                       "",
                       R"json({"type":"environment","path":"studio.hdr","intensity":-1})json"));
  expect_error([&] { (void)load_scene(path, SceneLoadOptions{false}); },
               "must be non-negative", "negative environment intensity rejection");
}

void test_scene_parser() {
  const auto path = temporary(".json");
  std::ofstream output(path);
  output << R"json({
    "schema_version": 5,
    "camera": {"look_from":[0,1,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
    "background": {"type":"constant","color":[0.1,0.2,0.3],"exposure":1},
    "integrator": {"direct_light_sampling":"uniform"},
    "render": {"width":64,"height":32,"spp":2,"max_depth":4,"seed":7},
    "textures": [{"name":"white","type":"constant","color":[0.8,0.8,0.8]}],
    "materials": [{"name":"mat","type":"lambertian","texture":"white"},
                  {"name":"emit","type":"emitter","emission":[4,5,6]},
                  {"name":"metal_default","type":"metal"},
                  {"name":"glass_default","type":"dielectric"}],
    "objects": [{"name":"ball","type":"sphere","center":[0,0,0],"radius":1,"material":"mat"},
                {"name":"panel","type":"rectangle","p1":[-1,2,-1],"p2":[1,2,-1],"p3":[1,2,1],"material":"emit"}],
    "lights": [{"name":"key","type":"rectangle","object":"panel","position":[-1,2,-1],"edge_u":[2,0,0],"edge_v":[0,0,2],"emission":[4,5,6]}]
  })json";
  output.close();
  const Scene scene = load_scene(path);
  std::filesystem::remove(path);
  check(scene.render.width == 64 && scene.render.height == 32 && scene.render.seed == 7, "render defaults");
  check(scene.textures.size() == 1 && scene.materials.size() == 4 && scene.objects.size() == 2,
        "scene arrays");
  near(scene.materials[2].roughness, 0.5f, 0.0f,
       "metal default roughness");
  near(scene.materials[3].roughness, 0.0f, 0.0f,
       "dielectric default roughness outside water scenes");
  check(scene.objects[0].front_material == 0 && scene.objects[0].back_material == 0,
        "material name resolution");
  check(scene.lights.size() == 1, "light parsing");
  check(scene.lights[0].object_id == 1, "explicit light-object binding");
  near(scene.background.exposure, 1.0f, 1.0e-6f, "background exposure");
  check(scene.integrator.direct_light_sampling == DirectLightSampling::Uniform,
        "scene integrator mode");
}

void check_ember_forge_contract(const Scene& scene,
                                const std::filesystem::path& path) {
  check(scene.background.type == BackgroundType::Constant,
        "Ember Forge background must be constant: " + path.string());
  check(length_squared(scene.background.color) < 1.0e-12f,
        "Ember Forge background must be black: " + path.string());
  for (const Material& material : scene.materials) {
    check(material.type != MaterialType::Emitter,
          "Ember Forge must not contain emitter materials: " + path.string());
  }
  check(scene.lights.size() == 3,
        "Ember Forge must contain exactly three lights: " + path.string());
  for (const Light& light : scene.lights) {
    check(light.type == LightType::Flame,
          "Ember Forge lights must all be flames: " + path.string());
  }
}

void check_builtin_scene_contract(const Scene& scene,
                                  const std::filesystem::path& path) {
  if (path.filename() == "ember-forge.json") {
    check_ember_forge_contract(scene, path);
  }
}

}  // namespace

int main(int argc, char** argv) {
  try {
    test_vectors();
    test_png();
    test_pfm();
    test_hdr_and_sampling_distributions();
    test_obj_loader();
    test_transform_order();
    test_schema_version();
    test_environment_scene_parser();
    test_scene_parser();
    test_meshes();
    test_flame_lights();
    test_water_surfaces();
    for (int i = 1; i < argc; ++i) {
      const std::filesystem::path path = argv[i];
      const Scene scene = load_scene(path, SceneLoadOptions{false});
      check(!scene.objects.empty(), "scene has no objects: " + path.string());
      check_builtin_scene_contract(scene, path);
    }
    std::cout << "all core tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "test failure: " << error.what() << '\n';
    return 1;
  }
}
