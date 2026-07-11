#include <optix_device.h>

#include <cuda_runtime.h>

#include "spectraldock/device_types.h"

using spectraldock::AreaLight;
using GeometryData = spectraldock::DeviceGeometryData;
using spectraldock::HitgroupData;
using spectraldock::LaunchParams;
using spectraldock::MaterialData;
using spectraldock::TextureData;

extern "C" {
__constant__ LaunchParams params;
}

namespace {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kInvPi = 0.31830988618379067154f;
constexpr float kInfinity = 1.0e16f;

static __forceinline__ __device__ float3 f3(float x, float y, float z) {
  return make_float3(x, y, z);
}
static __forceinline__ __device__ float2 f2(float x, float y) {
  return make_float2(x, y);
}
static __forceinline__ __device__ float3 add(float3 a, float3 b) {
  return f3(a.x + b.x, a.y + b.y, a.z + b.z);
}
static __forceinline__ __device__ float3 sub(float3 a, float3 b) {
  return f3(a.x - b.x, a.y - b.y, a.z - b.z);
}
static __forceinline__ __device__ float3 mul(float3 a, float3 b) {
  return f3(a.x * b.x, a.y * b.y, a.z * b.z);
}
static __forceinline__ __device__ float3 mul(float3 a, float b) {
  return f3(a.x * b, a.y * b, a.z * b);
}
static __forceinline__ __device__ float3 divv(float3 a, float b) {
  return mul(a, 1.0f / b);
}
static __forceinline__ __device__ float dot3(float3 a, float3 b) {
  return a.x * b.x + a.y * b.y + a.z * b.z;
}
static __forceinline__ __device__ float3 cross3(float3 a, float3 b) {
  return f3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z,
            a.x * b.y - a.y * b.x);
}
static __forceinline__ __device__ float length2(float3 a) {
  return dot3(a, a);
}
static __forceinline__ __device__ float length3(float3 a) {
  return sqrtf(length2(a));
}
static __forceinline__ __device__ float3 normalize3(float3 a) {
  const float l2 = length2(a);
  return l2 > 1.0e-30f ? mul(a, rsqrtf(l2)) : f3(0.0f, 1.0f, 0.0f);
}
static __forceinline__ __device__ float3 neg(float3 a) {
  return f3(-a.x, -a.y, -a.z);
}
static __forceinline__ __device__ float3 lerp3(float3 a, float3 b, float t) {
  return add(mul(a, 1.0f - t), mul(b, t));
}
static __forceinline__ __device__ float max_component(float3 a) {
  return fmaxf(a.x, fmaxf(a.y, a.z));
}
static __forceinline__ __device__ float3 clamp_nonnegative(float3 a) {
  return f3(fmaxf(a.x, 0.0f), fmaxf(a.y, 0.0f), fmaxf(a.z, 0.0f));
}

// Russian roulette scales path throughput, not the local solid-angle BSDF
// density later used by MIS.
struct ContinuationResolution {
  bool survived = false;
  float throughput_scale = 0.0f;
  float bsdf_pdf = 0.0f;
};

static __forceinline__ __device__ ContinuationResolution resolve_continuation(
    float bsdf_pdf, float survival_probability, float roulette_sample) {
  const bool survived = survival_probability > 0.0f &&
                        roulette_sample < survival_probability;
  return {survived,
          survived ? 1.0f / survival_probability : 0.0f,
          bsdf_pdf};
}

// Normalize by the larger PDF before squaring to keep complementary weights
// finite without imposing an arbitrary denominator floor.
static __forceinline__ __device__ float power_heuristic(
    float pdf_a, float pdf_b) {
  if (!(pdf_a > 0.0f)) return 0.0f;
  if (!(pdf_b > 0.0f)) return 1.0f;
  const float scale = pdf_a > pdf_b ? pdf_a : pdf_b;
  const float a = pdf_a / scale;
  const float b = pdf_b / scale;
  const float aa = a * a;
  const float bb = b * b;
  return aa / (aa + bb);
}

static __forceinline__ __device__ float direct_light_mis_weight(
    float light_pdf, float bsdf_pdf, bool light_can_be_hit,
    bool next_bsdf_ray_exists) {
  return light_can_be_hit && next_bsdf_ray_exists
             ? power_heuristic(light_pdf, bsdf_pdf)
             : 1.0f;
}

static __forceinline__ __device__ float emitter_hit_mis_weight(
    float bsdf_pdf, float light_pdf, bool previous_event_was_delta,
    bool emitter_is_bound_to_light) {
  return previous_event_was_delta || !emitter_is_bound_to_light
             ? 1.0f
             : power_heuristic(bsdf_pdf, light_pdf);
}

static __forceinline__ __device__ float3 reflect3(float3 incident, float3 n) {
  return sub(incident, mul(n, 2.0f * dot3(incident, n)));
}
static __forceinline__ __device__ bool inside_aabb(
    float3 p, const GeometryData& g) {
  const float e = 2.0e-5f;
  return p.x >= g.aabb_min.x - e && p.x <= g.aabb_max.x + e &&
         p.y >= g.aabb_min.y - e && p.y <= g.aabb_max.y + e &&
         p.z >= g.aabb_min.z - e && p.z <= g.aabb_max.z + e;
}
static __forceinline__ __device__ void make_basis(
    float3 n, float3& tangent, float3& bitangent) {
  const float3 helper =
      fabsf(n.z) < 0.999f ? f3(0.0f, 0.0f, 1.0f) : f3(0.0f, 1.0f, 0.0f);
  tangent = normalize3(cross3(helper, n));
  bitangent = cross3(n, tangent);
}
static __forceinline__ __device__ float3 local_to_world(
    float3 local, float3 n) {
  float3 t;
  float3 b;
  make_basis(n, t, b);
  return normalize3(add(add(mul(t, local.x), mul(b, local.y)),
                        mul(n, local.z)));
}

