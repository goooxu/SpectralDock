#include <PxConfig.h>
#include <PxPhysicsAPI.h>
#include <cudamanager/PxCudaContextManager.h>
#include <gpu/PxGpu.h>

#include <cuda_runtime_api.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <system_error>
#include <type_traits>
#include <utility>
#include <vector>

namespace {

using namespace physx;

constexpr std::array<char, 8> kRequestMagic = {
    'S', 'D', 'P', 'X', 'R', 'Q', '2', '\0'};
constexpr std::array<char, 8> kResultMagic = {
    'S', 'D', 'P', 'X', 'R', 'S', '2', '\0'};
constexpr std::uint32_t kProtocolVersion = 2;
constexpr std::uint32_t kMaximumItems = 1'000'000;
constexpr std::uint32_t kMaximumStringBytes = 1'048'576;
constexpr const char* kPhysxCommit =
    "fc1018a3745664a1db2b95ce03fb5e91eb585f2e";
constexpr float kPi = 3.14159265358979323846f;
static_assert(sizeof(float) == sizeof(std::uint32_t) &&
                  std::numeric_limits<float>::is_iec559,
              "the PhysX IPC requires IEEE-754 binary32 floats");

[[noreturn]] void fail(const std::string& message) {
  throw std::runtime_error(message);
}

void require_finite(float value, const char* label) {
  if (!std::isfinite(value)) fail(std::string(label) + " must be finite");
}

struct Arguments {
  std::filesystem::path request;
  std::filesystem::path result;
};

Arguments parse_arguments(int argc, char** argv) {
  Arguments arguments;
  for (int index = 1; index < argc; ++index) {
    const std::string option(argv[index]);
    if (option == "-h" || option == "--help") {
      std::cout << "Usage: spectraldock_physx_worker --request PATH --result PATH\n";
      std::exit(0);
    }
    if (index + 1 >= argc) fail("missing value for " + option);
    const char* value = argv[++index];
    if (option == "--request")
      arguments.request = value;
    else if (option == "--result")
      arguments.result = value;
    else
      fail("unknown option: " + option);
  }
  if (arguments.request.empty() || arguments.result.empty())
    fail("--request and --result are required");
  if (std::filesystem::absolute(arguments.request).lexically_normal() ==
      std::filesystem::absolute(arguments.result).lexically_normal())
    fail("--request and --result must name different files");
  return arguments;
}

std::vector<std::uint8_t> read_file(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary | std::ios::ate);
  if (!input) fail("cannot open request: " + path.string());
  const std::streamoff size = input.tellg();
  if (size < 0 || size > static_cast<std::streamoff>(512ULL * 1024ULL * 1024ULL))
    fail("request has an invalid or excessive size");
  input.seekg(0);
  std::vector<std::uint8_t> data(static_cast<std::size_t>(size));
  if (size != 0 && !input.read(reinterpret_cast<char*>(data.data()), size))
    fail("failed to read request: " + path.string());
  return data;
}

class Reader {
 public:
  explicit Reader(const std::vector<std::uint8_t>& data) : data_(data) {}

  std::array<char, 8> magic() {
    std::array<char, 8> result{};
    read_bytes(result.data(), result.size());
    return result;
  }

  std::uint8_t u8() {
    std::uint8_t result = 0;
    read_bytes(&result, sizeof(result));
    return result;
  }

  std::uint32_t u32() { return unsigned_le<std::uint32_t>(); }

  std::int32_t i32() {
    const std::uint32_t bits = u32();
    std::int32_t result = 0;
    static_assert(sizeof(result) == sizeof(bits));
    std::memcpy(&result, &bits, sizeof(result));
    return result;
  }

  std::uint64_t u64() { return unsigned_le<std::uint64_t>(); }

  float f32(const char* label = "float") {
    const std::uint32_t bits = u32();
    float value = 0.0f;
    static_assert(sizeof(value) == sizeof(bits));
    std::memcpy(&value, &bits, sizeof(value));
    require_finite(value, label);
    return value;
  }

  PxVec3 vec3(const char* label = "vector") {
    const float x = f32(label);
    const float y = f32(label);
    const float z = f32(label);
    const PxVec3 value(x, y, z);
    if (!value.isFinite()) fail(std::string(label) + " is not finite");
    return value;
  }

  PxQuat quat(const char* label = "quaternion") {
    const float x = f32(label);
    const float y = f32(label);
    const float z = f32(label);
    const float w = f32(label);
    PxQuat value(x, y, z, w);
    if (!value.isFinite() || value.magnitudeSquared() <= 1.0e-12f)
      fail(std::string(label) + " is invalid");
    value.normalize();
    return value;
  }

