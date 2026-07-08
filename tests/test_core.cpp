#include "spectraldock/math.h"
#include "spectraldock/integrator_policy.h"
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

void test_vectors_and_optics() {
  const Vec3 x{1.0f, 0.0f, 0.0f};
  const Vec3 y{0.0f, 1.0f, 0.0f};
  check(length_squared(cross(x, y) - Vec3{0.0f, 0.0f, 1.0f}) < 1.0e-12f, "cross product");
  near(dot(x, y), 0.0f, 1.0e-7f, "dot product");
  near(length(normalize(Vec3{2.0f, 3.0f, 4.0f})), 1.0f, 1.0e-6f, "normalize");

  Vec3 refracted;
  check(refract(Vec3{0.0f, -1.0f, 0.0f}, Vec3{0.0f, 1.0f, 0.0f}, 1.0f / 1.5f, refracted),
        "normal-incidence refraction");
  near(refracted.y, -1.0f, 1.0e-6f, "normal-incidence direction");
  check(!refract(normalize(Vec3{0.9f, 0.4358899f, 0.0f}),
                 Vec3{0.0f, -1.0f, 0.0f},
                 1.5f,
                 refracted),
        "total internal reflection");
  near(fresnel_schlick(1.0f, 1.0f, 1.5f), 0.04f, 1.0e-6f, "normal Fresnel");
}

void test_intersections() {
  SurfaceHit hit;
  check(intersect_sphere(Ray{{0.0f, 0.0f, 3.0f}, {0.0f, 0.0f, -1.0f}},
                         Vec3{0.0f}, 1.0f, 0.001f, 100.0f, hit),
        "sphere intersection");
  near(hit.t, 2.0f, 1.0e-6f, "sphere distance");
  near(hit.uv.x, 0.25f, 1.0e-6f, "sphere u coordinate");
  near(hit.uv.y, 0.5f, 1.0e-6f, "sphere v coordinate");
  check(hit.front_face, "sphere front face");
  check(intersect_sphere(Ray{Vec3{0.0f}, Vec3{1.0f, 0.0f, 0.0f}},
                         Vec3{0.0f}, 1.0f, 0.001f, 100.0f, hit),
        "sphere inside intersection");
  check(!hit.front_face && hit.normal.x < 0.0f, "sphere back face orientation");

  const Vec3 p1{-1.0f, -1.0f, 0.0f};
  const Vec3 p2{-1.0f, 1.0f, 0.0f};
  const Vec3 p3{1.0f, 1.0f, 0.0f};
  check(intersect_parallelogram(
            Ray{{0.5f, -0.5f, 2.0f}, {0.0f, 0.0f, -1.0f}},
            p1, p2, p3, 0.001f, 100.0f, hit),
        "rectangle intersection");
  near(hit.uv.x, 0.75f, 1.0e-6f, "rectangle u coordinate");
  near(hit.uv.y, 0.25f, 1.0e-6f, "rectangle v coordinate");
  check(hit.front_face, "rectangle front face");
  check(intersect_parallelogram(
            Ray{{0.0f, 0.0f, -2.0f}, {0.0f, 0.0f, 1.0f}},
            p1, p2, p3, 0.001f, 100.0f, hit),
        "rectangle back intersection");
  check(!hit.front_face, "rectangle back face");

  check(intersect_disk(Ray{{0.0f, 2.0f, 0.0f}, {0.0f, -1.0f, 0.0f}},
                       Vec3{0.0f},
                       Vec3{0.0f, 1.0f, 0.0f},
                       1.0f,
                       0.001f,
                       100.0f,
                       hit),
        "disk intersection");
  near(hit.t, 2.0f, 1.0e-6f, "disk distance");
  near(hit.uv.x, 0.5f, 1.0e-6f, "disk center u");
  near(hit.uv.y, 0.5f, 1.0e-6f, "disk center v");
  check(hit.front_face, "disk front face");

  check(intersect_cylinder(Ray{{2.0f, 1.0f, 0.0f}, {-1.0f, 0.0f, 0.0f}},
                           Vec3{0.0f},
                           Vec3{0.0f, 1.0f, 0.0f},
                           2.0f,
                           1.0f,
                           0.001f,
                           100.0f,
                           hit),
        "cylinder intersection");
  near(hit.t, 1.0f, 1.0e-6f, "cylinder distance");
  near(hit.outward_normal.x, 1.0f, 1.0e-6f, "cylinder normal");
  near(hit.uv.x, 0.5f, 1.0e-6f, "cylinder axial u");
  near(hit.uv.y, 1.0f, 1.0e-6f, "cylinder azimuth v");
  check(!intersect_cylinder(Ray{{2.0f, 3.0f, 0.0f}, {-1.0f, 0.0f, 0.0f}},
                            Vec3{0.0f},
                            Vec3{0.0f, 1.0f, 0.0f},
                            2.0f,
                            1.0f,
                            0.001f,
                            100.0f,
                            hit),
        "cylinder height clipping");

  const Aabb clip{{-2.0f, -2.0f, -1.0f}, {2.0f, 2.0f, 3.0f}};
  check(intersect_parabola(Ray{{0.0f, 0.0f, -1.0f}, {0.0f, 0.0f, 1.0f}},
                           Vec3{0.0f},
                           Vec3{0.0f, 1.0f, 0.0f},
                           Vec3{0.0f, 0.0f, 1.0f},
                           clip,
                           0.001f,
                           100.0f,
                           hit),
        "parabola vertex intersection");
  near(hit.t, 1.0f, 1.0e-5f, "parabola distance");
  near(hit.outward_normal.z, -1.0f, 1.0e-5f, "parabola normal");
}