// PCG-XSH-RR 64/32 transition and output, copyright 2014 M. E. O'Neill,
// adapted under Apache-2.0. Stream initialization is project-specific.
// See THIRD_PARTY_NOTICES.md.
struct Pcg32 {
  unsigned long long state;
  unsigned long long increment;

  // Chris Wellons's public-domain/Unlicense lowbias32 integer mixer.
  static __forceinline__ __device__ unsigned int hash(unsigned int x) {
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
  }

  __forceinline__ __device__ Pcg32(
      unsigned int seed, unsigned int pixel, unsigned int sample) {
    const unsigned int a = hash(seed ^ (pixel * 0x9e3779b9u));
    const unsigned int b = hash(sample ^ (pixel * 0x85ebca6bu) ^ seed);
    state = (static_cast<unsigned long long>(a) << 32) | b;
    increment =
        (static_cast<unsigned long long>(hash(a ^ b)) << 1) | 1ull;
    next_uint();
    state += (static_cast<unsigned long long>(b) << 32) | a;
    next_uint();
  }

  __forceinline__ __device__ unsigned int next_uint() {
    const unsigned long long old = state;
    state = old * 6364136223846793005ull + increment;
    const unsigned int x =
        static_cast<unsigned int>(((old >> 18u) ^ old) >> 27u);
    const unsigned int r = static_cast<unsigned int>(old >> 59u);
    return (x >> r) | (x << ((0u - r) & 31u));
  }

  __forceinline__ __device__ float next() {
    return static_cast<float>(next_uint() >> 8) * 0x1.0p-24f;
  }
};

struct SurfaceHit {
  int hit;
  int material_index;
  int light_index;
  int front_face;
  float3 position;
  float3 normal;
  float2 uv;
};

struct BsdfSample {
  float3 wi;
  float3 weight;
  float pdf;
  int delta;
  int valid;
};

static __forceinline__ __device__ void pack_pointer(
    const void* pointer, unsigned int& p0, unsigned int& p1) {
  const unsigned long long value =
      reinterpret_cast<unsigned long long>(pointer);
  p0 = static_cast<unsigned int>(value >> 32);
  p1 = static_cast<unsigned int>(value);
}

template <typename T>
static __forceinline__ __device__ T* unpack_pointer() {
  const unsigned long long value =
      (static_cast<unsigned long long>(optixGetPayload_0()) << 32) |
      optixGetPayload_1();
  return reinterpret_cast<T*>(value);
}

static __forceinline__ __device__ float srgb_channel_to_linear(float c) {
  return c <= 0.04045f ? c / 12.92f
                       : powf((c + 0.055f) / 1.055f, 2.4f);
}

static __forceinline__ __device__ float4 sample_texture(
    int texture_index, float2 uv) {
  if (texture_index < 0 ||
      static_cast<unsigned int>(texture_index) >= params.texture_count ||
      params.textures == nullptr) {
    return make_float4(1.0f, 1.0f, 1.0f, 1.0f);
  }
  const TextureData texture = params.textures[texture_index];
  if (texture.object == 0) {
    return make_float4(1.0f, 1.0f, 1.0f, 1.0f);
  }
  const float u = fminf(fmaxf(uv.x, 0.0f), 1.0f);
  const float v = 1.0f - fminf(fmaxf(uv.y, 0.0f), 1.0f);
  float4 value =
      tex2D<float4>(static_cast<cudaTextureObject_t>(texture.object), u, v);
  if ((texture.flags & spectraldock::kTextureSrgb) != 0u) {
    value.x = srgb_channel_to_linear(value.x);
    value.y = srgb_channel_to_linear(value.y);
    value.z = srgb_channel_to_linear(value.z);
  }
  return value;
}

static __forceinline__ __device__ float3 material_color(
    const MaterialData& material, float2 uv) {
  const float4 texel = sample_texture(material.texture_index, uv);
  return mul(material.base_color, f3(texel.x, texel.y, texel.z));
}

static __forceinline__ __device__ float2 triangle_uv(
    const GeometryData& geometry) {
  const float2 b = optixGetTriangleBarycentrics();
  const unsigned int primitive =
      optixGetPrimitiveIndex() - geometry.primitive_index_base;
  if ((primitive & 1u) == 0u) {
    return f2(b.y, b.x + b.y);
  }
  return f2(b.x + b.y, b.x);
}

static __forceinline__ __device__ uint3 mesh_triangle(
    const HitgroupData& hitgroup) {
  const unsigned int primitive = optixGetPrimitiveIndex();
  if (hitgroup.mesh.indices == nullptr ||
      primitive >= hitgroup.mesh.triangle_count) {
    return make_uint3(0u, 0u, 0u);
  }
  return hitgroup.mesh.indices[primitive];
}

static __forceinline__ __device__ float3 mesh_barycentric_weights() {
  const float2 b = optixGetTriangleBarycentrics();
  return f3(1.0f - b.x - b.y, b.x, b.y);
}