  std::string string() {
    const std::uint32_t size = u32();
    if (size > kMaximumStringBytes) fail("request string exceeds protocol limit");
    std::string result(size, '\0');
    if (size != 0) read_bytes(result.data(), size);
    if (result.find('\0') != std::string::npos)
      fail("request strings must not contain NUL bytes");
    return result;
  }

  std::uint32_t count(const char* label) {
    const std::uint32_t result = u32();
    if (result > kMaximumItems)
      fail(std::string(label) + " count exceeds protocol limit");
    return result;
  }

  std::vector<float> values(std::uint32_t expected, const char* label) {
    const std::uint32_t count_value = count(label);
    if (count_value != expected)
      fail(std::string(label) + " has the wrong number of values");
    std::vector<float> result;
    result.reserve(count_value);
    for (std::uint32_t index = 0; index < count_value; ++index)
      result.push_back(f32(label));
    return result;
  }

  void finish() const {
    if (offset_ != data_.size()) fail("request contains trailing bytes");
  }

 private:
  template <typename UInt>
  UInt unsigned_le() {
    static_assert(std::is_unsigned<UInt>::value,
                  "little-endian protocol scalars must be unsigned");
    std::array<std::uint8_t, sizeof(UInt)> bytes{};
    read_bytes(bytes.data(), bytes.size());
    UInt result = 0;
    for (std::size_t index = 0; index < bytes.size(); ++index)
      result |= static_cast<UInt>(bytes[index]) << (index * 8U);
    return result;
  }

  void read_bytes(void* output, std::size_t size) {
    if (size > data_.size() - std::min(offset_, data_.size()))
      fail("request is truncated");
    std::memcpy(output, data_.data() + offset_, size);
    offset_ += size;
  }

  const std::vector<std::uint8_t>& data_;
  std::size_t offset_ = 0;
};

class Writer {
 public:
  void magic(const std::array<char, 8>& value) {
    bytes(value.data(), value.size());
  }

  void u8(std::uint8_t value) { bytes(&value, sizeof(value)); }
  void u32(std::uint32_t value) { unsigned_le(value); }
  void i32(std::int32_t value) {
    std::uint32_t bits = 0;
    static_assert(sizeof(value) == sizeof(bits));
    std::memcpy(&bits, &value, sizeof(bits));
    u32(bits);
  }
  void u64(std::uint64_t value) { unsigned_le(value); }

  void f32(float value) {
    require_finite(value, "result float");
    std::uint32_t bits = 0;
    static_assert(sizeof(value) == sizeof(bits));
    std::memcpy(&bits, &value, sizeof(bits));
    u32(bits);
  }

  void vec3(const PxVec3& value) {
    if (!value.isFinite()) fail("simulation produced a non-finite vector");
    f32(value.x);
    f32(value.y);
    f32(value.z);
  }

  void quat(PxQuat value) {
    if (!value.isFinite() || value.magnitudeSquared() <= 1.0e-12f)
      fail("simulation produced an invalid quaternion");
    value.normalize();
    f32(value.x);
    f32(value.y);
    f32(value.z);
    f32(value.w);
  }

  void string(const std::string& value) {
    if (value.size() > kMaximumStringBytes)
      fail("result string exceeds protocol limit");
    u32(static_cast<std::uint32_t>(value.size()));
    bytes(value.data(), value.size());
  }

  const std::vector<std::uint8_t>& data() const { return data_; }

 private:
  template <typename UInt>
  void unsigned_le(UInt value) {
    static_assert(std::is_unsigned<UInt>::value,
                  "little-endian protocol scalars must be unsigned");
    for (std::size_t index = 0; index < sizeof(value); ++index)
      data_.push_back(static_cast<std::uint8_t>(value >> (index * 8U)));
  }

  void bytes(const void* value, std::size_t size) {
    const auto* begin = static_cast<const std::uint8_t*>(value);
    data_.insert(data_.end(), begin, begin + size);
  }

  std::vector<std::uint8_t> data_;
};

struct MaterialRequest {
  std::string name;
  float static_friction = 0.0f;
  float dynamic_friction = 0.0f;
  float restitution = 0.0f;
};

struct StaticRequest {
  std::uint8_t kind = 0;
  std::string name;
  std::uint32_t material = 0;
  PxTransform pose;
  std::vector<float> values;
};

struct ShapeRequest {
  std::uint8_t kind = 0;
  std::uint32_t material = 0;
  PxTransform pose;
  std::vector<float> values;
};

struct ActionRequest {
  PxVec3 delta_velocity;
  PxVec3 position;
};

struct AttachmentRequest {
  std::uint8_t kind = 0;
  std::string name;
  std::vector<float> values;
  std::uint32_t global_index = 0;
};

