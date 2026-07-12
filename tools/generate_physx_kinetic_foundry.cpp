#include <PxConfig.h>
#include <PxPhysicsAPI.h>
#include <cudamanager/PxCudaContextManager.h>
#include <gpu/PxGpu.h>

#include <cuda_runtime_api.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <locale>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

namespace {

using json = nlohmann::json;
using namespace physx;

constexpr const char* kGenerator = "spectraldock-physx-kinetic-foundry/1.0";
constexpr const char* kPhysxVersion = "5.8.0";
constexpr const char* kPhysxCommit =
    "fc1018a3745664a1db2b95ce03fb5e91eb585f2e";
constexpr std::uint64_t kDefaultSeed = 20260711ULL;
constexpr PxU32 kSteps = 960;
constexpr float kFixedDt = 1.0f / 120.0f;
constexpr PxU32 kMascotCount = 24;
constexpr PxU32 kSphereCount = 192;
constexpr float kMascotScale = 0.70f;
constexpr float kCapsuleRadius = 0.42f;
constexpr float kCapsuleHalfHeight = 0.28f;
constexpr PxU32 kMinimumToppled = 12;
constexpr float kPi = 3.14159265358979323846f;

struct Arguments {
  std::filesystem::path output = "scenes/generated/kinetic-foundry.json";
  std::filesystem::path metadata =
      "scenes/generated/kinetic-foundry.physics.json";
  std::filesystem::path verify;
  int device = 0;
  std::uint64_t seed = kDefaultSeed;
};

[[noreturn]] void fail(const std::string& message) {
  throw std::runtime_error(message);
}

std::uint64_t parse_u64(const char* text, const char* option) {
  if (text == nullptr || *text == '\0' || *text == '-')
    fail(std::string(option) + " requires a non-negative integer");
  std::size_t consumed = 0;
  unsigned long long value = 0;
  try {
    value = std::stoull(text, &consumed, 10);
  } catch (const std::exception&) {
    fail(std::string(option) + " requires a non-negative integer");
  }
  if (text[consumed] != '\0')
    fail(std::string(option) + " requires a non-negative integer");
  return static_cast<std::uint64_t>(value);
}

Arguments parse_arguments(int argc, char** argv) {
  Arguments args;
  for (int i = 1; i < argc; ++i) {
    const std::string option(argv[i]);
    if (option == "-h" || option == "--help") {
      std::cout
          << "Usage: spectraldock_physx_scene [options]\n"
          << "  --output PATH    baked renderer scene JSON\n"
          << "  --metadata PATH  PhysX GPU manifest JSON\n"
          << "  --device N       CUDA device ordinal (default 0)\n"
          << "  --seed N         deterministic initial-layout seed\n"
          << "  --verify PATH    run Python contract checker after writing\n";
      std::exit(0);
    }
    if (i + 1 >= argc) fail("missing value for " + option);
    const char* value = argv[++i];
    if (option == "--output")
      args.output = value;
    else if (option == "--metadata")
      args.metadata = value;
    else if (option == "--verify")
      args.verify = value;
    else if (option == "--device") {
      const std::uint64_t parsed = parse_u64(value, "--device");
      if (parsed > static_cast<std::uint64_t>(std::numeric_limits<int>::max()))
        fail("--device is too large");
      args.device = static_cast<int>(parsed);
    } else if (option == "--seed") {
      args.seed = parse_u64(value, "--seed");
    } else {
      fail("unknown option: " + option);
    }
  }
  if (args.output.empty() || args.metadata.empty())
    fail("output and metadata paths must not be empty");
  if (std::filesystem::absolute(args.output).lexically_normal() ==
      std::filesystem::absolute(args.metadata).lexically_normal())
    fail("--output and --metadata must name different files");
  return args;
}

double rounded(double value) {
  if (!std::isfinite(value)) fail("simulation produced a non-finite number");
  double result = std::round(value * 1000000.0) / 1000000.0;
  if (std::fabs(result) < 0.5e-6) result = 0.0;
  return result;
}

json vector_json(const PxVec3& value) {
  return json::array({rounded(value.x), rounded(value.y), rounded(value.z)});
}

struct SplitMix64 {
  explicit SplitMix64(std::uint64_t initial) : state(initial) {}