static __forceinline__ __device__ float2 mesh_uv(
    const HitgroupData& hitgroup) {
  if ((hitgroup.mesh.flags & spectraldock::kMeshHasTexcoords) == 0u ||
      hitgroup.mesh.texcoords == nullptr) {
    return f2(0.0f, 0.0f);
  }
  const uint3 triangle = mesh_triangle(hitgroup);
  if (triangle.x >= hitgroup.mesh.vertex_count ||
      triangle.y >= hitgroup.mesh.vertex_count ||
      triangle.z >= hitgroup.mesh.vertex_count) {
    return f2(0.0f, 0.0f);
  }
  const float3 w = mesh_barycentric_weights();
  const float2 a = hitgroup.mesh.texcoords[triangle.x];
  const float2 b = hitgroup.mesh.texcoords[triangle.y];
  const float2 c = hitgroup.mesh.texcoords[triangle.z];
  return f2(a.x * w.x + b.x * w.y + c.x * w.z,
            a.y * w.x + b.y * w.y + c.y * w.z);
}

static __forceinline__ __device__ float2 geometry_uv(
    const HitgroupData& hitgroup, float3 object_point) {
  const GeometryData& geometry = hitgroup.geometry;
  if (geometry.primitive_type == spectraldock::kPrimitiveMesh) {
    return mesh_uv(hitgroup);
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveTriangle) {
    return triangle_uv(geometry);
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveSphere) {
    const float3 n = normalize3(sub(object_point, geometry.p0));
    return f2(0.5f - atan2f(n.z, n.x) / (2.0f * kPi),
              0.5f + asinf(fminf(fmaxf(n.y, -1.0f), 1.0f)) / kPi);
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveDisk) {
    const float3 n = normalize3(geometry.p1);
    float3 u = geometry.p2;
    u = sub(u, mul(n, dot3(u, n)));
    float3 v;
    if (length2(u) < 1.0e-12f) {
      make_basis(n, u, v);
    } else {
      u = normalize3(u);
      v = cross3(n, u);
    }
    const float3 q = sub(object_point, geometry.p0);
    const float inv_diameter =
        geometry.radius > 0.0f ? 0.5f / geometry.radius : 0.0f;
    return f2(0.5f + dot3(q, u) * inv_diameter,
              0.5f + dot3(q, v) * inv_diameter);
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveCylinder) {
    const float3 axis = normalize3(geometry.p1);
    float3 u;
    float3 v;
    make_basis(axis, u, v);
    const float3 q = sub(object_point, geometry.p0);
    const float s = dot3(q, axis);
    const float3 radial = sub(q, mul(axis, s));
    const float vv = 0.5f + atan2f(dot3(radial, v), dot3(radial, u)) /
                                 (2.0f * kPi);
    const float uu = geometry.height > 0.0f ? s / geometry.height : s;
    return f2(uu, vv);
  }
  const float3 axis = normalize3(geometry.p1);
  const float3 focus_vector = sub(geometry.p2, geometry.p0);
  const float3 m = normalize3(focus_vector);
  const float3 v = normalize3(cross3(m, axis));
  const float3 q = sub(object_point, geometry.p0);
  return f2(dot3(q, v), dot3(q, axis));
}

static __forceinline__ __device__ float3 object_outward_normal(
    const HitgroupData& hitgroup, float3 object_point) {
  const GeometryData& geometry = hitgroup.geometry;
  if (geometry.primitive_type == spectraldock::kPrimitiveMesh) {
    const uint3 triangle = mesh_triangle(hitgroup);
    if (hitgroup.mesh.positions == nullptr ||
        triangle.x >= hitgroup.mesh.vertex_count ||
        triangle.y >= hitgroup.mesh.vertex_count ||
        triangle.z >= hitgroup.mesh.vertex_count) {
      return f3(0.0f, 1.0f, 0.0f);
    }
    const float3 a = hitgroup.mesh.positions[triangle.x];
    const float3 b = hitgroup.mesh.positions[triangle.y];
    const float3 c = hitgroup.mesh.positions[triangle.z];
    return normalize3(cross3(sub(b, a), sub(c, a)));
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveTriangle) {
    return normalize3(cross3(sub(geometry.p2, geometry.p1),
                             sub(geometry.p1, geometry.p0)));
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveSphere) {
    return normalize3(sub(object_point, geometry.p0));
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveDisk) {
    return normalize3(geometry.p1);
  }
  if (geometry.primitive_type == spectraldock::kPrimitiveCylinder) {
    const float3 axis = normalize3(geometry.p1);
    const float3 q = sub(object_point, geometry.p0);
    return normalize3(sub(q, mul(axis, dot3(q, axis))));
  }
  const float3 axis = normalize3(geometry.p1);
  const float3 focus_vector = sub(geometry.p2, geometry.p0);
  const float focal_distance = fmaxf(length3(focus_vector), 1.0e-6f);
  const float3 m = divv(focus_vector, focal_distance);
  const float3 v = normalize3(cross3(m, axis));
  const float x = dot3(sub(object_point, geometry.p0), v);
  return normalize3(sub(mul(v, 2.0f * x), mul(m, 4.0f * focal_distance)));
}

static __forceinline__ __device__ float3 object_shading_normal(
    const HitgroupData& hitgroup, float3 object_point) {
  const float3 geometric = object_outward_normal(hitgroup, object_point);
  if (hitgroup.geometry.primitive_type != spectraldock::kPrimitiveMesh ||
      (hitgroup.mesh.flags & spectraldock::kMeshHasNormals) == 0u ||
      hitgroup.mesh.normals == nullptr) {
    return geometric;
  }
  const uint3 triangle = mesh_triangle(hitgroup);
  if (triangle.x >= hitgroup.mesh.vertex_count ||
      triangle.y >= hitgroup.mesh.vertex_count ||
      triangle.z >= hitgroup.mesh.vertex_count) {
    return geometric;
  }
  const float3 w = mesh_barycentric_weights();
  float3 shading = normalize3(add(
      add(mul(hitgroup.mesh.normals[triangle.x], w.x),
          mul(hitgroup.mesh.normals[triangle.y], w.y)),
      mul(hitgroup.mesh.normals[triangle.z], w.z)));
  if (dot3(shading, geometric) < 0.0f) shading = neg(shading);
  return shading;
}