struct BodyRequest {
  std::string name;
  std::string category;
  PxTransform pose;
  float density = 0.0f;
  float linear_damping = 0.0f;
  float angular_damping = 0.0f;
  float sleep_threshold = 0.0f;
  std::uint32_t position_iterations = 0;
  std::uint32_t velocity_iterations = 0;
  PxVec3 linear_velocity;
  PxVec3 angular_velocity;
  std::vector<ShapeRequest> shapes;
  std::vector<ActionRequest> actions;
  std::vector<AttachmentRequest> attachments;
};

struct Request {
  std::int32_t device = 0;
  std::uint64_t seed = 0;
  float fixed_dt = 0.0f;
  std::uint32_t steps = 0;
  PxVec3 gravity;
  std::string scene_name;
  std::vector<MaterialRequest> materials;
  std::vector<StaticRequest> statics;
  std::vector<BodyRequest> bodies;
  std::uint32_t attachment_count = 0;
};

std::uint32_t attachment_value_count(std::uint8_t kind) {
  switch (kind) {
    case 1: return 4;  // sphere
    case 2: return 9;  // rectangle
    case 3: return 8;  // cylinder
    case 4: return 7;  // disk
    case 5: return 10; // mesh: local position, quaternion, scale
    default: fail("request contains an unknown attachment kind");
  }
}

std::uint32_t shape_value_count(std::uint8_t kind) {
  switch (kind) {
    case 1: return 3;
    case 2: return 1;
    case 3: return 2;
    default: fail("request contains an unknown shape kind");
  }
}

Request parse_request(const std::vector<std::uint8_t>& data) {
  Reader reader(data);
  if (reader.magic() != kRequestMagic) fail("unknown request format");
  if (reader.u32() != kProtocolVersion) fail("unsupported request protocol version");

  Request request;
  request.device = reader.i32();
  request.seed = reader.u64();
  request.fixed_dt = reader.f32("fixed_dt");
  request.steps = reader.u32();
  request.gravity = reader.vec3("gravity");
  request.scene_name = reader.string();
  if (request.device < 0) fail("CUDA device ordinal must be non-negative");
  if (!(request.fixed_dt > 0.0f)) fail("fixed_dt must be positive");
  if (request.steps == 0 || request.steps > 10'000'000)
    fail("simulation step count is invalid");
  if (request.scene_name.empty()) fail("scene_name must not be empty");

  const std::uint32_t material_count = reader.count("material");
  if (material_count == 0) fail("request has no contact materials");
  request.materials.reserve(material_count);
  for (std::uint32_t index = 0; index < material_count; ++index) {
    MaterialRequest material;
    material.name = reader.string();
    material.static_friction = reader.f32("static friction");
    material.dynamic_friction = reader.f32("dynamic friction");
    material.restitution = reader.f32("restitution");
    if (material.name.empty() || material.static_friction < 0.0f ||
        material.dynamic_friction < 0.0f || material.restitution < 0.0f ||
        material.restitution > 1.0f)
      fail("invalid contact material");
    request.materials.push_back(std::move(material));
  }

  const std::uint32_t static_count = reader.count("static actor");
  request.statics.reserve(static_count);
  for (std::uint32_t index = 0; index < static_count; ++index) {
    StaticRequest actor;
    actor.kind = reader.u8();
    actor.name = reader.string();
    actor.material = reader.u32();
    const PxVec3 position = reader.vec3("static position");
    const PxQuat rotation = reader.quat("static rotation");
    actor.pose = PxTransform(position, rotation);
    const std::uint32_t expected = actor.kind == 1 ? 4U : actor.kind == 2 ? 3U : 0U;
    if (expected == 0) fail("request contains an unknown static actor kind");
    actor.values = reader.values(expected, "static actor values");
    if (actor.name.empty() || actor.material >= material_count)
      fail("invalid static actor");
    if (actor.kind == 1) {
      const PxVec3 normal(actor.values[0], actor.values[1], actor.values[2]);
      if (normal.magnitudeSquared() <= 1.0e-12f) fail("plane normal must not be zero");
    } else if (!(actor.values[0] > 0.0f && actor.values[1] > 0.0f &&
                 actor.values[2] > 0.0f)) {
      fail("static box extents must be positive");
    }
    request.statics.push_back(std::move(actor));
  }

  const std::uint32_t body_count = reader.count("body");
  if (body_count == 0) fail("request has no dynamic rigid bodies");
  request.bodies.reserve(body_count);
  std::uint32_t next_attachment = 0;
  for (std::uint32_t body_index = 0; body_index < body_count; ++body_index) {
    BodyRequest body;
    body.name = reader.string();
    body.category = reader.string();
    const PxVec3 position = reader.vec3("body position");
    const PxQuat rotation = reader.quat("body rotation");
    body.pose = PxTransform(position, rotation);
    body.density = reader.f32("density");
    body.linear_damping = reader.f32("linear damping");
    body.angular_damping = reader.f32("angular damping");
    body.sleep_threshold = reader.f32("sleep threshold");
    body.position_iterations = reader.u32();
    body.velocity_iterations = reader.u32();
    body.linear_velocity = reader.vec3("linear velocity");
    body.angular_velocity = reader.vec3("angular velocity");
    if (body.name.empty() || body.category.empty() || !(body.density > 0.0f) ||
        body.linear_damping < 0.0f || body.angular_damping < 0.0f ||
        body.sleep_threshold < 0.0f || body.position_iterations == 0 ||
        body.position_iterations > 255 || body.velocity_iterations == 0 ||
        body.velocity_iterations > 255)
      fail("invalid dynamic body parameters");

    const std::uint32_t shape_count = reader.count("shape");
    if (shape_count == 0) fail("dynamic body has no shapes");
    body.shapes.reserve(shape_count);
    for (std::uint32_t shape_index = 0; shape_index < shape_count; ++shape_index) {
      ShapeRequest shape;
      shape.kind = reader.u8();
      shape.material = reader.u32();
      const PxVec3 shape_position = reader.vec3("shape position");
      const PxQuat shape_rotation = reader.quat("shape rotation");
      shape.pose = PxTransform(shape_position, shape_rotation);
      shape.values = reader.values(shape_value_count(shape.kind), "shape values");
      if (shape.material >= material_count)
        fail("shape references an invalid contact material");
      if (!std::all_of(shape.values.begin(), shape.values.end(),
                       [](float value) { return value > 0.0f; }))
        fail("shape dimensions must be positive");
      body.shapes.push_back(std::move(shape));
    }

    const std::uint32_t action_count = reader.count("action");
    body.actions.reserve(action_count);
    for (std::uint32_t action_index = 0; action_index < action_count; ++action_index) {
      if (reader.u8() != 1) fail("request contains an unknown action kind");
      body.actions.push_back({reader.vec3("delta velocity"),
                              reader.vec3("impulse position")});
    }

    const std::uint32_t attachment_count = reader.count("attachment");
    if (attachment_count > kMaximumItems - next_attachment)
      fail("total attachment count exceeds protocol limit");
    body.attachments.reserve(attachment_count);
    for (std::uint32_t attachment_index = 0; attachment_index < attachment_count;
         ++attachment_index) {
      AttachmentRequest attachment;
      attachment.kind = reader.u8();
      attachment.name = reader.string();
      attachment.values = reader.values(attachment_value_count(attachment.kind),
                                        "attachment values");
      attachment.global_index = next_attachment++;
      if (attachment.name.empty()) fail("attachment name must not be empty");
      body.attachments.push_back(std::move(attachment));
    }
    request.bodies.push_back(std::move(body));
  }
  request.attachment_count = next_attachment;
  reader.finish();
  return request;
}

