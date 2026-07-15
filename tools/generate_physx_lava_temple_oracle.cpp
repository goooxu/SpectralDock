#include <PxConfig.h>
#include <PxPhysicsAPI.h>
#include <cudamanager/PxCudaContextManager.h>
#include <gpu/PxGpu.h>

#include <cuda_runtime_api.h>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <locale>
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

constexpr const char* kGenerator =
    "spectraldock-physx-lava-temple-oracle/1.0";
constexpr const char* kPhysxVersion = "5.8.0";
constexpr const char* kPhysxCommit =
    "fc1018a3745664a1db2b95ce03fb5e91eb585f2e";
constexpr std::uint64_t kDefaultSeed = 909ULL;
constexpr PxU32 kSteps = 24;
constexpr float kFixedDt = 1.0f / 120.0f;
constexpr float kPi = 3.14159265358979323846f;
constexpr PxU32 kShellPlateCount = 24;
constexpr PxU32 kVisorPanelCount = 2;
constexpr PxU32 kEyeCount = 2;
constexpr PxU32 kLimbCount = 4;
constexpr PxU32 kAntennaPartCount = 3;
constexpr PxU32 kGearCount = 6;
constexpr PxU32 kMechanicalPartCount = 29;
constexpr PxU32 kRoofStoneCount = 12;
constexpr PxU32 kSparkCount = 48;
constexpr PxU32 kDynamicActorCount =
    kShellPlateCount + kVisorPanelCount + kEyeCount + kLimbCount +
    kAntennaPartCount + kGearCount + kMechanicalPartCount +
    kRoofStoneCount + kSparkCount;
constexpr PxU32 kMinimumMovingActors = 120;
constexpr float kMinimumRadialDisplacement = 0.08f;
const PxVec3 kExplosionCenter(0.0f, 5.25f, -1.55f);
const PxVec3 kGodrayOrigin(-4.10f, 10.25f, 3.65f);
const PxVec3 kGodrayAxisRaw(0.50f, -0.61f, -0.63f);

static_assert(kDynamicActorCount == 130,
              "the cover-scene actor contract must remain stable");

struct Arguments {
  std::filesystem::path output =
      "scenes/generated/lava-temple-oracle.json";
  std::filesystem::path metadata =
      "scenes/generated/lava-temple-oracle.physics.json";
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
          << "Usage: spectraldock_physx_lava_temple_oracle [options]\n"
          << "  --output PATH    baked renderer scene JSON\n"
          << "  --metadata PATH  PhysX GPU manifest JSON\n"
          << "  --device N       CUDA device ordinal (default 0)\n"
          << "  --seed N         initial-layout seed (default 909)\n"
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

json quaternion_json(const PxQuat& input) {
  PxQuat value = input;
  value.normalize();
  return json::array({rounded(value.x), rounded(value.y), rounded(value.z),
                      rounded(value.w)});
}

std::string indexed_name(const char* prefix, PxU32 index) {
  char buffer[64];
  std::snprintf(buffer, sizeof(buffer), "%s_%02u", prefix, index);
  return buffer;
}

PxVec3 safe_unit(const PxVec3& value, const PxVec3& fallback) {
  const float length_squared = value.magnitudeSquared();
  return length_squared > 1.0e-12f ? value * (1.0f / std::sqrt(length_squared))
                                  : fallback;
}

struct SplitMix64 {
  explicit SplitMix64(std::uint64_t initial) : state(initial) {}

  std::uint64_t next() {
    std::uint64_t z = (state += 0x9e3779b97f4a7c15ULL);
    z = (z ^ (z >> 30U)) * 0xbf58476d1ce4e5b9ULL;
    z = (z ^ (z >> 27U)) * 0x94d049bb133111ebULL;
    return z ^ (z >> 31U);
  }

  float unit() {
    return static_cast<float>(static_cast<double>(next() >> 11U) /
                              static_cast<double>(std::uint64_t{1} << 53U));
  }

  float symmetric(float magnitude) {
    return (2.0f * unit() - 1.0f) * magnitude;
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
    if (device < 0 || device >= count)
      fail("CUDA device ordinal is unavailable");
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
    scene_desc.flags &= ~PxSceneFlag::eENABLE_ENHANCED_DETERMINISM;
    if (!scene_desc.isValid()) fail("GPU PxSceneDesc is invalid");
    scene = physics->createScene(scene_desc);
    if (!scene)
      fail("GPU PhysX scene creation failed; CPU fallback is forbidden");

    const PxSceneFlags flags = scene->getFlags();
    if (!flags.isSet(PxSceneFlag::eENABLE_GPU_DYNAMICS) ||
        !flags.isSet(PxSceneFlag::eENABLE_PCM) ||
        !flags.isSet(PxSceneFlag::eENABLE_STABILIZATION) ||
        flags.isSet(PxSceneFlag::eENABLE_ENHANCED_DETERMINISM) ||
        scene->getBroadPhaseType() != PxBroadPhaseType::eGPU ||
        !cuda_manager->contextIsValid())
      fail("created scene does not satisfy the PhysX GPU-only contract");

    stone_material = physics->createMaterial(0.72f, 0.61f, 0.08f);
    metal_material = physics->createMaterial(0.42f, 0.35f, 0.16f);
    spark_material = physics->createMaterial(0.18f, 0.12f, 0.04f);
    if (!stone_material || !metal_material || !spark_material)
      fail("PxMaterial creation failed");
  }

  ~PhysicsRuntime() {
    if (scene) scene->release();
    if (spark_material) spark_material->release();
    if (metal_material) metal_material->release();
    if (stone_material) stone_material->release();
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
  PxMaterial* stone_material = nullptr;
  PxMaterial* metal_material = nullptr;
  PxMaterial* spark_material = nullptr;
  bool extensions_initialized = false;
  std::string device_name;
};

struct BodyRecord {
  PxRigidDynamic* actor = nullptr;
  std::string name;
  std::string category;
  PxVec3 initial_position{};
};

struct PlateRecord {
  PxRigidDynamic* actor = nullptr;
  PxVec3 half_extents{};
  std::string material;
};

struct SphereRecord {
  PxRigidDynamic* actor = nullptr;
  float radius = 0.0f;
  std::string material;
};

struct CapsuleRecord {
  PxRigidDynamic* actor = nullptr;
  float radius = 0.0f;
  float half_height = 0.0f;
  std::string material;
};

struct GearRecord {
  PxRigidDynamic* actor = nullptr;
  float radius = 0.0f;
  float half_thickness = 0.0f;
  std::string material;
};

struct MechanicalRecord {
  PxRigidDynamic* actor = nullptr;
  bool rod = false;
  PxVec3 half_extents{};
  float radius = 0.0f;
  float half_height = 0.0f;
  std::string material;
};

class GeneratedWorld {
 public:
  GeneratedWorld(PhysicsRuntime& runtime, std::uint64_t seed)
      : runtime_(runtime), random_(seed) {
    build_collision_geometry();
    build_shell_plates();
    build_face_and_limbs();
    build_gears();
    build_mechanical_parts();
    build_roof_stones();
    build_sparks();
    if (bodies.size() != kDynamicActorCount)
      fail("internal dynamic actor count mismatch");
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

  std::vector<BodyRecord> bodies;
  std::vector<PlateRecord> shell_plates;
  std::vector<PlateRecord> visor_panels;
  std::vector<SphereRecord> eyes;
  std::vector<CapsuleRecord> limbs;
  std::vector<CapsuleRecord> antenna_rods;
  std::vector<SphereRecord> antenna_tips;
  std::vector<GearRecord> gears;
  std::vector<MechanicalRecord> mechanical_parts;
  std::vector<PlateRecord> roof_stones;
  std::vector<SphereRecord> sparks;

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
            *actor, PxBoxGeometry(half_extents), *runtime_.stone_material)) {
      actor->release();
      fail("static box shape creation failed");
    }
    remember(actor);
  }