static __forceinline__ __device__ SurfaceHit trace_radiance(
    float3 origin, float3 direction, unsigned long long& traced_rays) {
  SurfaceHit hit = {};
  hit.hit = 0;
  unsigned int p0;
  unsigned int p1;
  pack_pointer(&hit, p0, p1);
  ++traced_rays;
  optixTrace(params.traversable, origin, direction, params.scene_epsilon,
             kInfinity, 0.0f, OptixVisibilityMask(255),
             OPTIX_RAY_FLAG_NONE, spectraldock::kRayRadiance,
             spectraldock::kRayTypeCount, spectraldock::kRayRadiance, p0, p1);
  return hit;
}

static __forceinline__ __device__ bool trace_visible(
    float3 origin, float3 direction, float distance, int light_index,
    unsigned long long& traced_rays) {
  unsigned int visible = 0u;
  unsigned int target_light = static_cast<unsigned int>(light_index);
  ++traced_rays;
  optixTrace(params.traversable, origin, direction, params.scene_epsilon,
             fmaxf(distance - params.scene_epsilon, params.scene_epsilon),
             0.0f, OptixVisibilityMask(255),
             OPTIX_RAY_FLAG_TERMINATE_ON_FIRST_HIT |
                 OPTIX_RAY_FLAG_DISABLE_CLOSESTHIT,
             spectraldock::kRayShadow, spectraldock::kRayTypeCount,
             spectraldock::kRayShadow, visible, target_light);
  return visible != 0u;
}

static __forceinline__ __device__ float ggx_distribution(
    float no_h, float alpha) {
  const float a2 = alpha * alpha;
  const float d = no_h * no_h * (a2 - 1.0f) + 1.0f;
  return a2 / fmaxf(kPi * d * d, 1.0e-20f);
}

static __forceinline__ __device__ float ggx_g1(float no_x, float alpha) {
  const float a2 = alpha * alpha;
  return 2.0f * no_x /
         fmaxf(no_x + sqrtf(a2 + (1.0f - a2) * no_x * no_x), 1.0e-20f);
}

static __forceinline__ __device__ float3 fresnel_schlick(
    float cos_theta, float3 f0) {
  const float x = 1.0f - fminf(fmaxf(cos_theta, 0.0f), 1.0f);
  const float x2 = x * x;
  const float x5 = x2 * x2 * x;
  return add(f0, mul(sub(f3(1.0f, 1.0f, 1.0f), f0), x5));
}

static __forceinline__ __device__ void evaluate_bsdf(
    const MaterialData& material, float3 base_color, float3 n, float3 wo,
    float3 wi, float3& value, float& pdf) {
  value = f3(0.0f, 0.0f, 0.0f);
  pdf = 0.0f;
  const float no_l = dot3(n, wi);
  const float no_v = dot3(n, wo);
  if (no_l <= 0.0f || no_v <= 0.0f) {
    return;
  }
  if (material.type == spectraldock::kMaterialLambertian) {
    value = mul(base_color, kInvPi);
    pdf = no_l * kInvPi;
    return;
  }
  if (material.type != spectraldock::kMaterialMetal) {
    return;
  }
  const float3 half_vector = normalize3(add(wo, wi));
  const float no_h = fmaxf(dot3(n, half_vector), 0.0f);
  const float vo_h = fmaxf(dot3(wo, half_vector), 0.0f);
  if (no_h <= 0.0f || vo_h <= 0.0f) {
    return;
  }
  const float alpha =
      fmaxf(material.roughness * material.roughness, 0.001f);
  const float d = ggx_distribution(no_h, alpha);
  const float g = ggx_g1(no_v, alpha) * ggx_g1(no_l, alpha);
  const float3 dielectric_f0 = f3(0.04f, 0.04f, 0.04f);
  const float3 f0 =
      lerp3(dielectric_f0, base_color,
            fminf(fmaxf(material.metallic, 0.0f), 1.0f));
  const float3 fresnel = fresnel_schlick(vo_h, f0);
  value = mul(fresnel, d * g / fmaxf(4.0f * no_v * no_l, 1.0e-20f));
  pdf = d * no_h / fmaxf(4.0f * vo_h, 1.0e-20f);
}