  std::uint64_t next() {
    std::uint64_t z = (state += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27U)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31U);
  }

  float symmetric(float magnitude) {
    const double unit = static_cast<double>(next() >> 11U) /
                        static_cast<double>(std::uint64_t{1} << 53U);
    return static_cast<float>((2.0 * unit - 1.0) * magnitude);
  }

  std::uint64_t state;
};

class ErrorCallback final : public PxErrorCallback {
 public:
  void reportError(PxErrorCode::Enum code,
                   const char* message,
                   const char* file,
                   int line) override {
    std::cerr << "PhysX[" << static_cast<int>(code) << "] "
              << (message ? message : "unknown error") << " ("
              << (file ? file : "unknown") << ':' << line << ")\n";
    if (code == PxErrorCode::eINVALID_PARAMETER ||
        code == PxErrorCode::eINVALID_OPERATION ||
        code == PxErrorCode::eOUT_OF_MEMORY ||
        code == PxErrorCode::eINTERNAL_ERROR ||
        code == PxErrorCode::eABORT)
      fatal_error.store(true, std::memory_order_relaxed);
  }

  std::atomic_bool fatal_error{false};
};

void check_cuda(cudaError_t status, const char* operation) {
  if (status != cudaSuccess)
    fail(std::string(operation) + ": " + cudaGetErrorString(status));
}

struct PhysicsRuntime {
  explicit PhysicsRuntime(int device) {
    int count = 0;
    check_cuda(cudaGetDeviceCount(&count), "cudaGetDeviceCount");
    if (device < 0 || device >= count) fail("CUDA device ordinal is unavailable");
    check_cuda(cudaSetDevice(device), "cudaSetDevice");
    cudaDeviceProp properties{};
    check_cuda(cudaGetDeviceProperties(&properties, device),
               "cudaGetDeviceProperties");
    device_name = properties.name;

    foundation =
        PxCreateFoundation(PX_PHYSICS_VERSION, allocator, error_callback);
    if (!foundation) fail("PxCreateFoundation failed");

    PxTolerancesScale scale;
    physics = PxCreatePhysics(PX_PHYSICS_VERSION, *foundation, scale, true,
                              nullptr);
    if (!physics) fail("PxCreatePhysics failed");
    if (!PxInitExtensions(*physics, nullptr)) fail("PxInitExtensions failed");
    extensions_initialized = true;

    PxCudaContextManagerDesc cuda_desc;
    cuda_desc.deviceOrdinal = device;
    cuda_manager = PxCreateCudaContextManager(*foundation, cuda_desc);
    if (!cuda_manager || !cuda_manager->contextIsValid())
      fail("PhysX CUDA context manager is unavailable or invalid");

    dispatcher = PxDefaultCpuDispatcherCreate(1);
    if (!dispatcher) fail("PxDefaultCpuDispatcherCreate failed");

    PxSceneDesc scene_desc(scale);
    scene_desc.gravity = PxVec3(0.0f, -9.81f, 0.0f);
    scene_desc.cpuDispatcher = dispatcher;
    scene_desc.filterShader = PxDefaultSimulationFilterShader;
    scene_desc.cudaContextManager = cuda_manager;
    scene_desc.broadPhaseType = PxBroadPhaseType::eGPU;
    scene_desc.solverType = PxSolverType::eTGS;
    scene_desc.flags |= PxSceneFlag::eENABLE_GPU_DYNAMICS;
    scene_desc.flags |= PxSceneFlag::eENABLE_PCM;
    scene_desc.flags |= PxSceneFlag::eENABLE_STABILIZATION;
    // PhysX 5.8 explicitly does not support enhanced determinism on GPU.
    scene_desc.flags &= ~PxSceneFlag::eENABLE_ENHANCED_DETERMINISM;
    if (!scene_desc.isValid()) fail("GPU PxSceneDesc is invalid");
    scene = physics->createScene(scene_desc);
    if (!scene) fail("GPU PhysX scene creation failed; CPU fallback is forbidden");

    const PxSceneFlags flags = scene->getFlags();
    if (!flags.isSet(PxSceneFlag::eENABLE_GPU_DYNAMICS) ||
        !flags.isSet(PxSceneFlag::eENABLE_PCM) ||
        !flags.isSet(PxSceneFlag::eENABLE_STABILIZATION) ||
        flags.isSet(PxSceneFlag::eENABLE_ENHANCED_DETERMINISM) ||
        scene->getBroadPhaseType() != PxBroadPhaseType::eGPU ||
        !cuda_manager->contextIsValid()) {
      fail("created scene does not satisfy the PhysX GPU-only contract");
    }

    material = physics->createMaterial(0.58f, 0.52f, 0.04f);
    if (!material) fail("PxMaterial creation failed");
  }

