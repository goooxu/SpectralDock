#include "spectraldock/optix_renderer.h"

#include "spectraldock/device_types.h"
#include "spectraldock/math.h"
#include "spectraldock/sampling.h"
#include "spectraldock/scene_types.h"

#include <cuda.h>
#include <cuda_runtime.h>
#include <dlfcn.h>
#include <nvtx3/nvToolsExt.h>
#include <optix.h>
#include <optix_function_table_definition.h>
#include <optix_stack_size.h>
#include <optix_stubs.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#ifndef SPECTRALDOCK_OPTIX_MODULE_INPUT_PATH
#define SPECTRALDOCK_OPTIX_MODULE_INPUT_PATH "device_programs.ptx"
#endif

namespace spectraldock {
namespace {

constexpr unsigned int kGasBuildFlags =
    OPTIX_BUILD_FLAG_ALLOW_COMPACTION | OPTIX_BUILD_FLAG_PREFER_FAST_TRACE;
constexpr unsigned int kMaxTraversableDepth = 2;

void check_cuda(cudaError_t result, const char* expression) {
  if (result != cudaSuccess)
    throw std::runtime_error(std::string(expression) + " failed: " +
                             cudaGetErrorName(result) + ": " +
                             cudaGetErrorString(result));
}

void check_cu(CUresult result, const char* expression) {
  if (result == CUDA_SUCCESS) return;
  const char* name = nullptr;
  const char* text = nullptr;
  cuGetErrorName(result, &name);
  cuGetErrorString(result, &text);
  throw std::runtime_error(std::string(expression) + " failed: " +
                           (name ? name : "CUDA driver error") +
                           (text ? std::string(": ") + text : std::string{}));
}

void check_optix(OptixResult result, const char* expression,
                 const char* log = nullptr, std::size_t log_size = 0) {
  if (result == OPTIX_SUCCESS) return;
  std::ostringstream message;
  message << expression << " failed: " << optixGetErrorName(result)
          << ": " << optixGetErrorString(result);
  if (log && log_size && log[0])
    message << "\nOptiX log: "
            << std::string(log, std::min(log_size, std::strlen(log)));
  throw std::runtime_error(message.str());
}

void optix_log(unsigned int level, const char* tag, const char* message, void*) {
  std::cerr << "[OptiX][" << level << "][" << (tag ? tag : "") << "] "
            << (message ? message : "") << '\n';
}

class NvtxRange {
 public:
  explicit NvtxRange(const char* name) { nvtxRangePushA(name); }
  NvtxRange(const NvtxRange&) = delete;
  NvtxRange& operator=(const NvtxRange&) = delete;
  ~NvtxRange() { nvtxRangePop(); }
};

std::size_t checked_product(std::size_t a, std::size_t b, const char* what) {
  if (a && b > std::numeric_limits<std::size_t>::max() / a)
    throw std::runtime_error(std::string(what) + " size overflow");
  return a * b;
}

float next_float_down(float value) {
  return std::nextafter(value, -std::numeric_limits<float>::infinity());
}

float next_float_up(float value) {
  return std::nextafter(value, std::numeric_limits<float>::infinity());
}

OptixAabb outward_aabb(float min_x, float min_y, float min_z,
                       float max_x, float max_y, float max_z) {
  return {next_float_down(min_x), next_float_down(min_y),
          next_float_down(min_z), next_float_up(max_x),
          next_float_up(max_y), next_float_up(max_z)};
}

template <typename T>
unsigned int checked_u32(T value, const char* what) {
  if (value > static_cast<T>(std::numeric_limits<unsigned int>::max()))
    throw std::runtime_error(std::string(what) + " exceeds 32-bit OptiX limit");
  return static_cast<unsigned int>(value);
}

struct MemoryTracker {
  std::size_t current = 0;
  std::size_t peak = 0;
  std::size_t baseline_free = 0;
  std::size_t minimum_free = 0;
  void start() {
    std::size_t total = 0;
    check_cuda(cudaMemGetInfo(&baseline_free, &total), "cudaMemGetInfo(baseline)");
    minimum_free = baseline_free;
  }
  void sample() {
    std::size_t free = 0;
    std::size_t total = 0;
    check_cuda(cudaMemGetInfo(&free, &total), "cudaMemGetInfo(sample)");
    minimum_free = std::min(minimum_free, free);
  }
  void add(std::size_t bytes) {
    current += bytes;
    peak = std::max(peak, current);
    sample();
  }
  void remove(std::size_t bytes) noexcept {
    current = bytes <= current ? current - bytes : 0;
  }
  std::size_t observed_peak() const noexcept {
    return baseline_free > minimum_free ? baseline_free - minimum_free : 0;
  }
};

std::string nvidia_driver_version() {
  void* library = dlopen("libnvidia-ml.so.1", RTLD_LAZY | RTLD_LOCAL);
  if (!library) return "unknown";
  using NvmlFunction = int (*)();
  using VersionFunction = int (*)(char*, unsigned int);
  const auto init = reinterpret_cast<NvmlFunction>(
      dlsym(library, "nvmlInit_v2"));
  const auto get_version = reinterpret_cast<VersionFunction>(
      dlsym(library, "nvmlSystemGetDriverVersion"));
  const auto shutdown = reinterpret_cast<NvmlFunction>(
      dlsym(library, "nvmlShutdown"));
  std::string result = "unknown";
  if (init && get_version && shutdown && init() == 0) {
    std::array<char, 96> version{};
    if (get_version(version.data(),
                    static_cast<unsigned int>(version.size())) == 0)
      result = version.data();
    shutdown();
  }
  dlclose(library);
  return result;
}

class DeviceBuffer {
 public:
  DeviceBuffer() = default;
  DeviceBuffer(MemoryTracker& tracker, std::size_t bytes) {
    allocate(tracker, bytes);
  }
  DeviceBuffer(const DeviceBuffer&) = delete;
  DeviceBuffer& operator=(const DeviceBuffer&) = delete;
  DeviceBuffer(DeviceBuffer&& other) noexcept { take(std::move(other)); }
  DeviceBuffer& operator=(DeviceBuffer&& other) noexcept {
    if (this != &other) {
      reset();
      take(std::move(other));
    }
    return *this;
  }
  ~DeviceBuffer() { reset(); }

  void allocate(MemoryTracker& tracker, std::size_t bytes) {
    reset();
    tracker_ = &tracker;
    bytes_ = bytes;
    if (!bytes) return;
    void* memory = nullptr;
    check_cuda(cudaMalloc(&memory, bytes), "cudaMalloc");
    pointer_ = reinterpret_cast<CUdeviceptr>(memory);
    tracker.add(bytes);
  }
  void reset() noexcept {
    if (pointer_) {
      cudaFree(reinterpret_cast<void*>(pointer_));
      if (tracker_) tracker_->remove(bytes_);
    }
    pointer_ = 0;
    bytes_ = 0;
    tracker_ = nullptr;
  }
  void upload(const void* data, std::size_t bytes,
              cudaStream_t stream = nullptr) const {
    if (bytes > bytes_) throw std::runtime_error("device upload exceeds buffer");
    if (!bytes) return;
    if (stream)
      check_cuda(cudaMemcpyAsync(reinterpret_cast<void*>(pointer_), data, bytes,
                                 cudaMemcpyHostToDevice, stream),
                 "cudaMemcpyAsync(H2D)");
    else
      check_cuda(cudaMemcpy(reinterpret_cast<void*>(pointer_), data, bytes,
                            cudaMemcpyHostToDevice), "cudaMemcpy(H2D)");
  }
  void clear(cudaStream_t stream = nullptr) const {
    if (!bytes_) return;
    if (stream)
      check_cuda(cudaMemsetAsync(reinterpret_cast<void*>(pointer_), 0, bytes_,
                                 stream),
                 "cudaMemsetAsync");
    else
      check_cuda(cudaMemset(reinterpret_cast<void*>(pointer_), 0, bytes_),
                 "cudaMemset");
  }
  template <typename T>
  void upload(const std::vector<T>& values,
              cudaStream_t stream = nullptr) const {
    upload(values.data(), values.size() * sizeof(T), stream);
  }
  void download(void* data, std::size_t bytes,
                cudaStream_t stream = nullptr) const {
    if (bytes > bytes_) throw std::runtime_error("device download exceeds buffer");
    if (!bytes) return;
    if (stream)
      check_cuda(cudaMemcpyAsync(data, reinterpret_cast<const void*>(pointer_),
                                 bytes, cudaMemcpyDeviceToHost, stream),
                 "cudaMemcpyAsync(D2H)");
    else
      check_cuda(cudaMemcpy(data, reinterpret_cast<const void*>(pointer_),
                            bytes, cudaMemcpyDeviceToHost), "cudaMemcpy(D2H)");
  }
  CUdeviceptr pointer() const noexcept { return pointer_; }
  std::size_t size() const noexcept { return bytes_; }