void test_color() {
  near(linear_to_srgb(0.0f), 0.0f, 1.0e-7f, "sRGB black");
  near(linear_to_srgb(1.0f), 1.0f, 1.0e-6f, "sRGB white");
  near(srgb_to_linear(linear_to_srgb(0.18f)), 0.18f, 1.0e-5f, "sRGB round trip");
  const Vec3 dark = aces_tonemap(Vec3{0.1f});
  const Vec3 bright = aces_tonemap(Vec3{10.0f});
  check(dark.x >= 0.0f && bright.x <= 1.0f && bright.x > dark.x, "ACES range and monotonicity");
}

void test_mis() {
  near(power_heuristic(1.0f, 1.0f), 0.5f, 1.0e-7f, "equal MIS PDFs");
  near(power_heuristic(1.0f, 2.0f), 0.2f, 1.0e-7f, "unequal MIS PDFs");
  near(power_heuristic(0.0f, 0.0f), 0.0f, 1.0e-7f, "zero MIS PDFs");

  const float pdf_pairs[][2] = {
      {1.0f, 1.0f},
      {1.0f, 2.0f},
      {1.0e-30f, 2.0e-30f},
      {1.0e30f, 2.0e30f},
      {1.0e-30f, 1.0e30f},
      {0.0f, 1.0f},
  };
  for (const auto& pdfs : pdf_pairs) {
    const float a = power_heuristic(pdfs[0], pdfs[1]);
    const float b = power_heuristic(pdfs[1], pdfs[0]);
    check(std::isfinite(a) && std::isfinite(b),
          "MIS weights must remain finite");
    near(a + b, 1.0f, 1.0e-6f, "complementary MIS weights");
  }

  for (const float survival : {0.05f, 0.2f, 0.95f}) {
    const ContinuationResolution continuation =
        resolve_continuation(0.375f, survival, 0.0f);
    check(continuation.survived, "roulette survivor");
    near(continuation.bsdf_pdf, 0.375f, 0.0f,
         "roulette must not change the BSDF PDF");
    near(survival * continuation.throughput_scale, 1.0f, 1.0e-6f,
         "roulette expected throughput compensation");
  }
  const ContinuationResolution boundary =
      resolve_continuation(0.375f, 0.2f, 0.2f);
  check(!boundary.survived && boundary.throughput_scale == 0.0f,
        "roulette terminates at the survival boundary");
  check(resolve_continuation(
            0.375f, 0.2f, std::nextafter(0.2f, 0.0f)).survived,
        "roulette survives immediately below the boundary");

  near(direct_light_mis_weight(1.0f, 2.0f, true, true), 0.2f,
       1.0e-7f, "nonterminal bound light uses MIS");
  near(direct_light_mis_weight(1.0f, 2.0f, true, false), 1.0f,
       1.0e-7f, "terminal direct light has full weight");
  near(direct_light_mis_weight(1.0f, 2.0f, false, true), 1.0f,
       1.0e-7f, "unbound direct light has full weight");
  near(emitter_hit_mis_weight(2.0f, 1.0f, false, true), 0.8f,
       1.0e-7f, "ordinary bound emitter hit uses MIS");
  near(emitter_hit_mis_weight(2.0f, 1.0f, true, true), 1.0f,
       1.0e-7f, "delta predecessor has full emitter weight");
  near(emitter_hit_mis_weight(2.0f, 1.0f, false, false), 1.0f,
       1.0e-7f, "unbound emitter hit has full weight");
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

void test_schema_v2_meshes() {
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
    "schema_version": 2,
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
  check(scene.schema_version == 2 && scene.meshes.size() == 1,
        "schema v2 mesh declaration");
  check(scene.meshes[0].mesh.indices.size() == 1 &&
            scene.meshes[0].mesh.has_complete_uvs(),
        "schema v2 loaded mesh data");
  check(scene.objects.size() == 1 &&
            scene.objects[0].type == GeometryType::Mesh,
        "schema v2 mesh object");
  const auto& instance = std::get<MeshInstanceData>(scene.objects[0].geometry);
  check(instance.mesh_id == 0, "schema v2 mesh reference");
  near(instance.transform.translate.y, 2.0f, 1.0e-6f,
       "schema v2 translation");
  near(instance.transform.rotate_degrees.z, 30.0f, 1.0e-6f,
       "schema v2 rotation");
  near(instance.transform.scale.x, 2.0f, 1.0e-6f,
       "schema v2 scale");

  write_text(directory.path / "no-uv.obj",
             "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n");
  const auto textured = directory.path / "textured-no-uv.json";
  write_text(textured, R"json({
    "schema_version": 2,
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
    "schema_version": 2,
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

void test_scene_parser() {
  const auto path = temporary(".json");
  std::ofstream output(path);
  output << R"json({
    "schema_version": 1,
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
    test_vectors_and_optics();
    test_intersections();
    test_color();
    test_mis();
    test_png();
    test_obj_loader();
    test_transform_order();
    test_scene_parser();
    test_schema_v2_meshes();
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