  ~PhysicsRuntime() {
    if (scene) scene->release();
    if (material) material->release();
    if (dispatcher) dispatcher->release();
    if (cuda_manager) cuda_manager->release();
    if (extensions_initialized) PxCloseExtensions();
    if (physics) physics->release();
    if (foundation) foundation->release();
  }

  PhysicsRuntime(const PhysicsRuntime&) = delete;
  PhysicsRuntime& operator=(const PhysicsRuntime&) = delete;

  PxDefaultAllocator allocator;
  ErrorCallback error_callback;
  PxFoundation* foundation = nullptr;
  PxPhysics* physics = nullptr;
  PxCudaContextManager* cuda_manager = nullptr;
  PxDefaultCpuDispatcher* dispatcher = nullptr;
  PxScene* scene = nullptr;
  PxMaterial* material = nullptr;
  bool extensions_initialized = false;
  std::string device_name;
};

struct MascotRecord {
  PxRigidDynamic* actor = nullptr;
  std::string material;
};

struct SphereRecord {
  PxRigidDynamic* actor = nullptr;
  float radius = 0.0f;
  std::string material;
};

class GeneratedWorld {
 public:
  GeneratedWorld(PhysicsRuntime& runtime, std::uint64_t seed)
      : runtime_(runtime), random_(seed) {
    build_static_geometry();
    build_mascots();
    build_spheres();
    if (mascots.size() != kMascotCount || spheres.size() != kSphereCount)
      fail("internal dynamic-body count mismatch");
  }

  ~GeneratedWorld() {
    for (auto it = owned_actors_.rbegin(); it != owned_actors_.rend(); ++it)
      (*it)->release();
  }

  void simulate() {
    for (PxU32 step = 0; step < kSteps; ++step) {
      runtime_.scene->simulate(kFixedDt);
      if (!runtime_.scene->fetchResults(true))
        fail("PxScene::fetchResults failed at step " + std::to_string(step));
      if (runtime_.error_callback.fatal_error.load(std::memory_order_relaxed))
        fail("PhysX reported a fatal error during GPU simulation");
    }
  }

  std::array<PxTransform, 2> chute_poses;
  std::vector<MascotRecord> mascots;
  std::vector<SphereRecord> spheres;

 private:
  void remember(PxRigidActor* actor) {
    if (!actor) fail("PhysX actor creation failed");
    owned_actors_.push_back(actor);
    runtime_.scene->addActor(*actor);
  }

  void add_static_box(const PxTransform& pose, const PxVec3& half_extents) {
    PxRigidStatic* actor = runtime_.physics->createRigidStatic(pose);
    if (!actor) fail("static rigid actor creation failed");
    if (!PxRigidActorExt::createExclusiveShape(
            *actor, PxBoxGeometry(half_extents), *runtime_.material)) {
      actor->release();
      fail("static box shape creation failed");
    }
    remember(actor);
  }