static __forceinline__ __device__ BsdfSample sample_bsdf(
    const MaterialData& material, float3 base_color, float3 n, float3 wo,
    int front_face, Pcg32& rng) {
  BsdfSample sample = {};
  sample.weight = f3(0.0f, 0.0f, 0.0f);
  if (material.type == spectraldock::kMaterialLambertian) {
    const float r1 = rng.next();
    const float r2 = rng.next();
    const float radius = sqrtf(r1);
    const float phi = 2.0f * kPi * r2;
    const float3 local =
        f3(radius * cosf(phi), radius * sinf(phi), sqrtf(1.0f - r1));
    sample.wi = local_to_world(local, n);
    sample.pdf = fmaxf(dot3(n, sample.wi), 0.0f) * kInvPi;
    sample.weight = base_color;
    sample.valid = sample.pdf > 0.0f;
    sample.delta = 0;
    return sample;
  }
  if (material.type == spectraldock::kMaterialMetal) {
    const float alpha =
        fmaxf(material.roughness * material.roughness, 0.001f);
    const float r1 = rng.next();
    const float r2 = rng.next();
    const float phi = 2.0f * kPi * r1;
    const float cos_theta =
        sqrtf((1.0f - r2) / fmaxf(1.0f + (alpha * alpha - 1.0f) * r2,
                                  1.0e-20f));
    const float sin_theta = sqrtf(fmaxf(0.0f, 1.0f - cos_theta * cos_theta));
    const float3 half_vector = local_to_world(
        f3(sin_theta * cosf(phi), sin_theta * sinf(phi), cos_theta), n);
    sample.wi = normalize3(reflect3(neg(wo), half_vector));
    float3 value;
    evaluate_bsdf(material, base_color, n, wo, sample.wi, value, sample.pdf);
    const float no_l = fmaxf(dot3(n, sample.wi), 0.0f);
    if (sample.pdf > 0.0f && no_l > 0.0f) {
      sample.weight = mul(value, no_l / sample.pdf);
      sample.valid = 1;
    }
    sample.delta = 0;
    return sample;
  }
  if (material.type == spectraldock::kMaterialDielectric) {
    const float eta_i = front_face ? 1.0f : fmaxf(material.ior, 1.0e-3f);
    const float eta_t = front_face ? fmaxf(material.ior, 1.0e-3f) : 1.0f;
    const float eta = eta_i / eta_t;
    const float cos_theta = fminf(dot3(wo, n), 1.0f);
    const float sin2_theta = fmaxf(0.0f, 1.0f - cos_theta * cos_theta);
    const float r0_base = (eta_i - eta_t) / (eta_i + eta_t);
    const float r0 = r0_base * r0_base;
    const float m = 1.0f - cos_theta;
    const float reflectance = r0 + (1.0f - r0) * m * m * m * m * m;
    bool transmitted = false;
    if (eta * eta * sin2_theta > 1.0f || rng.next() < reflectance) {
      sample.wi = normalize3(reflect3(neg(wo), n));
    } else {
      const float3 perpendicular =
          mul(add(neg(wo), mul(n, cos_theta)), eta);
      const float3 parallel =
          mul(n, -sqrtf(fmaxf(0.0f, 1.0f - length2(perpendicular))));
      sample.wi = normalize3(add(perpendicular, parallel));
      transmitted = true;
    }
    sample.weight = transmitted ? mul(base_color, eta * eta) : base_color;
    sample.pdf = 1.0f;
    sample.valid = 1;
    sample.delta = 1;
  }
  return sample;
}

static __forceinline__ __device__ float light_direction_pdf(
    int light_index, float3 from, float3 point) {
  if (light_index < 0 ||
      static_cast<unsigned int>(light_index) >= params.light_count ||
      params.lights == nullptr || params.light_count == 0) {
    return 0.0f;
  }
  const AreaLight light = params.lights[light_index];
  if (light.geometry_index < 0) {
    return 0.0f;
  }
  const float3 displacement = sub(point, from);
  const float distance2 = length2(displacement);
  const float3 wi = normalize3(displacement);
  const float3 light_normal = light.type == spectraldock::kLightSphere
      ? normalize3(sub(point, light.p0))
      : normalize3(light.normal);
  float cos_light = dot3(light_normal, neg(wi));
  if (light.two_sided != 0) {
    cos_light = fabsf(cos_light);
  }
  const float area =
      light.area > 0.0f ? light.area
                        : length3(cross3(light.edge_u, light.edge_v));
  if (cos_light <= 0.0f || area <= 0.0f) {
    return 0.0f;
  }
  return distance2 /
         (cos_light * area * static_cast<float>(params.light_count));
}

static __forceinline__ __device__ void sample_light_surface(
    const AreaLight& light, float u0, float u1,
    float3& point, float3& normal) {
  if (light.type == spectraldock::kLightDisk) {
    const float radius = light.radius * sqrtf(u0);
    const float phi = 2.0f * kPi * u1;
    point = add(light.p0,
                add(mul(light.edge_u, radius * cosf(phi)),
                    mul(light.edge_v, radius * sinf(phi))));
    normal = normalize3(light.normal);
    return;
  }
  if (light.type == spectraldock::kLightSphere) {
    const float z = 1.0f - 2.0f * u0;
    const float radial = sqrtf(fmaxf(0.0f, 1.0f - z * z));
    const float phi = 2.0f * kPi * u1;
    normal = f3(radial * cosf(phi), z, radial * sinf(phi));
    point = add(light.p0, mul(normal, light.radius));
    return;
  }
  point = add(light.p0,
              add(mul(light.edge_u, u0), mul(light.edge_v, u1)));
  normal = normalize3(light.normal);
}

