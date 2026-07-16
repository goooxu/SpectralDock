#include "spectraldock/math.h"
#include "spectraldock/obj_loader.h"
#include "spectraldock/sampling.h"
#include "spectraldock/scene_builder.h"
#include "spectraldock/scene_types.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using namespace spectraldock;

void check(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

void near(float actual, float expected, float epsilon,
          const std::string& message) {
  if (std::fabs(actual - expected) > epsilon)
    throw std::runtime_error(message + ": expected " +
                             std::to_string(expected) + ", got " +
                             std::to_string(actual));
}

std::filesystem::path temporary(const char* suffix) {
  const auto stamp =
      std::chrono::high_resolution_clock::now().time_since_epoch().count();
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

void write_text(const std::filesystem::path& path,
                const std::string& contents) {
  std::ofstream output(path);
  if (!output)
    throw std::runtime_error("cannot create test file: " + path.string());
  output << contents;
  if (!output)
    throw std::runtime_error("cannot write test file: " + path.string());
}

void write_binary(const std::filesystem::path& path,
                  const std::vector<std::uint8_t>& contents) {
  std::ofstream output(path, std::ios::binary);
  if (!output)
    throw std::runtime_error("cannot create test file: " + path.string());
  output.write(reinterpret_cast<const char*>(contents.data()),
               static_cast<std::streamsize>(contents.size()));
  if (!output)
    throw std::runtime_error("cannot write test file: " + path.string());
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
      matrix[0] * point.x + matrix[1] * point.y + matrix[2] * point.z +
          matrix[3],
      matrix[4] * point.x + matrix[5] * point.y + matrix[6] * point.z +
          matrix[7],
      matrix[8] * point.x + matrix[9] * point.y + matrix[10] * point.z +
          matrix[11],
  };
}

void test_vectors() {
  const Vec3 x{1.0f, 0.0f, 0.0f};
  const Vec3 y{0.0f, 1.0f, 0.0f};
  check(length_squared(cross(x, y) - Vec3{0.0f, 0.0f, 1.0f}) < 1.0e-12f,
        "cross product");
  near(dot(x, y), 0.0f, 1.0e-7f, "dot product");
  near(length(normalize(Vec3{2.0f, 3.0f, 4.0f})), 1.0f, 1.0e-6f,
       "normalize");
}

void test_image_io() {
  const auto png = temporary(".png");
  const std::vector<std::uint8_t> expected = {
      255, 0, 0, 255, 0, 255, 0, 128,
      0, 0, 255, 64, 255, 255, 255, 0};
  write_png_rgba8(png, 2, 2, expected);
  const ImageRgba8 actual = load_png_rgba8(png);
  std::filesystem::remove(png);
  check(actual.width == 2 && actual.height == 2, "PNG dimensions");
  check(actual.pixels == expected, "PNG lossless RGBA round trip");

  const auto pfm = temporary(".pfm");
  const std::vector<float> top_to_bottom = {
      1.0f, 2.0f, 3.0f, 4.0f, 5.0f, 6.0f,
      7.0f, 8.0f, 9.0f, 10.0f, 11.0f, 12.0f};
  write_pfm_rgb32f(pfm, 2, 2, top_to_bottom);
  std::ifstream input(pfm, std::ios::binary);
  std::string line;
  std::getline(input, line);
  check(line == "PF", "PFM RGB magic");
  std::getline(input, line);
  check(line == "2 2", "PFM dimensions");
  std::getline(input, line);
  check(line == "-1.0", "PFM little-endian scale");
  const auto read_float = [&] {
    std::uint32_t bits = 0;
    input.read(reinterpret_cast<char*>(&bits), sizeof(bits));
    check(input.gcount() == static_cast<std::streamsize>(sizeof(bits)),
          "PFM payload length");
    float value = 0.0f;
    std::memcpy(&value, &bits, sizeof(value));
    return value;
  };
  for (float value : std::vector<float>{7.0f, 8.0f, 9.0f, 10.0f, 11.0f,
                                        12.0f, 1.0f, 2.0f, 3.0f, 4.0f,
                                        5.0f, 6.0f})
    near(read_float(), value, 0.0f, "PFM bottom-up payload");
  input.close();
  std::filesystem::remove(pfm);

  expect_error([&] { write_pfm_rgb32f(pfm, 0, 1, {}); }, "non-zero",
               "PFM zero dimension rejection");
  expect_error([&] { write_pfm_rgb32f(pfm, 1, 1, {1.0f, 2.0f}); },
               "expected 3 RGB floats", "PFM channel count rejection");
  expect_error(
      [&] {
        write_pfm_rgb32f(
            pfm, 1, 1,
            {1.0f, std::numeric_limits<float>::infinity(), 3.0f});
      },
      "samples must be finite", "PFM non-finite rejection");
}

void test_hdr_and_sampling_distributions() {
  TemporaryDirectory directory;
  const std::string header =
      "#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 2\n";
  std::vector<std::uint8_t> raw(header.begin(), header.end());
  raw.insert(raw.end(), {128, 64, 32, 129, 0, 0, 0, 0});
  const auto path = directory.path / "raw.hdr";
  write_binary(path, raw);
  const ImageRgb32f image = load_radiance_hdr(path);
  check(image.width == 2 && image.height == 1, "raw RGBE dimensions");
  near(image.pixels[0], 1.0f, 1.0e-6f, "raw RGBE red");
  near(image.pixels[1], 0.5f, 1.0e-6f, "raw RGBE green");
  near(image.pixels[2], 0.25f, 1.0e-6f, "raw RGBE blue");

  std::vector<std::uint8_t> trailing(raw);
  trailing.push_back(0);
  const auto trailing_path = directory.path / "trailing.hdr";
  write_binary(trailing_path, trailing);
  expect_error([&] { (void)load_radiance_hdr(trailing_path); },
               "unexpected trailing data", "trailing HDR rejection");

  Light small;
  small.type = LightType::Sphere;
  small.radius = 0.1f;
  small.emission = {1.0f, 1.0f, 1.0f};
  Light large;
  large.type = LightType::Rectangle;
  large.edge_u = {10.0f, 0.0f, 0.0f};
  large.edge_v = {0.0f, 0.0f, 10.0f};
  large.emission = {10.0f, 10.0f, 10.0f};
  Light point;
  point.type = LightType::Point;
  point.emission = {100.0f, 100.0f, 100.0f};
  Light directional = point;
  directional.type = LightType::Directional;
  const std::vector<Light> lights{small, point, large, directional};
  const FiniteLightDistribution uniform =
      build_finite_light_distribution(lights, DirectLightSampling::Uniform);
  const FiniteLightDistribution importance =
      build_finite_light_distribution(lights, DirectLightSampling::Importance);
  check(uniform.indices == std::vector<std::uint32_t>({0u, 2u}),
        "delta lights excluded from finite-light distribution");
  near(uniform.probabilities[0], 0.5f, 1.0e-6f,
       "uniform finite-light probability");
  check(importance.probabilities[1] > 0.98f &&
            importance.probabilities[0] > 0.0f,
        "finite-light importance support");
  for (std::size_t i = 0; i < importance.probabilities.size(); ++i)
    near(importance.probabilities[i],
         importance.cdf[i + 1] - importance.cdf[i], 0.0f,
         "finite-light CDF consistency");

  ImageRgb32f black;
  black.width = 2;
  black.height = 2;
  black.pixels.assign(12, 0.0f);
  const EnvironmentDistribution black_distribution =
      build_environment_distribution(black, DirectLightSampling::Importance);
  check(black_distribution.black, "black environment fallback");
  near(black_distribution.row_probabilities[0], 0.5f, 1.0e-6f,
       "black environment sphere row");
  ImageRgb32f bright = black;
  bright.pixels[0] = bright.pixels[1] = bright.pixels[2] = 100.0f;
  const EnvironmentDistribution bright_distribution =
      build_environment_distribution(bright, DirectLightSampling::Importance);
  check(!bright_distribution.black &&
            bright_distribution.conditional_probabilities[0] > 0.98f,
        "environment importance sampling");
}

void test_obj_loader() {
  TemporaryDirectory directory;
  const auto quad = directory.path / "quad.obj";
  write_text(quad, R"obj(
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 -2
s 7
f -4/-4/1 -3/-3/1 -2/-2/1 -1/-1/1
)obj");
  const TriangleMesh triangulated = load_obj_mesh(quad);
  check(triangulated.indices.size() == 2, "OBJ polygon triangulation");
  check(triangulated.positions.size() == 6 &&
            triangulated.normals.size() == 6 &&
            triangulated.has_complete_uvs(),
        "OBJ expanded attributes");
  for (Vec3 normal : triangulated.normals)
    near(normal.z, -1.0f, 1.0e-6f, "OBJ explicit normal");

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
  int shared = 0;
  for (std::size_t i = 0; i < generated.positions.size(); ++i) {
    if (length_squared(generated.positions[i]) < 1.0e-12f) {
      near(generated.normals[i].x, expected, 1.0e-6f,
           "generated smooth normal x");
      near(generated.normals[i].z, expected, 1.0e-6f,
           "generated smooth normal z");
      ++shared;
    }
  }
  check(shared == 2, "shared smoothing-group vertices");

  const auto invalid = directory.path / "invalid.obj";
  write_text(invalid, "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 9\n");
  expect_error([&] { (void)load_obj_mesh(invalid); }, "out-of-range",
               "OBJ invalid index");
  const auto degenerate = directory.path / "degenerate.obj";
  write_text(degenerate, "v 0 0 0\nv 1 0 0\nv 2 0 0\nf 1 2 3\n");
  expect_error([&] { (void)load_obj_mesh(degenerate); }, "degenerate",
               "OBJ degenerate face");
  const auto repeated = directory.path / "repeated-position.obj";
  write_text(repeated, R"obj(
v 0 0 0
v 1 0 0
v 0 1 0
v 0 0 0
f 1 4 2
f 1 2 3
)obj");
  check(load_obj_mesh(repeated).indices.size() == 1,
        "OBJ exact repeated-position face is discarded");
  const auto tiny_nonzero = directory.path / "tiny-nonzero.obj";
  write_text(tiny_nonzero, R"obj(
v 0 0 0
v 1e-30 0 0
v 0 1e-30 0
v 1 0 0
v 0 1 0
f 1 2 3
f 1 4 5
)obj");
  expect_error([&] { (void)load_obj_mesh(tiny_nonzero); }, "degenerate",
               "OBJ tiny nonzero positions are not treated as duplicates");
}

void test_obj_material_bindings() {
  TemporaryDirectory directory;
  const auto add_test_diffuse = [](
      SceneBuilder& builder, const std::string& name,
      std::int32_t texture = kInvalidId) {
    return builder.add_material(name, MaterialType::Lambertian, texture,
                                Vec3{0.7f}, Vec3{0.0f}, 0.5f, 1.5f,
                                Vec3{0.0f});
  };
  const auto materials = directory.path / "panels.mtl";
  const auto mesh_path = directory.path / "panels.obj";
  write_text(materials, R"mtl(
newmtl RedPanel
Kd 0.8 0.1 0.05
newmtl BluePanel
Kd 0.05 0.2 0.8
newmtl UnusedPanel
Kd 0.5 0.5 0.5
)mtl");
  write_text(mesh_path, R"obj(
mtllib panels.mtl
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
vt 0 0
vt 1 0
vt 1 1
vt 0 1
vn 0 0 -2
usemtl RedPanel
f 1 1 2
f 1/1/1 2/2/1 3/3/1
usemtl BluePanel
f 1/1/1 3/3/1 4/4/1
)obj");

  std::vector<std::string> triangle_slots;
  const TriangleMesh strict = load_obj_mesh(mesh_path, triangle_slots);
  check(strict.indices.size() == 2 &&
            strict.has_complete_uvs() &&
            triangle_slots ==
                std::vector<std::string>{"RedPanel", "BluePanel"},
        "OBJ strict per-triangle material slots and retained UVs");
  check(std::all_of(strict.normals.begin(), strict.normals.end(),
                    [](Vec3 normal) { return normal.z < -0.999f; }),
        "discarded OBJ face does not pollute retained explicit normals");

  SceneBuilder mapped;
  const auto texture =
      mapped.add_constant_texture("blue-texture", {0.1f, 0.2f, 0.8f});
  const auto red = add_test_diffuse(mapped, "red");
  const auto blue = add_test_diffuse(mapped, "blue", texture);
  const auto mapped_mesh = mapped.add_mesh(
      "panels", mesh_path, {{"BluePanel", blue}, {"RedPanel", red}});
  mapped.add_mesh_instance("mapped-instance", mapped_mesh, Transform{},
                           kInvalidId, kInvalidId, kInvalidId, 0.5f);
  expect_error(
      [&] {
        mapped.add_mesh_instance("mapped-override", mapped_mesh, Transform{},
                                 red, red, kInvalidId, 0.5f);
      },
      "material-mapped meshes do not accept front/back materials",
      "mapped OBJ materials cannot be overridden per instance");
  mapped.set_camera({0.0f, 4.0f, 8.0f}, {0.0f, 0.0f, 0.0f},
                    {0.0f, 1.0f, 0.0f}, 40.0f, 0.0f, 8.0f);
  mapped.set_constant_background({0.01f, 0.02f, 0.03f}, 0.0f);
  const std::shared_ptr<const Scene> scene = mapped.finish();
  check(scene->meshes.size() == 1 &&
            scene->meshes[0].material_ids ==
                std::vector<std::int32_t>{red, blue},
        "OBJ material slots resolve to global material ids");

  const auto legacy_path = directory.path / "legacy.obj";
  write_text(legacy_path, R"obj(
mtllib missing-and-deliberately-ignored.mtl
v 0 0 0
v 1 0 0
v 0 1 0
usemtl MissingMaterial
f 1 2 3
)obj");
  check(load_obj_mesh(legacy_path).indices.size() == 1,
        "empty material mapping keeps legacy MTL-ignore behavior");
  SceneBuilder legacy;
  const auto legacy_material =
      add_test_diffuse(legacy, "legacy-material");
  const auto legacy_mesh = legacy.add_mesh("legacy", legacy_path);
  expect_error(
      [&] {
        legacy.add_mesh_instance("missing-instance-material", legacy_mesh,
                                 Transform{}, kInvalidId, kInvalidId,
                                 kInvalidId, 0.5f);
      },
      "at least one face material", "legacy mesh still requires a material");
  legacy.add_mesh_instance("legacy-instance", legacy_mesh, Transform{},
                           legacy_material, legacy_material, kInvalidId, 0.5f);

  SceneBuilder missing;
  const auto missing_red = add_test_diffuse(missing, "red");
  expect_error(
      [&] {
        missing.add_mesh("missing-slot", mesh_path,
                         {{"RedPanel", missing_red}});
      },
      "missing binding for used OBJ material slot 'BluePanel'",
      "OBJ used material slot requires a binding");

  SceneBuilder extra;
  const auto extra_red = add_test_diffuse(extra, "red");
  const auto extra_blue = add_test_diffuse(extra, "blue");
  const auto extra_unused = add_test_diffuse(extra, "unused");
  expect_error(
      [&] {
        extra.add_mesh("extra-slot", mesh_path,
                       {{"RedPanel", extra_red},
                        {"BluePanel", extra_blue},
                        {"UnusedPanel", extra_unused}});
      },
      "binding for unused OBJ material slot 'UnusedPanel'",
      "OBJ material bindings reject unused slots");
  expect_error(
      [&] {
        extra.add_mesh("duplicate-slot", mesh_path,
                       {{"RedPanel", extra_red},
                        {"RedPanel", extra_blue},
                        {"BluePanel", extra_blue}});
      },
      "duplicate OBJ material slot 'RedPanel'",
      "OBJ material bindings reject duplicate keys");
  expect_error(
      [&] {
        extra.add_mesh("invalid-material", mesh_path,
                       {{"RedPanel", 99}, {"BluePanel", extra_blue}});
      },
      "invalid typed handle", "OBJ material bindings validate material ids");

  const auto unassigned_path = directory.path / "unassigned.obj";
  write_text(unassigned_path, R"obj(
mtllib panels.mtl
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
f 1 2 3
usemtl RedPanel
f 1 3 4
)obj");
  SceneBuilder unassigned;
  const auto unassigned_red = add_test_diffuse(unassigned, "red");
  expect_error(
      [&] {
        unassigned.add_mesh("unassigned", unassigned_path,
                            {{"RedPanel", unassigned_red}});
      },
      "has no valid usemtl assignment",
      "mapped OBJ requires every triangle to have a material");

  const auto no_uv_mtl = directory.path / "no-uv.mtl";
  const auto no_uv_obj = directory.path / "no-uv.obj";
  write_text(no_uv_mtl, "newmtl Painted\nKd 1 1 1\n");
  write_text(no_uv_obj, R"obj(
mtllib no-uv.mtl
v 0 0 0
v 1 0 0
v 0 1 0
usemtl Painted
f 1 2 3
)obj");
  SceneBuilder no_uv;
  const auto paint_texture =
      no_uv.add_constant_texture("paint", {1.0f, 1.0f, 1.0f});
  const auto painted = add_test_diffuse(no_uv, "painted", paint_texture);
  expect_error(
      [&] {
        no_uv.add_mesh("no-uv", no_uv_obj, {{"Painted", painted}});
      },
      "require complete UV coordinates",
      "textured OBJ material slot requires UVs");

  SceneBuilder water;
  const auto water_material = water.add_material(
      "water", MaterialType::Water, kInvalidId, Vec3{1.0f}, Vec3{0.0f},
      0.0f, 1.333f, {0.35f, 0.08f, 0.025f});
  expect_error(
      [&] {
        water.add_mesh("water-slot", mesh_path,
                       {{"RedPanel", water_material},
                        {"BluePanel", water_material}});
      },
      "water materials cannot be bound to OBJ material slots",
      "OBJ material slots reject water materials");
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

std::int32_t add_diffuse(SceneBuilder& builder, const std::string& name,
                         std::int32_t texture = kInvalidId,
                         Vec3 color = {0.7f, 0.7f, 0.7f}) {
  return builder.add_material(name, MaterialType::Lambertian, texture, color,
                              Vec3{0.0f}, 0.5f, 1.5f, Vec3{0.0f});
}

std::int32_t add_emitter(SceneBuilder& builder, const std::string& name,
                         Vec3 emission = {4.0f, 5.0f, 6.0f},
                         std::int32_t texture = kInvalidId) {
  return builder.add_material(name, MaterialType::Emitter, texture, Vec3{1.0f},
                              emission, 0.5f, 1.5f, Vec3{0.0f});
}

std::int32_t add_glass(SceneBuilder& builder, const std::string& name) {
  return builder.add_material(name, MaterialType::Dielectric, kInvalidId,
                              Vec3{1.0f}, Vec3{0.0f}, 0.0f, 1.5f,
                              Vec3{0.0f});
}

std::int32_t add_water(SceneBuilder& builder, const std::string& name,
                       float roughness = 0.0f) {
  return builder.add_material(name, MaterialType::Water, kInvalidId,
                              Vec3{1.0f}, Vec3{0.0f}, roughness, 1.333f,
                              {0.35f, 0.08f, 0.025f});
}

void set_camera_and_background(SceneBuilder& builder,
                               Vec3 look_from = {0.0f, 4.0f, 8.0f}) {
  builder.set_camera(look_from, {0.0f, 0.0f, 0.0f}, {0.0f, 1.0f, 0.0f},
                     40.0f, 0.0f, 8.0f);
  builder.set_constant_background({0.01f, 0.02f, 0.03f}, 0.0f);
}

void add_minimal_object(SceneBuilder& builder) {
  const std::int32_t material = add_diffuse(builder, "minimal-material");
  builder.add_sphere("minimal-object", {0.0f, 0.0f, 0.0f}, 1.0f,
                     material, material, kInvalidId, 0.5f);
}

struct Assets {
  std::filesystem::path image;
  std::filesystem::path mesh;
  std::filesystem::path environment;
};

Assets make_assets(const TemporaryDirectory& directory) {
  Assets result{directory.path / "texture.png", directory.path / "mesh.obj",
                directory.path / "studio.hdr"};
  write_png_rgba8(result.image, 1, 1, {255, 128, 64, 255});
  write_text(result.mesh, R"obj(
v 0 0 0
v 1 0 0
v 0 1 0
vt 0 0
vt 1 0
vt 0 1
f 1/1 2/2 3/3
)obj");
  const std::string header =
      "#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n";
  std::vector<std::uint8_t> pixels(header.begin(), header.end());
  pixels.insert(pixels.end(), {128, 128, 128, 129});
  write_binary(result.environment, pixels);
  return result;
}

void test_scene_builder_complete_scene() {
  TemporaryDirectory directory;
  const Assets assets = make_assets(directory);
  SceneBuilder builder;
  builder.set_camera({0.0f, 4.0f, 8.0f}, {0.0f, 0.0f, 0.0f},
                     {0.0f, 2.0f, 0.0f}, 40.0f, 0.0f, 8.0f);
  builder.set_integrator(DirectLightSampling::Uniform, 12.0f, 3.0f);
  builder.set_constant_background({0.1f, 0.2f, 0.3f}, 1.0f);

  const std::int32_t mask =
      builder.add_constant_texture("mask", {1.0f, 1.0f, 1.0f});
  const std::int32_t image =
      builder.add_image_texture("image", assets.image, true);
  const std::int32_t diffuse = add_diffuse(builder, "diffuse", image);
  const std::int32_t metal = builder.add_material(
      "metal", MaterialType::Metal, kInvalidId, {0.8f, 0.6f, 0.2f},
      Vec3{0.0f}, 0.2f, 1.5f, Vec3{0.0f});
  const std::int32_t glass = add_glass(builder, "glass");
  const std::int32_t emitter = add_emitter(builder, "emitter");
  const std::int32_t water = add_water(builder, "water", 0.12f);
  const std::int32_t mesh = builder.add_mesh("triangle", assets.mesh);

  const std::int32_t glass_sphere = builder.add_sphere(
      "glass-sphere", {0.0f, 0.0f, 0.0f}, 1.0f, glass, glass,
      kInvalidId, 0.5f);
  const std::int32_t panel = builder.add_rectangle(
      "panel", {-1.0f, 3.0f, -1.0f}, {1.0f, 3.0f, -1.0f},
      {1.0f, 3.0f, 1.0f}, emitter, emitter, kInvalidId, 0.5f);
  const std::int32_t sketch = builder.add_sketch(
      "sketch", {-2.0f, 0.0f, -2.0f}, {-2.0f, 2.0f, -2.0f},
      {0.0f, 2.0f, -2.0f}, diffuse, diffuse, mask, 0.25f);
  const std::int32_t disk = builder.add_disk(
      "disk", {3.0f, 2.0f, 0.0f}, {0.0f, -2.0f, 0.0f}, 0.75f,
      emitter, emitter, kInvalidId, 0.5f);
  const std::int32_t cylinder = builder.add_cylinder(
      "cylinder", {-3.0f, 0.0f, 2.0f}, {0.0f, 2.0f, 0.0f}, 2.0f,
      0.5f, metal, metal, kInvalidId, 0.5f);
  const std::int32_t parabola = builder.add_parabola(
      "parabola", {-3.0f, 0.0f, 0.0f}, {0.0f, 1.0f, 0.0f},
      {-3.0f, 0.0f, 1.0f}, {{-4.0f, -1.0f, -1.0f},
                              {-2.0f, 2.0f, 2.0f}},
      kInvalidId, metal, kInvalidId, 0.5f);
  const Transform transform{{1.0f, 2.0f, 3.0f},
                            {10.0f, 20.0f, 30.0f},
                            {2.0f, 3.0f, 4.0f}};
  const std::int32_t instance = builder.add_mesh_instance(
      "instance", mesh, transform, diffuse, diffuse, kInvalidId, 0.5f);
  const std::vector<WaterWave> waves = {
      {{2.0f, 0.0f}, 0.05f, 1.0f, -0.5f}};
  const std::int32_t surface = builder.add_water_surface(
      "surface", {10.0f, 0.0f, 10.0f}, {2.0f, 2.0f}, water, waves);
  const std::int32_t emitter_sphere = builder.add_sphere(
      "emitter-sphere", {-3.0f, 3.0f, 0.0f}, 0.25f, emitter, emitter,
      kInvalidId, 0.5f);

  check(mask == 0 && image == 1, "typed texture ids");
  check(diffuse == 0 && metal == 1 && glass == 2 && emitter == 3 &&
            water == 4 && mesh == 0,
        "typed resource ids");
  check(glass_sphere == 0 && panel == 1 && sketch == 2 && disk == 3 &&
            cylinder == 4 && parabola == 5 && instance == 6 &&
            surface == 7 && emitter_sphere == 8,
        "stable object ids");

  check(builder.add_sphere_light("sphere-light", {-3.0f, 3.0f, 0.0f},
                                 0.25f, {4.0f, 5.0f, 6.0f},
                                 emitter_sphere) == 0,
        "sphere light id");
  check(builder.add_rectangle_light(
            "rectangle-light", {-1.0f, 3.0f, -1.0f}, {2.0f, 0.0f, 0.0f},
            {0.0f, 0.0f, 2.0f}, {4.0f, 5.0f, 6.0f}, panel) == 1,
        "rectangle light id");
  check(builder.add_disk_light("disk-light", {3.0f, 2.0f, 0.0f},
                               {0.0f, -1.0f, 0.0f}, 0.75f,
                               {4.0f, 5.0f, 6.0f}, disk) == 2,
        "disk light id");
  check(builder.add_flame_light(
            "flame", {0.0f, 0.0f, 3.0f}, {0.0f, 2.0f, 0.0f}, 1.0f,
            0.2f, 0.1f, {8.0f, 2.0f, 0.2f}, {1.0f, 0.1f, 0.0f}, 1.0f,
            1.0f, 0.35f, 2.0f, 7u) == 3,
        "flame light id");
  check(builder.add_point_light("point", {2.0f, 2.0f, 2.0f},
                                {3.0f, 2.0f, 1.0f}) == 4,
        "point light id");
  check(builder.add_directional_light("directional", {0.0f, -2.0f, 0.0f},
                                      {0.2f, 0.3f, 0.4f}) == 5,
        "directional light id");

  const std::shared_ptr<const Scene> scene = builder.finish();
  check(scene->textures.size() == 2 && scene->materials.size() == 5 &&
            scene->meshes.size() == 1 && scene->objects.size() == 9 &&
            scene->lights.size() == 6,
        "complete builder scene dimensions");
  near(scene->camera.up.y, 1.0f, 1.0e-6f, "camera up normalization");
  near(scene->background.exposure, 1.0f, 0.0f, "background exposure");
  check(scene->integrator.direct_light_sampling == DirectLightSampling::Uniform,
        "integrator mode");
  near(scene->integrator.clamp_direct, 12.0f, 0.0f,
       "integrator direct clamp");
  check(scene->textures[1].type == TextureType::Image &&
            scene->textures[1].srgb,
        "image texture fields");
  check(scene->materials[2].type == MaterialType::Dielectric &&
            scene->materials[4].type == MaterialType::Water,
        "material types");
  near(scene->materials[4].roughness, 0.12f, 0.0f, "water roughness");
  check(scene->meshes[0].mesh.indices.size() == 1 &&
            scene->meshes[0].mesh.has_complete_uvs(),
        "mesh resource loading");

  const std::array<GeometryType, 9> expected_geometry = {
      GeometryType::Sphere,       GeometryType::Rectangle,
      GeometryType::Sketch,       GeometryType::Disk,
      GeometryType::Cylinder,     GeometryType::Parabola,
      GeometryType::Mesh,         GeometryType::WaterSurface,
      GeometryType::Sphere};
  for (std::size_t i = 0; i < expected_geometry.size(); ++i)
    check(scene->objects[i].type == expected_geometry[i],
          "all geometry types retained");
  const auto& built_transform =
      std::get<MeshInstanceData>(scene->objects[6].geometry).transform;
  near(built_transform.rotate_degrees.z, 30.0f, 0.0f,
       "mesh transform retained");
  const auto& built_water =
      std::get<WaterSurfaceData>(scene->objects[7].geometry);
  check(built_water.wave_count == 1 && built_water.tiles_x == 4 &&
            built_water.tiles_z == 4,
        "water derived tile counts");
  near(built_water.waves[0].direction.x, 1.0f, 1.0e-6f,
       "water direction normalization");
  near(built_water.waves[0].phase_radians, 2.0f * kPi - 0.5f, 1.0e-6f,
       "water phase wrapping");

  const std::array<LightType, 6> expected_lights = {
      LightType::Sphere, LightType::Rectangle, LightType::Disk,
      LightType::Flame,  LightType::Point,     LightType::Directional};
  for (std::size_t i = 0; i < expected_lights.size(); ++i)
    check(scene->lights[i].type == expected_lights[i],
          "all light types retained");
  near(scene->lights[3].axis.y, 1.0f, 1.0e-6f,
       "flame axis normalization");
  near(scene->lights[5].axis.y, -1.0f, 1.0e-6f,
       "directional axis normalization");
  expect_error([&] { builder.set_integrator(DirectLightSampling::Importance,
                                             1.0f, 1.0f); },
               "finalized", "finalized builder mutation rejection");
}

void test_scene_builder_configuration_and_resources() {
  TemporaryDirectory directory;
  const Assets assets = make_assets(directory);

  SceneBuilder missing_camera;
  missing_camera.set_constant_background(Vec3{0.0f}, 0.0f);
  add_minimal_object(missing_camera);
  expect_error([&] { (void)missing_camera.finish(); }, "camera",
               "missing camera rejection");
  SceneBuilder missing_background;
  missing_background.set_camera({0.0f, 1.0f, 4.0f}, Vec3{0.0f},
                                {0.0f, 1.0f, 0.0f}, 40.0f, 0.0f, 4.0f);
  add_minimal_object(missing_background);
  expect_error([&] { (void)missing_background.finish(); }, "background",
               "missing background rejection");
  SceneBuilder missing_objects;
  set_camera_and_background(missing_objects);
  expect_error([&] { (void)missing_objects.finish(); }, "at least one object",
               "empty scene rejection");

  SceneBuilder camera;
  expect_error(
      [&] {
        camera.set_camera(Vec3{0.0f}, Vec3{0.0f}, {0.0f, 1.0f, 0.0f},
                          40.0f, 0.0f, 1.0f);
      },
      "must differ", "coincident camera endpoints");
  expect_error(
      [&] {
        camera.set_camera({0.0f, 0.0f, 1.0f}, Vec3{0.0f},
                          {0.0f, 0.0f, 2.0f}, 40.0f, 0.0f, 1.0f);
      },
      "parallel", "parallel camera up vector");
  expect_error(
      [&] {
        camera.set_camera({0.0f, 0.0f, 1.0f}, Vec3{0.0f},
                          {0.0f, 1.0f, 0.0f}, 179.0f, 0.0f, 1.0f);
      },
      "(0, 179)", "camera FOV range");
  expect_error(
      [&] {
        camera.set_camera({0.0f, 0.0f, 1.0f}, Vec3{0.0f},
                          {0.0f, 1.0f, 0.0f}, 40.0f, -1.0f, 1.0f);
      },
      "non-negative", "camera aperture range");

  SceneBuilder sky;
  sky.set_camera({0.0f, 1.0f, 4.0f}, Vec3{0.0f}, {0.0f, 1.0f, 0.0f},
                 40.0f, 0.0f, 4.0f);
  sky.set_sky_background(Vec3{0.1f}, {0.2f, 0.3f, 0.4f},
                         {0.0f, 2.0f, 0.0f},
                         {1.0f, 0.5f, 0.25f}, 0.99f, 0.5f);
  add_minimal_object(sky);
  const auto sky_scene = sky.finish();
  check(sky_scene->background.type == BackgroundType::Sky,
        "sky background type");
  near(sky_scene->background.sun_direction.y, 1.0f, 1.0e-6f,
       "sky direction normalization");

  SceneBuilder environment;
  environment.set_camera({0.0f, 1.0f, 4.0f}, Vec3{0.0f},
                         {0.0f, 1.0f, 0.0f}, 40.0f, 0.0f, 4.0f);
  environment.set_environment_background(assets.environment, 2.5f, -45.0f,
                                         1.0f);
  add_minimal_object(environment);
  const auto environment_scene = environment.finish();
  check(environment_scene->background.type == BackgroundType::Environment,
        "environment background type");
  near(environment_scene->background.environment_intensity, 2.5f, 0.0f,
       "environment intensity");
  near(environment_scene->background.environment_rotation_degrees, -45.0f,
       0.0f, "environment rotation");
  SceneBuilder bad_background;
  expect_error(
      [&] {
        bad_background.set_environment_background(
            directory.path / "missing.hdr", 1.0f, 0.0f, 0.0f);
      },
      "asset not found", "missing environment rejection");
  expect_error(
      [&] { bad_background.set_constant_background({-1.0f, 0.0f, 0.0f}, 0.0f); },
      "non-negative", "negative constant background");
  expect_error(
      [&] {
        bad_background.set_sky_background(
            Vec3{0.0f}, Vec3{0.0f}, {1.0f, 0.0f, 0.0f}, Vec3{0.0f},
            -2.0f, 0.0f);
      },
      "[-1, 2]", "sky sun angle range");
  expect_error(
      [&] {
        bad_background.set_integrator(DirectLightSampling::Importance, -1.0f,
                                      0.0f);
      },
      "non-negative", "integrator clamp range");

  SceneBuilder resources;
  const std::int32_t constant =
      resources.add_constant_texture("constant", {0.2f, 0.3f, 0.4f});
  check(constant == 0, "constant texture id");
  expect_error(
      [&] { resources.add_constant_texture("constant", Vec3{1.0f}); },
      "duplicate name", "duplicate texture name");
  expect_error(
      [&] {
        resources.add_image_texture("missing", directory.path / "none.png",
                                    true);
      },
      "asset not found", "missing image texture");
  expect_error(
      [&] { add_diffuse(resources, "bad-reference", 99); },
      "invalid typed handle", "invalid texture id");
  add_diffuse(resources, "material");
  expect_error([&] { add_diffuse(resources, "material"); }, "duplicate name",
               "duplicate material name");
  expect_error(
      [&] {
        resources.add_material("rough", MaterialType::Metal, kInvalidId,
                               Vec3{1.0f}, Vec3{0.0f}, 1.1f, 1.5f,
                               Vec3{0.0f});
      },
      "[0, 1]", "material roughness range");
  expect_error(
      [&] {
        resources.add_material("glass", MaterialType::Dielectric, kInvalidId,
                               Vec3{1.0f}, Vec3{0.0f}, 0.0f, 1.0f,
                               Vec3{0.0f});
      },
      "greater than 1", "dielectric IOR range");
  expect_error(
      [&] {
        resources.add_material("dark-emitter", MaterialType::Emitter,
                               kInvalidId, Vec3{1.0f}, Vec3{0.0f}, 0.5f,
                               1.5f, Vec3{0.0f});
      },
      "positive emission", "empty emitter rejection");
  expect_error(
      [&] {
        resources.add_material("bad-water", MaterialType::Water, constant,
                               Vec3{1.0f}, Vec3{0.0f}, 0.0f, 1.333f,
                               {0.35f, 0.08f, 0.025f});
      },
      "not supported", "water texture rejection");

  check(resources.add_mesh("mesh", assets.mesh) == 0, "mesh id");
  expect_error([&] { resources.add_mesh("mesh", assets.mesh); },
               "duplicate name", "duplicate mesh name");
  expect_error(
      [&] { resources.add_mesh("missing-mesh", directory.path / "none.obj"); },
      "asset not found", "missing mesh rejection");

  write_text(directory.path / "no-uv.obj",
             "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
  SceneBuilder uv;
  const auto texture = uv.add_constant_texture("paint", Vec3{1.0f});
  const auto textured = add_diffuse(uv, "textured", texture);
  const auto plain_mesh = uv.add_mesh("plain", directory.path / "no-uv.obj");
  expect_error(
      [&] {
        uv.add_mesh_instance("bad-uv", plain_mesh, Transform{}, textured,
                             textured, kInvalidId, 0.5f);
      },
      "no complete UV coordinates", "textured mesh UV requirement");
}

void test_scene_builder_geometry_validation() {
  TemporaryDirectory directory;
  const Assets assets = make_assets(directory);
  SceneBuilder builder;
  const auto diffuse = add_diffuse(builder, "diffuse");
  const auto water = add_water(builder, "water");
  const auto mesh = builder.add_mesh("mesh", assets.mesh);

  expect_error(
      [&] {
        builder.add_sphere("sphere", Vec3{0.0f}, 0.0f, diffuse, diffuse,
                           kInvalidId, 0.5f);
      },
      "positive", "sphere radius validation");
  expect_error(
      [&] {
        builder.add_rectangle("rectangle", Vec3{0.0f}, {1.0f, 0.0f, 0.0f},
                              {2.0f, 0.0f, 0.0f}, diffuse, diffuse,
                              kInvalidId, 0.5f);
      },
      "degenerate", "rectangle degeneracy");
  expect_error(
      [&] {
        builder.add_sketch("sketch", Vec3{0.0f}, {0.0f, 1.0f, 0.0f},
                           {1.0f, 1.0f, 0.0f}, diffuse, diffuse, kInvalidId,
                           0.5f);
      },
      "requires alpha_texture", "sketch alpha requirement");
  expect_error(
      [&] {
        builder.add_disk("disk", Vec3{0.0f}, Vec3{0.0f}, 1.0f, diffuse,
                         diffuse, kInvalidId, 0.5f);
      },
      "non-zero", "disk normal validation");
  expect_error(
      [&] {
        builder.add_cylinder("cylinder", Vec3{0.0f},
                             {0.0f, 1.0f, 0.0f}, 0.0f, 1.0f, diffuse,
                             diffuse, kInvalidId, 0.5f);
      },
      "height", "cylinder height validation");
  expect_error(
      [&] {
        builder.add_parabola(
            "parabola", Vec3{0.0f}, {0.0f, 1.0f, 0.0f}, Vec3{0.0f},
            Aabb{Vec3{-1.0f}, Vec3{1.0f}}, diffuse, diffuse, kInvalidId,
            0.5f);
      },
      "must differ", "parabola focus validation");
  Transform zero_scale;
  zero_scale.scale = {1.0f, 0.0f, 1.0f};
  expect_error(
      [&] {
        builder.add_mesh_instance("instance", mesh, zero_scale, diffuse,
                                  diffuse, kInvalidId, 0.5f);
      },
      "greater than zero", "mesh scale validation");
  expect_error(
      [&] {
        builder.add_sphere("invalid-material", Vec3{0.0f}, 1.0f, 99, 99,
                           kInvalidId, 0.5f);
      },
      "invalid typed handle", "invalid material id");
  expect_error(
      [&] {
        builder.add_sphere("no-material", Vec3{0.0f}, 1.0f, kInvalidId,
                           kInvalidId, kInvalidId, 0.5f);
      },
      "at least one face material", "missing face materials");
  expect_error(
      [&] {
        builder.add_sphere("water-sphere", Vec3{0.0f}, 1.0f, water, water,
                           kInvalidId, 0.5f);
      },
      "only be bound", "water material geometry restriction");
  expect_error(
      [&] {
        builder.add_water_surface(
            "dry-surface", Vec3{0.0f}, {2.0f, 2.0f}, diffuse,
            {{{1.0f, 0.0f}, 0.05f, 1.0f, 0.0f}});
      },
      "requires a water material", "water surface material type");
  expect_error(
      [&] {
        builder.add_water_surface("no-waves", Vec3{0.0f}, {2.0f, 2.0f},
                                  water, {});
      },
      "1 to 4 waves", "water wave count");
  expect_error(
      [&] {
        builder.add_water_surface(
            "zero-direction", Vec3{0.0f}, {2.0f, 2.0f}, water,
            {{{0.0f, 0.0f}, 0.05f, 1.0f, 0.0f}});
      },
      "non-zero", "water direction validation");
  expect_error(
      [&] {
        builder.add_water_surface(
            "steep", Vec3{0.0f}, {2.0f, 2.0f}, water,
            {{{1.0f, 0.0f}, 0.4f, 1.0f, 0.0f}});
      },
      "slope", "water slope limit");
}

void test_scene_builder_light_validation() {
  SceneBuilder immediate;
  const auto diffuse = add_diffuse(immediate, "diffuse");
  const auto emitter = add_emitter(immediate, "emitter");
  const auto sphere = immediate.add_sphere(
      "sphere", Vec3{0.0f}, 1.0f, emitter, emitter, kInvalidId, 0.5f);
  expect_error(
      [&] {
        immediate.add_sphere_light("bad-sphere", Vec3{0.0f}, 0.0f,
                                   Vec3{1.0f}, sphere);
      },
      "positive", "sphere light radius");
  expect_error(
      [&] {
        immediate.add_rectangle_light(
            "bad-rectangle", Vec3{0.0f}, Vec3{1.0f}, Vec3{2.0f},
            Vec3{1.0f}, kInvalidId);
      },
      "degenerate", "rectangle light degeneracy");
  expect_error(
      [&] {
        immediate.add_disk_light("bad-disk", Vec3{0.0f}, Vec3{0.0f}, 1.0f,
                                 Vec3{1.0f}, kInvalidId);
      },
      "non-zero", "disk light normal");
  expect_error(
      [&] {
        immediate.add_flame_light(
            "bad-flame", Vec3{0.0f}, {0.0f, 1.0f, 0.0f}, 1.0f, 0.2f,
            0.1f, Vec3{1.0f}, Vec3{0.0f}, 1.0f, 1.0f, 1.1f, 2.0f, 0u);
      },
      "[0, 1]", "flame turbulence range");
  expect_error(
      [&] {
        immediate.add_point_light("bad-point", Vec3{0.0f},
                                  {-1.0f, 0.0f, 0.0f});
      },
      "non-negative", "point light energy");
  expect_error(
      [&] {
        immediate.add_directional_light("bad-directional", Vec3{0.0f},
                                        Vec3{1.0f});
      },
      "non-zero", "directional light direction");
  expect_error(
      [&] {
        immediate.add_sphere_light("invalid-object", Vec3{0.0f}, 1.0f,
                                   Vec3{1.0f}, 99);
      },
      "invalid typed handle", "invalid light object id");
  (void)diffuse;

  SceneBuilder mismatch;
  set_camera_and_background(mismatch);
  const auto mismatch_emitter = add_emitter(mismatch, "emitter");
  const auto rectangle = mismatch.add_rectangle(
      "rectangle", {-1.0f, 2.0f, -1.0f}, {1.0f, 2.0f, -1.0f},
      {1.0f, 2.0f, 1.0f}, mismatch_emitter, mismatch_emitter, kInvalidId,
      0.5f);
  mismatch.add_sphere_light("wrong-type", {0.0f, 2.0f, 0.0f}, 1.0f,
                            {4.0f, 5.0f, 6.0f}, rectangle);
  expect_error([&] { (void)mismatch.finish(); }, "does not match light type",
               "linked geometry type constraint");

  SceneBuilder energy;
  set_camera_and_background(energy);
  const auto energy_emitter = add_emitter(energy, "emitter");
  const auto energy_sphere = energy.add_sphere(
      "sphere", Vec3{0.0f}, 1.0f, energy_emitter, energy_emitter,
      kInvalidId, 0.5f);
  energy.add_sphere_light("mismatch", Vec3{0.0f}, 1.0f,
                          {1.0f, 1.0f, 1.0f}, energy_sphere);
  expect_error([&] { (void)energy.finish(); }, "must match linked emitter",
               "linked emitter energy constraint");

  SceneBuilder duplicate_link;
  set_camera_and_background(duplicate_link);
  const auto linked_emitter = add_emitter(duplicate_link, "emitter");
  const auto linked_sphere = duplicate_link.add_sphere(
      "sphere", Vec3{0.0f}, 1.0f, linked_emitter, linked_emitter,
      kInvalidId, 0.5f);
  duplicate_link.add_sphere_light("first", Vec3{0.0f}, 1.0f,
                                  {4.0f, 5.0f, 6.0f}, linked_sphere);
  duplicate_link.add_sphere_light("second", Vec3{0.0f}, 1.0f,
                                  {4.0f, 5.0f, 6.0f}, linked_sphere);
  expect_error([&] { (void)duplicate_link.finish(); }, "already linked",
               "one sampled light per object");

  SceneBuilder flame_limit;
  set_camera_and_background(flame_limit);
  add_minimal_object(flame_limit);
  for (int i = 0; i < 9; ++i)
    flame_limit.add_flame_light(
        "flame-" + std::to_string(i), {static_cast<float>(i), 0.0f, 0.0f},
        {0.0f, 1.0f, 0.0f}, 0.5f, 0.1f, 0.05f, Vec3{1.0f}, Vec3{0.1f},
        0.5f, 0.5f, 0.35f, 2.0f, static_cast<std::uint32_t>(i));
  expect_error([&] { (void)flame_limit.finish(); }, "at most 8 flame",
               "flame count limit");

  SceneBuilder optical_limit;
  set_camera_and_background(optical_limit);
  add_minimal_object(optical_limit);
  optical_limit.add_flame_light(
      "thick", Vec3{0.0f}, {0.0f, 1.0f, 0.0f}, 10.0f, 1.0f, 1.0f,
      Vec3{1.0f}, Vec3{0.1f}, 10.0f, 1.0f, 0.35f, 2.0f, 0u);
  expect_error([&] { (void)optical_limit.finish(); },
               "optical thickness must be at most 64",
               "flame optical thickness limit");

  SceneBuilder delta_limit;
  set_camera_and_background(delta_limit);
  add_minimal_object(delta_limit);
  for (int i = 0; i < 33; ++i)
    delta_limit.add_point_light("point-" + std::to_string(i),
                                {static_cast<float>(i), 1.0f, 0.0f},
                                {1.0f, 1.0f, 1.0f});
  expect_error([&] { (void)delta_limit.finish(); },
               "at most 32 point and directional",
               "delta light count limit");
}

SceneBuilder make_water_builder(Vec3 camera = {0.0f, 4.0f, 8.0f}) {
  SceneBuilder builder;
  set_camera_and_background(builder, camera);
  return builder;
}

void test_scene_builder_water_safety() {
  const std::vector<WaterWave> waves = {
      {{1.0f, 0.0f}, 0.05f, 1.0f, 0.0f}};

  SceneBuilder overlap = make_water_builder();
  const auto overlap_water = add_water(overlap, "water");
  overlap.add_water_surface("first", {0.0f, 0.0f, 0.0f}, {2.0f, 2.0f},
                            overlap_water, waves);
  overlap.add_water_surface("second", {1.0f, 0.0f, 0.0f}, {2.0f, 2.0f},
                            overlap_water, waves);
  expect_error([&] { (void)overlap.finish(); }, "footprints",
               "overlapping water surfaces");

  SceneBuilder open_dielectric = make_water_builder();
  const auto open_water = add_water(open_dielectric, "water");
  const auto glass = add_glass(open_dielectric, "glass");
  open_dielectric.add_water_surface("surface", {10.0f, 0.0f, 10.0f},
                                    {2.0f, 2.0f}, open_water, waves);
  open_dielectric.add_rectangle(
      "glass-panel", {-1.0f, 0.0f, 0.0f}, {-1.0f, 1.0f, 0.0f},
      {1.0f, 1.0f, 0.0f}, glass, glass, kInvalidId, 0.5f);
  expect_error([&] { (void)open_dielectric.finish(); },
               "require closed sphere geometry",
               "open dielectric boundary in water scene");

  SceneBuilder crossing = make_water_builder();
  const auto crossing_water = add_water(crossing, "water");
  const auto crossing_glass = add_glass(crossing, "glass");
  crossing.add_water_surface("surface", {0.0f, 0.0f, 0.0f},
                             {4.0f, 4.0f}, crossing_water, waves);
  crossing.add_sphere("glass-sphere", {0.0f, 0.0f, 0.0f}, 0.5f,
                      crossing_glass, crossing_glass, kInvalidId, 0.5f);
  expect_error([&] { (void)crossing.finish(); }, "may intersect",
               "water and dielectric intersection");

  SceneBuilder submerged = make_water_builder({0.0f, 0.0f, 1.0f});
  const auto submerged_water = add_water(submerged, "water");
  submerged.add_water_surface("surface", {0.0f, 0.0f, 0.0f},
                              {4.0f, 4.0f}, submerged_water, waves);
  expect_error([&] { (void)submerged.finish(); }, "outside and above",
               "camera below water safety boundary");

  SceneBuilder split = make_water_builder();
  const auto split_water = add_water(split, "water");
  const auto split_glass = add_glass(split, "glass");
  split.add_water_surface("surface", {10.0f, 0.0f, 10.0f},
                          {2.0f, 2.0f}, split_water, waves);
  split.add_sphere("split-glass", Vec3{0.0f}, 1.0f, split_glass,
                   kInvalidId, kInvalidId, 0.5f);
  expect_error([&] { (void)split.finish(); }, "one shared dielectric",
               "split dielectric sphere boundary");

  SceneBuilder count = make_water_builder();
  const auto count_water = add_water(count, "water");
  for (int i = 0; i < 4; ++i)
    count.add_water_surface("surface-" + std::to_string(i),
                            {10.0f * static_cast<float>(i), 0.0f, 0.0f},
                            {2.0f, 2.0f}, count_water, waves);
  expect_error(
      [&] {
        count.add_water_surface("surface-4", {40.0f, 0.0f, 0.0f},
                                {2.0f, 2.0f}, count_water, waves);
      },
      "at most 4 water_surface", "water surface count limit");
}

void test_scene_builder_duplicate_names() {
  SceneBuilder objects;
  const auto material = add_diffuse(objects, "material");
  objects.add_sphere("object", Vec3{0.0f}, 1.0f, material, material,
                     kInvalidId, 0.5f);
  expect_error(
      [&] {
        objects.add_sphere("object", {2.0f, 0.0f, 0.0f}, 1.0f, material,
                           material, kInvalidId, 0.5f);
      },
      "duplicate name", "duplicate object name");

  SceneBuilder lights;
  lights.add_point_light("light", Vec3{0.0f}, Vec3{1.0f});
  expect_error(
      [&] { lights.add_point_light("light", Vec3{1.0f}, Vec3{1.0f}); },
               "duplicate name", "duplicate light name");
}

}  // namespace

int main() {
  try {
    test_vectors();
    test_image_io();
    test_hdr_and_sampling_distributions();
    test_obj_loader();
    test_obj_material_bindings();
    test_transform_order();
    test_scene_builder_complete_scene();
    test_scene_builder_configuration_and_resources();
    test_scene_builder_geometry_validation();
    test_scene_builder_light_validation();
    test_scene_builder_water_safety();
    test_scene_builder_duplicate_names();
    std::cout << "all core tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "test failure: " << error.what() << '\n';
    return 1;
  }
}