  PxRigidDynamic* add_dynamic(const PxTransform& pose,
                              const PxGeometry& geometry,
                              float density,
                              const PxTransform* local_pose = nullptr) {
    PxRigidDynamic* actor = runtime_.physics->createRigidDynamic(pose);
    if (!actor) fail("dynamic rigid actor creation failed");
    PxShape* shape = PxRigidActorExt::createExclusiveShape(
        *actor, geometry, *runtime_.material);
    if (!shape) {
      actor->release();
      fail("dynamic shape creation failed");
    }
    if (local_pose) shape->setLocalPose(*local_pose);
    if (!PxRigidBodyExt::updateMassAndInertia(*actor, density)) {
      actor->release();
      fail("mass/inertia computation failed");
    }
    actor->setSolverIterationCounts(8, 2);
    actor->setLinearDamping(0.08f);
    actor->setAngularDamping(0.12f);
    remember(actor);
    return actor;
  }

  void build_static_geometry() {
    PxRigidStatic* ground = PxCreatePlane(
        *runtime_.physics, PxPlane(0.0f, 1.0f, 0.0f, 0.0f),
        *runtime_.material);
    remember(ground);

    add_static_box(PxTransform(PxVec3(-7.15f, 1.0f, 0.0f)),
                   PxVec3(0.15f, 1.0f, 4.6f));
    add_static_box(PxTransform(PxVec3(7.15f, 1.0f, 0.0f)),
                   PxVec3(0.15f, 1.0f, 4.6f));
    add_static_box(PxTransform(PxVec3(0.0f, 1.0f, -4.45f)),
                   PxVec3(7.0f, 1.0f, 0.15f));
    add_static_box(PxTransform(PxVec3(0.0f, 1.0f, 4.45f)),
                   PxVec3(7.0f, 1.0f, 0.15f));

    chute_poses = {
        PxTransform(PxVec3(-4.4f, 3.4f, 0.0f),
                    PxQuat(-30.0f * kPi / 180.0f, PxVec3(0.0f, 0.0f, 1.0f))),
        PxTransform(PxVec3(4.4f, 3.4f, 0.0f),
                    PxQuat(30.0f * kPi / 180.0f, PxVec3(0.0f, 0.0f, 1.0f))),
    };
    for (const PxTransform& chute : chute_poses) {
      add_static_box(chute, PxVec3(3.5f, 0.12f, 1.35f));
      add_static_box(chute.transform(PxTransform(PxVec3(0.0f, 0.45f, -1.43f))),
                     PxVec3(3.5f, 0.35f, 0.08f));
      add_static_box(chute.transform(PxTransform(PxVec3(0.0f, 0.45f, 1.43f))),
                     PxVec3(3.5f, 0.35f, 0.08f));
    }
  }

  void build_mascots() {
    const PxTransform capsule_pose(
        PxVec3(0.0f), PxQuat(PxHalfPi, PxVec3(0.0f, 0.0f, 1.0f)));
    const char* materials[] = {
        "mascot_vermilion", "mascot_gold", "mascot_cyan", "mascot_ivory"};
    for (PxU32 side_index = 0; side_index < 2; ++side_index) {
      const float direction = side_index == 0 ? -1.0f : 1.0f;
      const PxTransform& chute = chute_poses[side_index];
      for (PxU32 row = 0; row < 6; ++row) {
        for (PxU32 lane = 0; lane < 2; ++lane) {
          const PxU32 index = side_index * 12 + row * 2 + lane;
          const PxVec3 local(direction * (2.55f - 1.00f * row),
                             0.97f + random_.symmetric(0.015f),
                             lane == 0 ? -0.52f : 0.52f);
          const PxVec3 position = chute.transform(local);
          const float yaw = random_.symmetric(15.0f) * kPi / 180.0f;
          PxRigidDynamic* actor = add_dynamic(
              PxTransform(position, PxQuat(yaw, PxVec3(0.0f, 1.0f, 0.0f))),
              PxCapsuleGeometry(kCapsuleRadius, kCapsuleHalfHeight), 2.4f,
              &capsule_pose);
          mascots.push_back({actor, materials[index % 4]});
        }
      }
    }
  }