static __forceinline__ __device__ float3 sample_direct_light(
    const SurfaceHit& hit, const MaterialData& material, float3 base_color,
    float3 wo, bool next_bsdf_ray_exists, Pcg32& rng,
    unsigned long long& traced_rays) {
  if (params.lights == nullptr || params.light_count == 0 ||
      (material.type != spectraldock::kMaterialLambertian &&
       material.type != spectraldock::kMaterialMetal)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const unsigned int candidate =
      static_cast<unsigned int>(rng.next() * params.light_count);
  const unsigned int light_index =
      candidate < params.light_count ? candidate : params.light_count - 1u;
  const AreaLight light = params.lights[light_index];
  float3 light_point;
  float3 light_normal;
  sample_light_surface(light, rng.next(), rng.next(),
                       light_point, light_normal);
  const float3 displacement = sub(light_point, hit.position);
  const float distance2 = length2(displacement);
  if (distance2 <= params.scene_epsilon * params.scene_epsilon) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float distance = sqrtf(distance2);
  const float3 wi = divv(displacement, distance);
  const float no_l = dot3(hit.normal, wi);
  if (no_l <= 0.0f) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  float cos_light = dot3(light_normal, neg(wi));
  if (light.two_sided != 0) {
    cos_light = fabsf(cos_light);
  }
  const float area =
      light.area > 0.0f ? light.area
                        : length3(cross3(light.edge_u, light.edge_v));
  if (cos_light <= 0.0f || area <= 0.0f) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float light_pdf =
      distance2 /
      (cos_light * area * static_cast<float>(params.light_count));
  float3 bsdf;
  float bsdf_pdf;
  evaluate_bsdf(material, base_color, hit.normal, wo, wi, bsdf, bsdf_pdf);
  if (bsdf_pdf <= 0.0f) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float3 shadow_origin =
      add(hit.position, mul(hit.normal, params.scene_epsilon * 2.0f));
  const float3 shadow_displacement = sub(light_point, shadow_origin);
  const float shadow_distance = length3(shadow_displacement);
  if (shadow_distance <= params.scene_epsilon * 2.0f) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float3 shadow_direction =
      divv(shadow_displacement, shadow_distance);
  if (!trace_visible(shadow_origin, shadow_direction, shadow_distance,
                     static_cast<int>(light_index), traced_rays)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float mis = direct_light_mis_weight(
      light_pdf, bsdf_pdf, light.geometry_index >= 0,
      next_bsdf_ray_exists);
  return mul(mul(bsdf, light.emission), no_l * mis / light_pdf);
}

static __forceinline__ __device__ float3 background(float3 direction) {
  float3 result = params.background_color;
  if (params.background_type == spectraldock::kBackgroundSky) {
    const float t = 0.5f * (fminf(fmaxf(direction.y, -1.0f), 1.0f) + 1.0f);
    result = lerp3(params.sky_bottom, params.sky_top, t);
  }
  if (params.sun_cos_angle <= 1.0f &&
      dot3(direction, normalize3(params.sun_direction)) >=
          params.sun_cos_angle) {
    result = add(result, params.sun_color);
  }
  return result;
}

static __forceinline__ __device__ float2 sample_disk(Pcg32& rng) {
  const float radius = sqrtf(rng.next());
  const float phi = 2.0f * kPi * rng.next();
  return f2(radius * cosf(phi), radius * sinf(phi));
}

static __forceinline__ __device__ void generate_camera_ray(
    unsigned int x, unsigned int y, Pcg32& rng, float3& origin,
    float3& direction) {
  const float sx =
      2.0f * ((static_cast<float>(x) + rng.next()) / params.width) - 1.0f;
  const float sy =
      1.0f - 2.0f * ((static_cast<float>(y) + rng.next()) / params.height);
  const float3 focal_vector =
      mul(add(add(neg(params.camera.w),
                  mul(params.camera.u,
                      sx * params.camera.aspect * params.camera.tan_half_fov)),
              mul(params.camera.v, sy * params.camera.tan_half_fov)),
          params.camera.focus_distance);
  float3 lens_offset = f3(0.0f, 0.0f, 0.0f);
  if (params.camera.lens_radius > 0.0f) {
    const float2 lens = sample_disk(rng);
    lens_offset =
        mul(add(mul(params.camera.u, lens.x),
                mul(params.camera.v, lens.y)),
            params.camera.lens_radius);
  }
  origin = add(params.camera.origin, lens_offset);
  direction = normalize3(sub(focal_vector, lens_offset));
}

static __forceinline__ __device__ bool valid_t(float t) {
  return isfinite(t) && t >= optixGetRayTmin() && t <= optixGetRayTmax();
}

static __forceinline__ __device__ bool report_root(
    float t, const GeometryData& geometry) {
  if (!valid_t(t)) {
    return false;
  }
  const float3 point =
      add(optixGetObjectRayOrigin(), mul(optixGetObjectRayDirection(), t));
  if (!inside_aabb(point, geometry)) {
    return false;
  }
  return optixReportIntersection(t, 0u);
}

static __forceinline__ __device__ void report_quadratic(
    float a, float b, float c, const GeometryData& geometry) {
  if (fabsf(a) < 1.0e-12f) {
    if (fabsf(b) > 1.0e-12f) {
      report_root(-c / b, geometry);
    }
    return;
  }
  const float discriminant = b * b - 4.0f * a * c;
  if (discriminant < 0.0f) {
    return;
  }
  const float root = sqrtf(discriminant);
  const float q = -0.5f * (b + copysignf(root, b));
  float t0;
  float t1;
  if (fabsf(q) > 1.0e-20f) {
    t0 = q / a;
    t1 = c / q;
  } else {
    t0 = -b / (2.0f * a);
    t1 = t0;
  }
  if (t1 < t0) {
    const float temp = t0;
    t0 = t1;
    t1 = temp;
  }
  if (!report_root(t0, geometry) && t1 > t0 + 1.0e-7f) {
    report_root(t1, geometry);
  }
}

static __forceinline__ __device__ void alpha_any_hit() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  const float t = optixGetRayTmax();
  const float3 object_point =
      add(optixGetObjectRayOrigin(), mul(optixGetObjectRayDirection(), t));
  const float3 outward = object_outward_normal(*record, object_point);
  const bool front_face =
      dot3(optixGetObjectRayDirection(), outward) < 0.0f;
  const int material =
      front_face ? geometry.material_front : geometry.material_back;
  if (material < 0) {
    optixIgnoreIntersection();
    return;
  }
  if (geometry.alpha_texture < 0) {
    return;
  }
  const float alpha =
      sample_texture(geometry.alpha_texture,
                     geometry_uv(*record, object_point)).w;
  if (alpha < geometry.alpha_cutoff) {
    optixIgnoreIntersection();
  }
}

}  // namespace

