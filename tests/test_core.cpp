#include "spectraldock/math.h"
#include "spectraldock/obj_loader.h"
#include "spectraldock/scene_types.h"

#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <functional>
#include <iostream>
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
    "schema_version": 4,
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
    "schema_version": 4,
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
    "schema_version": 4,
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
    return std::string(R"json({"schema_version":4,
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
    return std::string(R"json({"schema_version":4,
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
  check(load_scene(scene_path).objects.size() == 2,
        "closed dielectric sphere is accepted in a water scene");
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

  for (const std::uint32_t version : {1u, 2u, 3u, 5u}) {
    write_text(path, "{\"schema_version\":" + std::to_string(version) +
                         "," + body);
    expect_error([&] { (void)load_scene(path); }, "schema_version",
                 "non-v4 schema rejection");
  }

  write_text(path, "{\"schema_version\":\"4\"," + body);
  expect_error([&] { (void)load_scene(path); }, "expected the integer 4",
               "non-integer schema version rejection");
}

void test_scene_parser() {
  const auto path = temporary(".json");
  std::ofstream output(path);
  output << R"json({
    "schema_version": 4,
    "camera": {"look_from":[0,1,4],"look_at":[0,0,0],"up":[0,1,0],"vfov":40},
    "background": {"type":"constant","color":[0.1,0.2,0.3],"exposure":1},
    "render": {"width":64,"height":32,"spp":2,"max_depth":4,"seed":7},
    "textures": [{"name":"white","type":"constant","color":[0.8,0.8,0.8]}],
    "materials": [{"name":"mat","type":"lambertian","texture":"white"},
                  {"name":"emit","type":"emitter","emission":[4,5,6]}],
    "objects": [{"name":"ball","type":"sphere","center":[0,0,0],"radius":1,"material":"mat"},
                {"name":"panel","type":"rectangle","p1":[-1,2,-1],"p2":[1,2,-1],"p3":[1,2,1],"material":"emit"}],
    "lights": [{"name":"key","type":"rectangle","object":"panel","position":[-1,2,-1],"edge_u":[2,0,0],"edge_v":[0,0,2],"emission":[4,5,6]}]
  })json";
  output.close();
  const Scene scene = load_scene(path);
  std::filesystem::remove(path);
  check(scene.render.width == 64 && scene.render.height == 32 && scene.render.seed == 7, "render defaults");
  check(scene.textures.size() == 1 && scene.materials.size() == 2 && scene.objects.size() == 2,
        "scene arrays");
  check(scene.objects[0].front_material == 0 && scene.objects[0].back_material == 0,
        "material name resolution");
  check(scene.lights.size() == 1, "light parsing");
  check(scene.lights[0].object_id == 1, "explicit light-object binding");
  near(scene.background.exposure, 1.0f, 1.0e-6f, "background exposure");
}

}  // namespace

int main(int argc, char** argv) {
  try {
    test_vectors();
    test_png();
    test_obj_loader();
    test_transform_order();
    test_schema_version();
    test_scene_parser();
    test_meshes();
    test_flame_lights();
    test_water_surfaces();
    for (int i = 1; i < argc; ++i) {
      const Scene scene = load_scene(argv[i], SceneLoadOptions{false});
      check(!scene.objects.empty(), std::string("scene has no objects: ") + argv[i]);
    }
    std::cout << "all core tests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "test failure: " << error.what() << '\n';
    return 1;
  }
}