  void build_spheres() {
    const char* materials[] = {"bead_copper", "bead_blue", "bead_silver"};
    for (PxU32 side_index = 0; side_index < 2; ++side_index) {
      const float direction = side_index == 0 ? -1.0f : 1.0f;
      const PxTransform& chute = chute_poses[side_index];
      for (PxU32 layer = 0; layer < 6; ++layer) {
        for (PxU32 along = 0; along < 4; ++along) {
          for (PxU32 across = 0; across < 4; ++across) {
            const PxU32 local_index = layer * 16 + along * 4 + across;
            const PxU32 index = side_index * 96 + local_index;
            const float radius =
                0.12f + 0.01f * static_cast<float>(random_.next() % 8U);
            const PxVec3 local(
                direction * (2.75f - 0.44f * along) +
                    random_.symmetric(0.012f),
                2.05f + 0.44f * layer + random_.symmetric(0.012f),
                -0.72f + 0.48f * across + random_.symmetric(0.012f));
            PxRigidDynamic* actor = add_dynamic(
                PxTransform(chute.transform(local)), PxSphereGeometry(radius),
                0.85f);
            spheres.push_back({actor, radius, materials[index % 3]});
          }
        }
      }
    }
  }

  PhysicsRuntime& runtime_;
  SplitMix64 random_;
  std::vector<PxRigidActor*> owned_actors_;
};

std::array<double, 3> euler_degrees(const PxQuat& input) {
  PxQuat q = input;
  q.normalize();
  const PxMat33 matrix(q);
  const float m00 = matrix.column0.x;
  const float m10 = matrix.column0.y;
  const float m20 = matrix.column0.z;
  const float m11 = matrix.column1.y;
  const float m21 = matrix.column1.z;
  const float m12 = matrix.column2.y;
  const float m22 = matrix.column2.z;
  const float y = std::asin(std::max(-1.0f, std::min(1.0f, -m20)));
  float x = 0.0f;
  float z = 0.0f;
  if (std::fabs(std::cos(y)) > 1.0e-6f) {
    x = std::atan2(m21, m22);
    z = std::atan2(m10, m00);
  } else {
    x = std::atan2(-m12, m11);
  }
  const double to_degrees = 180.0 / static_cast<double>(kPi);
  return {rounded(x * to_degrees), rounded(y * to_degrees),
          rounded(z * to_degrees)};
}

json rectangle_object(const char* name,
                      const PxVec3& p1,
                      const PxVec3& p2,
                      const PxVec3& p3,
                      const char* material) {
  return {{"name", name},
          {"type", "rectangle"},
          {"p1", vector_json(p1)},
          {"p2", vector_json(p2)},
          {"p3", vector_json(p3)},
          {"material", material}};
}

json chute_surface(const char* name,
                   const PxTransform& pose,
                   const char* material) {
  return rectangle_object(name,
                          pose.transform(PxVec3(-3.5f, 0.12f, 1.35f)),
                          pose.transform(PxVec3(-3.5f, 0.12f, -1.35f)),
                          pose.transform(PxVec3(3.5f, 0.12f, -1.35f)),
                          material);
}