  void finish_dynamic(PxRigidDynamic* actor,
                      float density,
                      const std::string& name,
                      const char* category,
                      const PxVec3& initial_position) {
    if (!PxRigidBodyExt::updateMassAndInertia(*actor, density)) {
      actor->release();
      fail("mass/inertia computation failed");
    }
    actor->setSolverIterationCounts(8, 2);
    actor->setLinearDamping(0.025f);
    actor->setAngularDamping(0.045f);
    actor->setSleepThreshold(0.001f);
    remember(actor);
    bodies.push_back({actor, name, category, initial_position});
  }

  PxRigidDynamic* add_dynamic_box(const PxTransform& pose,
                                  const PxVec3& half_extents,
                                  float density,
                                  const std::string& name,
                                  const char* category,
                                  PxMaterial& material) {
    PxRigidDynamic* actor = runtime_.physics->createRigidDynamic(pose);
    if (!actor) fail("dynamic rigid actor creation failed");
    if (!PxRigidActorExt::createExclusiveShape(
            *actor, PxBoxGeometry(half_extents), material)) {
      actor->release();
      fail("dynamic box shape creation failed");
    }
    finish_dynamic(actor, density, name, category, pose.p);
    return actor;
  }

  PxRigidDynamic* add_dynamic_sphere(const PxTransform& pose,
                                     float radius,
                                     float density,
                                     const std::string& name,
                                     const char* category,
                                     PxMaterial& material) {
    PxRigidDynamic* actor = runtime_.physics->createRigidDynamic(pose);
    if (!actor) fail("dynamic rigid actor creation failed");
    if (!PxRigidActorExt::createExclusiveShape(
            *actor, PxSphereGeometry(radius), material)) {
      actor->release();
      fail("dynamic sphere shape creation failed");
    }
    finish_dynamic(actor, density, name, category, pose.p);
    return actor;
  }

  PxRigidDynamic* add_dynamic_capsule(const PxTransform& pose,
                                      float radius,
                                      float half_height,
                                      float density,
                                      const std::string& name,
                                      const char* category,
                                      PxMaterial& material) {
    PxRigidDynamic* actor = runtime_.physics->createRigidDynamic(pose);
    if (!actor) fail("dynamic rigid actor creation failed");
    if (!PxRigidActorExt::createExclusiveShape(
            *actor, PxCapsuleGeometry(radius, half_height), material)) {
      actor->release();
      fail("dynamic capsule shape creation failed");
    }
    finish_dynamic(actor, density, name, category, pose.p);
    return actor;
  }

  void apply_explosion(PxRigidDynamic& actor,
                       const PxVec3& initial_position,
                       float speed,
                       float upward_bias) {
    PxVec3 radial = initial_position - kExplosionCenter;
    radial.y *= 0.38f;
    radial += PxVec3(random_.symmetric(0.16f), upward_bias,
                     random_.symmetric(0.16f));
    radial = safe_unit(radial, PxVec3(0.0f, 1.0f, 0.0f));
    const PxVec3 tangent =
        safe_unit(PxVec3(-radial.z, 0.35f, radial.x), PxVec3(1.0f, 0.0f, 0.0f));
    const PxVec3 application = initial_position +
                               tangent * random_.symmetric(0.22f) +
                               PxVec3(0.0f, random_.symmetric(0.12f), 0.0f);
    const PxVec3 impulse = radial * actor.getMass() *
                           (speed + random_.symmetric(0.8f));
    PxRigidBodyExt::addForceAtPos(actor, impulse, application,
                                  PxForceMode::eIMPULSE, true);
  }

  void build_collision_geometry() {
    PxRigidStatic* ground = PxCreatePlane(
        *runtime_.physics, PxPlane(0.0f, 1.0f, 0.0f, 0.0f),
        *runtime_.stone_material);
    remember(ground);
    add_static_box(PxTransform(PxVec3(0.0f, 0.6f, -1.55f)),
                   PxVec3(1.75f, 0.6f, 1.55f));
    add_static_box(PxTransform(PxVec3(-9.5f, 5.0f, -3.0f)),
                   PxVec3(0.45f, 5.0f, 7.0f));
    add_static_box(PxTransform(PxVec3(9.5f, 5.0f, -3.0f)),
                   PxVec3(0.45f, 5.0f, 7.0f));
    add_static_box(PxTransform(PxVec3(0.0f, 5.0f, -9.5f)),
                   PxVec3(9.5f, 5.0f, 0.45f));
  }

  void build_shell_plates() {
    const float row_y[] = {-1.12f, -0.38f, 0.38f, 1.12f};
    const float row_radius[] = {1.02f, 1.35f, 1.35f, 1.02f};
    for (PxU32 row = 0; row < 4; ++row) {
      for (PxU32 segment = 0; segment < 6; ++segment) {
        const PxU32 index = row * 6 + segment;
        const float angle = (static_cast<float>(segment) + 0.18f * row) *
                            (2.0f * kPi / 6.0f);
        const PxVec3 radial(std::sin(angle), 0.0f, std::cos(angle));
        const PxVec3 position =
            kExplosionCenter + radial * row_radius[row] +
            PxVec3(0.0f, row_y[row], 0.0f);
        const PxQuat rotation(angle, PxVec3(0.0f, 1.0f, 0.0f));
        const PxVec3 half_extents(row == 0 || row == 3 ? 0.40f : 0.53f,
                                  0.33f, 0.09f);
        PxRigidDynamic* actor = add_dynamic_box(
            PxTransform(position, rotation), half_extents, 2.7f,
            indexed_name("shell_plate", index), "shell_plate",
            *runtime_.metal_material);
        apply_explosion(*actor, position, 2.66f + 0.056f * index, 0.22f);
        shell_plates.push_back(
            {actor, half_extents, "shell_dark_metal"});
      }
    }
  }