 private:
  void take(DeviceBuffer&& other) noexcept {
    pointer_ = other.pointer_;
    bytes_ = other.bytes_;
    tracker_ = other.tracker_;
    other.pointer_ = 0;
    other.bytes_ = 0;
    other.tracker_ = nullptr;
  }
  CUdeviceptr pointer_ = 0;
  std::size_t bytes_ = 0;
  MemoryTracker* tracker_ = nullptr;
};

class Stream {
 public:
  Stream() { check_cuda(cudaStreamCreate(&value_), "cudaStreamCreate"); }
  ~Stream() { if (value_) cudaStreamDestroy(value_); }
  operator cudaStream_t() const noexcept { return value_; }
 private:
  cudaStream_t value_ = nullptr;
};

class Event {
 public:
  Event() { check_cuda(cudaEventCreate(&value_), "cudaEventCreate"); }
  ~Event() { if (value_) cudaEventDestroy(value_); }
  void record(cudaStream_t stream) {
    check_cuda(cudaEventRecord(value_, stream), "cudaEventRecord");
  }
  void wait() { check_cuda(cudaEventSynchronize(value_), "cudaEventSynchronize"); }
  double elapsed(const Event& start) const {
    float ms = 0.0f;
    check_cuda(cudaEventElapsedTime(&ms, start.value_, value_),
               "cudaEventElapsedTime");
    return ms;
  }
 private:
  cudaEvent_t value_ = nullptr;
};

struct OptixState {
  OptixDeviceContext context = nullptr;
  OptixModule module = nullptr;
  OptixModule sphere_module = nullptr;
  std::vector<OptixProgramGroup> groups;
  OptixPipeline pipeline = nullptr;
  OptixDenoiser denoiser = nullptr;
  ~OptixState() {
    if (denoiser) optixDenoiserDestroy(denoiser);
    if (pipeline) optixPipelineDestroy(pipeline);
    for (auto it = groups.rbegin(); it != groups.rend(); ++it)
      if (*it) optixProgramGroupDestroy(*it);
    if (sphere_module) optixModuleDestroy(sphere_module);
    if (module) optixModuleDestroy(module);
    if (context) optixDeviceContextDestroy(context);
  }
};

float3 f3(Vec3 value) { return make_float3(value.x, value.y, value.z); }

void basis(Vec3 normal, Vec3& tangent, Vec3& bitangent) {
  normal = normalize(normal);
  const Vec3 helper = std::fabs(normal.z) < 0.999f
                          ? Vec3{0.0f, 0.0f, 1.0f}
                          : Vec3{0.0f, 1.0f, 0.0f};
  tangent = normalize(cross(helper, normal));
  bitangent = cross(normal, tangent);
}
struct TextureHandle {
  cudaArray_t array = nullptr;
  cudaTextureObject_t object = 0;
  MemoryTracker* tracker = nullptr;
  std::size_t bytes = 0;
  TextureHandle() = default;
  TextureHandle(const TextureHandle&) = delete;
  TextureHandle& operator=(const TextureHandle&) = delete;
  TextureHandle(TextureHandle&& o) noexcept
      : array(o.array), object(o.object), tracker(o.tracker), bytes(o.bytes) {
    o.array = nullptr; o.object = 0; o.tracker = nullptr; o.bytes = 0;
  }
  ~TextureHandle() {
    if (object) cudaDestroyTextureObject(object);
    if (array) cudaFreeArray(array);
    if (tracker) tracker->remove(bytes);
  }
};

cudaTextureAddressMode texture_address_mode(TextureWrap wrap) {
  switch (wrap) {
    case TextureWrap::ClampToEdge: return cudaAddressModeClamp;
    case TextureWrap::Repeat: return cudaAddressModeWrap;
    case TextureWrap::MirroredRepeat: return cudaAddressModeMirror;
  }
  throw std::runtime_error("unsupported texture wrap mode");
}

TextureHandle make_texture(const Texture& source, TextureData& out,
                           MemoryTracker& tracker) {
  TextureHandle h;
  h.tracker = &tracker;
  std::uint32_t w = 1, height = 1;
  cudaChannelFormatDesc channel{};
  cudaTextureReadMode read_mode = cudaReadModeElementType;
  float4 constant = make_float4(source.color.x, source.color.y, source.color.z, 1.0f);
  std::vector<std::uint8_t> rgba8_pixels;
  std::vector<float4> rgba32f_pixels;
  std::size_t element_size = sizeof(float4);
  if (source.type == TextureType::Image) {
    if (source.color_space == TextureColorSpace::Hdr) {
      ImageRgba32f image = load_hdr_avif_rgba32f(source.image_path);
      if (image.empty())
        throw std::runtime_error("empty HDR texture: " +
                                 source.image_path.string());
      w = image.width;
      height = image.height;
      const std::size_t pixel_count =
          static_cast<std::size_t>(w) * height;
      if (image.pixels.size() != pixel_count * 4u)
        throw std::runtime_error("HDR texture pixel buffer size mismatch: " +
                                 source.image_path.string());
      rgba32f_pixels.resize(pixel_count);
      for (std::size_t i = 0; i < pixel_count; ++i) {
        rgba32f_pixels[i] =
            make_float4(image.pixels[4u * i], image.pixels[4u * i + 1u],
                        image.pixels[4u * i + 2u],
                        image.pixels[4u * i + 3u]);
      }
      channel = cudaCreateChannelDesc<float4>();
    } else {
      ImageRgba8 image =
          load_avif_rgba8(source.image_path, source.color_space);
      if (image.empty())
        throw std::runtime_error("empty texture: " +
                                 source.image_path.string());
      w = image.width;
      height = image.height;
      rgba8_pixels = std::move(image.pixels);
      channel = cudaCreateChannelDesc<uchar4>();
      read_mode = cudaReadModeNormalizedFloat;
      element_size = sizeof(uchar4);
    }
    h.bytes = static_cast<std::size_t>(w) * height * element_size;
  } else {
    channel = cudaCreateChannelDesc<float4>();
    h.bytes = sizeof(float4);
  }
  check_cuda(cudaMallocArray(&h.array, &channel, w, height), "cudaMallocArray");
  tracker.add(h.bytes);
  const void* src = &constant;
  if (!rgba8_pixels.empty()) src = rgba8_pixels.data();
  if (!rgba32f_pixels.empty()) src = rgba32f_pixels.data();
  const std::size_t pitch = static_cast<std::size_t>(w) * element_size;
  check_cuda(cudaMemcpy2DToArray(h.array, 0, 0, src, pitch, pitch, height,
                                 cudaMemcpyHostToDevice), "cudaMemcpy2DToArray");
  cudaResourceDesc rd{}; rd.resType = cudaResourceTypeArray; rd.res.array.array = h.array;
  cudaTextureDesc td{};
  td.addressMode[0] = texture_address_mode(source.wrap_u);
  td.addressMode[1] = texture_address_mode(source.wrap_v);
  td.filterMode = cudaFilterModeLinear;
  td.readMode = read_mode;
  td.sRGB = source.type == TextureType::Image &&
                    source.color_space == TextureColorSpace::Srgb
                ? 1
                : 0;
  td.normalizedCoords = 1;
  check_cuda(cudaCreateTextureObject(&h.object, &rd, &td, nullptr),
             "cudaCreateTextureObject");
  out.object = static_cast<std::uint64_t>(h.object);
  return h;
}

TextureHandle make_environment_texture(const ImageRgb32f& source,
                                       MemoryTracker& tracker) {
  if (source.empty()) throw std::runtime_error("empty HDR environment");
  const std::size_t pixel_count = checked_product(
      static_cast<std::size_t>(source.width), source.height,
      "HDR environment pixel count");
  if (source.pixels.size() != checked_product(
          pixel_count, std::size_t{3}, "HDR environment component count")) {
    throw std::runtime_error("HDR environment pixel buffer size mismatch");
  }
  std::vector<float4> pixels(pixel_count);
  for (std::size_t i = 0; i < pixel_count; ++i) {
    pixels[i] = make_float4(source.pixels[3u * i],
                            source.pixels[3u * i + 1u],
                            source.pixels[3u * i + 2u], 1.0f);
  }

  TextureHandle handle;
  handle.tracker = &tracker;
  handle.bytes = checked_product(pixel_count, sizeof(float4),
                                 "HDR environment texture");
  const cudaChannelFormatDesc channel = cudaCreateChannelDesc<float4>();
  check_cuda(cudaMallocArray(&handle.array, &channel, source.width,
                             source.height),
             "cudaMallocArray(HDR environment)");
  tracker.add(handle.bytes);
  const std::size_t pitch = checked_product(
      static_cast<std::size_t>(source.width), sizeof(float4),
      "HDR environment pitch");
  check_cuda(cudaMemcpy2DToArray(
                 handle.array, 0, 0, pixels.data(), pitch, pitch,
                 source.height, cudaMemcpyHostToDevice),
             "cudaMemcpy2DToArray(HDR environment)");
  cudaResourceDesc resource{};
  resource.resType = cudaResourceTypeArray;
  resource.res.array.array = handle.array;
  cudaTextureDesc texture{};
  texture.addressMode[0] = cudaAddressModeWrap;
  texture.addressMode[1] = cudaAddressModeClamp;
  texture.filterMode = cudaFilterModeLinear;
  texture.readMode = cudaReadModeElementType;
  texture.normalizedCoords = 1;
  check_cuda(cudaCreateTextureObject(
                 &handle.object, &resource, &texture, nullptr),
             "cudaCreateTextureObject(HDR environment)");
  return handle;
}

std::vector<MaterialData> materials_for(const Scene& scene) {
  std::vector<MaterialData> result;
  for (const Material& m : scene.materials) {
    MaterialData d{}; d.base_color = f3(m.base_color); d.emission = f3(m.emission);
    d.roughness = m.roughness; d.ior = m.ior; d.texture_index = m.texture_id;
    d.metallic_roughness_texture_index =
        m.metallic_roughness_texture_id;
    d.normal_texture_index = m.normal_texture_id;
    d.normal_scale = m.normal_scale;
    d.absorption = f3(m.absorption);
    d.metallic = m.type == MaterialType::Metal ? 1.0f : m.metallic;
    d.type = m.type == MaterialType::Lambertian ? kMaterialLambertian :
             m.type == MaterialType::Metal ? kMaterialMetal :
             m.type == MaterialType::Dielectric ? kMaterialDielectric :
             m.type == MaterialType::Water ? kMaterialWater :
             m.type == MaterialType::Pbr ? kMaterialPbr :
             kMaterialEmitter;
    if (m.type == MaterialType::Emitter &&
        max_component(m.emission) <= 0.0f)
      d.emission = make_float3(1.0f, 1.0f, 1.0f);
    result.push_back(d);
  }
  return result;
}

std::vector<LightData> lights_for(
    const Scene& scene, const FiniteLightDistribution& distribution) {
  if (distribution.probabilities.size() != distribution.indices.size()) {
    throw std::runtime_error("finite-light probability count mismatch");
  }
  if (distribution.cdf.size() != distribution.indices.size() + 1u) {
    throw std::runtime_error("finite-light CDF size mismatch");
  }
  std::vector<float> selection_probabilities(scene.lights.size(), 0.0f);
  for (std::size_t slot = 0; slot < distribution.indices.size(); ++slot) {
    const std::size_t light_index = distribution.indices[slot];
    if (light_index >= scene.lights.size()) {
      throw std::runtime_error("finite-light index is out of range");
    }
    selection_probabilities[light_index] = distribution.probabilities[slot];
  }
  std::vector<LightData> result;
  result.reserve(scene.lights.size());
  for (std::size_t light_index = 0; light_index < scene.lights.size();
       ++light_index) {
    const Light& l = scene.lights[light_index];
    LightData d{}; d.emission = f3(l.emission); d.geometry_index = l.object_id;
    d.selection_pdf = selection_probabilities[light_index];
    if (l.type == LightType::Rectangle) {
      d.type = kLightRectangle;
      d.p0 = f3(l.position); d.edge_u = f3(l.edge_u); d.edge_v = f3(l.edge_v);
      d.area = length(cross(l.edge_u, l.edge_v));
      d.normal = f3(normalize(cross(l.edge_u, l.edge_v)));
    } else if (l.type == LightType::Disk) {
      Vec3 u, v;
      const Vec3 normal = normalize(l.normal);
      basis(normal, u, v);
      d.type = kLightDisk;
      d.p0 = f3(l.position);
      d.edge_u = f3(u); d.edge_v = f3(v); d.normal = f3(normal);
      d.radius = l.radius;
      d.area = 3.14159265358979323846f * l.radius * l.radius;
    } else if (l.type == LightType::Sphere) {
      d.type = kLightSphere;
      d.p0 = f3(l.position);
      d.radius = l.radius;
      d.area = 4.0f * 3.14159265358979323846f * l.radius * l.radius;
    } else if (l.type == LightType::Flame) {
      d.type = kLightFlame;
      d.p0 = f3(l.position);
      d.axis = f3(l.axis);
      d.height = l.height;
      d.radius_start = l.radius_start;
      d.radius_end = l.radius_end;
      d.emission_start = f3(l.emission_start);
      d.emission_end = f3(l.emission_end);
      d.extinction = l.extinction;
      d.density_scale = l.density_scale;
      d.turbulence = l.turbulence;
      d.noise_scale = l.noise_scale;
      d.seed = l.seed;
    } else if (l.type == LightType::Point) {
      d.type = kLightPoint;
      d.p0 = f3(l.position);
      d.geometry_index = kInvalidIndex;
    } else {
      d.type = kLightDirectional;
      d.axis = f3(l.axis);
      d.geometry_index = kInvalidIndex;
    }
    result.push_back(d);
  }
  return result;
}

DeviceGeometryData geometry_for(const Scene& scene, const Object& object,
                                std::size_t object_index) {
  DeviceGeometryData d{};
  d.material_front = object.front_material; d.material_back = object.back_material;
  d.alpha_texture = object.alpha_texture; d.alpha_cutoff = object.alpha_cutoff;
  for (std::size_t i = 0; i < scene.lights.size(); ++i) {
    if (scene.lights[i].object_id == static_cast<std::int32_t>(object_index))
      d.light_index = static_cast<int>(i);
  }
  if (object.type == GeometryType::Sphere) {
    const auto& g = std::get<SphereData>(object.geometry);
    const bool water_scene = std::any_of(
        scene.objects.begin(), scene.objects.end(), [](const Object& candidate) {
          return candidate.type == GeometryType::WaterSurface;
        });
    const auto is_dielectric = [&](std::int32_t material_id) {
      return material_id >= 0 &&
             static_cast<std::size_t>(material_id) < scene.materials.size() &&
             scene.materials[static_cast<std::size_t>(material_id)].type ==
                 MaterialType::Dielectric;
    };
    const bool needs_solid_boundary = water_scene &&
        (is_dielectric(object.front_material) ||
         is_dielectric(object.back_material));
    d.primitive_type = needs_solid_boundary
        ? kPrimitiveSolidSphere : kPrimitiveSphere;
    d.p0 = f3(g.center);
    d.radius = g.radius;
    if (needs_solid_boundary) {
      const Vec3 extent{g.radius + 1.0e-5f};
      d.aabb_min = f3(g.center - extent);
      d.aabb_max = f3(g.center + extent);
    }
  } else if (object.type == GeometryType::Rectangle) {
    const auto& g = std::get<RectangleData>(object.geometry);
    d.primitive_type = kPrimitiveTriangle;
    d.p0 = f3(g.p1);
    d.p1 = f3(g.p2);
    d.p2 = f3(g.p3);
  } else if (object.type == GeometryType::Disk) {
    const auto& g = std::get<DiskData>(object.geometry); Vec3 u,v; basis(g.normal,u,v);
    const Vec3 n=normalize(g.normal), e{
      g.radius*std::sqrt(std::max(0.0f,1-n.x*n.x)),
      g.radius*std::sqrt(std::max(0.0f,1-n.y*n.y)),
      g.radius*std::sqrt(std::max(0.0f,1-n.z*n.z))};
    d.primitive_type=kPrimitiveDisk; d.p0=f3(g.center); d.p1=f3(n); d.p2=f3(u); d.radius=g.radius;
    d.aabb_min=f3(g.center-e-Vec3{1e-5f}); d.aabb_max=f3(g.center+e+Vec3{1e-5f});
  } else if (object.type == GeometryType::Cylinder) {
    const auto& g=std::get<CylinderData>(object.geometry); const Vec3 a=normalize(g.axis), top=g.base+a*g.height;
    const Vec3 e{g.radius*std::sqrt(std::max(0.0f,1-a.x*a.x)),
                 g.radius*std::sqrt(std::max(0.0f,1-a.y*a.y)),
                 g.radius*std::sqrt(std::max(0.0f,1-a.z*a.z))};
    const Vec3 lo{std::min(g.base.x,top.x),std::min(g.base.y,top.y),std::min(g.base.z,top.z)};
    const Vec3 hi{std::max(g.base.x,top.x),std::max(g.base.y,top.y),std::max(g.base.z,top.z)};
    d.primitive_type=kPrimitiveCylinder; d.p0=f3(g.base); d.p1=f3(a); d.radius=g.radius; d.height=g.height;
    d.aabb_min=f3(lo-e); d.aabb_max=f3(hi+e);
  } else if (object.type == GeometryType::Parabola) {
    const auto& g=std::get<ParabolaData>(object.geometry);
    d.primitive_type=kPrimitiveParabola; d.p0=f3(g.origin); d.p1=f3(normalize(g.normal)); d.p2=f3(g.focus);
    d.aabb_min=f3(g.clip.min); d.aabb_max=f3(g.clip.max);
  } else if (object.type == GeometryType::Mesh) {
    d.primitive_type = kPrimitiveMesh;
  } else if (object.type == GeometryType::WaterSurface) {
    const auto& g = std::get<WaterSurfaceData>(object.geometry);
    d.primitive_type = kPrimitiveWaterSurface;
    d.p0 = f3(g.center);
    d.water_size = make_float2(g.size.x, g.size.y);
    d.water_wave_count = g.wave_count;
    d.water_tiles_x = g.tiles_x;
    d.water_tiles_z = g.tiles_z;
    float total_amplitude = 0.0f;
    for (std::uint32_t i = 0; i < g.wave_count; ++i) {
      const WaterWave& wave = g.waves[i];
      d.water_waves[i].direction =
          make_float2(wave.direction.x, wave.direction.y);
      d.water_waves[i].amplitude = wave.amplitude;
      d.water_waves[i].wave_number =
          2.0f * 3.14159265358979323846f / wave.wavelength;
      d.water_waves[i].phase = wave.phase_radians;
      total_amplitude += wave.amplitude;
    }
    const Vec3 half_extent{0.5f * g.size.x, total_amplitude,
                           0.5f * g.size.y};
    d.aabb_min = f3(g.center - half_extent);
    d.aabb_max = f3(g.center + half_extent);
  } else {
    throw std::runtime_error("unsupported object geometry type");
  }
  if (d.primitive_type == kPrimitiveDisk ||
      d.primitive_type == kPrimitiveCylinder ||
      d.primitive_type == kPrimitiveParabola ||
      d.primitive_type == kPrimitiveWaterSurface ||
      d.primitive_type == kPrimitiveSolidSphere) {
    d.aabb_min = make_float3(next_float_down(d.aabb_min.x),
                             next_float_down(d.aabb_min.y),
                             next_float_down(d.aabb_min.z));
    d.aabb_max = make_float3(next_float_up(d.aabb_max.x),
                             next_float_up(d.aabb_max.y),
                             next_float_up(d.aabb_max.z));
  }
  return d;
}

struct Gas { DeviceBuffer output; OptixTraversableHandle handle=0; };

Gas compact_gas(OptixDeviceContext context, cudaStream_t stream,
                const OptixBuildInput& input, MemoryTracker& tracker) {
  OptixAccelBuildOptions options{}; options.buildFlags=kGasBuildFlags;
  options.operation=OPTIX_BUILD_OPERATION_BUILD;
  OptixAccelBufferSizes sizes{};
  check_optix(optixAccelComputeMemoryUsage(context,&options,&input,1,&sizes),
              "optixAccelComputeMemoryUsage");
  DeviceBuffer temp(tracker,sizes.tempSizeInBytes), output(tracker,sizes.outputSizeInBytes);
  DeviceBuffer size_device(tracker,sizeof(std::uint64_t));
  size_device.clear(stream);
  OptixAccelEmitDesc emit{}; emit.type=OPTIX_PROPERTY_TYPE_COMPACTED_SIZE; emit.result=size_device.pointer();
  OptixTraversableHandle handle=0;
  check_optix(optixAccelBuild(context,stream,&options,&input,1,temp.pointer(),temp.size(),
                              output.pointer(),output.size(),&handle,&emit,1),
              "optixAccelBuild");
  std::uint64_t compact_size=0; size_device.download(&compact_size,sizeof(compact_size),stream);
  check_cuda(cudaStreamSynchronize(stream),"cudaStreamSynchronize(GAS)");
  temp.reset(); size_device.reset();
  if (compact_size && compact_size < output.size()) {
    DeviceBuffer compact(tracker,compact_size); OptixTraversableHandle compact_handle=0;
    check_optix(optixAccelCompact(context,stream,handle,compact.pointer(),compact.size(),
                                  &compact_handle),"optixAccelCompact");
    check_cuda(cudaStreamSynchronize(stream),"cudaStreamSynchronize(compact)");
    return {std::move(compact),compact_handle};
  }
  return {std::move(output),handle};
}

struct MeshGpu {
  DeviceBuffer positions;
  DeviceBuffer normals;
  DeviceBuffer texcoords;
  DeviceBuffer tangents;
  DeviceBuffer indices;
  DeviceBuffer material_ids;
  Gas gas;