json build_scene(const GeneratedWorld& world, std::uint64_t seed) {
  json objects = json::array();
  objects.push_back(rectangle_object(
      "pool_floor", PxVec3(-8.0f, 0.0f, 5.0f),
      PxVec3(-8.0f, 0.0f, -5.0f), PxVec3(8.0f, 0.0f, -5.0f), "floor"));
  objects.push_back(rectangle_object(
      "pool_back", PxVec3(-8.0f, 0.0f, -4.4f),
      PxVec3(-8.0f, 5.5f, -4.4f), PxVec3(8.0f, 5.5f, -4.4f), "wall"));
  objects.push_back(chute_surface(
      "left_chute", world.chute_poses[0], "chute_hot"));
  objects.push_back(chute_surface(
      "right_chute", world.chute_poses[1], "chute_cool"));

  for (PxU32 index = 0; index < world.mascots.size(); ++index) {
    const MascotRecord& record = world.mascots[index];
    const PxTransform pose = record.actor->getGlobalPose();
    const PxVec3 translate =
        pose.p + pose.q.rotate(PxVec3(0.0f, -kMascotScale, 0.0f));
    const auto rotation = euler_degrees(pose.q);
    char name[32];
    std::snprintf(name, sizeof(name), "mascot_%02u", index);
    objects.push_back(
        {{"name", name},
         {"type", "mesh"},
         {"mesh", "mascot"},
         {"transform",
          {{"translate", vector_json(translate)},
           {"rotate_degrees",
            json::array({rotation[0], rotation[1], rotation[2]})},
           {"scale", json::array({0.7, 0.7, 0.7})}}},
         {"material", record.material}});
  }
  for (PxU32 index = 0; index < world.spheres.size(); ++index) {
    const SphereRecord& record = world.spheres[index];
    char name[32];
    std::snprintf(name, sizeof(name), "bead_%03u", index);
    objects.push_back({{"name", name},
                       {"type", "sphere"},
                       {"center", vector_json(record.actor->getGlobalPose().p)},
                       {"radius", rounded(record.radius)},
                       {"material", record.material}});
  }

  json scene;
  scene["schema_version"] = 2;
  scene["camera"] = {{"look_from", {0.0, 8.0, 17.0}},
                     {"look_at", {0.0, 1.2, 0.0}},
                     {"up", {0.0, 1.0, 0.0}},
                     {"vfov", 36.0},
                     {"aperture", 0.035},
                     {"focus_distance", 18.3}};
  scene["background"] = {{"type", "sky"},
                         {"bottom", {0.025, 0.04, 0.07}},
                         {"top", {0.002, 0.006, 0.015}},
                         {"sun_direction", {-0.45, 0.74, -0.5}},
                         {"sun_color", {2.8, 2.1, 1.3}},
                         {"sun_cos_angle", 0.996},
                         {"exposure", 0.0}};
  scene["render"] = {{"width", 1920},
                     {"height", 1080},
                     {"spp", 512},
                     {"max_depth", 12},
                     {"seed", seed},
                     {"denoise", true}};
  scene["textures"] = json::array();
  scene["materials"] = json::array(
      {{{"name", "floor"}, {"type", "lambertian"},
        {"base_color", {0.1, 0.13, 0.17}}},
       {{"name", "wall"}, {"type", "lambertian"},
        {"base_color", {0.12, 0.15, 0.22}}},
       {{"name", "chute_hot"}, {"type", "lambertian"},
        {"base_color", {0.62, 0.18, 0.035}}},
       {{"name", "chute_cool"}, {"type", "lambertian"},
        {"base_color", {0.035, 0.25, 0.48}}},
       {{"name", "mascot_vermilion"}, {"type", "lambertian"},
        {"base_color", {0.82, 0.1, 0.045}}},
       {{"name", "mascot_gold"}, {"type", "metal"},
        {"base_color", {0.88, 0.5, 0.09}}, {"roughness", 0.24}},
       {{"name", "mascot_cyan"}, {"type", "lambertian"},
        {"base_color", {0.035, 0.42, 0.62}}},
       {{"name", "mascot_ivory"}, {"type", "lambertian"},
        {"base_color", {0.86, 0.84, 0.74}}},
       {{"name", "bead_copper"}, {"type", "metal"},
        {"base_color", {0.72, 0.28, 0.08}}, {"roughness", 0.18}},
       {{"name", "bead_blue"}, {"type", "metal"},
        {"base_color", {0.04, 0.22, 0.55}}, {"roughness", 0.16}},
       {{"name", "bead_silver"}, {"type", "metal"},
        {"base_color", {0.72, 0.76, 0.8}}, {"roughness", 0.12}}});
  scene["meshes"] = json::array(
      {{{"name", "mascot"},
        {"path", "../../assets/examples/models/capsule-mascot.obj"}}});
  scene["objects"] = std::move(objects);
  scene["lights"] = json::array(
      {{{"name", "foundry_key"}, {"type", "rectangle"},
        {"position", {-5.0, 9.0, 3.0}}, {"edge_u", {0.0, 0.0, -5.5}},
        {"edge_v", {10.0, 0.0, 0.0}}, {"emission", {14.0, 10.0, 6.0}}},
       {{"name", "foundry_fill"}, {"type", "disk"},
        {"position", {7.0, 5.5, 7.5}}, {"normal", {-0.6, -0.35, -0.72}},
        {"radius", 2.0}, {"emission", {3.0, 6.0, 12.0}}},
       {{"name", "foundry_rim"}, {"type", "sphere"},
        {"position", {-6.0, 4.2, -2.5}}, {"radius", 0.55},
        {"emission", {8.0, 2.4, 0.8}}}});
  return scene;
}