  void build_face_and_limbs() {
    for (PxU32 index = 0; index < kVisorPanelCount; ++index) {
      const PxVec3 position = kExplosionCenter +
                              PxVec3(index == 0 ? -0.48f : 0.48f, 0.42f,
                                     1.42f);
      const PxQuat rotation((index == 0 ? -0.12f : 0.12f),
                            PxVec3(0.0f, 1.0f, 0.0f));
      const PxVec3 half_extents(0.42f, 0.48f, 0.075f);
      PxRigidDynamic* actor = add_dynamic_box(
          PxTransform(position, rotation), half_extents, 3.1f,
          indexed_name("visor_panel", index), "visor_panel",
          *runtime_.metal_material);
      apply_explosion(*actor, position, 2.76f, 0.20f);
      visor_panels.push_back({actor, half_extents, "visor_metal"});
    }

    for (PxU32 index = 0; index < kEyeCount; ++index) {
      const PxVec3 position = kExplosionCenter +
                              PxVec3(index == 0 ? -0.42f : 0.42f, 0.48f,
                                     1.52f);
      PxRigidDynamic* actor = add_dynamic_sphere(
          PxTransform(position), 0.16f, 1.4f, indexed_name("eye", index),
          "eye", *runtime_.metal_material);
      apply_explosion(*actor, position, 2.805f, 0.28f);
      eyes.push_back({actor, 0.16f, "eye_emitter"});
    }

    const std::array<PxVec3, 4> limb_positions = {
        kExplosionCenter + PxVec3(-1.55f, 0.38f, 0.0f),
        kExplosionCenter + PxVec3(1.55f, 0.38f, 0.0f),
        kExplosionCenter + PxVec3(-0.68f, -1.72f, 0.0f),
        kExplosionCenter + PxVec3(0.68f, -1.72f, 0.0f)};
    for (PxU32 index = 0; index < kLimbCount; ++index) {
      const bool arm = index < 2;
      const PxQuat rotation(arm ? 0.0f : kPi * 0.5f,
                            PxVec3(0.0f, 0.0f, 1.0f));
      PxRigidDynamic* actor = add_dynamic_capsule(
          PxTransform(limb_positions[index], rotation), arm ? 0.17f : 0.20f,
          arm ? 0.48f : 0.43f, 2.1f, indexed_name("limb", index), "limb",
          *runtime_.metal_material);
      apply_explosion(*actor, limb_positions[index], 2.94f, 0.30f);
      limbs.push_back({actor, arm ? 0.17f : 0.20f, arm ? 0.48f : 0.43f,
                       "limb_metal"});
    }

    for (PxU32 index = 0; index < 2; ++index) {
      const PxVec3 position = kExplosionCenter +
                              PxVec3(index == 0 ? -0.17f : 0.17f, 1.72f,
                                     0.04f);
      const PxQuat rotation(kPi * 0.5f + (index == 0 ? -0.16f : 0.16f),
                            PxVec3(0.0f, 0.0f, 1.0f));
      PxRigidDynamic* actor = add_dynamic_capsule(
          PxTransform(position, rotation), 0.075f, 0.34f, 1.8f,
          indexed_name("antenna_part", index), "antenna_part",
          *runtime_.metal_material);
      apply_explosion(*actor, position, 3.5f, 0.45f);
      antenna_rods.push_back({actor, 0.075f, 0.34f, "mechanism_copper"});
    }
    const PxVec3 tip_position =
        kExplosionCenter + PxVec3(0.0f, 2.18f, 0.04f);
    PxRigidDynamic* tip = add_dynamic_sphere(
        PxTransform(tip_position), 0.19f, 1.3f,
        indexed_name("antenna_part", 2), "antenna_part",
        *runtime_.metal_material);
    apply_explosion(*tip, tip_position, 3.78f, 0.55f);
    antenna_tips.push_back({tip, 0.19f, "mechanism_gold"});
  }

  void build_gears() {
    const std::array<PxVec3, kGearCount> offsets = {
        PxVec3(-0.55f, 0.42f, 0.28f), PxVec3(0.48f, 0.58f, 0.18f),
        PxVec3(-0.30f, -0.30f, 0.42f), PxVec3(0.58f, -0.42f, 0.12f),
        PxVec3(-0.02f, 0.03f, -0.30f), PxVec3(0.12f, 0.95f, -0.22f)};
    for (PxU32 index = 0; index < kGearCount; ++index) {
      const PxVec3 position = kExplosionCenter + offsets[index];
      const PxQuat rotation(random_.symmetric(0.36f),
                            safe_unit(PxVec3(random_.symmetric(1.0f),
                                             random_.symmetric(1.0f), 1.0f),
                                      PxVec3(0.0f, 0.0f, 1.0f)));
      PxRigidDynamic* actor =
          runtime_.physics->createRigidDynamic(PxTransform(position, rotation));
      if (!actor) fail("compound gear actor creation failed");
      if (!PxRigidActorExt::createExclusiveShape(
              *actor, PxSphereGeometry(0.35f), *runtime_.metal_material)) {
        actor->release();
        fail("compound gear hub shape creation failed");
      }
      for (PxU32 tooth = 0; tooth < 6; ++tooth) {
        const float angle = 2.0f * kPi * static_cast<float>(tooth) / 6.0f;
        PxShape* shape = PxRigidActorExt::createExclusiveShape(
            *actor, PxBoxGeometry(0.18f, 0.11f, 0.12f),
            *runtime_.metal_material);
        if (!shape) {
          actor->release();
          fail("compound gear tooth shape creation failed");
        }
        shape->setLocalPose(PxTransform(
            PxVec3(0.52f * std::cos(angle), 0.52f * std::sin(angle), 0.0f),
            PxQuat(angle, PxVec3(0.0f, 0.0f, 1.0f))));
      }
      finish_dynamic(actor, 4.2f, indexed_name("compound_gear", index),
                     "compound_gear", position);
      apply_explosion(*actor, position, 2.66f + index * 0.154f, 0.24f);
      gears.push_back(
          {actor, 0.55f, 0.12f,
           index % 2 == 0 ? "mechanism_gold" : "mechanism_copper"});
    }
  }

  void build_mechanical_parts() {
    for (PxU32 index = 0; index < kMechanicalPartCount; ++index) {
      const float angle = 2.0f * kPi * static_cast<float>(index) /
                              static_cast<float>(kMechanicalPartCount) +
                          random_.symmetric(0.12f);
      const float radius = 0.24f + 0.66f * random_.unit();
      const PxVec3 position =
          kExplosionCenter +
          PxVec3(radius * std::cos(angle), random_.symmetric(0.95f),
                 radius * std::sin(angle));
      const PxQuat rotation(random_.symmetric(kPi),
                            safe_unit(PxVec3(random_.symmetric(1.0f),
                                             random_.symmetric(1.0f),
                                             random_.symmetric(1.0f)),
                                      PxVec3(1.0f, 0.0f, 0.0f)));
      const std::string material =
          index % 3 == 0 ? "mechanism_gold" : "mechanism_copper";
      if (index < 17) {
        const float part_radius = 0.055f + 0.018f * (index % 3);
        const float half_height = 0.24f + 0.055f * (index % 4);
        PxRigidDynamic* actor = add_dynamic_capsule(
            PxTransform(position, rotation), part_radius, half_height, 3.4f,
            indexed_name("mechanical_part", index), "mechanical_part",
            *runtime_.metal_material);
        apply_explosion(*actor, position, 2.94f + 0.056f * index, 0.18f);
        mechanical_parts.push_back({actor, true, PxVec3(), part_radius,
                                    half_height, material});
      } else {
        const PxVec3 half_extents(0.16f + 0.025f * (index % 4),
                                  0.11f + 0.018f * (index % 3), 0.045f);
        PxRigidDynamic* actor = add_dynamic_box(
            PxTransform(position, rotation), half_extents, 3.6f,
            indexed_name("mechanical_part", index), "mechanical_part",
            *runtime_.metal_material);
        apply_explosion(*actor, position, 3.08f + 0.049f * index, 0.20f);
        mechanical_parts.push_back(
            {actor, false, half_extents, 0.0f, 0.0f, material});
      }
    }
  }

  void build_roof_stones() {
    for (PxU32 index = 0; index < kRoofStoneCount; ++index) {
      const float column = static_cast<float>(index % 4);
      const float row = static_cast<float>(index / 4);
      const PxVec3 position(-3.6f + 1.22f * column + random_.symmetric(0.12f),
                            10.25f + 0.52f * row +
                                random_.symmetric(0.12f),
                            -2.4f + 0.72f * row +
                                random_.symmetric(0.18f));
      const PxQuat rotation(random_.symmetric(0.32f),
                            safe_unit(PxVec3(random_.symmetric(1.0f), 1.0f,
                                             random_.symmetric(1.0f)),
                                      PxVec3(0.0f, 1.0f, 0.0f)));
      const PxVec3 half_extents(0.42f + 0.08f * (index % 3),
                                0.24f + 0.04f * (index % 2),
                                0.34f + 0.06f * ((index + 1) % 3));
      PxRigidDynamic* actor = add_dynamic_box(
          PxTransform(position, rotation), half_extents, 2.8f,
          indexed_name("roof_stone", index), "roof_stone",
          *runtime_.stone_material);
      actor->setLinearVelocity(PxVec3(0.25f * std::sin(index),
                                      -2.0f - 0.12f * index,
                                      0.18f * std::cos(index)));
      actor->setAngularVelocity(
          PxVec3(random_.symmetric(2.1f), random_.symmetric(1.4f),
                 random_.symmetric(2.1f)));
      roof_stones.push_back({actor, half_extents, "roof_stone"});
    }
  }