class ErrorCallback final : public PxErrorCallback {
 public:
  void reportError(PxErrorCode::Enum code, const char* message,
                   const char* file, int line) override {
    std::cerr << "PhysX[" << static_cast<int>(code) << "] "
              << (message ? message : "unknown error") << " ("
              << (file ? file : "unknown") << ':' << line << ")\n";
    if (message) {
      std::string text(message);
      std::transform(text.begin(), text.end(), text.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
      });
      const auto contains = [&text](const char* token) {
        return text.find(token) != std::string::npos;
      };
      const bool fallback = contains("fallback") || contains("fall back");
      const bool gpu_subsystem =
          contains("gpu dynamics") || contains("gpu broadphase") ||
          contains("gpu broad phase") || contains("gpu simulation") ||
          contains("cuda context");
      const bool unavailable =
          contains("failed") || contains("failure") || contains("invalid") ||
          contains("unavailable") || contains("disabled") ||
          contains("not supported");
      if (fallback || (gpu_subsystem && unavailable))
        gpu_contract_violation.store(true, std::memory_order_relaxed);
    }
    if (code == PxErrorCode::eINVALID_PARAMETER ||
        code == PxErrorCode::eINVALID_OPERATION ||
        code == PxErrorCode::eOUT_OF_MEMORY ||
        code == PxErrorCode::eINTERNAL_ERROR || code == PxErrorCode::eABORT)
      fatal.store(true, std::memory_order_relaxed);
  }

  std::atomic_bool fatal{false};
  std::atomic_bool gpu_contract_violation{false};
};

struct GpuPipelineStatistics {
  std::uint32_t samples = 0;
  std::uint64_t heap_bytes = 0;
  std::uint64_t broad_phase_bytes = 0;
  std::uint64_t narrow_phase_bytes = 0;
  std::uint64_t solver_bytes = 0;
  std::uint64_t simulation_bytes = 0;