PxU32 count_toppled(const GeneratedWorld& world) {
  PxU32 count = 0;
  const float threshold = std::cos(15.0f * kPi / 180.0f);
  for (const MascotRecord& record : world.mascots)
    if (record.actor->getGlobalPose().q.rotate(PxVec3(0.0f, 1.0f, 0.0f)).y <
        threshold)
      ++count;
  return count;
}

json build_metadata(const PhysicsRuntime& runtime,
                    const GeneratedWorld& world,
                    const Arguments& args) {
  PxU32 sleeping = 0;
  for (const MascotRecord& record : world.mascots)
    if (record.actor->isSleeping()) ++sleeping;
  for (const SphereRecord& record : world.spheres)
    if (record.actor->isSleeping()) ++sleeping;
  return {{"schema_version", 1},
          {"generator", kGenerator},
          {"backend",
           {{"name", "NVIDIA PhysX"},
            {"mode", "gpu"},
            {"physx_version", kPhysxVersion},
            {"physx_commit", kPhysxCommit},
            {"device_ordinal", args.device},
            {"device_name", runtime.device_name},
            {"cuda_context_valid", true},
            {"cpu_fallback", false}}},
          {"simulation",
           {{"seed", args.seed},
            {"fixed_dt", rounded(kFixedDt)},
            {"fixed_dt_numerator", 1},
            {"fixed_dt_denominator", 120},
            {"steps", kSteps},
            {"gravity", {0.0, -9.81, 0.0}},
            {"broad_phase", "gpu"},
            {"solver", "tgs"},
            {"flags",
             {{"gpu_dynamics", true},
              {"pcm", true},
              {"stabilization", true},
              {"enhanced_determinism", false}}},
            {"determinism_limitation",
             "enhanced_determinism_unsupported_on_gpu"}}},
          {"geometry",
           {{"mascots", kMascotCount},
            {"spheres", kSphereCount},
            {"mascot_scale", rounded(kMascotScale)},
            {"capsule_radius", rounded(kCapsuleRadius)},
            {"capsule_half_height", rounded(kCapsuleHalfHeight)}}},
          {"contract",
           {{"dynamic_center_bounds",
             {{"min", {-8.0, -0.1, -5.0}}, {"max", {8.0, 9.0, 5.0}}}}}},
          {"results",
           {{"toppled_mascots", count_toppled(world)},
            {"minimum_toppled_mascots", kMinimumToppled},
            {"sleeping_dynamic_actors", sleeping}}}};
}

void write_indent(std::ostream& output, int depth) {
  for (int index = 0; index < depth * 2; ++index) output.put(' ');
}