  void build_sparks() {
    for (PxU32 index = 0; index < kSparkCount; ++index) {
      const float angle = 2.0f * kPi * random_.unit();
      const float radial = 0.18f + 0.72f * random_.unit();
      const PxVec3 position(
          radial * std::cos(angle), 1.72f + 1.15f * random_.unit(),
          -1.55f + radial * std::sin(angle));
      const float radius = 0.025f + 0.020f * random_.unit();
      PxRigidDynamic* actor = add_dynamic_sphere(
          PxTransform(position), radius, 0.32f, indexed_name("spark", index),
          "spark", *runtime_.spark_material);
      actor->setLinearVelocity(
          PxVec3(1.8f * std::cos(angle) + random_.symmetric(0.8f),
                 8.0f + 5.2f * random_.unit(),
                 1.8f * std::sin(angle) + random_.symmetric(0.8f)));
      actor->setAngularVelocity(PxVec3(random_.symmetric(4.0f),
                                       random_.symmetric(4.0f),
                                       random_.symmetric(4.0f)));
      sparks.push_back({actor, radius, "spark_emitter"});
    }
  }

  PhysicsRuntime& runtime_;
  SplitMix64 random_;
  std::vector<PxRigidActor*> owned_actors_;
};

json rectangle_object(const std::string& name,
                      const PxVec3& p1,
                      const PxVec3& p2,
                      const PxVec3& p3,
                      const std::string& material) {
  return {{"name", name},
          {"type", "rectangle"},
          {"p1", vector_json(p1)},
          {"p2", vector_json(p2)},
          {"p3", vector_json(p3)},
          {"material", material}};
}

json sphere_object(const std::string& name,
                   const PxVec3& center,
                   float radius,
                   const std::string& material) {
  return {{"name", name},
          {"type", "sphere"},
          {"center", vector_json(center)},
          {"radius", rounded(radius)},
          {"material", material}};
}

json cylinder_object(const std::string& name,
                     const PxVec3& base,
                     const PxVec3& axis,
                     float height,
                     float radius,
                     const std::string& material) {
  return {{"name", name},
          {"type", "cylinder"},
          {"base", vector_json(base)},
          {"axis", vector_json(safe_unit(axis, PxVec3(0.0f, 1.0f, 0.0f)))},
          {"height", rounded(height)},
          {"radius", rounded(radius)},
          {"material", material}};
}

json disk_object(const std::string& name,
                 const PxVec3& center,
                 const PxVec3& normal,
                 float radius,
                 const std::string& material) {
  return {{"name", name},
          {"type", "disk"},
          {"center", vector_json(center)},
          {"normal",
           vector_json(safe_unit(normal, PxVec3(0.0f, 1.0f, 0.0f)))},
          {"radius", rounded(radius)},
          {"material", material}};
}

json pose_rectangle(const std::string& name,
                    const PxTransform& pose,
                    float half_x,
                    float half_y,
                    float local_z,
                    const std::string& material) {
  return rectangle_object(
      name, pose.transform(PxVec3(-half_x, -half_y, local_z)),
      pose.transform(PxVec3(-half_x, half_y, local_z)),
      pose.transform(PxVec3(half_x, half_y, local_z)), material);
}

void append_capsule_objects(json& objects,
                            const std::string& prefix,
                            const CapsuleRecord& record) {
  const PxTransform pose = record.actor->getGlobalPose();
  const PxVec3 axis = safe_unit(pose.q.rotate(PxVec3(1.0f, 0.0f, 0.0f)),
                                PxVec3(1.0f, 0.0f, 0.0f));
  const PxVec3 end_a = pose.p - axis * record.half_height;
  const PxVec3 end_b = pose.p + axis * record.half_height;
  objects.push_back(cylinder_object(prefix + "_shaft", end_a, axis,
                                    2.0f * record.half_height, record.radius,
                                    record.material));
  objects.push_back(sphere_object(prefix + "_cap_a", end_a, record.radius,
                                  record.material));
  objects.push_back(sphere_object(prefix + "_cap_b", end_b, record.radius,
                                  record.material));
}