extern "C" __global__ void __raygen__pathtrace() {
  const uint3 launch_index = optixGetLaunchIndex();
  if (launch_index.x >= params.width || launch_index.y >= params.height) {
    return;
  }
  const unsigned int pixel =
      launch_index.y * params.width + launch_index.x;
  const unsigned int spp = params.spp > 0u ? params.spp : 1u;
  float3 beauty_sum = f3(0.0f, 0.0f, 0.0f);
  float3 albedo_sum = f3(0.0f, 0.0f, 0.0f);
  float3 normal_sum = f3(0.0f, 0.0f, 0.0f);
  unsigned long long traced_rays = 0ull;

  for (unsigned int sample_index = 0; sample_index < spp; ++sample_index) {
    Pcg32 rng(params.seed, pixel, sample_index);
    float3 ray_origin;
    float3 ray_direction;
    generate_camera_ray(launch_index.x, launch_index.y, rng, ray_origin,
                        ray_direction);
    float3 throughput = f3(1.0f, 1.0f, 1.0f);
    float3 radiance = f3(0.0f, 0.0f, 0.0f);
    float previous_pdf = 0.0f;
    int previous_delta = 1;
    int guide_written = 0;

    for (unsigned int bounce = 0; bounce < params.max_depth; ++bounce) {
      const SurfaceHit hit = trace_radiance(ray_origin, ray_direction, traced_rays);
      if (hit.hit == 0) {
        radiance =
            add(radiance, mul(throughput, background(ray_direction)));
        break;
      }
      if (hit.material_index < 0 ||
          static_cast<unsigned int>(hit.material_index) >=
              params.material_count ||
          params.materials == nullptr) {
        break;
      }
      const MaterialData material = params.materials[hit.material_index];
      const float3 base_color = material_color(material, hit.uv);
      if (guide_written == 0) {
        albedo_sum = add(albedo_sum, base_color);
        const float3 camera_normal =
            f3(dot3(hit.normal, params.camera.u),
               dot3(hit.normal, params.camera.v),
               dot3(hit.normal, params.camera.w));
        normal_sum = add(normal_sum, camera_normal);
        guide_written = 1;
      }
      if (material.type == spectraldock::kMaterialEmitter) {
        float3 emitted = material.emission;
        if (material.texture_index >= 0) {
          const float4 texel = sample_texture(material.texture_index, hit.uv);
          emitted = mul(emitted, f3(texel.x, texel.y, texel.z));
        }
        const bool emitter_is_bound_to_light = hit.light_index >= 0;
        const float light_pdf = emitter_is_bound_to_light
            ? light_direction_pdf(hit.light_index, ray_origin, hit.position)
            : 0.0f;
        const float weight = emitter_hit_mis_weight(
            previous_pdf, light_pdf, previous_delta != 0,
            emitter_is_bound_to_light);
        radiance = add(radiance, mul(mul(throughput, emitted), weight));
        break;
      }

      const float3 wo = neg(ray_direction);
      const bool next_bsdf_ray_exists = bounce + 1u < params.max_depth;
      const float3 direct =
          sample_direct_light(hit, material, base_color, wo,
                              next_bsdf_ray_exists, rng, traced_rays);
      radiance = add(radiance, mul(throughput, direct));
      if (!next_bsdf_ray_exists) {
        break;
      }

      const BsdfSample scatter =
          sample_bsdf(material, base_color, hit.normal, wo,
                      hit.front_face, rng);
      if (scatter.valid == 0) {
        break;
      }
      throughput = clamp_nonnegative(mul(throughput, scatter.weight));
      if (max_component(throughput) <= 0.0f) {
        break;
      }
      previous_pdf = scatter.pdf;
      previous_delta = scatter.delta;

      if (bounce >= 4u) {
        const float survival =
            fminf(fmaxf(max_component(throughput), 0.05f), 0.95f);
        const ContinuationResolution continuation =
            resolve_continuation(previous_pdf, survival, rng.next());
        previous_pdf = continuation.bsdf_pdf;
        if (!continuation.survived) {
          break;
        }
        throughput = mul(throughput, continuation.throughput_scale);
      }
      const float side = dot3(scatter.wi, hit.normal) >= 0.0f ? 1.0f : -1.0f;
      ray_origin =
          add(hit.position, mul(hit.normal,
                                side * params.scene_epsilon * 2.0f));
      ray_direction = scatter.wi;
    }
    beauty_sum = add(beauty_sum, radiance);
  }

  if (params.traced_rays != nullptr) {
    params.traced_rays[pixel] = traced_rays;
  }

  const float inv_spp = 1.0f / static_cast<float>(spp);
  if (params.beauty != nullptr) {
    const float3 value = mul(beauty_sum, inv_spp);
    params.beauty[pixel] = make_float4(value.x, value.y, value.z, 1.0f);
  }
  if (params.albedo != nullptr) {
    const float3 value = mul(albedo_sum, inv_spp);
    params.albedo[pixel] = make_float4(value.x, value.y, value.z, 1.0f);
  }
  if (params.normal != nullptr) {
    const float3 average = mul(normal_sum, inv_spp);
    params.normal[pixel] =
        length2(average) > 1.0e-20f
            ? normalize3(average)
            : f3(0.0f, 0.0f, 0.0f);
  }
}