void write_json(std::ostream& output, const json& value, int depth = 0) {
  if (value.is_object()) {
    if (value.empty()) {
      output << "{}";
      return;
    }
    output << "{\n";
    std::size_t index = 0;
    for (const auto& item : value.items()) {
      write_indent(output, depth + 1);
      output << json(item.key()).dump() << ": ";
      write_json(output, item.value(), depth + 1);
      output << (++index == value.size() ? '\n' : ',');
      if (index != value.size()) output << '\n';
    }
    write_indent(output, depth);
    output << '}';
    return;
  }
  if (value.is_array()) {
    if (value.empty()) {
      output << "[]";
      return;
    }
    output << "[\n";
    for (std::size_t index = 0; index < value.size(); ++index) {
      write_indent(output, depth + 1);
      write_json(output, value[index], depth + 1);
      output << (index + 1 == value.size() ? '\n' : ',');
      if (index + 1 != value.size()) output << '\n';
    }
    write_indent(output, depth);
    output << ']';
    return;
  }
  if (value.is_string()) {
    output << value.dump();
    return;
  }
  if (value.is_boolean()) {
    output << (value.get<bool>() ? "true" : "false");
    return;
  }
  if (value.is_null()) {
    output << "null";
    return;
  }
  if (value.is_number_unsigned()) {
    output << value.get<std::uint64_t>();
    return;
  }
  if (value.is_number_integer()) {
    output << value.get<std::int64_t>();
    return;
  }
  if (value.is_number_float()) {
    std::ostringstream token;
    token.imbue(std::locale::classic());
    token << std::fixed << std::setprecision(6)
          << rounded(value.get<double>());
    std::string number = token.str();
    while (!number.empty() && number.back() == '0') number.pop_back();
    if (!number.empty() && number.back() == '.') number.pop_back();
    if (number == "-0" || number.empty()) number = "0";
    output << number;
    return;
  }
  fail("unsupported JSON value during serialization");
}

void atomic_write(const std::filesystem::path& path, const json& document) {
  if (!path.parent_path().empty())
    std::filesystem::create_directories(path.parent_path());
  const std::filesystem::path temporary =
      path.parent_path() /
      ("." + path.filename().string() + ".tmp-" + std::to_string(getpid()));
  try {
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output) fail("cannot create temporary output: " + temporary.string());
    write_json(output, document);
    output << '\n';
    output.flush();
    if (!output) fail("cannot write temporary output: " + temporary.string());
    output.close();
    std::filesystem::rename(temporary, path);
  } catch (...) {
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    throw;
  }
}

void run_verifier(const std::filesystem::path& checker,
                  const std::filesystem::path& scene,
                  const std::filesystem::path& metadata) {
  if (checker.empty()) return;
  const pid_t child = fork();
  if (child < 0) fail("fork failed while starting scene verifier");
  if (child == 0) {
    execlp("python3", "python3", checker.c_str(), scene.c_str(),
           metadata.c_str(), static_cast<char*>(nullptr));
    _exit(127);
  }
  int status = 0;
  if (waitpid(child, &status, 0) != child)
    fail("waitpid failed while running scene verifier");
  if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
    fail("scene verifier rejected generated output");
}

}  // namespace

int main(int argc, char** argv) {
  try {
    static_assert(PX_PHYSICS_VERSION_MAJOR == 5 &&
                      PX_PHYSICS_VERSION_MINOR == 8 &&
                      PX_PHYSICS_VERSION_BUGFIX == 0,
                  "Kinetic Foundry requires PhysX 5.8.0");
    const Arguments args = parse_arguments(argc, argv);
    if (args.seed >
        static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
      fail("--seed exceeds the renderer's signed 64-bit JSON range");
    PhysicsRuntime runtime(args.device);
    GeneratedWorld world(runtime, args.seed);
    world.simulate();
    const json scene = build_scene(world, args.seed);
    const json metadata = build_metadata(runtime, world, args);
    atomic_write(args.output, scene);
    atomic_write(args.metadata, metadata);
    run_verifier(args.verify, args.output, args.metadata);
    std::cout << "generated Kinetic Foundry with " << kMascotCount
              << " mascot capsules and " << kSphereCount
              << " spheres on PhysX GPU device " << args.device << " ("
              << runtime.device_name << ")\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 2;
  }
}