void append_static_temple(json& objects) {
  objects.push_back(rectangle_object(
      "temple_floor_left", PxVec3(-9.5f, 0.0f, 6.0f),
      PxVec3(-9.5f, 0.0f, -9.5f), PxVec3(2.75f, 0.0f, -9.5f),
      "temple_floorstone"));
  objects.push_back(rectangle_object(
      "temple_floor_front_right", PxVec3(2.75f, 0.0f, 6.0f),
      PxVec3(2.75f, 0.0f, 2.15f), PxVec3(9.5f, 0.0f, 2.15f),
      "temple_wetstone"));
  objects.push_back(rectangle_object(
      "temple_floor_back_right", PxVec3(2.75f, 0.0f, -5.95f),
      PxVec3(2.75f, 0.0f, -9.5f), PxVec3(9.5f, 0.0f, -9.5f),
      "temple_wetstone"));
  objects.push_back(rectangle_object(
      "temple_back_wall", PxVec3(-9.5f, 0.0f, -9.5f),
      PxVec3(-9.5f, 10.5f, -9.5f), PxVec3(9.5f, 10.5f, -9.5f),
      "temple_blackstone"));
  objects.push_back(rectangle_object(
      "temple_left_wall", PxVec3(-9.5f, 0.0f, 6.0f),
      PxVec3(-9.5f, 10.5f, 6.0f), PxVec3(-9.5f, 10.5f, -9.5f),
      "temple_blackstone"));
  objects.push_back(rectangle_object(
      "temple_right_wall_back", PxVec3(9.5f, 0.0f, -9.5f),
      PxVec3(9.5f, 10.5f, -9.5f), PxVec3(9.5f, 10.5f, -1.0f),
      "temple_blackstone"));
  objects.push_back(rectangle_object(
      "temple_right_wall_front", PxVec3(9.5f, 0.0f, 2.8f),
      PxVec3(9.5f, 8.2f, 2.8f), PxVec3(9.5f, 8.2f, 6.0f),
      "temple_blackstone"));

  objects.push_back(rectangle_object(
      "roof_left_slab", PxVec3(-9.5f, 10.5f, 6.0f),
      PxVec3(-9.5f, 10.5f, -9.5f), PxVec3(-4.45f, 10.5f, -9.5f),
      "roof_stone"));
  objects.push_back(rectangle_object(
      "roof_back_slab", PxVec3(-4.45f, 10.5f, -9.5f),
      PxVec3(-4.45f, 10.5f, -5.2f), PxVec3(9.5f, 10.5f, -5.2f),
      "roof_stone"));
  objects.push_back(rectangle_object(
      "roof_right_slab", PxVec3(3.8f, 10.5f, -5.2f),
      PxVec3(3.8f, 10.5f, 6.0f), PxVec3(9.5f, 10.5f, 6.0f),
      "roof_stone"));
  objects.push_back(rectangle_object(
      "roof_front_fragment", PxVec3(-4.45f, 10.5f, 3.5f),
      PxVec3(-4.45f, 10.5f, 6.0f), PxVec3(3.8f, 10.5f, 6.0f),
      "roof_stone"));

  const std::array<PxVec3, 8> columns = {
      PxVec3(-8.1f, 0.0f, -7.4f), PxVec3(-8.1f, 0.0f, -2.7f),
      PxVec3(-8.1f, 0.0f, 2.2f), PxVec3(-4.4f, 0.0f, -8.3f),
      PxVec3(8.7f, 0.0f, -7.4f), PxVec3(8.7f, 0.0f, -2.7f),
      PxVec3(9.30f, 0.0f, -1.35f), PxVec3(4.3f, 0.0f, -8.3f)};
  for (PxU32 index = 0; index < columns.size(); ++index) {
    objects.push_back(cylinder_object(
        indexed_name("column_shaft", index), columns[index],
        PxVec3(0.0f, 1.0f, 0.0f), 9.8f, 0.64f,
        "temple_carved_stone"));
    objects.push_back(cylinder_object(
        indexed_name("column_base", index), columns[index],
        PxVec3(0.0f, 1.0f, 0.0f), 0.34f, 0.86f,
        "temple_wetstone"));
    objects.push_back(cylinder_object(
        indexed_name("column_band", index),
        columns[index] + PxVec3(0.0f, 4.35f, 0.0f),
        PxVec3(0.0f, 1.0f, 0.0f), 0.16f, 0.70f,
        "temple_wetstone"));
    objects.push_back(cylinder_object(
        indexed_name("column_capital", index),
        columns[index] + PxVec3(0.0f, 9.45f, 0.0f),
        PxVec3(0.0f, 1.0f, 0.0f), 0.35f, 0.88f, "roof_stone"));
  }

  objects.push_back(cylinder_object(
      "altar_lower", PxVec3(0.0f, 0.0f, -1.55f),
      PxVec3(0.0f, 1.0f, 0.0f), 0.65f, 1.75f, "altar_obsidian"));
  objects.push_back(cylinder_object(
      "altar_upper", PxVec3(0.0f, 0.65f, -1.55f),
      PxVec3(0.0f, 1.0f, 0.0f), 0.55f, 1.38f,
      "temple_blackstone"));
  objects.push_back(disk_object(
      "altar_bowl", PxVec3(0.0f, 1.22f, -1.55f),
      PxVec3(0.0f, 1.0f, 0.0f), 1.18f, "altar_obsidian"));
  for (PxU32 index = 0; index < 8; ++index) {
    const float angle = 2.0f * kPi * static_cast<float>(index) / 8.0f;
    const PxVec3 base(1.26f * std::cos(angle), 0.52f,
                      -1.55f + 1.26f * std::sin(angle));
    objects.push_back(cylinder_object(
        indexed_name("altar_gold_inlay", index), base,
        PxVec3(0.0f, 1.0f, 0.0f), 0.12f, 0.075f, "mechanism_gold"));
  }

  objects.push_back(rectangle_object(
      "pool_floor_shallow", PxVec3(5.0f, -0.75f, 2.0f),
      PxVec3(5.0f, -0.75f, -5.8f), PxVec3(8.45f, -0.75f, -5.8f),
      "pool_moss"));
  objects.push_back(rectangle_object(
      "pool_floor_deep", PxVec3(2.95f, -2.55f, 2.0f),
      PxVec3(2.95f, -2.55f, -5.8f), PxVec3(5.0f, -2.55f, -5.8f),
      "pool_mosaic"));
  objects.push_back(rectangle_object(
      "pool_depth_riser", PxVec3(5.0f, -2.55f, 2.0f),
      PxVec3(5.0f, -0.75f, 2.0f), PxVec3(5.0f, -0.75f, -5.8f),
      "pool_moss"));
  objects.push_back(rectangle_object(
      "pool_left_wall", PxVec3(2.95f, -2.55f, -5.8f),
      PxVec3(2.95f, 0.50f, -5.8f), PxVec3(2.95f, 0.50f, 2.0f),
      "temple_wetstone"));
  objects.push_back(rectangle_object(
      "pool_right_wall", PxVec3(8.45f, -2.55f, 2.0f),
      PxVec3(8.45f, 0.50f, 2.0f), PxVec3(8.45f, 0.50f, -5.8f),
      "temple_wetstone"));
  objects.push_back(rectangle_object(
      "pool_back_wall", PxVec3(2.95f, -2.55f, -5.8f),
      PxVec3(2.95f, 0.50f, -5.8f), PxVec3(8.45f, 0.50f, -5.8f),
      "temple_wetstone"));
  objects.push_back(rectangle_object(
      "pool_front_wall", PxVec3(2.95f, -2.55f, 2.0f),
      PxVec3(8.45f, -2.55f, 2.0f), PxVec3(8.45f, 0.50f, 2.0f),
      "temple_wetstone"));
  for (PxU32 index = 0; index < 9; ++index) {
    const float x = 5.35f + 0.90f * static_cast<float>(index % 3);
    const float z = -4.8f + 2.65f * static_cast<float>(index / 3);
    objects.push_back(rectangle_object(
        indexed_name("pool_moss_tile", index), PxVec3(x, -0.735f, z + 0.8f),
        PxVec3(x, -0.735f, z), PxVec3(x + 0.72f, -0.735f, z),
        index % 2 == 0 ? "pool_moss" : "pool_mosaic"));
  }
  objects.push_back(
      {{"name", "pool_water"},
       {"type", "water_surface"},
       {"center", {5.7, 0.22, -1.9}},
       {"size", {5.4, 7.6}},
       {"material", "oracle_water"},
       {"waves",
        {{{"direction", {1.0, 0.18}},
          {"amplitude", 0.065},
          {"wavelength", 2.7},
          {"phase_radians", 0.55}},
         {{"direction", {-0.32, 1.0}},
          {"amplitude", 0.038},
          {"wavelength", 1.55},
          {"phase_radians", 2.15}},
         {{"direction", {0.72, 1.0}},
          {"amplitude", 0.019},
          {"wavelength", 0.92},
          {"phase_radians", 4.1}}}}});

  for (PxU32 index = 0; index < 16; ++index) {
    const bool right = index >= 8;
    const PxU32 local = index % 8;
    const float x = right ? 9.38f : -9.38f;
    const float y = 2.0f + 0.68f * static_cast<float>(local % 4);
    const float z = -7.0f + 2.3f * static_cast<float>(local / 4);
    const PxVec3 base(x, y, z);
    const PxVec3 direction(0.0f, 0.58f,
                           (local % 2 == 0 ? 0.34f : -0.34f));
    objects.push_back(cylinder_object(
        indexed_name("rune_stroke", index), base, direction, 0.78f, 0.035f,
        "rune_emitter"));
  }

  const std::array<PxVec3, 12> frost_centers = {
      PxVec3(-4.02f, 10.08f, 2.92f), PxVec3(-3.38f, 9.92f, 3.18f),
      PxVec3(-2.62f, 10.14f, 3.28f), PxVec3(-1.72f, 9.96f, 3.34f),
      PxVec3(2.72f, 10.10f, 3.16f), PxVec3(3.32f, 9.91f, 2.76f),
      PxVec3(3.48f, 10.13f, 1.96f), PxVec3(-4.06f, 10.04f, -4.78f),
      PxVec3(-3.42f, 9.88f, -4.92f), PxVec3(2.56f, 10.08f, -4.96f),
      PxVec3(3.22f, 9.90f, -4.84f), PxVec3(3.48f, 10.12f, -4.18f)};
  const std::array<float, 12> frost_radii = {
      0.14f, 0.20f, 0.12f, 0.17f, 0.13f, 0.19f,
      0.11f, 0.18f, 0.12f, 0.16f, 0.11f, 0.15f};
  for (PxU32 index = 0; index < frost_centers.size(); ++index)
    objects.push_back(sphere_object(indexed_name("frost_crystal", index),
                                    frost_centers[index], frost_radii[index],
                                    "frost_ice"));

  const PxVec3 godray_axis =
      safe_unit(kGodrayAxisRaw, PxVec3(0.0f, -1.0f, 0.0f));
  const PxVec3 godray_u =
      safe_unit(PxVec3(0.63f, 0.0f, 0.50f), PxVec3(1.0f, 0.0f, 0.0f));
  const PxVec3 godray_v = safe_unit(godray_axis.cross(godray_u),
                                    PxVec3(0.0f, 0.0f, 1.0f));
  for (PxU32 index = 0; index < 30; ++index) {
    const float fraction =
        (static_cast<float>(index) + 0.5f) / 30.0f;
    const float distance = 0.70f + 13.50f * fraction;
    const float angle = 2.0f * kPi * 0.61803398875f *
                        static_cast<float>(index);
    const float jitter_radius =
        0.05f + 0.15f * static_cast<float>(index % 5) / 4.0f;
    const PxVec3 center = kGodrayOrigin + godray_axis * distance +
                          godray_u * (jitter_radius * std::cos(angle)) +
                          godray_v * (jitter_radius * std::sin(angle));
    objects.push_back(sphere_object(indexed_name("dust_mote", index), center,
                                    0.018f + 0.006f * (index % 3),
                                    "dust_gold"));
  }
}