  void observe(const PxSimulationStatistics& value) {
    ++samples;
    heap_bytes = std::max(heap_bytes,
                          static_cast<std::uint64_t>(value.gpuMemHeap));
    broad_phase_bytes = std::max(
        broad_phase_bytes,
        static_cast<std::uint64_t>(value.gpuMemHeapBroadPhase));
    narrow_phase_bytes = std::max(
        narrow_phase_bytes,
        static_cast<std::uint64_t>(value.gpuMemHeapNarrowPhase));
    solver_bytes = std::max(
        solver_bytes, static_cast<std::uint64_t>(value.gpuMemHeapSolver));
    simulation_bytes = std::max(
        simulation_bytes,
        static_cast<std::uint64_t>(value.gpuMemHeapSimulation));
  }

  bool proves_gpu_pipeline() const {
    return samples > 0 && heap_bytes > 0 && broad_phase_bytes > 0 &&
           narrow_phase_bytes > 0 && solver_bytes > 0 &&
           simulation_bytes > 0;
  }
};

void check_cuda(cudaError_t status, const char* operation) {
  if (status != cudaSuccess)
    fail(std::string(operation) + ": " + cudaGetErrorString(status));
}

class Runtime {
 public:
  explicit Runtime(const Request& request) {
    int device_count = 0;
    check_cuda(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
    if (request.device >= device_count) fail("CUDA device ordinal is unavailable");
    check_cuda(cudaSetDevice(request.device), "cudaSetDevice");
    cudaDeviceProp properties{};
    check_cuda(cudaGetDeviceProperties(&properties, request.device),
               "cudaGetDeviceProperties");
    device_name = properties.name;
    check_cuda(cudaRuntimeGetVersion(&cuda_runtime_version),
               "cudaRuntimeGetVersion");

    foundation_ = PxCreateFoundation(PX_PHYSICS_VERSION, allocator_, errors_);
    if (!foundation_) fail("PxCreateFoundation failed");
    PxTolerancesScale scale;
    physics_ = PxCreatePhysics(PX_PHYSICS_VERSION, *foundation_, scale, true, nullptr);
    if (!physics_) fail("PxCreatePhysics failed");
    if (!PxInitExtensions(*physics_, nullptr)) fail("PxInitExtensions failed");
    extensions_initialized_ = true;

    PxCudaContextManagerDesc cuda_description;
    cuda_description.deviceOrdinal = request.device;
    cuda_manager_ = PxCreateCudaContextManager(*foundation_, cuda_description);
    if (!cuda_manager_ || !cuda_manager_->contextIsValid())
      fail("PhysX CUDA context manager is unavailable or invalid");
    // PhysX requires a host task dispatcher even for GPU rigid bodies. This
    // thread schedules tasks only; dynamics and broadphase remain GPU-only.
    dispatcher_ = PxDefaultCpuDispatcherCreate(1);
    if (!dispatcher_) fail("PxDefaultCpuDispatcherCreate failed");

    PxSceneDesc description(scale);
    description.gravity = request.gravity;
    description.cpuDispatcher = dispatcher_;
    description.filterShader = PxDefaultSimulationFilterShader;
    description.cudaContextManager = cuda_manager_;
    description.broadPhaseType = PxBroadPhaseType::eGPU;
    description.solverType = PxSolverType::eTGS;
    description.flags |= PxSceneFlag::eENABLE_GPU_DYNAMICS;
    description.flags |= PxSceneFlag::eENABLE_PCM;
    description.flags |= PxSceneFlag::eENABLE_STABILIZATION;
    description.flags &= ~PxSceneFlag::eENABLE_ENHANCED_DETERMINISM;
    if (!description.isValid()) fail("GPU PxSceneDesc is invalid");
    scene_ = physics_->createScene(description);
    if (!scene_) fail("GPU PhysX scene creation failed; CPU fallback is forbidden");
    verify_gpu_contract("after scene creation");

    materials_.reserve(request.materials.size());
    for (const MaterialRequest& input : request.materials) {
      PxMaterial* material = physics_->createMaterial(
          input.static_friction, input.dynamic_friction, input.restitution);
      if (!material) fail("PxMaterial creation failed");
      materials_.push_back(material);
    }
  }

  ~Runtime() {
    for (auto iterator = actors_.rbegin(); iterator != actors_.rend(); ++iterator)
      (*iterator)->release();
    for (auto iterator = materials_.rbegin(); iterator != materials_.rend(); ++iterator)
      (*iterator)->release();
    if (scene_) scene_->release();
    if (dispatcher_) dispatcher_->release();
    if (cuda_manager_) cuda_manager_->release();
    if (extensions_initialized_) PxCloseExtensions();
    if (physics_) physics_->release();
    if (foundation_) foundation_->release();
  }

  Runtime(const Runtime&) = delete;
  Runtime& operator=(const Runtime&) = delete;

  PxPhysics& physics() { return *physics_; }
  PxScene& scene() { return *scene_; }
  PxMaterial& material(std::uint32_t index) { return *materials_.at(index); }
  ErrorCallback& errors() { return errors_; }
  const GpuPipelineStatistics& gpu_statistics() const { return gpu_statistics_; }
  bool cuda_context_valid() const {
    return cuda_manager_ && cuda_manager_->contextIsValid();
  }
  bool gpu_dynamics_enabled() const {
    return scene_->getFlags().isSet(PxSceneFlag::eENABLE_GPU_DYNAMICS);
  }
  bool gpu_broad_phase_enabled() const {
    return scene_->getBroadPhaseType() == PxBroadPhaseType::eGPU;
  }
  bool tgs_solver_enabled() const {
    return scene_->getSolverType() == PxSolverType::eTGS;
  }
  bool pcm_enabled() const {
    return scene_->getFlags().isSet(PxSceneFlag::eENABLE_PCM);
  }
  bool stabilization_enabled() const {
    return scene_->getFlags().isSet(PxSceneFlag::eENABLE_STABILIZATION);
  }
  bool cpu_fallback_observed() const {
    return errors_.gpu_contract_violation.load(std::memory_order_relaxed);
  }
  bool enhanced_determinism_enabled() const {
    return scene_->getFlags().isSet(PxSceneFlag::eENABLE_ENHANCED_DETERMINISM);
  }

  void verify_gpu_contract(const char* stage) const {
    if (!scene_ || !cuda_manager_ || !cuda_manager_->contextIsValid() ||
        scene_->getCudaContextManager() != cuda_manager_ ||
        scene_->getCpuDispatcher() != dispatcher_ ||
        scene_->getBroadPhaseType() != PxBroadPhaseType::eGPU ||
        scene_->getSolverType() != PxSolverType::eTGS) {
      fail(std::string("PhysX GPU-only contract failed ") + stage);
    }
    const PxSceneFlags flags = scene_->getFlags();
    if (!flags.isSet(PxSceneFlag::eENABLE_GPU_DYNAMICS) ||
        !flags.isSet(PxSceneFlag::eENABLE_PCM) ||
        !flags.isSet(PxSceneFlag::eENABLE_STABILIZATION) ||
        flags.isSet(PxSceneFlag::eENABLE_ENHANCED_DETERMINISM) ||
        errors_.fatal.load(std::memory_order_relaxed) ||
        errors_.gpu_contract_violation.load(std::memory_order_relaxed)) {
      fail(std::string("PhysX rejected the GPU-only scene contract ") + stage +
           "; CPU fallback is forbidden");
    }
  }

  void observe_gpu_statistics() {
    PxSimulationStatistics value;
    scene_->getSimulationStatistics(value);
    gpu_statistics_.observe(value);
  }

  void require_gpu_statistics() const {
    if (!gpu_statistics_.proves_gpu_pipeline())
      fail("PhysX did not report non-zero GPU broadphase, narrowphase, solver, "
           "and simulation heap usage; CPU fallback is forbidden");
  }

  void add(PxRigidActor* actor) {
    if (!actor) fail("PhysX actor creation failed");
    actors_.push_back(actor);
    scene_->addActor(*actor);
  }

  std::string device_name;
  int cuda_runtime_version = 0;

 private:
  PxDefaultAllocator allocator_;
  ErrorCallback errors_;
  PxFoundation* foundation_ = nullptr;
  PxPhysics* physics_ = nullptr;
  PxCudaContextManager* cuda_manager_ = nullptr;
  PxDefaultCpuDispatcher* dispatcher_ = nullptr;
  PxScene* scene_ = nullptr;
  std::vector<PxMaterial*> materials_;
  std::vector<PxRigidActor*> actors_;
  GpuPipelineStatistics gpu_statistics_;
  bool extensions_initialized_ = false;
};

PxVec3 vec3(const std::vector<float>& values, std::size_t offset) {
  return PxVec3(values.at(offset), values.at(offset + 1), values.at(offset + 2));
}

PxQuat quat(const std::vector<float>& values, std::size_t offset) {
  PxQuat result(values.at(offset), values.at(offset + 1), values.at(offset + 2),
                values.at(offset + 3));
  result.normalize();
  return result;
}

void create_static_actors(Runtime& runtime, const Request& request) {
  for (const StaticRequest& input : request.statics) {
    if (input.kind == 1) {
      PxVec3 normal(input.values[0], input.values[1], input.values[2]);
      normal.normalize();
      runtime.add(PxCreatePlane(runtime.physics(),
                                PxPlane(normal, input.values[3]),
                                runtime.material(input.material)));
    } else {
      PxRigidStatic* actor = runtime.physics().createRigidStatic(input.pose);
      if (!actor) fail("static rigid actor creation failed");
      if (!PxRigidActorExt::createExclusiveShape(
              *actor, PxBoxGeometry(vec3(input.values, 0)),
              runtime.material(input.material))) {
        actor->release();
        fail("static box shape creation failed");
      }
      runtime.add(actor);
    }
  }
}

PxShape* add_shape(Runtime& runtime, PxRigidDynamic& actor,
                   const ShapeRequest& input) {
  PxShape* shape = nullptr;
  if (input.kind == 1) {
    shape = PxRigidActorExt::createExclusiveShape(
        actor, PxBoxGeometry(vec3(input.values, 0)),
        runtime.material(input.material));
  } else if (input.kind == 2) {
    shape = PxRigidActorExt::createExclusiveShape(
        actor, PxSphereGeometry(input.values[0]),
        runtime.material(input.material));
  } else if (input.kind == 3) {
    shape = PxRigidActorExt::createExclusiveShape(
        actor, PxCapsuleGeometry(input.values[0], input.values[1]),
        runtime.material(input.material));
  }
  if (!shape) fail("dynamic shape creation failed");
  shape->setLocalPose(input.pose);
  return shape;
}

std::vector<PxRigidDynamic*> create_dynamic_actors(Runtime& runtime,
                                                   const Request& request) {
  std::vector<PxRigidDynamic*> actors;
  actors.reserve(request.bodies.size());
  for (const BodyRequest& input : request.bodies) {
    PxRigidDynamic* actor = runtime.physics().createRigidDynamic(input.pose);
    if (!actor) fail("dynamic rigid actor creation failed");
    bool runtime_owns_actor = false;
    try {
      for (const ShapeRequest& shape : input.shapes) add_shape(runtime, *actor, shape);
      if (!PxRigidBodyExt::updateMassAndInertia(*actor, input.density))
        fail("mass/inertia computation failed");
      actor->setSolverIterationCounts(
          static_cast<PxU32>(input.position_iterations),
          static_cast<PxU32>(input.velocity_iterations));
      actor->setLinearDamping(input.linear_damping);
      actor->setAngularDamping(input.angular_damping);
      actor->setSleepThreshold(input.sleep_threshold);
      actor->setLinearVelocity(input.linear_velocity);
      actor->setAngularVelocity(input.angular_velocity);
      runtime.add(actor);
      runtime_owns_actor = true;
      for (const ActionRequest& action : input.actions) {
        const PxVec3 impulse = action.delta_velocity * actor->getMass();
        PxRigidBodyExt::addForceAtPos(*actor, impulse, action.position,
                                     PxForceMode::eIMPULSE, true);
      }
    } catch (...) {
      if (!runtime_owns_actor) actor->release();
      throw;
    }
    actors.push_back(actor);
  }
  return actors;
}

void simulate(Runtime& runtime, const Request& request) {
  for (std::uint32_t step = 0; step < request.steps; ++step) {
    runtime.scene().simulate(request.fixed_dt);
    if (!runtime.scene().fetchResults(true))
      fail("PxScene::fetchResults failed at step " + std::to_string(step));
    if (runtime.errors().fatal.load(std::memory_order_relaxed))
      fail("PhysX reported a fatal error during GPU simulation");
    runtime.verify_gpu_contract("after simulation step");
    runtime.observe_gpu_statistics();
  }
  runtime.verify_gpu_contract("after simulation");
  runtime.require_gpu_statistics();
}

std::array<float, 3> euler_degrees(PxQuat quaternion) {
  quaternion.normalize();
  const PxMat33 matrix(quaternion);
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
  constexpr float to_degrees = 180.0f / kPi;
  return {x * to_degrees, y * to_degrees, z * to_degrees};
}

PxVec3 normalized(PxVec3 value, const char* label) {
  if (!value.isFinite() || value.magnitudeSquared() <= 1.0e-12f)
    fail(std::string(label) + " must not be zero");
  return value.getNormalized();
}

void write_attachment(Writer& writer, const PxTransform& body_pose,
                      std::uint32_t body_index,
                      const AttachmentRequest& attachment) {
  writer.u32(attachment.global_index);
  writer.u32(body_index);
  writer.u8(attachment.kind);
  const std::vector<float>& value = attachment.values;
  if (attachment.kind == 1) {
    writer.vec3(body_pose.transform(vec3(value, 0)));
    writer.f32(value[3]);
  } else if (attachment.kind == 2) {
    writer.vec3(body_pose.transform(vec3(value, 0)));
    writer.vec3(body_pose.transform(vec3(value, 3)));
    writer.vec3(body_pose.transform(vec3(value, 6)));
  } else if (attachment.kind == 3) {
    writer.vec3(body_pose.transform(vec3(value, 0)));
    writer.vec3(normalized(body_pose.q.rotate(vec3(value, 3)), "cylinder axis"));
    writer.f32(value[6]);
    writer.f32(value[7]);
  } else if (attachment.kind == 4) {
    writer.vec3(body_pose.transform(vec3(value, 0)));
    writer.vec3(normalized(body_pose.q.rotate(vec3(value, 3)), "disk normal"));
    writer.f32(value[6]);
  } else if (attachment.kind == 5) {
    const PxTransform local(vec3(value, 0), quat(value, 3));
    const PxTransform world = body_pose.transform(local);
    writer.vec3(world.p);
    const auto rotation = euler_degrees(world.q);
    writer.f32(rotation[0]);
    writer.f32(rotation[1]);
    writer.f32(rotation[2]);
    writer.f32(value[7]);
    writer.f32(value[8]);
    writer.f32(value[9]);
  }
}

Writer build_result(const Request& request, const Runtime& runtime,
                    const std::vector<PxRigidDynamic*>& actors) {
  Writer writer;
  writer.magic(kResultMagic);
  writer.u32(kProtocolVersion);
  writer.i32(request.device);
  writer.u64(request.seed);
  writer.f32(request.fixed_dt);
  writer.u32(request.steps);
  writer.u32(PX_PHYSICS_VERSION);
  writer.u32(static_cast<std::uint32_t>(runtime.cuda_runtime_version));
  writer.string(kPhysxCommit);
  writer.string(request.scene_name);
  writer.string("physx-gpu");
  writer.string(runtime.device_name);

  // Explicit contract evidence. Python validates every field instead of
  // inferring GPU execution from a backend label or device name.
  writer.u8(runtime.cuda_context_valid() ? 1 : 0);
  writer.u8(runtime.gpu_dynamics_enabled() ? 1 : 0);
  writer.u8(runtime.gpu_broad_phase_enabled() ? 1 : 0);
  writer.u8(runtime.tgs_solver_enabled() ? 1 : 0);
  writer.u8(runtime.pcm_enabled() ? 1 : 0);
  writer.u8(runtime.stabilization_enabled() ? 1 : 0);
  writer.u8(runtime.cpu_fallback_observed() ? 1 : 0);
  writer.u8(runtime.enhanced_determinism_enabled() ? 1 : 0);

  const GpuPipelineStatistics& gpu = runtime.gpu_statistics();
  writer.u32(gpu.samples);
  writer.u64(gpu.heap_bytes);
  writer.u64(gpu.broad_phase_bytes);
  writer.u64(gpu.narrow_phase_bytes);
  writer.u64(gpu.solver_bytes);
  writer.u64(gpu.simulation_bytes);

  writer.u32(static_cast<std::uint32_t>(request.bodies.size()));
  for (std::size_t index = 0; index < request.bodies.size(); ++index) {
    const BodyRequest& input = request.bodies[index];
    const PxRigidDynamic& actor = *actors[index];
    const PxTransform pose = actor.getGlobalPose();
    writer.string(input.name);
    writer.string(input.category);
    writer.vec3(input.pose.p);
    writer.quat(input.pose.q);
    writer.vec3(pose.p);
    writer.quat(pose.q);
    writer.vec3(actor.getLinearVelocity());
    writer.vec3(actor.getAngularVelocity());
    writer.u8(actor.isSleeping() ? 1 : 0);
  }

  writer.u32(request.attachment_count);
  for (std::size_t body_index = 0; body_index < request.bodies.size(); ++body_index) {
    const PxTransform pose = actors[body_index]->getGlobalPose();
    for (const AttachmentRequest& attachment : request.bodies[body_index].attachments)
      write_attachment(writer, pose, static_cast<std::uint32_t>(body_index), attachment);
  }
  return writer;
}

void atomic_write(const std::filesystem::path& destination,
                  const std::vector<std::uint8_t>& data) {
  const std::filesystem::path parent = destination.parent_path().empty()
                                           ? std::filesystem::path(".")
                                           : destination.parent_path();
  std::error_code error;
  std::filesystem::create_directories(parent, error);
  if (error) fail("cannot create result directory: " + error.message());
  const std::filesystem::path temporary =
      parent / ("." + destination.filename().string() + ".tmp");
  {
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output) fail("cannot open temporary result: " + temporary.string());
    output.write(reinterpret_cast<const char*>(data.data()),
                 static_cast<std::streamsize>(data.size()));
    output.flush();
    if (!output) fail("failed to write temporary result: " + temporary.string());
  }
  std::filesystem::rename(temporary, destination, error);
  if (error) {
    std::filesystem::remove(temporary);
    fail("cannot publish PhysX result: " + error.message());
  }
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const Arguments arguments = parse_arguments(argc, argv);
    const Request request = parse_request(read_file(arguments.request));
    Runtime runtime(request);
    create_static_actors(runtime, request);
    const std::vector<PxRigidDynamic*> actors = create_dynamic_actors(runtime, request);
    simulate(runtime, request);
    const Writer result = build_result(request, runtime, actors);
    atomic_write(arguments.result, result.data());
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "spectraldock_physx_worker: " << error.what() << '\n';
    return 1;
  }
}