  DeviceMeshData device_data(const MeshResource& resource) const {
    const TriangleMesh& mesh = resource.mesh;
    DeviceMeshData data{};
    data.positions = reinterpret_cast<const float3*>(positions.pointer());
    data.normals = reinterpret_cast<const float3*>(normals.pointer());
    data.texcoords = reinterpret_cast<const float2*>(texcoords.pointer());
    data.corner_tangents =
        reinterpret_cast<const float4*>(tangents.pointer());
    data.indices = reinterpret_cast<const uint3*>(indices.pointer());
    data.material_ids = reinterpret_cast<const std::int32_t*>(
        material_ids.pointer());
    data.vertex_count = checked_u32(mesh.positions.size(), "mesh vertex count");
    data.triangle_count = checked_u32(mesh.indices.size(), "mesh triangle count");
    data.material_id_count = checked_u32(resource.material_ids.size(),
                                         "mesh material id count");
    if (!mesh.normals.empty()) data.flags |= kMeshHasNormals;
    if (mesh.has_complete_uvs()) data.flags |= kMeshHasTexcoords;
    if (mesh.has_complete_tangents()) data.flags |= kMeshHasTangents;
    if (!resource.material_ids.empty()) data.flags |= kMeshHasMaterials;
    return data;
  }
};

MeshGpu build_mesh(OptixDeviceContext context, cudaStream_t stream,
                   const MeshResource& resource, std::size_t material_count,
                   MemoryTracker& tracker) {
  const TriangleMesh& mesh = resource.mesh;
  if (mesh.empty())
    throw std::runtime_error("mesh is empty: " + resource.name);
  if (mesh.normals.size() != mesh.positions.size())
    throw std::runtime_error("mesh normals are incomplete: " + resource.name);
  if (!mesh.texcoords.empty() && !mesh.has_complete_uvs())
    throw std::runtime_error("mesh texture coordinates are incomplete: " + resource.name);
  if (!resource.material_ids.empty() &&
      resource.material_ids.size() != mesh.indices.size())
    throw std::runtime_error("mesh material ids are incomplete: " + resource.name);
  for (std::int32_t material_id : resource.material_ids) {
    if (material_id < 0 ||
        static_cast<std::size_t>(material_id) >= material_count)
      throw std::runtime_error("mesh material id is invalid: " + resource.name);
  }

  MeshGpu result;
  result.positions.allocate(tracker, mesh.positions.size() * sizeof(Vec3));
  result.normals.allocate(tracker, mesh.normals.size() * sizeof(Vec3));
  result.indices.allocate(tracker, mesh.indices.size() * sizeof(MeshTriangle));
  if (!mesh.texcoords.empty())
    result.texcoords.allocate(tracker, mesh.texcoords.size() * sizeof(Vec2));
  if (!mesh.tangents.empty())
    result.tangents.allocate(
        tracker, mesh.tangents.size() * sizeof(MeshTangent));
  if (!resource.material_ids.empty())
    result.material_ids.allocate(
        tracker, checked_product(resource.material_ids.size(),
                                 sizeof(std::int32_t), "mesh material ids"));
  result.positions.upload(mesh.positions, stream);
  result.normals.upload(mesh.normals, stream);
  result.indices.upload(mesh.indices, stream);
  if (!mesh.texcoords.empty()) result.texcoords.upload(mesh.texcoords, stream);
  if (!mesh.tangents.empty()) result.tangents.upload(mesh.tangents, stream);
  if (!resource.material_ids.empty())
    result.material_ids.upload(resource.material_ids, stream);

  unsigned int flag = OPTIX_GEOMETRY_FLAG_NONE;
  CUdeviceptr vertex_pointer = result.positions.pointer();
  OptixBuildInput input{};
  input.type = OPTIX_BUILD_INPUT_TYPE_TRIANGLES;
  input.triangleArray.vertexBuffers = &vertex_pointer;
  input.triangleArray.numVertices =
      checked_u32(mesh.positions.size(), "mesh vertex count");
  input.triangleArray.vertexFormat = OPTIX_VERTEX_FORMAT_FLOAT3;
  input.triangleArray.vertexStrideInBytes = sizeof(Vec3);
  input.triangleArray.indexBuffer = result.indices.pointer();
  input.triangleArray.numIndexTriplets =
      checked_u32(mesh.indices.size(), "mesh triangle count");
  input.triangleArray.indexFormat = OPTIX_INDICES_FORMAT_UNSIGNED_INT3;
  input.triangleArray.indexStrideInBytes = sizeof(MeshTriangle);
  input.triangleArray.flags = &flag;
  input.triangleArray.numSbtRecords = 1;
  input.triangleArray.transformFormat = OPTIX_TRANSFORM_FORMAT_NONE;
  result.gas = compact_gas(context, stream, input, tracker);
  return result;
}

Gas build_object(OptixDeviceContext context, cudaStream_t stream,
                 const Object& object, const DeviceGeometryData& g,
                 MemoryTracker& tracker) {
  if (object.type == GeometryType::Mesh)
    throw std::runtime_error("mesh objects must use a shared mesh GAS");
  unsigned int flag=OPTIX_GEOMETRY_FLAG_NONE; OptixBuildInput input{};
  DeviceBuffer a(tracker,0), b(tracker,0); CUdeviceptr ap=0,bp=0;
  if (object.type == GeometryType::Sphere &&
      g.primitive_type == kPrimitiveSphere) {
    a.allocate(tracker,sizeof(float3)); b.allocate(tracker,sizeof(float));
    a.upload(&g.p0,sizeof(float3),stream); b.upload(&g.radius,sizeof(float),stream);
    ap=a.pointer(); bp=b.pointer(); input.type=OPTIX_BUILD_INPUT_TYPE_SPHERES;
    input.sphereArray.vertexBuffers=&ap; input.sphereArray.numVertices=1;
    input.sphereArray.vertexStrideInBytes=sizeof(float3); input.sphereArray.radiusBuffers=&bp;
    input.sphereArray.radiusStrideInBytes=sizeof(float); input.sphereArray.singleRadius=1;
    input.sphereArray.flags=&flag; input.sphereArray.numSbtRecords=1;
  } else if (object.type == GeometryType::Rectangle) {
    const float3 p3=make_float3(g.p0.x+g.p2.x-g.p1.x,g.p0.y+g.p2.y-g.p1.y,g.p0.z+g.p2.z-g.p1.z);
    const std::array<float3,4> vertices{g.p0,g.p1,g.p2,p3};
    const std::array<uint3,2> indices{make_uint3(0,1,2),make_uint3(0,2,3)};
    a.allocate(tracker,sizeof(vertices)); b.allocate(tracker,sizeof(indices));
    a.upload(vertices.data(),sizeof(vertices),stream); b.upload(indices.data(),sizeof(indices),stream);
    ap=a.pointer(); input.type=OPTIX_BUILD_INPUT_TYPE_TRIANGLES;
    input.triangleArray.vertexBuffers=&ap; input.triangleArray.numVertices=4;
    input.triangleArray.vertexFormat=OPTIX_VERTEX_FORMAT_FLOAT3;
    input.triangleArray.vertexStrideInBytes=sizeof(float3); input.triangleArray.indexBuffer=b.pointer();
    input.triangleArray.numIndexTriplets=2; input.triangleArray.indexFormat=OPTIX_INDICES_FORMAT_UNSIGNED_INT3;
    input.triangleArray.indexStrideInBytes=sizeof(uint3); input.triangleArray.flags=&flag;
    input.triangleArray.numSbtRecords=1; input.triangleArray.transformFormat=OPTIX_TRANSFORM_FORMAT_NONE;
  } else if (object.type == GeometryType::WaterSurface) {
    const std::uint64_t tile_count =
        static_cast<std::uint64_t>(g.water_tiles_x) * g.water_tiles_z;
    if (tile_count == 0u || tile_count > 4096u)
      throw std::runtime_error("water surface has an invalid tile count");
    std::vector<OptixAabb> boxes(static_cast<std::size_t>(tile_count));
    const float minimum_x = g.p0.x - 0.5f * g.water_size.x;
    const float minimum_z = g.p0.z - 0.5f * g.water_size.y;
    const float tile_width = g.water_size.x / g.water_tiles_x;
    const float tile_depth = g.water_size.y / g.water_tiles_z;
    constexpr float overlap = 1.0e-5f;
    for (std::uint32_t z = 0; z < g.water_tiles_z; ++z) {
      for (std::uint32_t x = 0; x < g.water_tiles_x; ++x) {
        const std::size_t index =
            static_cast<std::size_t>(z) * g.water_tiles_x + x;
        const float x0 = minimum_x + tile_width * static_cast<float>(x);
        const float x1 =
            minimum_x + tile_width * static_cast<float>(x + 1u);
        const float z0 = minimum_z + tile_depth * static_cast<float>(z);
        const float z1 =
            minimum_z + tile_depth * static_cast<float>(z + 1u);
        boxes[index] = outward_aabb(
            x0 - overlap, g.aabb_min.y - overlap, z0 - overlap,
            x1 + overlap, g.aabb_max.y + overlap, z1 + overlap);
      }
    }
    a.allocate(tracker, boxes.size() * sizeof(OptixAabb));
    a.upload(boxes, stream);
    ap = a.pointer();
    input.type = OPTIX_BUILD_INPUT_TYPE_CUSTOM_PRIMITIVES;
    input.customPrimitiveArray.aabbBuffers = &ap;
    input.customPrimitiveArray.numPrimitives =
        checked_u32(boxes.size(), "water tile count");
    input.customPrimitiveArray.strideInBytes = sizeof(OptixAabb);
    input.customPrimitiveArray.flags = &flag;
    input.customPrimitiveArray.numSbtRecords = 1;
  } else {
    constexpr float clip = kCustomPrimitiveClipTolerance;
    const OptixAabb box = outward_aabb(
        g.aabb_min.x - clip, g.aabb_min.y - clip, g.aabb_min.z - clip,
        g.aabb_max.x + clip, g.aabb_max.y + clip, g.aabb_max.z + clip);
    a.allocate(tracker,sizeof(box)); a.upload(&box,sizeof(box),stream); ap=a.pointer();
    input.type=OPTIX_BUILD_INPUT_TYPE_CUSTOM_PRIMITIVES;
    input.customPrimitiveArray.aabbBuffers=&ap; input.customPrimitiveArray.numPrimitives=1;
    input.customPrimitiveArray.strideInBytes=sizeof(OptixAabb);
    input.customPrimitiveArray.flags=&flag; input.customPrimitiveArray.numSbtRecords=1;
  }
  return compact_gas(context,stream,input,tracker);
}
struct Programs {
  OptixProgramGroup raygen = nullptr;
  std::array<OptixProgramGroup, kRayTypeCount> miss{};
  std::array<std::array<OptixProgramGroup, kRayTypeCount>, 8> hit{};
};

std::vector<char> load_module_input() {
  std::ifstream input(SPECTRALDOCK_OPTIX_MODULE_INPUT_PATH, std::ios::binary);
  if (!input)
    throw std::runtime_error(std::string("cannot open OptiX module input: ") +
                             SPECTRALDOCK_OPTIX_MODULE_INPUT_PATH);
  input.seekg(0, std::ios::end);
  const std::streamoff size = input.tellg();
  if (size <= 0) throw std::runtime_error("OptiX module input is empty");
  std::vector<char> bytes(static_cast<std::size_t>(size));
  input.seekg(0, std::ios::beg);
  input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
  if (!input) throw std::runtime_error("failed to read OptiX module input");
  return bytes;
}

OptixProgramGroup make_program(OptixState& state,
                               const OptixProgramGroupDesc& desc) {
  std::array<char, 8192> log{};
  std::size_t log_size = log.size();
  OptixProgramGroupOptions options{};
  OptixProgramGroup group = nullptr;
  const OptixResult status =
      optixProgramGroupCreate(state.context, &desc, 1, &options,
                              log.data(), &log_size, &group);
  check_optix(status, "optixProgramGroupCreate", log.data(), log_size);
  state.groups.push_back(group);
  return group;
}

Programs create_pipeline(OptixState& state) {
  const std::vector<char> module_input = load_module_input();
  OptixModuleCompileOptions module_options{};
  module_options.maxRegisterCount = OPTIX_COMPILE_DEFAULT_MAX_REGISTER_COUNT;
  module_options.optLevel = OPTIX_COMPILE_OPTIMIZATION_DEFAULT;
  module_options.debugLevel = OPTIX_COMPILE_DEBUG_LEVEL_MODERATE;

  OptixPipelineCompileOptions pipeline_options{};
  pipeline_options.usesMotionBlur = false;
  pipeline_options.traversableGraphFlags =
      OPTIX_TRAVERSABLE_GRAPH_FLAG_ALLOW_SINGLE_LEVEL_INSTANCING;
  pipeline_options.numPayloadValues = 2;
  pipeline_options.numAttributeValues = 2;
  pipeline_options.exceptionFlags = OPTIX_EXCEPTION_FLAG_STACK_OVERFLOW;
  pipeline_options.pipelineLaunchParamsVariableName = "params";
  pipeline_options.usesPrimitiveTypeFlags =
      OPTIX_PRIMITIVE_TYPE_FLAGS_TRIANGLE |
      OPTIX_PRIMITIVE_TYPE_FLAGS_SPHERE |
      OPTIX_PRIMITIVE_TYPE_FLAGS_CUSTOM;
  pipeline_options.pipelineLaunchParamsSizeInBytes = sizeof(LaunchParams);

  std::array<char, 8192> log{};
  std::size_t log_size = log.size();
  OptixResult status =
      optixModuleCreate(state.context, &module_options, &pipeline_options,
                        module_input.data(), module_input.size(), log.data(),
                        &log_size, &state.module);
  check_optix(status, "optixModuleCreate", log.data(), log_size);

  OptixBuiltinISOptions sphere_options{};
  sphere_options.builtinISModuleType = OPTIX_PRIMITIVE_TYPE_SPHERE;
  sphere_options.usesMotionBlur = false;
  sphere_options.buildFlags = kGasBuildFlags;
  check_optix(optixBuiltinISModuleGet(
                  state.context, &module_options, &pipeline_options,
                  &sphere_options, &state.sphere_module),
              "optixBuiltinISModuleGet");

  Programs programs;
  OptixProgramGroupDesc desc{};
  desc.kind = OPTIX_PROGRAM_GROUP_KIND_RAYGEN;
  desc.raygen.module = state.module;
  desc.raygen.entryFunctionName = "__raygen__pathtrace";
  programs.raygen = make_program(state, desc);

  desc = {};
  desc.kind = OPTIX_PROGRAM_GROUP_KIND_MISS;
  desc.miss.module = state.module;
  desc.miss.entryFunctionName = "__miss__radiance";
  programs.miss[kRayRadiance] = make_program(state, desc);
  desc.miss.entryFunctionName = "__miss__shadow";
  programs.miss[kRayShadow] = make_program(state, desc);

  const std::array<const char*, 8> intersections = {
      nullptr, nullptr, "__intersection__disk",
      "__intersection__cylinder", "__intersection__parabola", nullptr,
      "__intersection__water_surface", "__intersection__solid_sphere"};
  for (unsigned int primitive = 0; primitive < programs.hit.size();
       ++primitive) {
    for (unsigned int ray = 0; ray < kRayTypeCount; ++ray) {
      desc = {};
      desc.kind = OPTIX_PROGRAM_GROUP_KIND_HITGROUP;
      desc.hitgroup.moduleCH = state.module;
      desc.hitgroup.entryFunctionNameCH =
          ray == kRayRadiance ? "__closesthit__radiance"
                              : "__closesthit__shadow";
      desc.hitgroup.moduleAH = state.module;
      desc.hitgroup.entryFunctionNameAH =
          ray == kRayRadiance ? "__anyhit__alpha_radiance"
                              : "__anyhit__alpha_shadow";
      if (primitive == kPrimitiveSphere) {
        desc.hitgroup.moduleIS = state.sphere_module;
      } else if (primitive == kPrimitiveDisk ||
                 primitive == kPrimitiveCylinder ||
                 primitive == kPrimitiveParabola ||
                 primitive == kPrimitiveWaterSurface ||
                 primitive == kPrimitiveSolidSphere) {
        desc.hitgroup.moduleIS = state.module;
        desc.hitgroup.entryFunctionNameIS = intersections[primitive];
      }
      programs.hit[primitive][ray] = make_program(state, desc);
    }
  }

  OptixPipelineLinkOptions link{};
  link.maxTraceDepth = 1;
  log_size = log.size();
  status = optixPipelineCreate(
      state.context, &pipeline_options, &link, state.groups.data(),
      checked_u32(state.groups.size(), "program group count"),
      log.data(), &log_size, &state.pipeline);
  check_optix(status, "optixPipelineCreate", log.data(), log_size);
  check_optix(optixPipelineSetStackSize(
                  state.pipeline, 0, 0, 4096, kMaxTraversableDepth),
              "optixPipelineSetStackSize");
  return programs;
}

Gas build_ias(OptixDeviceContext context, cudaStream_t stream,
              const Scene& scene,
              const std::vector<OptixTraversableHandle>& handles,
              MemoryTracker& tracker) {
  if (handles.empty()) throw std::runtime_error("scene has no geometry");
  if (handles.size() != scene.objects.size())
    throw std::runtime_error("IAS instance/object count mismatch");
  std::vector<OptixInstance> instances(handles.size());
  const float identity[12] =
      {1,0,0,0, 0,1,0,0, 0,0,1,0};
  for (std::size_t i = 0; i < handles.size(); ++i) {
    OptixInstance& instance = instances[i];
    if (scene.objects[i].type == GeometryType::Mesh) {
      const auto& mesh = std::get<MeshInstanceData>(scene.objects[i].geometry);
      const TransformMatrix3x4 transform = compose_transform(mesh.transform);
      std::memcpy(instance.transform, transform.data(), sizeof(instance.transform));
    } else {
      std::memcpy(instance.transform, identity, sizeof(identity));
    }
    instance.instanceId = checked_u32(i, "instance id");
    instance.sbtOffset =
        checked_u32(i * kRayTypeCount, "instance SBT offset");
    instance.visibilityMask = 255;
    instance.flags = OPTIX_INSTANCE_FLAG_NONE;
    instance.traversableHandle = handles[i];
  }
  DeviceBuffer instance_buffer(
      tracker, instances.size() * sizeof(OptixInstance));
  instance_buffer.upload(instances, stream);
  CUdeviceptr instances_pointer = instance_buffer.pointer();
  OptixBuildInput input{};
  input.type = OPTIX_BUILD_INPUT_TYPE_INSTANCES;
  input.instanceArray.instances = instances_pointer;
  input.instanceArray.numInstances =
      checked_u32(instances.size(), "instance count");
  return compact_gas(context, stream, input, tracker);
}

struct EmptySbtData {};
template <typename T>
struct alignas(OPTIX_SBT_RECORD_ALIGNMENT) SbtRecord {
  char header[OPTIX_SBT_RECORD_HEADER_SIZE]{};
  T data{};
};

struct SbtStorage {
  DeviceBuffer raygen;
  DeviceBuffer miss;
  DeviceBuffer hit;
  OptixShaderBindingTable table{};
};

SbtStorage make_sbt(const Programs& programs,
                    const std::vector<HitgroupData>& hitgroups,
                    MemoryTracker& tracker) {
  SbtStorage storage;
  SbtRecord<EmptySbtData> raygen{};
  check_optix(optixSbtRecordPackHeader(programs.raygen, &raygen),
              "optixSbtRecordPackHeader(raygen)");
  storage.raygen.allocate(tracker, sizeof(raygen));
  storage.raygen.upload(&raygen, sizeof(raygen));

  std::array<SbtRecord<EmptySbtData>, kRayTypeCount> misses{};
  for (unsigned int ray = 0; ray < kRayTypeCount; ++ray)
    check_optix(optixSbtRecordPackHeader(programs.miss[ray], &misses[ray]),
                "optixSbtRecordPackHeader(miss)");
  storage.miss.allocate(tracker, sizeof(misses));
  storage.miss.upload(misses.data(), sizeof(misses));

  std::vector<SbtRecord<HitgroupData>> hits;
  hits.reserve(hitgroups.size() * kRayTypeCount);
  for (const HitgroupData& hitgroup : hitgroups) {
    const DeviceGeometryData& geometry = hitgroup.geometry;
    if (geometry.primitive_type < 0 ||
        static_cast<std::size_t>(geometry.primitive_type) >= programs.hit.size())
      throw std::runtime_error("invalid device primitive type");
    for (unsigned int ray = 0; ray < kRayTypeCount; ++ray) {
      SbtRecord<HitgroupData> record{};
      record.data = hitgroup;
      check_optix(
          optixSbtRecordPackHeader(
              programs.hit[geometry.primitive_type][ray], &record),
          "optixSbtRecordPackHeader(hit)");
      hits.push_back(record);
    }
  }
  storage.hit.allocate(tracker, hits.size() * sizeof(hits.front()));
  storage.hit.upload(hits);

  storage.table.raygenRecord = storage.raygen.pointer();
  storage.table.missRecordBase = storage.miss.pointer();
  storage.table.missRecordStrideInBytes = sizeof(misses[0]);
  storage.table.missRecordCount = kRayTypeCount;
  storage.table.hitgroupRecordBase = storage.hit.pointer();
  storage.table.hitgroupRecordStrideInBytes = sizeof(hits[0]);
  storage.table.hitgroupRecordCount =
      checked_u32(hits.size(), "hit record count");
  return storage;
}

CameraData camera_for(const Scene& scene, const RenderSettings& settings) {
  const Vec3 w = normalize(scene.camera.look_from - scene.camera.look_at);
  const Vec3 u = normalize(cross(scene.camera.up, w));
  const Vec3 v = cross(w, u);
  CameraData camera{};
  camera.origin = f3(scene.camera.look_from);
  camera.u = f3(u);
  camera.v = f3(v);
  camera.w = f3(w);
  camera.tan_half_fov =
      std::tan(scene.camera.vertical_fov_degrees * kPi / 360.0f);
  camera.aspect =
      static_cast<float>(settings.width) / static_cast<float>(settings.height);
  camera.lens_radius = 0.5f * scene.camera.aperture;
  camera.focus_distance = scene.camera.focus_distance;
  return camera;
}

OptixImage2D image_2d(const DeviceBuffer& buffer,
                      unsigned int width, unsigned int height) {
  OptixImage2D image{};
  image.data = buffer.pointer();
  image.width = width;
  image.height = height;
  image.rowStrideInBytes =
      static_cast<std::size_t>(width) * sizeof(float4);
  image.pixelStrideInBytes = sizeof(float4);
  image.format = OPTIX_PIXEL_FORMAT_FLOAT4;
  return image;
}

OptixImage2D normal_image_2d(const DeviceBuffer& buffer,
                             unsigned int width, unsigned int height) {
  OptixImage2D image{};
  image.data = buffer.pointer();
  image.width = width;
  image.height = height;
  image.rowStrideInBytes =
      static_cast<std::size_t>(width) * sizeof(float3);
  image.pixelStrideInBytes = sizeof(float3);
  image.format = OPTIX_PIXEL_FORMAT_FLOAT3;
  return image;
}

DeviceBuffer run_denoiser(
    OptixState& state, cudaStream_t stream, MemoryTracker& tracker,
    const DeviceBuffer& beauty, const DeviceBuffer& albedo,
    const DeviceBuffer& normal, unsigned int width, unsigned int height) {
  OptixDenoiserOptions options{};
  options.guideAlbedo = 1;
  options.guideNormal = 1;
  check_optix(optixDenoiserCreate(
                  state.context, OPTIX_DENOISER_MODEL_KIND_HDR,
                  &options, &state.denoiser),
              "optixDenoiserCreate");
  OptixDenoiserSizes sizes{};
  check_optix(optixDenoiserComputeMemoryResources(
                  state.denoiser, width, height, &sizes),
              "optixDenoiserComputeMemoryResources");
  DeviceBuffer denoiser_state(tracker, sizes.stateSizeInBytes);
  DeviceBuffer scratch(tracker, sizes.withoutOverlapScratchSizeInBytes);
  DeviceBuffer intensity(tracker, sizeof(float));
  DeviceBuffer output(
      tracker, checked_product(
                   checked_product(width, height, "denoiser pixels"),
                   sizeof(float4), "denoiser output"));
  check_optix(optixDenoiserSetup(
                  state.denoiser, stream, width, height,
                  denoiser_state.pointer(), denoiser_state.size(),
                  scratch.pointer(), scratch.size()),
              "optixDenoiserSetup");

  const OptixImage2D beauty_image = image_2d(beauty, width, height);
  check_optix(optixDenoiserComputeIntensity(
                  state.denoiser, stream, &beauty_image,
                  intensity.pointer(), scratch.pointer(), scratch.size()),
              "optixDenoiserComputeIntensity");
  OptixDenoiserGuideLayer guide{};
  guide.albedo = image_2d(albedo, width, height);
  guide.normal = normal_image_2d(normal, width, height);
  OptixDenoiserLayer layer{};
  layer.input = beauty_image;
  layer.output = image_2d(output, width, height);
  OptixDenoiserParams parameters{};
  parameters.hdrIntensity = intensity.pointer();
  parameters.blendFactor = 0.0f;
  check_optix(optixDenoiserInvoke(
                  state.denoiser, stream, &parameters,
                  denoiser_state.pointer(), denoiser_state.size(),
                  &guide, &layer, 1, 0, 0,
                  scratch.pointer(), scratch.size()),
              "optixDenoiserInvoke");
  check_cuda(cudaStreamSynchronize(stream),
             "cudaStreamSynchronize(denoiser)");
  return output;
}

}  // namespace

RenderResult render_optix(const Scene& scene,
                          const RenderSettings& settings) {
  if (!settings.width || !settings.height || !settings.spp ||
      !settings.max_depth)
    throw std::runtime_error(
        "width, height, spp, and max-depth must be positive");
  if (settings.width > kMaximumAvifDimension ||
      settings.height > kMaximumAvifDimension) {
    throw std::runtime_error(
        "render width and height must be at most 16384");
  }
  const float clamp_direct =
      settings.clamp_direct.value_or(scene.integrator.clamp_direct);
  const float clamp_indirect =
      settings.clamp_indirect.value_or(scene.integrator.clamp_indirect);
  if (!std::isfinite(clamp_direct) || clamp_direct < 0.0f ||
      !std::isfinite(clamp_indirect) || clamp_indirect < 0.0f) {
    throw std::runtime_error(
        "clamp-direct and clamp-indirect must be finite and non-negative");
  }
  const std::size_t pixel_count =
      checked_product(settings.width, settings.height, "pixel count");
  if (pixel_count > kMaximumAvifPixels) {
    throw std::runtime_error("render pixel count must be at most 2^25");
  }
  const auto total_begin = std::chrono::steady_clock::now();

  if (settings.device < 0)
    throw std::runtime_error("CUDA device ordinal must be non-negative");
  check_cuda(cudaSetDevice(settings.device), "cudaSetDevice");
  check_cuda(cudaFree(nullptr), "cudaFree(context init)");
  Stream stream;
  CUcontext cuda_context = nullptr;
  check_cu(cuCtxGetCurrent(&cuda_context), "cuCtxGetCurrent");
  if (!cuda_context) throw std::runtime_error("CUDA context is null");
  MemoryTracker tracker;
  tracker.start();
  check_optix(optixInit(), "optixInit");

  OptixState optix;
  OptixDeviceContextOptions context_options{};
  context_options.logCallbackFunction = optix_log;
  context_options.logCallbackLevel = settings.validation ? 4 : 2;
  context_options.validationMode =
      settings.validation ? OPTIX_DEVICE_CONTEXT_VALIDATION_MODE_ALL
                          : OPTIX_DEVICE_CONTEXT_VALIDATION_MODE_OFF;
  check_optix(optixDeviceContextCreate(
                  cuda_context, &context_options, &optix.context),
              "optixDeviceContextCreate");
  const Programs programs = create_pipeline(optix);
  tracker.sample();

  std::vector<TextureData> texture_data(scene.textures.size());
  std::vector<TextureHandle> textures;
  textures.reserve(scene.textures.size());
  {
    NvtxRange range("texture upload");
    for (std::size_t i = 0; i < scene.textures.size(); ++i)
      textures.push_back(make_texture(
          scene.textures[i], texture_data[i], tracker));
  }
  ImageRgb32f environment_image;
  EnvironmentDistribution environment_distribution;
  std::vector<TextureHandle> environment_textures;
  environment_textures.reserve(1u);
  if (scene.background.type == BackgroundType::Environment) {
    NvtxRange range("HDR environment upload");
    environment_image = load_radiance_hdr(scene.background.environment_path);
    environment_distribution = build_environment_distribution(
        environment_image, scene.integrator.direct_light_sampling);
    environment_textures.push_back(
        make_environment_texture(environment_image, tracker));
  }
  std::vector<MaterialData> material_data = materials_for(scene);
  const FiniteLightDistribution finite_light_distribution =
      build_finite_light_distribution(
          scene.lights, scene.integrator.direct_light_sampling);
  std::vector<LightData> light_data =
      lights_for(scene, finite_light_distribution);
  std::vector<std::uint32_t> delta_light_indices;
  delta_light_indices.reserve(scene.lights.size());
  for (std::size_t i = 0; i < scene.lights.size(); ++i) {
    if (scene.lights[i].type == LightType::Point ||
        scene.lights[i].type == LightType::Directional) {
      delta_light_indices.push_back(checked_u32(i, "delta light index"));
    }
  }
  if (delta_light_indices.size() > 32u) {
    throw std::runtime_error("delta light count exceeds the limit of 32");
  }
  const std::size_t flame_count = static_cast<std::size_t>(std::count_if(
      scene.lights.begin(), scene.lights.end(), [](const Light& light) {
        return light.type == LightType::Flame;
      }));
  const std::size_t water_surface_count =
      static_cast<std::size_t>(std::count_if(
          scene.objects.begin(), scene.objects.end(), [](const Object& object) {
            return object.type == GeometryType::WaterSurface;
          }));

  DeviceBuffer material_buffer(
      tracker, material_data.size() * sizeof(MaterialData));
  DeviceBuffer texture_buffer(
      tracker, texture_data.size() * sizeof(TextureData));
  DeviceBuffer light_buffer(
      tracker, light_data.size() * sizeof(LightData));
  DeviceBuffer light_cdf_buffer(
      tracker, finite_light_distribution.cdf.size() * sizeof(float));
  DeviceBuffer sampled_light_index_buffer(
      tracker, finite_light_distribution.indices.size() *
                   sizeof(std::uint32_t));
  DeviceBuffer delta_light_index_buffer(
      tracker, delta_light_indices.size() * sizeof(std::uint32_t));
  DeviceBuffer environment_row_cdf_buffer(
      tracker, environment_distribution.row_cdf.size() * sizeof(float));
  DeviceBuffer environment_conditional_cdf_buffer(
      tracker,
      environment_distribution.conditional_cdf.size() * sizeof(float));
  material_buffer.upload(material_data);
  texture_buffer.upload(texture_data);
  light_buffer.upload(light_data);
  light_cdf_buffer.upload(finite_light_distribution.cdf);
  sampled_light_index_buffer.upload(finite_light_distribution.indices);
  delta_light_index_buffer.upload(delta_light_indices);
  environment_row_cdf_buffer.upload(environment_distribution.row_cdf);
  environment_conditional_cdf_buffer.upload(
      environment_distribution.conditional_cdf);

  Event bvh_start, bvh_end;
  bvh_start.record(stream);
  std::vector<HitgroupData> hitgroup_data;
  std::vector<Gas> primitive_gases;
  std::vector<MeshGpu> mesh_gpus;
  std::vector<OptixTraversableHandle> instance_handles;
  std::vector<std::int32_t> mesh_gpu_indices(scene.meshes.size(), -1);
  hitgroup_data.reserve(scene.objects.size());
  primitive_gases.reserve(scene.objects.size());
  mesh_gpus.reserve(scene.meshes.size());
  instance_handles.reserve(scene.objects.size());
  std::uint64_t unique_mesh_count = 0;
  std::uint64_t mesh_triangle_count = 0;
  Gas ias;
  {
    NvtxRange range("BVH build and compact");
    // Mesh GAS ownership is resource-based: each referenced OBJ is uploaded
    // and compacted exactly once, then any number of IAS instances may use it.
    for (const Object& object : scene.objects) {
      if (object.type != GeometryType::Mesh) continue;
      const auto& instance = std::get<MeshInstanceData>(object.geometry);
      if (instance.mesh_id < 0 ||
          static_cast<std::size_t>(instance.mesh_id) >= scene.meshes.size())
        throw std::runtime_error("mesh object has an invalid resource id: " + object.name);
      std::int32_t& gpu_index = mesh_gpu_indices[instance.mesh_id];
      if (gpu_index >= 0) continue;
      gpu_index = static_cast<std::int32_t>(mesh_gpus.size());
      const MeshResource& resource = scene.meshes[instance.mesh_id];
      mesh_triangle_count += resource.mesh.indices.size();
      mesh_gpus.push_back(build_mesh(
          optix.context, stream, resource, scene.materials.size(), tracker));
      ++unique_mesh_count;
    }

    for (std::size_t object_index = 0;
         object_index < scene.objects.size(); ++object_index) {
      const Object& object = scene.objects[object_index];
      HitgroupData hitgroup{};
      hitgroup.geometry = geometry_for(scene, object, object_index);
      if (object.type == GeometryType::Mesh) {
        const auto& instance = std::get<MeshInstanceData>(object.geometry);
        const std::int32_t gpu_index = mesh_gpu_indices[instance.mesh_id];
        if (gpu_index < 0)
          throw std::runtime_error("referenced mesh GAS was not built: " + object.name);
        MeshGpu& mesh_gpu = mesh_gpus[static_cast<std::size_t>(gpu_index)];
        hitgroup.mesh =
            mesh_gpu.device_data(scene.meshes[instance.mesh_id]);
        instance_handles.push_back(mesh_gpu.gas.handle);
      } else {
        primitive_gases.push_back(build_object(
            optix.context, stream, object, hitgroup.geometry, tracker));
        instance_handles.push_back(primitive_gases.back().handle);
      }
      hitgroup_data.push_back(hitgroup);
    }
    ias = build_ias(optix.context, stream, scene, instance_handles, tracker);
  }
  bvh_end.record(stream);
  bvh_end.wait();
  const double bvh_ms = bvh_end.elapsed(bvh_start);

  SbtStorage sbt = make_sbt(programs, hitgroup_data, tracker);
  const std::size_t float_image_bytes =
      checked_product(pixel_count, sizeof(float4), "float image");
  DeviceBuffer beauty(tracker, float_image_bytes);
  DeviceBuffer albedo(tracker, float_image_bytes);
  DeviceBuffer normal(
      tracker, checked_product(pixel_count, sizeof(float3), "normal guide"));
  DeviceBuffer ray_count(
      tracker, checked_product(pixel_count, sizeof(unsigned long long),
                               "ray counters"));
  DeviceBuffer volume_count(
      tracker, flame_count == 0u
                   ? 0u
                   : checked_product(pixel_count, sizeof(VolumeCounters),
                                     "volume counters"));
  DeviceBuffer water_count(
      tracker, water_surface_count == 0u
                   ? 0u
                   : checked_product(pixel_count, sizeof(WaterCounters),
                                     "water counters"));
  const bool firefly_clamp_enabled =
      clamp_direct > 0.0f || clamp_indirect > 0.0f;
  DeviceBuffer firefly_count(
      tracker, firefly_clamp_enabled ? sizeof(FireflyCounters) : 0u);
  beauty.clear(stream);
  albedo.clear(stream);
  normal.clear(stream);
  ray_count.clear(stream);
  volume_count.clear(stream);
  water_count.clear(stream);
  firefly_count.clear(stream);

  LaunchParams parameters{};
  parameters.traversable = ias.handle;
  parameters.beauty =
      reinterpret_cast<float4*>(beauty.pointer());
  parameters.albedo =
      reinterpret_cast<float4*>(albedo.pointer());
  parameters.normal =
      reinterpret_cast<float3*>(normal.pointer());
  parameters.width = settings.width;
  parameters.height = settings.height;
  parameters.spp = settings.spp;
  parameters.max_depth = settings.max_depth;
  parameters.seed = settings.seed;
  parameters.camera = camera_for(scene, settings);
  parameters.background_type =
      scene.background.type == BackgroundType::Sky
          ? kBackgroundSky
          : scene.background.type == BackgroundType::Environment
                ? kBackgroundEnvironment
                : kBackgroundConstant;
  parameters.background_color = f3(scene.background.color);
  parameters.sky_bottom = f3(scene.background.sky_bottom);
  parameters.sky_top = f3(scene.background.sky_top);
  parameters.sun_direction = f3(scene.background.sun_direction);
  parameters.sun_color = f3(scene.background.sun_color);
  parameters.sun_cos_angle = scene.background.sun_cos_angle;
  parameters.environment_texture = environment_textures.empty()
      ? 0u
      : static_cast<std::uint64_t>(environment_textures.front().object);
  parameters.environment_row_cdf = environment_distribution.row_cdf.empty()
      ? nullptr
      : reinterpret_cast<const float*>(environment_row_cdf_buffer.pointer());
  parameters.environment_conditional_cdf =
      environment_distribution.conditional_cdf.empty()
          ? nullptr
          : reinterpret_cast<const float*>(
                environment_conditional_cdf_buffer.pointer());
  parameters.environment_width = environment_distribution.width;
  parameters.environment_height = environment_distribution.height;
  parameters.environment_intensity =
      scene.background.environment_intensity;
  parameters.environment_rotation_radians =
      scene.background.environment_rotation_degrees *
      (3.14159265358979323846f / 180.0f);
  parameters.materials = material_data.empty()
      ? nullptr
      : reinterpret_cast<const MaterialData*>(
            material_buffer.pointer());
  parameters.textures = texture_data.empty()
      ? nullptr
      : reinterpret_cast<const TextureData*>(
            texture_buffer.pointer());
  parameters.lights = light_data.empty()
      ? nullptr
      : reinterpret_cast<const LightData*>(light_buffer.pointer());
  parameters.light_cdf = finite_light_distribution.indices.empty()
      ? nullptr
      : reinterpret_cast<const float*>(light_cdf_buffer.pointer());
  parameters.sampled_light_indices =
      finite_light_distribution.indices.empty()
          ? nullptr
          : reinterpret_cast<const std::uint32_t*>(
                sampled_light_index_buffer.pointer());
  parameters.delta_light_indices = delta_light_indices.empty()
      ? nullptr
      : reinterpret_cast<const std::uint32_t*>(
            delta_light_index_buffer.pointer());
  parameters.material_count =
      checked_u32(material_data.size(), "material count");
  parameters.texture_count =
      checked_u32(texture_data.size(), "texture count");
  parameters.all_light_count =
      checked_u32(light_data.size(), "light count");
  parameters.sampled_light_count = checked_u32(
      finite_light_distribution.indices.size(), "sampled light count");
  parameters.delta_light_count =
      checked_u32(delta_light_indices.size(), "delta light count");
  parameters.flame_count = checked_u32(flame_count, "flame count");
  parameters.water_surface_count =
      checked_u32(water_surface_count, "water surface count");
  parameters.clamp_direct = clamp_direct;
  parameters.clamp_indirect = clamp_indirect;
  parameters.traced_rays =
      reinterpret_cast<unsigned long long*>(ray_count.pointer());
  parameters.volume_counters =
      flame_count == 0u
          ? nullptr
          : reinterpret_cast<VolumeCounters*>(volume_count.pointer());
  parameters.water_counters =
      water_surface_count == 0u
          ? nullptr
          : reinterpret_cast<WaterCounters*>(water_count.pointer());
  parameters.firefly_counters = firefly_clamp_enabled
      ? reinterpret_cast<FireflyCounters*>(firefly_count.pointer())
      : nullptr;

  DeviceBuffer launch_parameters(tracker, sizeof(parameters));
  launch_parameters.upload(&parameters, sizeof(parameters), stream);
  Event render_start, render_end;
  render_start.record(stream);
  {
    NvtxRange range("OptiX path trace and shading");
    check_optix(optixLaunch(
                    optix.pipeline, stream, launch_parameters.pointer(),
                    sizeof(parameters), &sbt.table,
                    settings.width, settings.height, 1),
                "optixLaunch");
    render_end.record(stream);
    render_end.wait();
  }
  const double render_ms = render_end.elapsed(render_start);

  const DeviceBuffer* final_beauty = &beauty;
  DeviceBuffer denoised;
  double denoise_ms = 0.0;
  if (settings.denoise) {
    NvtxRange range("OptiX AI denoiser");
    Event denoise_start, denoise_end;
    denoise_start.record(stream);
    denoised = run_denoiser(
        optix, stream, tracker, beauty, albedo, normal,
        settings.width, settings.height);
    denoise_end.record(stream);
    denoise_end.wait();
    denoise_ms = denoise_end.elapsed(denoise_start);
    final_beauty = &denoised;
  }

  // The fixed HDR transform and AVIF encoding run on the host. Always copy
  // the actual final beauty buffer (including denoising when requested) so no
  // device-specific postprocess kernel or baked CUDA architecture is needed.
  std::vector<float4> linear_pixels(pixel_count);
  std::vector<unsigned long long> ray_counts(pixel_count);
  std::vector<VolumeCounters> volume_counts(
      flame_count == 0u ? 0u : pixel_count);
  std::vector<WaterCounters> water_counts(
      water_surface_count == 0u ? 0u : pixel_count);
  FireflyCounters firefly_counts{};
  final_beauty->download(linear_pixels.data(),
                         linear_pixels.size() * sizeof(float4), stream);
  ray_count.download(ray_counts.data(),
                     ray_counts.size() * sizeof(unsigned long long), stream);
  volume_count.download(volume_counts.data(),
                        volume_counts.size() * sizeof(VolumeCounters), stream);
  water_count.download(water_counts.data(),
                       water_counts.size() * sizeof(WaterCounters), stream);
  if (firefly_clamp_enabled) {
    firefly_count.download(&firefly_counts, sizeof(firefly_counts), stream);
  }
  check_cuda(cudaStreamSynchronize(stream),
             "cudaStreamSynchronize(output)");
  unsigned long long traced_rays = 0;
  for (const unsigned long long count : ray_counts)
    traced_rays += count;
  VolumeCounters volume_totals{};
  for (const VolumeCounters& count : volume_counts) {
    volume_totals.density_evaluations += count.density_evaluations;
    volume_totals.real_collisions += count.real_collisions;
    volume_totals.light_samples += count.light_samples;
    volume_totals.majorant_violations += count.majorant_violations;
    volume_totals.tracking_overflows += count.tracking_overflows;
  }
  WaterCounters water_totals{};
  std::uint64_t water_rough_nee_attempts = 0;
  std::uint64_t water_rough_nee_contributions = 0;
  std::uint64_t water_delta_splits = 0;
  for (const WaterCounters& count : water_counts) {
    water_totals.height_evaluations += count.height_evaluations;
    water_totals.tile_tests += count.tile_tests;
    water_totals.roots_reported += count.roots_reported;
    water_totals.medium_segments += count.medium_segments;
    water_totals.solver_overflows += count.solver_overflows;
    water_totals.medium_errors += count.medium_errors;
    water_rough_nee_attempts += count.rough_nee_attempts;
    water_rough_nee_contributions += count.rough_nee_contributions;
    water_delta_splits += count.delta_splits;
  }
  if (volume_totals.majorant_violations != 0ull ||
      volume_totals.tracking_overflows != 0ull) {
    throw std::runtime_error(
        "volume tracking safety check failed: majorant violations=" +
        std::to_string(volume_totals.majorant_violations) +
        ", tracking overflows=" +
        std::to_string(volume_totals.tracking_overflows));
  }
  if (water_totals.solver_overflows != 0ull ||
      water_totals.medium_errors != 0ull) {
    throw std::runtime_error(
        "water transport safety check failed: solver overflows=" +
        std::to_string(water_totals.solver_overflows) +
        ", medium errors=" + std::to_string(water_totals.medium_errors));
  }
  tracker.sample();

  RenderResult result;
  result.width = settings.width;
  result.height = settings.height;
  result.linear_rgb.resize(
      checked_product(pixel_count, 3, "linear RGB output"));
  for (std::size_t i = 0; i < pixel_count; ++i) {
    result.linear_rgb[i * 3u + 0u] = linear_pixels[i].x;
    result.linear_rgb[i * 3u + 1u] = linear_pixels[i].y;
    result.linear_rgb[i * 3u + 2u] = linear_pixels[i].z;
  }
  result.stats.width = settings.width;
  result.stats.height = settings.height;
  result.stats.spp = settings.spp;
  result.stats.max_depth = settings.max_depth;
  result.stats.seed = settings.seed;
  result.stats.denoised = settings.denoise;
  result.stats.direct_light_sampling =
      scene.integrator.direct_light_sampling == DirectLightSampling::Uniform
          ? "uniform"
          : "importance";
  result.stats.clamp_direct = clamp_direct;
  result.stats.clamp_indirect = clamp_indirect;
  result.stats.firefly_direct_clamped_contributions =
      firefly_counts.direct_clamped_contributions;
  result.stats.firefly_indirect_clamped_contributions =
      firefly_counts.indirect_clamped_contributions;
  result.stats.bvh_build_ms = bvh_ms;
  result.stats.render_ms = render_ms;
  result.stats.denoise_ms = denoise_ms;
  result.stats.peak_device_bytes = tracker.observed_peak();
  result.stats.peak_tracked_device_bytes = tracker.peak;
  result.stats.traced_rays = traced_rays;
  result.stats.volume_density_evaluations =
      volume_totals.density_evaluations;
  result.stats.volume_real_collisions = volume_totals.real_collisions;
  result.stats.volume_light_samples = volume_totals.light_samples;
  result.stats.volume_majorant_violations =
      volume_totals.majorant_violations;
  result.stats.volume_tracking_overflows = volume_totals.tracking_overflows;
  result.stats.water_height_evaluations = water_totals.height_evaluations;
  result.stats.water_tile_tests = water_totals.tile_tests;
  result.stats.water_roots_reported = water_totals.roots_reported;
  result.stats.water_medium_segments = water_totals.medium_segments;
  result.stats.water_solver_overflows = water_totals.solver_overflows;
  result.stats.water_medium_errors = water_totals.medium_errors;
  result.stats.water_rough_nee_attempts = water_rough_nee_attempts;
  result.stats.water_rough_nee_contributions =
      water_rough_nee_contributions;
  result.stats.water_delta_splits = water_delta_splits;
  result.stats.rays_per_second =
      render_ms > 0.0 ? traced_rays / (render_ms * 1.0e-3) : 0.0;
  result.stats.objects = scene.objects.size();
  result.stats.instances = instance_handles.size();
  result.stats.unique_meshes = unique_mesh_count;
  result.stats.mesh_triangles = mesh_triangle_count;
  result.stats.gas_count = primitive_gases.size() + mesh_gpus.size();

  cudaDeviceProp properties{};
  check_cuda(cudaGetDeviceProperties(&properties, settings.device),
             "cudaGetDeviceProperties");
  result.stats.gpu_name = properties.name;
  result.stats.compute_major = properties.major;
  result.stats.compute_minor = properties.minor;
  result.stats.driver_version = nvidia_driver_version();
  check_cuda(cudaDriverGetVersion(&result.stats.cuda_driver_api_version),
             "cudaDriverGetVersion");
  check_cuda(cudaRuntimeGetVersion(
                 &result.stats.cuda_runtime_version),
             "cudaRuntimeGetVersion");
  result.stats.optix_version = OPTIX_VERSION;
  result.stats.total_ms =
      std::chrono::duration<double, std::milli>(
          std::chrono::steady_clock::now() - total_begin).count();
  return result;
}

}  // namespace spectraldock