void append_dynamic_objects(json& objects, const GeneratedWorld& world) {
  for (PxU32 index = 0; index < world.shell_plates.size(); ++index) {
    const PlateRecord& record = world.shell_plates[index];
    const PxTransform pose = record.actor->getGlobalPose();
    objects.push_back(pose_rectangle(
        indexed_name("shell_outer", index), pose, record.half_extents.x,
        record.half_extents.y, record.half_extents.z, record.material));
    objects.push_back(pose_rectangle(
        indexed_name("shell_inner", index), pose, record.half_extents.x,
        record.half_extents.y, -record.half_extents.z, "shell_inner_gold"));
  }
  for (PxU32 index = 0; index < world.visor_panels.size(); ++index) {
    const PlateRecord& record = world.visor_panels[index];
    objects.push_back(pose_rectangle(
        indexed_name("visor_panel", index), record.actor->getGlobalPose(),
        record.half_extents.x, record.half_extents.y, record.half_extents.z,
        record.material));
  }
  for (PxU32 index = 0; index < world.eyes.size(); ++index) {
    const SphereRecord& record = world.eyes[index];
    objects.push_back(sphere_object(indexed_name("eye", index),
                                    record.actor->getGlobalPose().p,
                                    record.radius, record.material));
  }
  for (PxU32 index = 0; index < world.limbs.size(); ++index)
    append_capsule_objects(objects, indexed_name("limb", index),
                           world.limbs[index]);
  for (PxU32 index = 0; index < world.antenna_rods.size(); ++index)
    append_capsule_objects(objects, indexed_name("antenna", index),
                           world.antenna_rods[index]);
  objects.push_back(sphere_object(
      "antenna_tip", world.antenna_tips[0].actor->getGlobalPose().p,
      world.antenna_tips[0].radius, world.antenna_tips[0].material));

  for (PxU32 index = 0; index < world.gears.size(); ++index) {
    const GearRecord& record = world.gears[index];
    const PxTransform pose = record.actor->getGlobalPose();
    const PxVec3 axis = safe_unit(pose.q.rotate(PxVec3(0.0f, 0.0f, 1.0f)),
                                  PxVec3(0.0f, 0.0f, 1.0f));
    const std::string prefix = indexed_name("gear", index);
    objects.push_back(cylinder_object(prefix + "_body",
                                      pose.p - axis * record.half_thickness,
                                      axis, 2.0f * record.half_thickness,
                                      record.radius * 0.55f, record.material));
    objects.push_back(disk_object(prefix + "_front",
                                  pose.p + axis * record.half_thickness, axis,
                                  record.radius * 0.55f, record.material));
    objects.push_back(disk_object(prefix + "_back",
                                  pose.p - axis * record.half_thickness, -axis,
                                  record.radius * 0.55f, record.material));
    if (index == 4)
      objects.push_back(sphere_object(prefix + "_oracle_core", pose.p, 0.24f,
                                      "oracle_core_emitter"));
    for (PxU32 element = 0; element < 6; ++element) {
      const float angle = 2.0f * kPi * static_cast<float>(element) / 6.0f;
      const PxVec3 local_radial(std::cos(angle), std::sin(angle), 0.0f);
      const PxVec3 local_tangent(-std::sin(angle), std::cos(angle), 0.0f);
      const PxVec3 radial = pose.q.rotate(local_radial);
      objects.push_back(cylinder_object(
          prefix + "_spoke_" + indexed_name("s", element), pose.p, radial,
          record.radius * 0.77f, 0.042f, record.material));
      const PxVec3 center_local = local_radial * record.radius;
      objects.push_back(rectangle_object(
          prefix + "_tooth_" + indexed_name("t", element),
          pose.transform(center_local - local_tangent * 0.16f -
                         local_radial * 0.10f),
          pose.transform(center_local - local_tangent * 0.16f +
                         local_radial * 0.10f),
          pose.transform(center_local + local_tangent * 0.16f +
                         local_radial * 0.10f),
          record.material));
    }
  }

  for (PxU32 index = 0; index < world.mechanical_parts.size(); ++index) {
    const MechanicalRecord& record = world.mechanical_parts[index];
    const std::string prefix = indexed_name("mechanism", index);
    if (record.rod) {
      const CapsuleRecord capsule{record.actor, record.radius,
                                  record.half_height, record.material};
      append_capsule_objects(objects, prefix, capsule);
    } else {
      const PxTransform pose = record.actor->getGlobalPose();
      objects.push_back(pose_rectangle(
          prefix + "_outer", pose, record.half_extents.x,
          record.half_extents.y, record.half_extents.z, record.material));
      objects.push_back(pose_rectangle(
          prefix + "_inner", pose, record.half_extents.x,
          record.half_extents.y, -record.half_extents.z,
          "shell_inner_gold"));
    }
  }

  for (PxU32 index = 0; index < world.roof_stones.size(); ++index) {
    const PlateRecord& record = world.roof_stones[index];
    const PxTransform pose = record.actor->getGlobalPose();
    const std::string prefix = indexed_name("roof_fragment", index);
    objects.push_back(pose_rectangle(prefix + "_front", pose,
                                     record.half_extents.x,
                                     record.half_extents.y,
                                     record.half_extents.z, record.material));
    const PxTransform side_pose(
        pose.transform(PxVec3(record.half_extents.x, 0.0f, 0.0f)),
        pose.q * PxQuat(kPi * 0.5f, PxVec3(0.0f, 1.0f, 0.0f)));
    objects.push_back(pose_rectangle(prefix + "_side", side_pose,
                                     record.half_extents.z,
                                     record.half_extents.y, 0.0f,
                                     record.material));
    const PxTransform top_pose(
        pose.transform(PxVec3(0.0f, record.half_extents.y, 0.0f)),
        pose.q * PxQuat(kPi * 0.5f, PxVec3(1.0f, 0.0f, 0.0f)));
    objects.push_back(pose_rectangle(prefix + "_top", top_pose,
                                     record.half_extents.x,
                                     record.half_extents.z, 0.0f,
                                     record.material));
  }
  for (PxU32 index = 0; index < world.sparks.size(); ++index) {
    const SphereRecord& record = world.sparks[index];
    objects.push_back(sphere_object(indexed_name("spark", index),
                                    record.actor->getGlobalPose().p,
                                    record.radius, record.material));
  }
}