extern "C" __global__ void __miss__radiance() {
  SurfaceHit* hit = unpack_pointer<SurfaceHit>();
  hit->hit = 0;
}

extern "C" __global__ void __miss__shadow() {
  optixSetPayload_0(1u);
}

extern "C" __global__ void __closesthit__radiance() {
  SurfaceHit* hit = unpack_pointer<SurfaceHit>();
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  const float t = optixGetRayTmax();
  const float3 world_direction = optixGetWorldRayDirection();
  const float3 world_point =
      add(optixGetWorldRayOrigin(), mul(world_direction, t));
  const float3 object_point =
      optixTransformPointFromWorldToObjectSpace(world_point);
  const float3 object_geometric =
      object_outward_normal(*record, object_point);
  const float3 object_shading =
      object_shading_normal(*record, object_point);
  const float3 world_outward = normalize3(
      optixTransformNormalFromObjectToWorldSpace(object_geometric));
  float3 world_shading = normalize3(
      optixTransformNormalFromObjectToWorldSpace(object_shading));
  if (dot3(world_shading, world_outward) < 0.0f)
    world_shading = neg(world_shading);
  const bool front_face =
      dot3(world_direction, world_outward) < 0.0f;
  const int material =
      front_face ? geometry.material_front : geometry.material_back;
  hit->hit = 1;
  hit->material_index = material;
  hit->light_index = geometry.light_index;
  hit->front_face = front_face ? 1 : 0;
  hit->position = world_point;
  hit->normal = front_face ? world_shading : neg(world_shading);
  hit->uv = geometry_uv(*record, object_point);
}

extern "C" __global__ void __closesthit__shadow() {
  optixSetPayload_0(0u);
}

extern "C" __global__ void __anyhit__alpha_radiance() {
  alpha_any_hit();
}

extern "C" __global__ void __anyhit__alpha_shadow() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const int light_index = record->geometry.light_index;
  if (light_index >= 0 &&
      static_cast<unsigned int>(light_index) == optixGetPayload_1()) {
    optixIgnoreIntersection();
    return;
  }
  alpha_any_hit();
}

extern "C" __global__ void __intersection__disk() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  const float3 origin = optixGetObjectRayOrigin();
  const float3 direction = optixGetObjectRayDirection();
  const float3 normal = normalize3(geometry.p1);
  const float denominator = dot3(normal, direction);
  if (fabsf(denominator) < 1.0e-10f) {
    return;
  }
  const float t = dot3(normal, sub(geometry.p0, origin)) / denominator;
  if (!valid_t(t)) {
    return;
  }
  const float3 point = add(origin, mul(direction, t));
  if (length2(sub(point, geometry.p0)) <= geometry.radius * geometry.radius &&
      inside_aabb(point, geometry)) {
    optixReportIntersection(t, 0u);
  }
}

extern "C" __global__ void __intersection__cylinder() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  const float3 origin = optixGetObjectRayOrigin();
  const float3 direction = optixGetObjectRayDirection();
  const float3 axis = normalize3(geometry.p1);
  const float3 q = sub(origin, geometry.p0);
  const float3 d_perp = sub(direction, mul(axis, dot3(direction, axis)));
  const float3 q_perp = sub(q, mul(axis, dot3(q, axis)));
  const float a = dot3(d_perp, d_perp);
  const float b = 2.0f * dot3(d_perp, q_perp);
  const float c =
      dot3(q_perp, q_perp) - geometry.radius * geometry.radius;
  if (geometry.height <= 0.0f) {
    report_quadratic(a, b, c, geometry);
    return;
  }
  const float discriminant = b * b - 4.0f * a * c;
  if (fabsf(a) < 1.0e-12f || discriminant < 0.0f) {
    return;
  }
  const float root = sqrtf(discriminant);
  float t0 = (-b - root) / (2.0f * a);
  float t1 = (-b + root) / (2.0f * a);
  if (t1 < t0) {
    const float temp = t0;
    t0 = t1;
    t1 = temp;
  }
  const float roots[2] = {t0, t1};
  for (int i = 0; i < 2; ++i) {
    const float t = roots[i];
    if (!valid_t(t)) {
      continue;
    }
    const float3 point = add(origin, mul(direction, t));
    const float s = dot3(sub(point, geometry.p0), axis);
    if (s >= 0.0f && s <= geometry.height && inside_aabb(point, geometry) &&
        optixReportIntersection(t, 0u)) {
      return;
    }
  }
}

extern "C" __global__ void __intersection__parabola() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  const float3 focus_vector = sub(geometry.p2, geometry.p0);
  const float focal_distance = length3(focus_vector);
  if (focal_distance <= 1.0e-8f) {
    return;
  }
  const float3 axis = normalize3(geometry.p1);
  const float3 m = divv(focus_vector, focal_distance);
  const float3 v = normalize3(cross3(m, axis));
  if (length2(v) < 0.5f) {
    return;
  }
  const float3 q = sub(optixGetObjectRayOrigin(), geometry.p0);
  const float3 direction = optixGetObjectRayDirection();
  const float x0 = dot3(q, v);
  const float y0 = dot3(q, m);
  const float dx = dot3(direction, v);
  const float dy = dot3(direction, m);
  const float a = dx * dx;
  const float b = 2.0f * x0 * dx - 4.0f * focal_distance * dy;
  const float c = x0 * x0 - 4.0f * focal_distance * y0;
  report_quadratic(a, b, c, geometry);
}