json build_scene(const GeneratedWorld& world, std::uint64_t seed) {
  json scene;
  scene["schema_version"] = 6;
  scene["integrator"] = {{"direct_light_sampling", "importance"},
                         {"clamp_direct", 64.0},
                         {"clamp_indirect", 16.0}};
  scene["camera"] = {{"look_from", {8.2, 6.65, 19.8}},
                     {"look_at", {0.2, 4.15, -1.65}},
                     {"up", {0.0, 1.0, 0.0}},
                     {"vfov", 29.5},
                     {"aperture", 0.012},
                     {"focus_distance", 23.05}};
  scene["background"] = {{"type", "sky"},
                         {"bottom", {0.003, 0.005, 0.012}},
                         {"top", {0.008, 0.016, 0.028}},
                         {"sun_direction",
                          vector_json(safe_unit(
                              -kGodrayAxisRaw,
                              PxVec3(0.0f, 1.0f, 0.0f)))},
                         {"sun_color", {0.0, 0.0, 0.0}},
                         {"sun_cos_angle", 2.0},
                         {"exposure", 0.0}};
  scene["render"] = {{"width", 3840},
                     {"height", 2160},
                     {"spp", 2048},
                     {"max_depth", 12},
                     {"seed", seed},
                     {"denoise", true}};
  scene["textures"] = json::array();
  scene["meshes"] = json::array();

  json materials = json::array();
  materials.push_back({{"name", "temple_blackstone"},
                       {"type", "lambertian"},
                       {"base_color", {0.070, 0.075, 0.085}}});
  materials.push_back({{"name", "temple_carved_stone"},
                       {"type", "lambertian"},
                       {"base_color", {0.115, 0.120, 0.130}}});
  materials.push_back({{"name", "temple_floorstone"},
                       {"type", "lambertian"},
                       {"base_color", {0.065, 0.058, 0.060}}});
  materials.push_back({{"name", "temple_wetstone"},
                       {"type", "lambertian"},
                       {"base_color", {0.075, 0.095, 0.105}}});
  materials.push_back({{"name", "roof_stone"},
                       {"type", "lambertian"},
                       {"base_color", {0.040, 0.043, 0.050}}});
  materials.push_back({{"name", "altar_obsidian"},
                       {"type", "metal"},
                       {"base_color", {0.105, 0.085, 0.075}},
                       {"roughness", 0.47}});
  materials.push_back({{"name", "pool_mosaic"},
                       {"type", "lambertian"},
                       {"base_color", {0.030, 0.135, 0.175}}});
  materials.push_back({{"name", "pool_moss"},
                       {"type", "lambertian"},
                       {"base_color", {0.065, 0.165, 0.095}}});
  materials.push_back({{"name", "oracle_water"},
                       {"type", "water"},
                       {"roughness", 0.11},
                       {"ior", 1.333},
                       {"absorption", {0.42, 0.085, 0.026}}});
  materials.push_back({{"name", "frost_ice"},
                       {"type", "metal"},
                       {"base_color", {0.65, 0.82, 0.95}},
                       {"roughness", 0.42}});
  materials.push_back({{"name", "shell_dark_metal"},
                       {"type", "metal"},
                       {"base_color", {0.34, 0.36, 0.40}},
                       {"roughness", 0.48}});
  materials.push_back({{"name", "shell_inner_gold"},
                       {"type", "metal"},
                       {"base_color", {0.92, 0.58, 0.12}},
                       {"roughness", 0.23}});
  materials.push_back({{"name", "mechanism_gold"},
                       {"type", "metal"},
                       {"base_color", {0.96, 0.68, 0.16}},
                       {"roughness", 0.18}});
  materials.push_back({{"name", "mechanism_copper"},
                       {"type", "metal"},
                       {"base_color", {0.80, 0.28, 0.07}},
                       {"roughness", 0.26}});
  materials.push_back({{"name", "visor_metal"},
                       {"type", "metal"},
                       {"base_color", {0.055, 0.095, 0.12}},
                       {"roughness", 0.14}});
  materials.push_back({{"name", "limb_metal"},
                       {"type", "metal"},
                       {"base_color", {0.31, 0.34, 0.38}},
                       {"roughness", 0.44}});
  materials.push_back({{"name", "eye_emitter"},
                       {"type", "emitter"},
                       {"emission", {0.8, 5.5, 9.5}}});
  materials.push_back({{"name", "oracle_core_emitter"},
                       {"type", "emitter"},
                       {"emission", {1.2, 5.5, 12.0}}});
  materials.push_back({{"name", "spark_emitter"},
                       {"type", "emitter"},
                       {"emission", {24.0, 6.0, 0.18}}});
  materials.push_back({{"name", "rune_emitter"},
                       {"type", "emitter"},
                       {"emission", {0.08, 1.7, 3.8}}});
  materials.push_back({{"name", "dust_gold"},
                       {"type", "lambertian"},
                       {"base_color", {0.90, 0.52, 0.12}}});
  scene["materials"] = std::move(materials);

  json objects = json::array();
  append_static_temple(objects);
  append_dynamic_objects(objects, world);
  if (objects.size() > 450)
    fail("cover scene exceeded the 450-object teaching budget");
  scene["objects"] = std::move(objects);

  scene["lights"] = json::array(
      {{{"name", "dawn_directional"},
        {"type", "directional"},
        {"direction",
         vector_json(safe_unit(-kGodrayAxisRaw,
                               PxVec3(0.0f, 1.0f, 0.0f)))},
        {"irradiance", {1.65, 2.25, 3.6}}},
       {{"name", "altar_white_core"},
        {"type", "flame"},
        {"position", {0.0, 1.20, -1.55}},
        {"axis",
         vector_json(safe_unit(PxVec3(0.02f, 1.0f, -0.03f),
                               PxVec3(0.0f, 1.0f, 0.0f)))},
        {"height", 1.35},
        {"radius_start", 0.72},
        {"radius_end", 0.26},
        {"emission_start", {95.0, 52.0, 12.0}},
        {"emission_end", {52.0, 10.0, 0.25}},
        {"extinction", 2.0},
        {"density_scale", 0.72},
        {"turbulence", 0.52},
        {"noise_scale", 4.4},
        {"seed", 909}},
       {{"name", "altar_main_flame"},
        {"type", "flame"},
        {"position", {-0.12, 1.35, -1.58}},
        {"axis",
         vector_json(safe_unit(PxVec3(-0.08f, 1.0f, 0.02f),
                               PxVec3(0.0f, 1.0f, 0.0f)))},
        {"height", 2.65},
        {"radius_start", 0.58},
        {"radius_end", 0.15},
        {"emission_start", {72.0, 18.0, 0.55}},
        {"emission_end", {11.0, 0.75, 0.015}},
        {"extinction", 1.78},
        {"density_scale", 0.61},
        {"turbulence", 0.86},
        {"noise_scale", 3.65},
        {"seed", 1909}},
       {{"name", "altar_side_tongue"},
        {"type", "flame"},
        {"position", {0.48, 1.42, -1.42}},
        {"axis",
         vector_json(safe_unit(PxVec3(0.28f, 1.0f, 0.09f),
                               PxVec3(0.0f, 1.0f, 0.0f)))},
        {"height", 1.95},
        {"radius_start", 0.34},
        {"radius_end", 0.08},
        {"emission_start", {58.0, 10.0, 0.2}},
        {"emission_end", {6.0, 0.25, 0.004}},
        {"extinction", 1.46},
        {"density_scale", 0.51},
        {"turbulence", 0.93},
        {"noise_scale", 5.1},
        {"seed", 2909}},
       {{"name", "smoke_lower"},
        {"type", "flame"},
        {"position", {0.25, 3.15, -1.62}},
        {"axis",
         vector_json(safe_unit(PxVec3(0.10f, 1.0f, -0.04f),
                               PxVec3(0.0f, 1.0f, 0.0f)))},
        {"height", 3.4},
        {"radius_start", 0.62},
        {"radius_end", 0.92},
        {"emission_start", {0.018, 0.014, 0.008}},
        {"emission_end", {0.004, 0.005, 0.008}},
        {"extinction", 1.744},
        {"density_scale", 0.752},
        {"turbulence", 0.88},
        {"noise_scale", 2.75},
        {"seed", 3909}},
       {{"name", "smoke_upper"},
        {"type", "flame"},
        {"position", {0.81, 5.65, -1.78}},
        {"axis",
         vector_json(safe_unit(PxVec3(-0.12f, 1.0f, -0.10f),
                               PxVec3(0.0f, 1.0f, 0.0f)))},
        {"height", 2.85},
        {"radius_start", 0.82},
        {"radius_end", 0.68},
        {"emission_start", {0.009, 0.008, 0.009}},
        {"emission_end", {0.002, 0.003, 0.006}},
        {"extinction", 1.616},
        {"density_scale", 0.704},
        {"turbulence", 0.79},
        {"noise_scale", 2.35},
        {"seed", 4909}},
       {{"name", "dawn_godray"},
        {"type", "flame"},
        {"position", vector_json(kGodrayOrigin)},
        {"axis",
         vector_json(safe_unit(kGodrayAxisRaw,
                               PxVec3(0.0f, -1.0f, 0.0f)))},
        {"height", 15.2},
        {"radius_start", 0.46},
        {"radius_end", 0.82},
        {"emission_start", {0.10, 0.25, 0.50}},
        {"emission_end", {0.04, 0.12, 0.28}},
        {"extinction", 0.25},
        {"density_scale", 0.45},
        {"turbulence", 0.12},
        {"noise_scale", 1.0},
        {"seed", 5909}},
       {{"name", "rune_point_00"},
        {"type", "point"},
        {"position", {-9.0, 3.2, -5.8}},
        {"intensity", {1.6, 7.2, 13.5}}},
       {{"name", "rune_point_01"},
        {"type", "point"},
        {"position", {-9.0, 4.2, -2.5}},
        {"intensity", {1.4, 6.5, 12.0}}},
       {{"name", "rune_point_02"},
        {"type", "point"},
        {"position", {9.0, 3.2, -5.8}},
        {"intensity", {1.6, 7.2, 13.5}}},
       {{"name", "rune_point_03"},
        {"type", "point"},
        {"position", {9.0, 4.2, -2.5}},
        {"intensity", {1.4, 6.5, 12.0}}}});
  return scene;
}

json build_metadata(const PhysicsRuntime& runtime,
                    const GeneratedWorld& world,
                    const Arguments& args) {
  json actors = json::array();
  PxU32 moving = 0;
  PxU32 radial = 0;
  PxU32 rotating = 0;
  std::array<bool, 4> quadrants = {false, false, false, false};
  double maximum_upward_displacement =
      -std::numeric_limits<double>::infinity();
  PxU32 sleeping = 0;
  for (const BodyRecord& body : world.bodies) {
    const PxTransform pose = body.actor->getGlobalPose();
    const PxVec3 linear_velocity = body.actor->getLinearVelocity();
    const PxVec3 angular_velocity = body.actor->getAngularVelocity();
    const PxVec3 displacement = pose.p - body.initial_position;
    const bool is_sleeping = body.actor->isSleeping();
    if (is_sleeping) ++sleeping;
    if (linear_velocity.magnitudeSquared() > 1.0e-6f ||
        angular_velocity.magnitudeSquared() > 1.0e-6f)
      ++moving;
    if (displacement.magnitude() >= kMinimumRadialDisplacement) ++radial;
    if (angular_velocity.magnitude() > 0.02f) ++rotating;
    maximum_upward_displacement = std::max(
        maximum_upward_displacement,
        rounded(pose.p.y) - rounded(body.initial_position.y));
    if (std::fabs(displacement.x) > 1.0e-6f &&
        std::fabs(displacement.z) > 1.0e-6f) {
      const PxU32 quadrant = (displacement.x < 0.0f ? 2U : 0U) +
                             (displacement.z < 0.0f ? 1U : 0U);
      quadrants[quadrant] = true;
    }
    actors.push_back({{"name", body.name},
                      {"category", body.category},
                      {"initial_position", vector_json(body.initial_position)},
                      {"position", vector_json(pose.p)},
                      {"rotation_xyzw", quaternion_json(pose.q)},
                      {"linear_velocity", vector_json(linear_velocity)},
                      {"angular_velocity", vector_json(angular_velocity)},
                      {"sleeping", is_sleeping}});
  }
  const PxU32 occupied_quadrants = static_cast<PxU32>(
      std::count(quadrants.begin(), quadrants.end(), true));

  return {
      {"schema_version", 1},
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
        {"capture_seconds", rounded(kSteps * kFixedDt)},
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
       {{"dynamic_actors", kDynamicActorCount},
        {"shell_plates", kShellPlateCount},
        {"visor_panels", kVisorPanelCount},
        {"eyes", kEyeCount},
        {"limbs", kLimbCount},
        {"antenna_parts", kAntennaPartCount},
        {"compound_gears", kGearCount},
        {"mechanical_parts", kMechanicalPartCount},
        {"roof_stones", kRoofStoneCount},
        {"sparks", kSparkCount},
        {"prefractured", true},
        {"actor_order",
         {{{"category", "shell_plate"}, {"count", kShellPlateCount}},
          {{"category", "visor_panel"}, {"count", kVisorPanelCount}},
          {{"category", "eye"}, {"count", kEyeCount}},
          {{"category", "limb"}, {"count", kLimbCount}},
          {{"category", "antenna_part"}, {"count", kAntennaPartCount}},
          {{"category", "compound_gear"}, {"count", kGearCount}},
          {{"category", "mechanical_part"},
           {"count", kMechanicalPartCount}},
          {{"category", "roof_stone"}, {"count", kRoofStoneCount}},
          {{"category", "spark"}, {"count", kSparkCount}}}}}},
      {"scene_features",
       {{"ancient_blackstone_temple", true},
        {"collapsed_roof_opening", true},
        {"prefractured_mechanical_oracle", true},
        {"compound_gear_actors", true},
        {"analytic_water_surface", true},
        {"procedural_fire_and_absorbing_smoke", true},
        {"directional_dawn_light", true},
        {"emissive_runes", true},
        {"opaque_frost_visual_proxy", true},
        {"external_meshes", false},
        {"external_textures", false}}},
      {"contract",
       {{"dynamic_center_bounds",
         {{"min", {-12.0, -0.2, -10.0}}, {"max", {12.0, 15.0, 8.0}}}},
        {"minimum_radial_displacement", kMinimumRadialDisplacement},
        {"minimum_moving_dynamic_actors", kMinimumMovingActors}}},
      {"results",
       {{"sleeping_dynamic_actors", sleeping},
        {"moving_dynamic_actors", moving},
        {"actors_beyond_minimum_radial_displacement", radial},
        {"rotating_dynamic_actors", rotating},
        {"occupied_explosion_quadrants", occupied_quadrants},
        {"maximum_upward_displacement", rounded(maximum_upward_displacement)}}},
      {"actors", std::move(actors)}};
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
    if (!output)
      fail("cannot create temporary output: " + temporary.string());
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
                  "Lava Temple Oracle requires PhysX 5.8.0");
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
    std::cout << "generated Lava Temple Oracle with " << kDynamicActorCount
              << " prefractured actors after " << kSteps
              << " PhysX GPU steps on device " << args.device << " ("
              << runtime.device_name << ")\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return 2;
  }
}
