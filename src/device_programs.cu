#include <optix_device.h>

#include <cuda_runtime.h>

#include "spectraldock/device_types.h"

using GeometryData = spectraldock::DeviceGeometryData;
using spectraldock::HitgroupData;
using spectraldock::LaunchParams;
using spectraldock::LightData;
using spectraldock::MaterialData;
using spectraldock::TextureData;
using spectraldock::VolumeCounters;
using spectraldock::WaterCounters;

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

static __forceinline__ __device__ float3 clamp_path_contribution(
    float3 contribution, float threshold,
    unsigned long long* clamped_counter) {
  if (!(threshold > 0.0f)) return contribution;
  const float maximum = max_component(contribution);
  if (!(maximum > threshold) || isnan(maximum)) return contribution;
  if (clamped_counter != nullptr) {
    atomicAdd(clamped_counter, 1ull);
  }
  if (!isfinite(maximum)) {
    // This is the limiting max-RGB normalization for overflowed positive
    // components; finite components vanish relative to an infinite maximum.
    return f3(isinf(contribution.x) && contribution.x > 0.0f
                  ? threshold : 0.0f,
              isinf(contribution.y) && contribution.y > 0.0f
                  ? threshold : 0.0f,
              isinf(contribution.z) && contribution.z > 0.0f
                  ? threshold : 0.0f);
  }
  return mul(contribution, threshold / maximum);
}

static __forceinline__ __device__ bool scaled_path_contribution_needs_clamp(
    float3 throughput, float3 term, float threshold) {
  if (!(threshold > 0.0f)) return false;
  // Volatile keeps this detection-only multiply from being algebraically
  // folded into the legacy grouped accumulation under --use_fast_math.
  volatile float maximum = fmaxf(
      throughput.x * term.x,
      fmaxf(throughput.y * term.y, throughput.z * term.z));
  return maximum > threshold && !isnan(maximum);
}

static __forceinline__ __device__ void accumulate_path_contribution(
    float3& radiance, float3 contribution, float threshold,
    unsigned long long* clamped_counter) {
  radiance = add(
      radiance,
      clamp_path_contribution(contribution, threshold, clamped_counter));
}

static __forceinline__ __device__ float3 exp_attenuation(
    float3 absorption, float distance) {
  return f3(absorption.x > 0.0f ? expf(-absorption.x * distance) : 1.0f,
            absorption.y > 0.0f ? expf(-absorption.y * distance) : 1.0f,
            absorption.z > 0.0f ? expf(-absorption.z * distance) : 1.0f);
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

static __forceinline__ __device__ float balance_heuristic(
    float pdf_a, float pdf_b) {
  if (!(pdf_a > 0.0f)) return 0.0f;
  if (!(pdf_b > 0.0f)) return 1.0f;
  const float scale = pdf_a > pdf_b ? pdf_a : pdf_b;
  const float a = pdf_a / scale;
  const float b = pdf_b / scale;
  return a / (a + b);
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

  __forceinline__ __device__ float next_open01() {
    const float value = next();
    // Keep exponential free-flight sampling strictly inside (0, 1) without
    // merging the zero outcome into an already occupied 24-bit sample bin.
    return value > 0.0f ? value : 0x1.0p-25f;
  }

  // A 53-bit [0, 1) uniform is used for environment CDF inversion. Even a
  // 32-bit variate cannot reach every positive conditional interval created
  // by the 1% sphere floor in a high-resolution map near its poles.
  __forceinline__ __device__ double next_cdf() {
    const unsigned long long high =
        static_cast<unsigned long long>(next_uint() >> 5u);
    const unsigned long long low =
        static_cast<unsigned long long>(next_uint() >> 6u);
    const unsigned long long bits = (high << 26u) | low;
    return static_cast<double>(bits) *
           1.1102230246251565404236316680908203125e-16;
  }
};

static __forceinline__ __device__ void fork_rng(
    Pcg32& rng, unsigned int tag) {
  const unsigned int lo = static_cast<unsigned int>(rng.state);
  const unsigned int hi = static_cast<unsigned int>(rng.state >> 32u);
  const unsigned int stream_lo = static_cast<unsigned int>(rng.increment);
  const unsigned int stream_hi =
      static_cast<unsigned int>(rng.increment >> 32u);
  const unsigned int mixed_lo = Pcg32::hash(lo ^ tag ^ stream_hi);
  const unsigned int mixed_hi =
      Pcg32::hash(hi ^ (tag * 0x9e3779b9u) ^ stream_lo);
  rng.state = (static_cast<unsigned long long>(mixed_hi) << 32u) | mixed_lo;
  rng.increment =
      (((static_cast<unsigned long long>(Pcg32::hash(stream_hi ^ tag))
         << 32u) |
        Pcg32::hash(stream_lo ^ mixed_hi)) |
       1ull);
  rng.next_uint();
}

constexpr unsigned int kMaxFlames = 8u;
constexpr unsigned int kMaxVolumeEvents = 2u * kMaxFlames;
constexpr unsigned int kMaxTrackingCandidates = 4096u;

struct VolumeEvent {
  float distance;
  unsigned int flame_slot;
  int entering;
};

struct VolumeCollision {
  int collided;
  float distance;
  float3 source;
};

static __forceinline__ __device__ float smoothstep01(float x) {
  x = fminf(fmaxf(x, 0.0f), 1.0f);
  return x * x * (3.0f - 2.0f * x);
}

static __forceinline__ __device__ float lattice_noise(
    int x, int y, int z, unsigned int seed) {
  unsigned int h = Pcg32::hash(static_cast<unsigned int>(x) ^ seed);
  h = Pcg32::hash(h ^ (static_cast<unsigned int>(y) * 0x9e3779b9u));
  h = Pcg32::hash(h ^ (static_cast<unsigned int>(z) * 0x85ebca6bu));
  return static_cast<float>(h >> 8) * 0x1.0p-24f;
}

static __forceinline__ __device__ float value_noise(
    float3 p, unsigned int seed) {
  const int ix = static_cast<int>(floorf(p.x));
  const int iy = static_cast<int>(floorf(p.y));
  const int iz = static_cast<int>(floorf(p.z));
  const float fx = smoothstep01(p.x - static_cast<float>(ix));
  const float fy = smoothstep01(p.y - static_cast<float>(iy));
  const float fz = smoothstep01(p.z - static_cast<float>(iz));
  const float n000 = lattice_noise(ix, iy, iz, seed);
  const float n100 = lattice_noise(ix + 1, iy, iz, seed);
  const float n010 = lattice_noise(ix, iy + 1, iz, seed);
  const float n110 = lattice_noise(ix + 1, iy + 1, iz, seed);
  const float n001 = lattice_noise(ix, iy, iz + 1, seed);
  const float n101 = lattice_noise(ix + 1, iy, iz + 1, seed);
  const float n011 = lattice_noise(ix, iy + 1, iz + 1, seed);
  const float n111 = lattice_noise(ix + 1, iy + 1, iz + 1, seed);
  const float nx00 = n000 + (n100 - n000) * fx;
  const float nx10 = n010 + (n110 - n010) * fx;
  const float nx01 = n001 + (n101 - n001) * fx;
  const float nx11 = n011 + (n111 - n011) * fx;
  const float nxy0 = nx00 + (nx10 - nx00) * fy;
  const float nxy1 = nx01 + (nx11 - nx01) * fy;
  return nxy0 + (nxy1 - nxy0) * fz;
}

static __forceinline__ __device__ float flame_fbm(
    float3 p, unsigned int seed) {
  float value = value_noise(p, seed);
  value += 0.5f * value_noise(mul(p, 2.0f), seed ^ 0xa511e9b3u);
  value += 0.25f * value_noise(mul(p, 4.0f), seed ^ 0x63d83595u);
  return value * (1.0f / 1.75f);
}

static __forceinline__ __device__ float flame_density(
    const LightData& light, float3 point, VolumeCounters& counters,
    float* axial_out = nullptr) {
  ++counters.density_evaluations;
  const float3 axis = normalize3(light.axis);
  const float axial_distance = dot3(sub(point, light.p0), axis);
  if (!(axial_distance >= 0.0f && axial_distance <= light.height) ||
      !(light.height > 0.0f)) {
    if (axial_out != nullptr) *axial_out = 0.0f;
    return 0.0f;
  }
  const float axial = axial_distance / light.height;
  if (axial_out != nullptr) *axial_out = axial;
  const float nominal_radius =
      light.radius_start + (light.radius_end - light.radius_start) * axial;
  if (!(nominal_radius > 0.0f)) return 0.0f;

  float3 tangent;
  float3 bitangent;
  make_basis(axis, tangent, bitangent);
  const float center_frequency = axial * light.noise_scale;
  const float offset_limit =
      0.2f * light.turbulence * nominal_radius;
  float offset_u =
      (value_noise(f3(center_frequency, 17.125f, -3.75f), light.seed) *
           2.0f -
       1.0f) * offset_limit;
  float offset_v =
      (value_noise(f3(-11.25f, center_frequency, 5.625f),
                   light.seed ^ 0x51ed270bu) *
           2.0f -
       1.0f) * offset_limit;
  float offset_length = sqrtf(offset_u * offset_u + offset_v * offset_v);
  if (offset_length > offset_limit && offset_length > 0.0f) {
    const float scale = offset_limit / offset_length;
    offset_u *= scale;
    offset_v *= scale;
    offset_length = offset_limit;
  }
  const float3 center =
      add(add(light.p0, mul(axis, axial_distance)),
          add(mul(tangent, offset_u), mul(bitangent, offset_v)));
  // Shrinking by the actual center-line displacement keeps every non-zero
  // density sample inside the declared max-radius support cylinder.
  const float local_radius = nominal_radius - offset_length;
  if (!(local_radius > 1.0e-8f)) return 0.0f;
  const float3 radial_vector = sub(point, center);
  const float radial_distance = length3(sub(
      radial_vector, mul(axis, dot3(radial_vector, axis))));
  const float radial = radial_distance / local_radius;
  if (!(radial < 1.0f)) return 0.0f;

  const float radial_envelope =
      1.0f - smoothstep01((radial - 0.55f) / 0.45f);
  const float root_fade = smoothstep01(axial / 0.04f);
  const float tip_fade = 1.0f - smoothstep01((axial - 0.85f) / 0.15f);
  const float max_radius = fmaxf(light.radius_start, light.radius_end);
  const float inverse_scale = 1.0f / fmaxf(max_radius, 1.0e-6f);
  const float3 local = sub(point, light.p0);
  const float3 noise_point =
      f3(dot3(local, tangent) * inverse_scale * light.noise_scale,
         axial * light.noise_scale,
         dot3(local, bitangent) * inverse_scale * light.noise_scale);
  const float noise = flame_fbm(noise_point, light.seed ^ 0xb5297a4du);
  const float modulation =
      (1.0f - light.turbulence) +
      light.turbulence * (0.35f + 0.65f * noise);
  return fminf(fmaxf(radial_envelope * root_fade * tip_fade * modulation,
                     0.0f),
               1.0f);
}

static __forceinline__ __device__ float3 flame_source(
    const LightData& light, float axial) {
  return lerp3(light.emission_start, light.emission_end,
               fminf(fmaxf(axial, 0.0f), 1.0f));
}

static __forceinline__ __device__ bool flame_sphere_interval(
    const LightData& light, float3 origin, float3 direction,
    float maximum_distance, float& near_distance, float& far_distance) {
  const float half_height = 0.5f * light.height;
  const float maximum_radius =
      fmaxf(light.radius_start, light.radius_end);
  const float sphere_radius =
      sqrtf(half_height * half_height + maximum_radius * maximum_radius);
  const float3 center = add(light.p0, mul(normalize3(light.axis), half_height));
  const float3 offset = sub(origin, center);
  const float b = dot3(offset, direction);
  const float c = length2(offset) - sphere_radius * sphere_radius;
  const float discriminant = b * b - c;
  if (!(discriminant > 0.0f)) return false;
  const float root = sqrtf(discriminant);
  near_distance = fmaxf(-b - root, 0.0f);
  far_distance = fminf(-b + root, maximum_distance);
  return far_distance > near_distance;
}

static __forceinline__ __device__ VolumeCollision track_volume(
    float3 origin, float3 direction, float maximum_distance, Pcg32& rng,
    VolumeCounters& counters) {
  VolumeCollision result{};
  result.source = f3(0.0f, 0.0f, 0.0f);
  if (params.flame_count == 0u || params.lights == nullptr) return result;

  unsigned int flame_indices[kMaxFlames]{};
  VolumeEvent events[kMaxVolumeEvents]{};
  unsigned int flame_slots = 0u;
  unsigned int event_count = 0u;
  for (unsigned int light_index = 0u;
       light_index < params.all_light_count && flame_slots < kMaxFlames;
       ++light_index) {
    const LightData& light = params.lights[light_index];
    if (light.type != spectraldock::kLightFlame) continue;
    const unsigned int slot = flame_slots++;
    flame_indices[slot] = light_index;
    float near_distance;
    float far_distance;
    if (!flame_sphere_interval(light, origin, direction, maximum_distance,
                               near_distance, far_distance)) {
      continue;
    }
    events[event_count++] = {near_distance, slot, 1};
    events[event_count++] = {far_distance, slot, 0};
  }
  if (event_count == 0u) return result;
  for (unsigned int i = 1u; i < event_count; ++i) {
    const VolumeEvent value = events[i];
    unsigned int j = i;
    while (j > 0u && events[j - 1u].distance > value.distance) {
      events[j] = events[j - 1u];
      --j;
    }
    events[j] = value;
  }

  unsigned int active_mask = 0u;
  unsigned int candidate_count = 0u;
  unsigned int event_index = 0u;
  float distance = 0.0f;
  while (event_index < event_count) {
    const float event_distance = events[event_index].distance;
    if (event_distance > distance && active_mask != 0u) {
      float majorant = 0.0f;
      for (unsigned int slot = 0u; slot < flame_slots; ++slot) {
        if ((active_mask & (1u << slot)) == 0u) continue;
        const LightData& light = params.lights[flame_indices[slot]];
        majorant += light.extinction * light.density_scale;
      }
      float candidate_distance = distance;
      while (majorant > 0.0f) {
        if (++candidate_count > kMaxTrackingCandidates) {
          ++counters.tracking_overflows;
          result.collided = 1;
          result.distance = candidate_distance;
          return result;
        }
        const float u = rng.next_open01();
        candidate_distance += -log1pf(-u) / majorant;
        if (!(candidate_distance < event_distance)) break;
        const float3 point = add(origin, mul(direction, candidate_distance));
        float sigma_total = 0.0f;
        float3 source_numerator = f3(0.0f, 0.0f, 0.0f);
        for (unsigned int slot = 0u; slot < flame_slots; ++slot) {
          if ((active_mask & (1u << slot)) == 0u) continue;
          const LightData& light = params.lights[flame_indices[slot]];
          float axial = 0.0f;
          const float density = flame_density(light, point, counters, &axial);
          const float sigma =
              light.extinction * light.density_scale * density;
          sigma_total += sigma;
          source_numerator =
              add(source_numerator, mul(flame_source(light, axial), sigma));
        }
        if (sigma_total > majorant) {
          ++counters.majorant_violations;
        }
        const float acceptance =
            fminf(fmaxf(sigma_total / majorant, 0.0f), 1.0f);
        if (rng.next() < acceptance) {
          ++counters.real_collisions;
          result.collided = 1;
          result.distance = candidate_distance;
          result.source = sigma_total > 0.0f
              ? divv(source_numerator, sigma_total)
              : f3(0.0f, 0.0f, 0.0f);
          return result;
        }
      }
    }
    distance = event_distance;
    do {
      const unsigned int bit = 1u << events[event_index].flame_slot;
      if (events[event_index].entering != 0) {
        active_mask |= bit;
      } else {
        active_mask &= ~bit;
      }
      ++event_index;
    } while (event_index < event_count &&
             events[event_index].distance == event_distance);
  }
  return result;
}

struct SurfaceHit {
  int hit;
  int material_index;
  int light_index;
  int front_face;
  float distance;
  float3 position;
  float3 geometric_normal;
  float3 normal;
  float2 uv;
};

struct BsdfSample {
  float3 wi;
  float3 weight;
  float pdf;
  int delta;
  int valid;
  int transmitted;
};

struct MediumLayer {
  int material_index;
  float ior;
  float3 absorption;
};

struct MediumState {
  MediumLayer layers[4];
  int depth;
};

static __forceinline__ __device__ WaterCounters* pixel_water_counters() {
  if (params.water_counters == nullptr) return nullptr;
  const uint3 index = optixGetLaunchIndex();
  if (index.x >= params.width || index.y >= params.height) return nullptr;
  return &params.water_counters[index.y * params.width + index.x];
}

static __forceinline__ __device__ float medium_ior(
    const MediumState& state) {
  return state.depth > 0 ? state.layers[state.depth - 1].ior : 1.0f;
}

static __forceinline__ __device__ float3 medium_absorption(
    const MediumState& state) {
  return state.depth > 0 ? state.layers[state.depth - 1].absorption
                         : f3(0.0f, 0.0f, 0.0f);
}

static __forceinline__ __device__ float3 medium_segment_transmittance(
    const MediumState& state, float distance, WaterCounters& counters) {
  if (state.depth <= 0 || !(distance > 0.0f)) {
    return f3(1.0f, 1.0f, 1.0f);
  }
  ++counters.medium_segments;
  return exp_attenuation(medium_absorption(state), distance);
}

static __forceinline__ __device__ float exit_ior(
    const MediumState& state, int material_index, WaterCounters& counters) {
  if (state.depth <= 0 ||
      state.layers[state.depth - 1].material_index != material_index) {
    ++counters.medium_errors;
    return 1.0f;
  }
  return state.depth > 1 ? state.layers[state.depth - 2].ior : 1.0f;
}

static __forceinline__ __device__ bool update_medium_after_transmission(
    MediumState& state, int material_index, const MaterialData& material,
    int front_face, WaterCounters& counters) {
  if (front_face != 0) {
    if (state.depth >= 4) {
      ++counters.medium_errors;
      return false;
    }
    state.layers[state.depth++] =
        {material_index, fmaxf(material.ior, 1.0e-3f), material.absorption};
    return true;
  }
  if (state.depth <= 0 ||
      state.layers[state.depth - 1].material_index != material_index) {
    ++counters.medium_errors;
    return false;
  }
  --state.depth;
  return true;
}

// A finite water top interface has no geometric side boundary. A path which
// enters below the footprint edge can therefore first encounter its back face
// while the stack is empty. Only that unambiguous base-water case is inferred;
// a non-empty stack (especially a nested dielectric) is never repaired or
// searched and remains a strict LIFO error.
static __forceinline__ __device__ void infer_base_water_incident_medium(
    const SurfaceHit& hit, MediumState& state) {
  if (state.depth != 0 || hit.front_face != 0 || hit.material_index < 0 ||
      params.materials == nullptr ||
      static_cast<unsigned int>(hit.material_index) >= params.material_count) {
    return;
  }
  const MaterialData material = params.materials[hit.material_index];
  if (material.type != spectraldock::kMaterialWater) return;
  state.layers[state.depth++] =
      {hit.material_index, fmaxf(material.ior, 1.0e-3f),
       material.absorption};
}

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

static __forceinline__ __device__ float water_height(
    const GeometryData& geometry, float x, float z,
    float* derivative_x = nullptr, float* derivative_z = nullptr) {
  if (WaterCounters* counters = pixel_water_counters()) {
    ++counters->height_evaluations;
  }
  float height = geometry.p0.y;
  float dx = 0.0f;
  float dz = 0.0f;
  const float local_x = x - geometry.p0.x;
  const float local_z = z - geometry.p0.z;
  const unsigned int count =
      geometry.water_wave_count < 4u ? geometry.water_wave_count : 4u;
  for (unsigned int i = 0u; i < count; ++i) {
    const spectraldock::DeviceWaterWave& wave = geometry.water_waves[i];
    const float angle = wave.wave_number *
                            (wave.direction.x * local_x +
                             wave.direction.y * local_z) +
                        wave.phase;
    height += wave.amplitude * sinf(angle);
    const float slope = wave.amplitude * wave.wave_number * cosf(angle);
    dx += slope * wave.direction.x;
    dz += slope * wave.direction.y;
  }
  if (derivative_x != nullptr) *derivative_x = dx;
  if (derivative_z != nullptr) *derivative_z = dz;
  return height;
}

static __forceinline__ __device__ float water_function_value(
    const GeometryData& geometry, float3 origin, float3 direction, float t) {
  const float3 point = add(origin, mul(direction, t));
  return point.y - water_height(geometry, point.x, point.z);
}

static __forceinline__ __device__ double water_function_value_precise(
    const GeometryData& geometry, float3 origin, float3 direction, double t) {
  const double x = static_cast<double>(origin.x) +
                   static_cast<double>(direction.x) * t;
  const double y = static_cast<double>(origin.y) +
                   static_cast<double>(direction.y) * t;
  const double z = static_cast<double>(origin.z) +
                   static_cast<double>(direction.z) * t;
  double height = static_cast<double>(geometry.p0.y);
  const double local_x = x - static_cast<double>(geometry.p0.x);
  const double local_z = z - static_cast<double>(geometry.p0.z);
  const unsigned int count =
      geometry.water_wave_count < 4u ? geometry.water_wave_count : 4u;
  for (unsigned int i = 0u; i < count; ++i) {
    const spectraldock::DeviceWaterWave& wave = geometry.water_waves[i];
    const double phase = static_cast<double>(wave.wave_number) *
                             (static_cast<double>(wave.direction.x) * local_x +
                              static_cast<double>(wave.direction.y) * local_z) +
                         static_cast<double>(wave.phase);
    height += static_cast<double>(wave.amplitude) * sin(phase);
  }
  return y - height;
}

static __forceinline__ __device__ bool refine_suspicious_water_bracket(
    const GeometryData& geometry, float3 origin, float3 direction,
    float lower, float upper, float& root, float& residual,
    int& orientation) {
  double precise_lower = static_cast<double>(lower);
  double precise_upper = static_cast<double>(upper);
  double lower_value = water_function_value_precise(
      geometry, origin, direction, precise_lower);
  const double upper_value = water_function_value_precise(
      geometry, origin, direction, precise_upper);
  if ((lower_value < 0.0) == (upper_value < 0.0)) return false;
  orientation = lower_value < 0.0 ? 1 : -1;
  for (int iteration = 0; iteration < 40; ++iteration) {
    const double middle = 0.5 * (precise_lower + precise_upper);
    const double middle_value = water_function_value_precise(
        geometry, origin, direction, middle);
    if ((middle_value < 0.0) == (lower_value < 0.0)) {
      precise_lower = middle;
      lower_value = middle_value;
    } else {
      precise_upper = middle;
    }
  }
  root = static_cast<float>(0.5 * (precise_lower + precise_upper));
  residual = fabsf(water_function_value(
      geometry, origin, direction, root));
  return true;
}

static __forceinline__ __device__ bool validate_water_endpoint_crossing(
    const GeometryData& geometry, float3 origin, float3 direction,
    float root, int& orientation) {
  const double ulp_scale =
      8.0 * static_cast<double>(1.1920928955078125e-7f) *
      fmax(1.0, fabs(static_cast<double>(root)));
  const double probe_distance =
      fmax(static_cast<double>(params.scene_epsilon), ulp_scale);
  const double left = water_function_value_precise(
      geometry, origin, direction,
      static_cast<double>(root) - probe_distance);
  const double right = water_function_value_precise(
      geometry, origin, direction,
      static_cast<double>(root) + probe_distance);
  if (left == 0.0 || right == 0.0 || (left < 0.0) == (right < 0.0)) {
    return false;
  }
  orientation = left < 0.0 ? 1 : -1;
  return true;
}

struct ScalarInterval {
  float lower;
  float upper;
};

static __forceinline__ __device__ ScalarInterval widen_interval(
    ScalarInterval interval) {
  const float scale = fmaxf(fabsf(interval.lower), fabsf(interval.upper));
  const float padding = 4.0e-6f * (1.0f + scale);
  interval.lower -= padding;
  interval.upper += padding;
  return interval;
}

static __forceinline__ __device__ bool contains_periodic_phase(
    float lower, float upper, float phase) {
  const float period = 2.0f * kPi;
  const float first = phase +
      ceilf((lower - phase) / period) * period;
  return first <= upper;
}

static __forceinline__ __device__ ScalarInterval sine_interval(
    float phase0, float phase1) {
  const float lower = fminf(phase0, phase1);
  const float upper = fmaxf(phase0, phase1);
  if (upper - lower >= 2.0f * kPi) return {-1.0f, 1.0f};
  float minimum = fminf(sinf(lower), sinf(upper));
  float maximum = fmaxf(sinf(lower), sinf(upper));
  if (contains_periodic_phase(lower, upper, 0.5f * kPi)) maximum = 1.0f;
  if (contains_periodic_phase(lower, upper, -0.5f * kPi)) minimum = -1.0f;
  return widen_interval({minimum, maximum});
}

static __forceinline__ __device__ ScalarInterval cosine_interval(
    float phase0, float phase1) {
  const float lower = fminf(phase0, phase1);
  const float upper = fmaxf(phase0, phase1);
  if (upper - lower >= 2.0f * kPi) return {-1.0f, 1.0f};
  float minimum = fminf(cosf(lower), cosf(upper));
  float maximum = fmaxf(cosf(lower), cosf(upper));
  if (contains_periodic_phase(lower, upper, 0.0f)) maximum = 1.0f;
  if (contains_periodic_phase(lower, upper, kPi)) minimum = -1.0f;
  return widen_interval({minimum, maximum});
}

static __forceinline__ __device__ void water_phase_line(
    const GeometryData& geometry, const spectraldock::DeviceWaterWave& wave,
    float3 origin, float3 direction, float& offset, float& rate) {
  const float local_x = origin.x - geometry.p0.x;
  const float local_z = origin.z - geometry.p0.z;
  offset = wave.wave_number *
               (wave.direction.x * local_x +
                wave.direction.y * local_z) +
           wave.phase;
  rate = wave.wave_number *
         (wave.direction.x * direction.x +
          wave.direction.y * direction.z);
}

static __forceinline__ __device__ ScalarInterval water_function_interval(
    const GeometryData& geometry, float3 origin, float3 direction,
    float t0, float t1) {
  const float y0 = origin.y + direction.y * t0 - geometry.p0.y;
  const float y1 = origin.y + direction.y * t1 - geometry.p0.y;
  ScalarInterval result{fminf(y0, y1), fmaxf(y0, y1)};
  const unsigned int count =
      geometry.water_wave_count < 4u ? geometry.water_wave_count : 4u;
  for (unsigned int i = 0u; i < count; ++i) {
    const spectraldock::DeviceWaterWave& wave = geometry.water_waves[i];
    float offset = 0.0f;
    float rate = 0.0f;
    water_phase_line(geometry, wave, origin, direction, offset, rate);
    const ScalarInterval sine =
        sine_interval(offset + rate * t0, offset + rate * t1);
    result.lower -= wave.amplitude * sine.upper;
    result.upper -= wave.amplitude * sine.lower;
  }
  return widen_interval(result);
}

static __forceinline__ __device__ ScalarInterval water_derivative_interval(
    const GeometryData& geometry, float3 origin, float3 direction,
    float t0, float t1) {
  ScalarInterval result{direction.y, direction.y};
  const unsigned int count =
      geometry.water_wave_count < 4u ? geometry.water_wave_count : 4u;
  for (unsigned int i = 0u; i < count; ++i) {
    const spectraldock::DeviceWaterWave& wave = geometry.water_waves[i];
    float offset = 0.0f;
    float rate = 0.0f;
    water_phase_line(geometry, wave, origin, direction, offset, rate);
    const ScalarInterval cosine =
        cosine_interval(offset + rate * t0, offset + rate * t1);
    const float coefficient = wave.amplitude * rate;
    const float term0 = coefficient * cosine.lower;
    const float term1 = coefficient * cosine.upper;
    const float term_minimum = fminf(term0, term1);
    const float term_maximum = fmaxf(term0, term1);
    result.lower -= term_maximum;
    result.upper -= term_minimum;
  }
  return widen_interval(result);
}

static __forceinline__ __device__ float water_derivative_value(
    const GeometryData& geometry, float3 origin, float3 direction, float t) {
  const float3 point = add(origin, mul(direction, t));
  float derivative_x = 0.0f;
  float derivative_z = 0.0f;
  water_height(geometry, point.x, point.z, &derivative_x, &derivative_z);
  return direction.y - derivative_x * direction.x -
         derivative_z * direction.z;
}

static __forceinline__ __device__ float solve_water_monotonic_root(
    const GeometryData& geometry, float3 origin, float3 direction,
    float lower, float upper, float lower_value, float upper_value) {
  if (lower_value == 0.0f) return lower;
  if (upper_value == 0.0f) return upper;
  float bracket_lower = lower;
  float bracket_upper = upper;
  float bracket_lower_value = lower_value;
  for (int iteration = 0; iteration < 12; ++iteration) {
    const float middle = 0.5f * (bracket_lower + bracket_upper);
    const float value =
        water_function_value(geometry, origin, direction, middle);
    if ((value < 0.0f) == (bracket_lower_value < 0.0f)) {
      bracket_lower = middle;
      bracket_lower_value = value;
    } else {
      bracket_upper = middle;
    }
  }
  float root = 0.5f * (bracket_lower + bracket_upper);
  for (int iteration = 0; iteration < 4; ++iteration) {
    const float value =
        water_function_value(geometry, origin, direction, root);
    const float derivative =
        water_derivative_value(geometry, origin, direction, root);
    if (fabsf(derivative) < 1.0e-10f) break;
    const float candidate = root - value / derivative;
    if (!(candidate > bracket_lower && candidate < bracket_upper)) break;
    root = candidate;
  }
  return root;
}

struct WaterRootWorkItem {
  float lower;
  float upper;
  float lower_value;
  float upper_value;
  unsigned int depth;
};

static __forceinline__ __device__ bool water_tile_owns_point(
    float3 point, float tile_min_x, float tile_max_x,
    float tile_min_z, float tile_max_z, unsigned int tile_x,
    unsigned int tile_z, unsigned int tiles_x, unsigned int tiles_z) {
  const bool owns_x = point.x >= tile_min_x &&
      (tile_x + 1u == tiles_x ? point.x <= tile_max_x
                              : point.x < tile_max_x);
  const bool owns_z = point.z >= tile_min_z &&
      (tile_z + 1u == tiles_z ? point.z <= tile_max_z
                              : point.z < tile_max_z);
  return owns_x && owns_z;
}

struct WaterRootCandidate {
  float distance;
  float residual;
  int orientation;
};

static __forceinline__ __device__ bool append_water_root_candidate(
    float root, float residual, int orientation,
    WaterRootCandidate* candidates, unsigned int& count,
    unsigned int capacity) {
  const float duplicate_tolerance =
      4.0f * 1.1920928955078125e-7f * fmaxf(1.0f, fabsf(root));
  for (unsigned int i = 0u; i < count; ++i) {
    if (candidates[i].orientation == orientation &&
        fabsf(candidates[i].distance - root) <= duplicate_tolerance) {
      if (residual < candidates[i].residual) {
        candidates[i] = {root, residual, orientation};
      }
      return true;
    }
  }
  if (count >= capacity) return false;
  candidates[count++] = {root, residual, orientation};
  return true;
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
  if (geometry.primitive_type == spectraldock::kPrimitiveSphere ||
      geometry.primitive_type == spectraldock::kPrimitiveSolidSphere) {
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
  if (geometry.primitive_type == spectraldock::kPrimitiveWaterSurface) {
    return f2((object_point.x - geometry.p0.x) / geometry.water_size.x +
                  0.5f,
              (object_point.z - geometry.p0.z) / geometry.water_size.y +
                  0.5f);
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
  if (geometry.primitive_type == spectraldock::kPrimitiveSphere ||
      geometry.primitive_type == spectraldock::kPrimitiveSolidSphere) {
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
  if (geometry.primitive_type == spectraldock::kPrimitiveWaterSurface) {
    float derivative_x = 0.0f;
    float derivative_z = 0.0f;
    water_height(geometry, object_point.x, object_point.z,
                 &derivative_x, &derivative_z);
    return normalize3(f3(-derivative_x, 1.0f, -derivative_z));
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
    float3 origin, float3 direction, unsigned long long& traced_rays,
    float maximum_distance = kInfinity) {
  SurfaceHit hit = {};
  hit.hit = 0;
  hit.distance = kInfinity;
  unsigned int p0;
  unsigned int p1;
  pack_pointer(&hit, p0, p1);
  ++traced_rays;
  optixTrace(params.traversable, origin, direction, params.scene_epsilon,
             maximum_distance, 0.0f, OptixVisibilityMask(255),
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

static __forceinline__ __device__ float dielectric_fresnel(
    float cos_i, float eta_i, float eta_t, float* cos_t_out = nullptr) {
  cos_i = fminf(fmaxf(cos_i, 0.0f), 1.0f);
  const float eta = eta_i / eta_t;
  const float sin2_t = eta * eta * fmaxf(0.0f, 1.0f - cos_i * cos_i);
  if (sin2_t >= 1.0f) {
    if (cos_t_out != nullptr) *cos_t_out = 0.0f;
    return 1.0f;
  }
  const float cos_t = sqrtf(fmaxf(0.0f, 1.0f - sin2_t));
  if (cos_t_out != nullptr) *cos_t_out = cos_t;
  const float rs_denominator = eta_i * cos_i + eta_t * cos_t;
  const float rp_denominator = eta_t * cos_i + eta_i * cos_t;
  const float rs = (eta_i * cos_i - eta_t * cos_t) /
                   fmaxf(rs_denominator, 1.0e-20f);
  const float rp = (eta_t * cos_i - eta_i * cos_t) /
                   fmaxf(rp_denominator, 1.0e-20f);
  return 0.5f * (rs * rs + rp * rp);
}

static __forceinline__ __device__ bool is_rough_dielectric(
    const MaterialData& material) {
  return (material.type == spectraldock::kMaterialDielectric ||
          material.type == spectraldock::kMaterialWater) &&
         material.roughness > 0.0f;
}

static __forceinline__ __device__ float rough_reflection_probability(
    const MaterialData& material, float fresnel) {
  // Moonlit water is reflection-dominated perceptually even when Fresnel is
  // small. Oversample that branch, while evaluate_bsdf keeps the exact F in
  // the BSDF value and uses this same probability only in the direction PDF.
  if (fresnel >= 1.0f) return 1.0f;
  return material.type == spectraldock::kMaterialWater
      ? fmaxf(fresnel, 0.5f)
      : fresnel;
}

static __forceinline__ __device__ bool supports_direct_lighting(
    const MaterialData& material) {
  return material.type == spectraldock::kMaterialLambertian ||
         material.type == spectraldock::kMaterialMetal ||
         is_rough_dielectric(material);
}

// Shading normals shape the lobe, but only the oriented geometric normal can
// decide which physical medium a direction occupies. Reject a rough
// dielectric direction when those two classifications disagree; otherwise a
// reflected sample could mutate the medium stack (or a transmitted one could
// stay on the incident side).
static __forceinline__ __device__ bool rough_macro_sides_agree(
    float3 shading_normal, float3 geometric_normal, float3 direction,
    bool& transmitted) {
  const float shading_side = dot3(shading_normal, direction);
  const float geometric_side = dot3(geometric_normal, direction);
  if (!(fabsf(shading_side) > 0.0f) ||
      !(fabsf(geometric_side) > 0.0f) ||
      (shading_side > 0.0f) != (geometric_side > 0.0f)) {
    return false;
  }
  transmitted = geometric_side < 0.0f;
  return true;
}

static __forceinline__ __device__ void dielectric_eta_pair(
    const MaterialData& material, int front_face, int material_index,
    const MediumState* media, WaterCounters& counters,
    float& eta_i, float& eta_t) {
  if (media != nullptr) {
    eta_i = medium_ior(*media);
    eta_t = front_face != 0
        ? fmaxf(material.ior, 1.0e-3f)
        : exit_ior(*media, material_index, counters);
    return;
  }
  eta_i = front_face != 0 ? 1.0f : fmaxf(material.ior, 1.0e-3f);
  eta_t = front_face != 0 ? fmaxf(material.ior, 1.0e-3f) : 1.0f;
}

// Heitz's isotropic GGX visible-normal sampler. Sampling the distribution of
// normals visible from wo avoids the grazing-angle rejection spikes of an NDF
// sampler and gives the reflection/transmission lobes one shared measure.
static __forceinline__ __device__ float3 sample_ggx_vndf(
    float3 n, float3 wo, float alpha, float u1, float u2) {
  float3 tangent;
  float3 bitangent;
  make_basis(n, tangent, bitangent);
  const float3 view =
      f3(dot3(wo, tangent), dot3(wo, bitangent), dot3(wo, n));
  const float3 stretched = normalize3(
      f3(alpha * view.x, alpha * view.y, fmaxf(view.z, 0.0f)));
  const float lensq = stretched.x * stretched.x +
                      stretched.y * stretched.y;
  const float3 t1 = lensq > 1.0e-20f
      ? f3(-stretched.y * rsqrtf(lensq),
           stretched.x * rsqrtf(lensq), 0.0f)
      : f3(1.0f, 0.0f, 0.0f);
  const float3 t2 = cross3(stretched, t1);
  const float radius = sqrtf(u1);
  const float phi = 2.0f * kPi * u2;
  const float disk_x = radius * cosf(phi);
  float disk_y = radius * sinf(phi);
  const float blend = 0.5f * (1.0f + stretched.z);
  disk_y = (1.0f - blend) *
               sqrtf(fmaxf(0.0f, 1.0f - disk_x * disk_x)) +
           blend * disk_y;
  const float disk_z = sqrtf(fmaxf(
      0.0f, 1.0f - disk_x * disk_x - disk_y * disk_y));
  const float3 visible = add(
      add(mul(t1, disk_x), mul(t2, disk_y)), mul(stretched, disk_z));
  const float3 local_half = normalize3(
      f3(alpha * visible.x, alpha * visible.y,
         fmaxf(visible.z, 0.0f)));
  return normalize3(add(add(mul(tangent, local_half.x),
                            mul(bitangent, local_half.y)),
                        mul(n, local_half.z)));
}

static __forceinline__ __device__ float ggx_visible_normal_pdf(
    float3 n, float3 wo, float3 half_vector, float alpha) {
  const float no_v = fmaxf(dot3(n, wo), 0.0f);
  const float no_h = fmaxf(dot3(n, half_vector), 0.0f);
  const float vo_h = fmaxf(dot3(wo, half_vector), 0.0f);
  if (!(no_v > 0.0f) || !(no_h > 0.0f) || !(vo_h > 0.0f)) {
    return 0.0f;
  }
  return ggx_distribution(no_h, alpha) * ggx_g1(no_v, alpha) * vo_h /
         no_v;
}

static __forceinline__ __device__ void evaluate_bsdf(
    const MaterialData& material, float3 base_color, float3 n, float3 wo,
    float3 wi, float eta_i, float eta_t, float3& value, float& pdf) {
  value = f3(0.0f, 0.0f, 0.0f);
  pdf = 0.0f;
  const float no_l = dot3(n, wi);
  const float no_v = dot3(n, wo);
  if (no_v <= 0.0f) {
    return;
  }
  if (material.type == spectraldock::kMaterialLambertian) {
    if (no_l <= 0.0f) return;
    value = mul(base_color, kInvPi);
    pdf = no_l * kInvPi;
    return;
  }
  if (material.type == spectraldock::kMaterialMetal) {
    if (no_l <= 0.0f) return;
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
    const float half_pdf = ggx_visible_normal_pdf(
        n, wo, half_vector, alpha);
    pdf = half_pdf / fmaxf(4.0f * vo_h, 1.0e-20f);
    return;
  }
  if (!is_rough_dielectric(material)) {
    return;
  }

  const float alpha =
      fmaxf(material.roughness * material.roughness, 0.001f);
  const bool reflection = no_l > 0.0f;
  float3 half_vector;
  float eta_path = 1.0f;
  if (reflection) {
    half_vector = normalize3(add(wo, wi));
  } else {
    // etap is eta_t / eta_i. With both directions pointing away from the
    // interface, h is proportional to wo + etap*wi (Walter et al. 2007).
    eta_path = eta_t / fmaxf(eta_i, 1.0e-20f);
    half_vector = normalize3(add(wo, mul(wi, eta_path)));
  }
  if (dot3(half_vector, n) < 0.0f) half_vector = neg(half_vector);
  const float no_h = fmaxf(dot3(n, half_vector), 0.0f);
  const float wo_h = dot3(wo, half_vector);
  const float wi_h = dot3(wi, half_vector);
  if (!(no_h > 0.0f) || !(wo_h > 0.0f)) return;
  if ((reflection && !(wi_h > 0.0f)) ||
      (!reflection && !(wi_h < 0.0f))) {
    return;
  }
  const float d = ggx_distribution(no_h, alpha);
  const float g = ggx_g1(no_v, alpha) *
                  ggx_g1(fabsf(no_l), alpha);
  const float fresnel = dielectric_fresnel(wo_h, eta_i, eta_t);
  const float reflection_probability =
      rough_reflection_probability(material, fresnel);
  const float half_pdf = ggx_visible_normal_pdf(
      n, wo, half_vector, alpha);
  if (reflection) {
    value = mul(base_color,
                fresnel * d * g /
                    fmaxf(4.0f * no_v * no_l, 1.0e-20f));
    pdf = reflection_probability * half_pdf /
          fmaxf(4.0f * fabsf(wo_h), 1.0e-20f);
    return;
  }
  const float denominator = wo_h + eta_path * wi_h;
  const float denominator2 = denominator * denominator;
  if (!(denominator2 > 1.0e-20f)) return;
  // Radiance transport carries the eta_i^2/eta_t^2 factor. It appears in the
  // sample weight through the solid-angle Jacobian below, matching the delta
  // transmission convention used by this renderer.
  value = mul(base_color,
              (1.0f - fresnel) * d * g * fabsf(wi_h * wo_h) /
                  fmaxf(no_v * fabsf(no_l) * denominator2, 1.0e-20f));
  const float jacobian =
      fabsf(eta_path * eta_path * wi_h / denominator2);
  pdf = (1.0f - reflection_probability) * half_pdf * jacobian;
}

static __forceinline__ __device__ BsdfSample sample_bsdf(
    const MaterialData& material, float3 base_color, float3 n,
    float3 geometric_n, float3 wo, int front_face, int material_index,
    Pcg32& rng, MediumState* media, WaterCounters& water_counters) {
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
    const float3 half_vector = sample_ggx_vndf(
        n, wo, alpha, rng.next(), rng.next());
    sample.wi = normalize3(reflect3(neg(wo), half_vector));
    float3 value;
    evaluate_bsdf(material, base_color, n, wo, sample.wi,
                  1.0f, 1.0f, value, sample.pdf);
    const float no_l = fmaxf(dot3(n, sample.wi), 0.0f);
    if (sample.pdf > 0.0f && no_l > 0.0f) {
      sample.weight = mul(value, no_l / sample.pdf);
      sample.valid = 1;
    }
    sample.delta = 0;
    return sample;
  }
  if (material.type == spectraldock::kMaterialDielectric ||
      material.type == spectraldock::kMaterialWater) {
    if (is_rough_dielectric(material)) {
      float eta_i = 1.0f;
      float eta_t = 1.0f;
      dielectric_eta_pair(material, front_face, material_index, media,
                          water_counters, eta_i, eta_t);
      const float alpha =
          fmaxf(material.roughness * material.roughness, 0.001f);
      const float3 half_vector = sample_ggx_vndf(
          n, wo, alpha, rng.next(), rng.next());
      const float wo_h = fmaxf(dot3(wo, half_vector), 0.0f);
      if (!(wo_h > 0.0f)) return sample;
      const float reflectance = dielectric_fresnel(
          wo_h, eta_i, eta_t);
      const float reflection_probability =
          rough_reflection_probability(material, reflectance);
      if (reflection_probability >= 1.0f ||
          rng.next() < reflection_probability) {
        sample.wi = normalize3(reflect3(neg(wo), half_vector));
      } else {
        const float eta = eta_i / eta_t;
        const float3 perpendicular =
            mul(add(neg(wo), mul(half_vector, wo_h)), eta);
        const float parallel_length2 =
            fmaxf(0.0f, 1.0f - length2(perpendicular));
        sample.wi = normalize3(add(
            perpendicular,
            mul(half_vector, -sqrtf(parallel_length2))));
        sample.transmitted = 1;
      }
      bool macro_transmitted = false;
      if (!rough_macro_sides_agree(
              n, geometric_n, sample.wi, macro_transmitted) ||
          (sample.transmitted != 0) != macro_transmitted) {
        return sample;
      }
      float3 value;
      evaluate_bsdf(material, base_color, n, wo, sample.wi,
                    eta_i, eta_t, value, sample.pdf);
      const float no_l = fabsf(dot3(n, sample.wi));
      if (sample.pdf > 0.0f && no_l > 0.0f) {
        sample.weight = mul(value, no_l / sample.pdf);
        sample.valid = max_component(sample.weight) > 0.0f ? 1 : 0;
      }
      sample.delta = 0;
      if (sample.valid != 0 && sample.transmitted != 0 && media != nullptr &&
          !update_medium_after_transmission(
              *media, material_index, material, front_face,
              water_counters)) {
        sample.valid = 0;
      }
      return sample;
    }
    // Keep the pre-water dielectric arithmetic and RNG sequence byte-for-byte
    // for scenes which do not opt into medium tracking.
    if (params.water_surface_count != 0u && media != nullptr) {
      const float eta_i = medium_ior(*media);
      const float eta_t = front_face
          ? fmaxf(material.ior, 1.0e-3f)
          : exit_ior(*media, material_index, water_counters);
      const float eta = eta_i / eta_t;
      const float cos_theta = fminf(fmaxf(dot3(wo, n), 0.0f), 1.0f);
      float cos_transmitted = 0.0f;
      const float reflectance = dielectric_fresnel(
          cos_theta, eta_i, eta_t, &cos_transmitted);
      if (reflectance >= 1.0f || rng.next() < reflectance) {
        sample.wi = normalize3(reflect3(neg(wo), n));
        sample.weight = base_color;
      } else {
        const float3 perpendicular =
            mul(add(neg(wo), mul(n, cos_theta)), eta);
        const float3 parallel = mul(n, -cos_transmitted);
        sample.wi = normalize3(add(perpendicular, parallel));
        sample.weight = mul(base_color, eta * eta);
        sample.transmitted = 1;
        if (!update_medium_after_transmission(
                *media, material_index, material, front_face,
                water_counters)) {
          sample.valid = 0;
          return sample;
        }
      }
      sample.pdf = 1.0f;
      sample.valid = 1;
      sample.delta = 1;
      return sample;
    }
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
    sample.transmitted = transmitted ? 1 : 0;
  }
  return sample;
}

// A direct-light connection represents exactly one BSDF event at the current
// vertex. Any later dielectric boundary is therefore an occluder; bending a
// straight shadow ray through it would be a different (specular-manifold)
// technique. For a rough transmission sampled at this vertex, however, the
// segment starts in the transmitted medium, so update a copy of the stack and
// apply Beer attenuation along that same-medium segment. The caller derives
// transmitted_connection from the oriented geometric normal after verifying
// that its macro-side classification agrees with the shading normal.
static __forceinline__ __device__ float3 direct_segment_transmittance(
    const SurfaceHit& hit, const MaterialData& material,
    float3 shadow_origin, float3 shadow_direction, float shadow_distance,
    int target_light, bool transmitted_connection, const MediumState& media,
    unsigned long long& traced_rays, WaterCounters& counters) {
  MediumState shadow_media = media;
  if (params.water_surface_count != 0u &&
      is_rough_dielectric(material) && transmitted_connection) {
    if (!update_medium_after_transmission(
            shadow_media, hit.material_index, material, hit.front_face,
            counters)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
  }
  if (!trace_visible(shadow_origin, shadow_direction, shadow_distance,
                     target_light, traced_rays)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  return params.water_surface_count != 0u
      ? medium_segment_transmittance(
            shadow_media, shadow_distance, counters)
      : f3(1.0f, 1.0f, 1.0f);
}

enum FiniteLightMode : unsigned int {
  kFiniteLightPower = 0u,
  kFiniteLightUniform = 1u,
  kFiniteLightWaterPowerSample = 2u,
  kFiniteLightWaterUniformSample = 3u,
};

static __forceinline__ __device__ bool is_water_finite_light_mode(
    FiniteLightMode mode) {
  return mode == kFiniteLightWaterPowerSample ||
         mode == kFiniteLightWaterUniformSample;
}

static __forceinline__ __device__ FiniteLightMode finite_light_mode(
    const MaterialData& material, const MediumState& media) {
  if (material.type == spectraldock::kMaterialWater &&
      material.roughness > 0.0f) {
    return kFiniteLightWaterPowerSample;
  }
  return media.depth > 0 ? kFiniteLightUniform : kFiniteLightPower;
}

static __forceinline__ __device__ float finite_light_selection_pdf(
    const LightData& light, FiniteLightMode mode) {
  if (params.sampled_light_count == 0u) return 0.0f;
  if (mode == kFiniteLightPower) return light.selection_pdf;
  const float uniform =
      1.0f / static_cast<float>(params.sampled_light_count);
  if (mode == kFiniteLightUniform) return uniform;
  // Rough water takes one power-CDF sample and one uniform-index sample.
  // Both light estimators use the combined density qG + qU, with no extra 0.5
  // scale. A reachable bound emitter adds pB through three-technique balance.
  return light.selection_pdf + uniform;
}

static __forceinline__ __device__ float sphere_visible_solid_angle_pdf(
    const LightData& light, float3 from,
    float* one_minus_cos_out = nullptr) {
  const float3 to_center = sub(light.p0, from);
  const float distance2 = length2(to_center);
  const float radius2 = light.radius * light.radius;
  const float minimum_distance = light.radius + params.scene_epsilon;
  if (!(light.radius > 0.0f) ||
      !(distance2 > minimum_distance * minimum_distance)) {
    return 0.0f;
  }
  const float sin2_theta_max =
      fminf(fmaxf(radius2 / distance2, 0.0f), 1.0f);
  const float cos_theta_max =
      sqrtf(fmaxf(0.0f, 1.0f - sin2_theta_max));
  // This stable form avoids losing the cone measure for a distant sphere.
  const float one_minus_cos =
      sin2_theta_max / fmaxf(1.0f + cos_theta_max, 1.0e-20f);
  if (!(one_minus_cos > 0.0f) || !isfinite(one_minus_cos)) return 0.0f;
  const float pdf = 1.0f / (2.0f * kPi * one_minus_cos);
  if (!isfinite(pdf)) return 0.0f;
  if (one_minus_cos_out != nullptr) {
    *one_minus_cos_out = one_minus_cos;
  }
  return pdf;
}

static __forceinline__ __device__ bool sample_visible_sphere_direction(
    const LightData& light, float3 from, float one_minus_cos,
    float u0, float u1, float3& wi, float3& point, float3& normal) {
  const float3 to_center = sub(light.p0, from);
  const float center_distance = length3(to_center);
  const float3 cone_axis = divv(to_center, center_distance);
  const float v = u0 * one_minus_cos;
  const float cos_theta = 1.0f - v;
  const float sin_theta = sqrtf(fmaxf(0.0f, v * (2.0f - v)));
  const float phi = 2.0f * kPi * u1;
  wi = local_to_world(
      f3(sin_theta * cosf(phi), sin_theta * sinf(phi), cos_theta),
      cone_axis);

  const float projection = dot3(to_center, wi);
  const float perpendicular2 =
      fmaxf(0.0f, length2(to_center) - projection * projection);
  const float sqrt_discriminant =
      sqrtf(fmaxf(0.0f, light.radius * light.radius - perpendicular2));
  const float denominator = projection + sqrt_discriminant;
  const float numerator =
      (center_distance - light.radius) *
      (center_distance + light.radius);
  if (!(denominator > 0.0f) || !isfinite(denominator) ||
      !(numerator > 0.0f) || !isfinite(numerator)) {
    return false;
  }
  const float hit_distance = numerator / denominator;
  if (!(hit_distance > 0.0f) || !isfinite(hit_distance)) return false;
  point = add(from, mul(wi, hit_distance));
  normal = normalize3(sub(point, light.p0));
  return true;
}

static __forceinline__ __device__ float light_direction_pdf(
    int light_index, float3 from, float3 point, FiniteLightMode mode) {
  if (light_index < 0 ||
      static_cast<unsigned int>(light_index) >= params.all_light_count ||
      params.lights == nullptr || params.all_light_count == 0) {
    return 0.0f;
  }
  const LightData light = params.lights[light_index];
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
  const float selection_pdf = finite_light_selection_pdf(light, mode);
  if (!(selection_pdf > 0.0f)) return 0.0f;
  if (light.type == spectraldock::kLightSphere) {
    const float solid_angle_pdf =
        sphere_visible_solid_angle_pdf(light, from);
    if (solid_angle_pdf > 0.0f) {
      return selection_pdf * solid_angle_pdf;
    }
  }
  return selection_pdf * distance2 / (cos_light * area);
}

static __forceinline__ __device__ void sample_light_surface(
    const LightData& light, float u0, float u1,
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

static __forceinline__ __device__ float3 sample_flame_volume(
    const LightData& light, float u0, float u1, float u2) {
  float3 tangent;
  float3 bitangent;
  const float3 axis = normalize3(light.axis);
  make_basis(axis, tangent, bitangent);
  const float radius =
      fmaxf(light.radius_start, light.radius_end) * sqrtf(u0);
  const float phi = 2.0f * kPi * u1;
  return add(add(light.p0, mul(axis, u2 * light.height)),
             add(mul(tangent, radius * cosf(phi)),
                 mul(bitangent, radius * sinf(phi))));
}

static __forceinline__ __device__ unsigned int sample_finite_light_slot(
    float value) {
  if (params.sampled_light_count == 0u) return 0u;
  if (params.light_cdf == nullptr) {
    const unsigned int candidate =
        static_cast<unsigned int>(value * params.sampled_light_count);
    return candidate < params.sampled_light_count
        ? candidate : params.sampled_light_count - 1u;
  }
  unsigned int lower = 0u;
  unsigned int upper = params.sampled_light_count;
  while (lower + 1u < upper) {
    const unsigned int middle = lower + (upper - lower) / 2u;
    if (value < params.light_cdf[middle]) {
      upper = middle;
    } else {
      lower = middle;
    }
  }
  return lower;
}

static __forceinline__ __device__ unsigned int sample_uniform_light_slot(
    float value) {
  const unsigned int candidate =
      static_cast<unsigned int>(value * params.sampled_light_count);
  return candidate < params.sampled_light_count
      ? candidate : params.sampled_light_count - 1u;
}

static __forceinline__ __device__ unsigned int sample_finite_light_index(
    float value, FiniteLightMode mode) {
  const unsigned int slot =
      mode == kFiniteLightPower || mode == kFiniteLightWaterPowerSample
          ? sample_finite_light_slot(value)
          : sample_uniform_light_slot(value);
  return params.sampled_light_indices != nullptr
      ? params.sampled_light_indices[slot] : slot;
}

static __forceinline__ __device__ float3 sample_finite_direct_light(
    const SurfaceHit& hit, const MaterialData& material, float3 base_color,
    float3 wo, bool next_bsdf_ray_exists, FiniteLightMode light_mode,
    Pcg32& rng,
    unsigned long long& traced_rays, VolumeCounters& volume_counters,
    const MediumState& media, WaterCounters& water_counters) {
  if (params.lights == nullptr || params.sampled_light_count == 0 ||
      !supports_direct_lighting(material)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const bool count_rough_water =
      material.type == spectraldock::kMaterialWater &&
      material.roughness > 0.0f;
  if (count_rough_water) ++water_counters.rough_nee_attempts;
  float eta_i = 1.0f;
  float eta_t = 1.0f;
  if (is_rough_dielectric(material)) {
    dielectric_eta_pair(
        material, hit.front_face, hit.material_index,
        params.water_surface_count != 0u ? &media : nullptr,
        water_counters, eta_i, eta_t);
  }
  const unsigned int light_index =
      sample_finite_light_index(rng.next(), light_mode);
  if (light_index >= params.all_light_count) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const LightData light = params.lights[light_index];
  const float selection_pdf =
      finite_light_selection_pdf(light, light_mode);
  if (!(selection_pdf > 0.0f)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  if (light.type == spectraldock::kLightFlame) {
    ++volume_counters.light_samples;
    const float3 light_point = sample_flame_volume(
        light, rng.next(), rng.next(), rng.next());
    float axial = 0.0f;
    const float density =
        flame_density(light, light_point, volume_counters, &axial);
    const float sigma =
        light.extinction * light.density_scale * density;
    if (!(sigma > 0.0f)) return f3(0.0f, 0.0f, 0.0f);
    const float3 displacement = sub(light_point, hit.position);
    const float distance2 = length2(displacement);
    if (distance2 <= params.scene_epsilon * params.scene_epsilon) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    const float distance = sqrtf(distance2);
    const float3 wi = divv(displacement, distance);
    const float signed_no_l = dot3(hit.normal, wi);
    bool transmitted_connection = signed_no_l < 0.0f;
    if (is_rough_dielectric(material) &&
        !rough_macro_sides_agree(
            hit.normal, hit.geometric_normal, wi,
            transmitted_connection)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    const float no_l = is_rough_dielectric(material)
        ? fabsf(signed_no_l) : signed_no_l;
    if (no_l <= 0.0f) return f3(0.0f, 0.0f, 0.0f);
    float3 bsdf;
    float bsdf_pdf;
    evaluate_bsdf(material, base_color, hit.normal, wo, wi,
                  eta_i, eta_t, bsdf, bsdf_pdf);
    if (!(bsdf_pdf > 0.0f)) return f3(0.0f, 0.0f, 0.0f);
    const float3 offset_normal = is_rough_dielectric(material)
        ? hit.geometric_normal : hit.normal;
    const float side = transmitted_connection ? -1.0f : 1.0f;
    const float3 shadow_origin =
        add(hit.position,
            mul(offset_normal, side * params.scene_epsilon * 2.0f));
    const float3 shadow_displacement = sub(light_point, shadow_origin);
    const float shadow_distance = length3(shadow_displacement);
    if (!(shadow_distance > params.scene_epsilon * 2.0f)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    const float3 shadow_direction =
        divv(shadow_displacement, shadow_distance);
    const float3 surface_transmittance = direct_segment_transmittance(
        hit, material, shadow_origin, shadow_direction, shadow_distance,
        static_cast<int>(light_index), transmitted_connection, media,
        traced_rays, water_counters);
    if (!(max_component(surface_transmittance) > 0.0f)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    if (track_volume(shadow_origin, shadow_direction, shadow_distance, rng,
                     volume_counters).collided != 0) {
      return f3(0.0f, 0.0f, 0.0f);
    }
    const float maximum_radius =
        fmaxf(light.radius_start, light.radius_end);
    const float support_volume =
        kPi * maximum_radius * maximum_radius * light.height;
    const float3 emission_coefficient =
        mul(flame_source(light, axial), sigma);
    const float3 contribution =
        mul(mul(mul(bsdf, emission_coefficient), surface_transmittance),
            no_l * support_volume /
                (selection_pdf * distance2));
    if (count_rough_water && max_component(contribution) > 0.0f) {
      ++water_counters.rough_nee_contributions;
    }
    return contribution;
  }
  float3 light_point;
  float3 light_normal;
  float3 wi;
  float one_minus_cos = 0.0f;
  float sphere_solid_angle_pdf = 0.0f;
  const bool sample_sphere_solid_angle =
      light.type == spectraldock::kLightSphere &&
      (sphere_solid_angle_pdf = sphere_visible_solid_angle_pdf(
           light, hit.position, &one_minus_cos)) > 0.0f;
  if (sample_sphere_solid_angle) {
    const float u0 = rng.next();
    const float u1 = rng.next();
    if (!sample_visible_sphere_direction(
            light, hit.position, one_minus_cos, u0, u1,
            wi, light_point, light_normal)) {
      return f3(0.0f, 0.0f, 0.0f);
    }
  } else {
    // Near or inside a sphere, where its visible cone is not well-defined,
    // fall back to the area-domain sampler used by other surface lights.
    sample_light_surface(light, rng.next(), rng.next(),
                         light_point, light_normal);
  }
  const float3 displacement = sub(light_point, hit.position);
  const float distance2 = length2(displacement);
  if (distance2 <= params.scene_epsilon * params.scene_epsilon) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float distance = sqrtf(distance2);
  if (!sample_sphere_solid_angle) {
    wi = divv(displacement, distance);
  }
  const float signed_no_l = dot3(hit.normal, wi);
  bool transmitted_connection = signed_no_l < 0.0f;
  if (is_rough_dielectric(material) &&
      !rough_macro_sides_agree(
          hit.normal, hit.geometric_normal, wi,
          transmitted_connection)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float no_l = is_rough_dielectric(material)
      ? fabsf(signed_no_l) : signed_no_l;
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
  float light_pdf =
      selection_pdf * distance2 / (cos_light * area);
  if (sample_sphere_solid_angle) {
    light_pdf = selection_pdf * sphere_solid_angle_pdf;
  }
  float3 bsdf;
  float bsdf_pdf;
  evaluate_bsdf(material, base_color, hit.normal, wo, wi,
                eta_i, eta_t, bsdf, bsdf_pdf);
  if (bsdf_pdf <= 0.0f) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float3 offset_normal = is_rough_dielectric(material)
      ? hit.geometric_normal : hit.normal;
  const float side = transmitted_connection ? -1.0f : 1.0f;
  const float3 shadow_origin =
      add(hit.position,
          mul(offset_normal, side * params.scene_epsilon * 2.0f));
  const float3 shadow_displacement = sub(light_point, shadow_origin);
  const float shadow_distance = length3(shadow_displacement);
  if (shadow_distance <= params.scene_epsilon * 2.0f) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float3 shadow_direction =
      divv(shadow_displacement, shadow_distance);
  const float3 surface_transmittance = direct_segment_transmittance(
      hit, material, shadow_origin, shadow_direction, shadow_distance,
      static_cast<int>(light_index), transmitted_connection, media,
      traced_rays, water_counters);
  if (!(max_component(surface_transmittance) > 0.0f)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  if (track_volume(shadow_origin, shadow_direction, shadow_distance, rng,
                   volume_counters).collided != 0) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  // Rough water takes one qG and one qU sample. Their shared light density is
  // pL=(qG+qU)c. When a bound surface emitter can also be reached by the next
  // BSDF ray, all three deterministic techniques use balance weights over
  // pL+pB. Flame and unbound lights have no BSDF endpoint competitor.
  const bool water_bsdf_competes =
      is_water_finite_light_mode(light_mode) &&
      light.geometry_index >= 0 && next_bsdf_ray_exists;
  const float mis = water_bsdf_competes
      ? balance_heuristic(light_pdf, bsdf_pdf)
      : direct_light_mis_weight(
            light_pdf, bsdf_pdf,
            !is_water_finite_light_mode(light_mode) &&
                light.geometry_index >= 0,
            next_bsdf_ray_exists);
  const float3 contribution =
      mul(mul(mul(bsdf, light.emission), surface_transmittance),
          no_l * mis / light_pdf);
  if (count_rough_water && max_component(contribution) > 0.0f) {
    ++water_counters.rough_nee_contributions;
  }
  return contribution;
}

// Point and directional lights are delta distributions in direction space.
// They have no emitter surface which a continuous BSDF can hit, so each light
// is evaluated exactly once and its direct-light MIS weight is one.
static __forceinline__ __device__ void accumulate_delta_direct_lights(
    const SurfaceHit& hit, const MaterialData& material, float3 base_color,
    float3 wo, Pcg32& rng, unsigned long long& traced_rays,
    VolumeCounters& volume_counters, const MediumState& media,
    WaterCounters& water_counters, float3 throughput, float clamp_threshold,
    unsigned long long* clamped_counter, float3& radiance) {
  if (params.lights == nullptr || params.delta_light_count == 0u ||
      params.delta_light_indices == nullptr ||
      !supports_direct_lighting(material)) {
    return;
  }

  float eta_i = 1.0f;
  float eta_t = 1.0f;
  if (is_rough_dielectric(material)) {
    dielectric_eta_pair(
        material, hit.front_face, hit.material_index,
        params.water_surface_count != 0u ? &media : nullptr,
        water_counters, eta_i, eta_t);
  }
  const bool count_rough_water =
      material.type == spectraldock::kMaterialWater &&
      material.roughness > 0.0f;

  for (unsigned int slot = 0u; slot < params.delta_light_count; ++slot) {
    const unsigned int light_index = params.delta_light_indices[slot];
    if (light_index >= params.all_light_count) continue;
    const LightData& light = params.lights[light_index];
    const bool is_point = light.type == spectraldock::kLightPoint;
    const bool is_directional =
        light.type == spectraldock::kLightDirectional;
    if (!is_point && !is_directional) continue;
    if (count_rough_water) ++water_counters.rough_nee_attempts;

    float3 wi;
    float radiometric_distance2 = 1.0f;
    float radiometric_distance = kInfinity;
    float shadow_distance = kInfinity;
    if (is_point) {
      const float3 displacement = sub(light.p0, hit.position);
      radiometric_distance2 = length2(displacement);
      if (!(radiometric_distance2 > 0.0f) ||
          !isfinite(radiometric_distance2)) {
        continue;
      }
      radiometric_distance = sqrtf(radiometric_distance2);
      wi = divv(displacement, radiometric_distance);
      shadow_distance = radiometric_distance;
    } else {
      if (!(length2(light.axis) > 1.0e-20f)) continue;
      wi = normalize3(light.axis);
    }

    const float signed_no_l = dot3(hit.normal, wi);
    bool transmitted_connection = signed_no_l < 0.0f;
    if (is_rough_dielectric(material) &&
        !rough_macro_sides_agree(
            hit.normal, hit.geometric_normal, wi,
            transmitted_connection)) {
      continue;
    }
    const float no_l = is_rough_dielectric(material)
        ? fabsf(signed_no_l) : signed_no_l;
    if (!(no_l > 0.0f)) continue;

    float3 bsdf;
    float bsdf_pdf;
    evaluate_bsdf(material, base_color, hit.normal, wo, wi,
                  eta_i, eta_t, bsdf, bsdf_pdf);
    if (!(bsdf_pdf > 0.0f)) continue;

    const float3 offset_normal = is_rough_dielectric(material)
        ? hit.geometric_normal : hit.normal;
    const float side = transmitted_connection ? -1.0f : 1.0f;
    const float offset_distance = is_point
        ? fminf(params.scene_epsilon * 2.0f,
                radiometric_distance * 0.25f)
        : params.scene_epsilon * 2.0f;
    const float3 shadow_origin = add(
        hit.position,
        mul(offset_normal, side * offset_distance));
    float3 shadow_direction = wi;
    if (is_point) {
      const float3 shadow_displacement = sub(light.p0, shadow_origin);
      shadow_distance = length3(shadow_displacement);
      if (!(shadow_distance > 0.0f) || !isfinite(shadow_distance)) continue;
      shadow_direction = divv(shadow_displacement, shadow_distance);
    }

    float3 surface_transmittance;
    if (is_point && shadow_distance <= params.scene_epsilon * 2.0f) {
      // There is no numerically representable shadow interval between tmin
      // and this very near ideal point. Do not invent a minimum light range;
      // retain the medium transition/Beer term and treat the tiny segment as
      // geometrically unobstructed.
      MediumState shadow_media = media;
      if (params.water_surface_count != 0u &&
          is_rough_dielectric(material) && transmitted_connection &&
          !update_medium_after_transmission(
              shadow_media, hit.material_index, material, hit.front_face,
              water_counters)) {
        continue;
      }
      surface_transmittance = params.water_surface_count != 0u
          ? medium_segment_transmittance(
                shadow_media, shadow_distance, water_counters)
          : f3(1.0f, 1.0f, 1.0f);
    } else {
      surface_transmittance = direct_segment_transmittance(
          hit, material, shadow_origin, shadow_direction, shadow_distance, -1,
          transmitted_connection, media, traced_rays, water_counters);
    }
    if (!(max_component(surface_transmittance) > 0.0f)) continue;
    if (track_volume(shadow_origin, shadow_direction, shadow_distance, rng,
                     volume_counters).collided != 0) {
      continue;
    }

    const float attenuation =
        is_point ? 1.0f / radiometric_distance2 : 1.0f;
    const float3 contribution = mul(
        mul(mul(bsdf, light.emission), surface_transmittance),
        no_l * attenuation);
    if (count_rough_water && max_component(contribution) > 0.0f) {
      ++water_counters.rough_nee_contributions;
    }
    accumulate_path_contribution(
        radiance, mul(throughput, contribution), clamp_threshold,
        clamped_counter);
  }
}

static __forceinline__ __device__ bool has_environment() {
  return params.background_type == spectraldock::kBackgroundEnvironment &&
         params.environment_texture != 0u &&
         params.environment_width > 0u && params.environment_height > 0u;
}

static __forceinline__ __device__ float3 rotate_environment_to_local(
    float3 direction) {
  const float c = cosf(params.environment_rotation_radians);
  const float s = sinf(params.environment_rotation_radians);
  return f3(c * direction.x - s * direction.z,
            direction.y,
            s * direction.x + c * direction.z);
}

static __forceinline__ __device__ float3 rotate_environment_to_world(
    float3 direction) {
  const float c = cosf(params.environment_rotation_radians);
  const float s = sinf(params.environment_rotation_radians);
  return f3(c * direction.x + s * direction.z,
            direction.y,
            -s * direction.x + c * direction.z);
}

static __forceinline__ __device__ float2 environment_uv(float3 direction) {
  const float3 local = rotate_environment_to_local(normalize3(direction));
  float u = atan2f(local.z, local.x) / (2.0f * kPi) + 0.5f;
  u -= floorf(u);
  const float v = acosf(fminf(fmaxf(local.y, -1.0f), 1.0f)) / kPi;
  return f2(u, fminf(fmaxf(v, 0.0f), 1.0f));
}

static __forceinline__ __device__ float3 environment_radiance(
    float3 direction) {
  if (!has_environment() || !(params.environment_intensity > 0.0f)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float2 uv = environment_uv(direction);
  const float4 value = tex2D<float4>(
      static_cast<cudaTextureObject_t>(params.environment_texture),
      uv.x, uv.y);
  return mul(clamp_nonnegative(f3(value.x, value.y, value.z)),
             params.environment_intensity);
}

static __forceinline__ __device__ unsigned int sample_cdf_interval(
    const float* cdf, unsigned int count, double value) {
  unsigned int lower = 0u;
  unsigned int upper = count;
  while (lower + 1u < upper) {
    const unsigned int middle = lower + (upper - lower) / 2u;
    if (value < cdf[middle]) {
      upper = middle;
    } else {
      lower = middle;
    }
  }
  return lower;
}

static __forceinline__ __device__ float environment_direction_pdf(
    float3 direction) {
  if (!has_environment()) return 0.0f;
  if (params.environment_row_cdf == nullptr ||
      params.environment_conditional_cdf == nullptr) {
    return 1.0f / (4.0f * kPi);
  }
  const float2 uv = environment_uv(direction);
  const unsigned int raw_column =
      static_cast<unsigned int>(uv.x * params.environment_width);
  const unsigned int raw_row =
      static_cast<unsigned int>(uv.y * params.environment_height);
  const unsigned int column = raw_column < params.environment_width
      ? raw_column : params.environment_width - 1u;
  const unsigned int row = raw_row < params.environment_height
      ? raw_row : params.environment_height - 1u;
  const float row_probability =
      params.environment_row_cdf[row + 1u] -
      params.environment_row_cdf[row];
  const unsigned int stride = params.environment_width + 1u;
  const float* conditional =
      params.environment_conditional_cdf + row * stride;
  const float column_probability =
      conditional[column + 1u] - conditional[column];
  const float theta0 = kPi * static_cast<float>(row) /
                       static_cast<float>(params.environment_height);
  const float theta1 = kPi * static_cast<float>(row + 1u) /
                       static_cast<float>(params.environment_height);
  const float solid_angle =
      (2.0f * kPi / static_cast<float>(params.environment_width)) *
      (cosf(theta0) - cosf(theta1));
  return solid_angle > 0.0f
             ? fmaxf(row_probability, 0.0f) *
                   fmaxf(column_probability, 0.0f) / solid_angle
             : 0.0f;
}

static __forceinline__ __device__ float3 sample_environment_direction(
    double row_sample, double column_sample, float& pdf) {
  if (params.environment_row_cdf == nullptr ||
      params.environment_conditional_cdf == nullptr) {
    const float y = 1.0f - 2.0f * static_cast<float>(row_sample);
    const float radial = sqrtf(fmaxf(0.0f, 1.0f - y * y));
    const float phi = 2.0f * kPi * static_cast<float>(column_sample);
    pdf = 1.0f / (4.0f * kPi);
    return f3(radial * cosf(phi), y, radial * sinf(phi));
  }

  const unsigned int row = sample_cdf_interval(
      params.environment_row_cdf, params.environment_height, row_sample);
  const float row_begin = params.environment_row_cdf[row];
  const float row_probability =
      params.environment_row_cdf[row + 1u] - row_begin;
  float row_fraction = row_probability > 0.0f
      ? static_cast<float>(fmin(fmax(
            (row_sample - static_cast<double>(row_begin)) /
                static_cast<double>(row_probability),
            0.0), 0.9999999999999999))
      : 0.5f;
  row_fraction = fminf(row_fraction, 0x1.fffffep-1f);

  const unsigned int stride = params.environment_width + 1u;
  const float* conditional =
      params.environment_conditional_cdf + row * stride;
  const unsigned int column = sample_cdf_interval(
      conditional, params.environment_width, column_sample);
  const float column_begin = conditional[column];
  const float column_probability = conditional[column + 1u] - column_begin;
  float column_fraction = column_probability > 0.0f
      ? static_cast<float>(fmin(fmax(
            (column_sample - static_cast<double>(column_begin)) /
                static_cast<double>(column_probability),
            0.0), 0.9999999999999999))
      : 0.5f;
  column_fraction = fminf(column_fraction, 0x1.fffffep-1f);

  const float theta0 = kPi * static_cast<float>(row) /
                       static_cast<float>(params.environment_height);
  const float theta1 = kPi * static_cast<float>(row + 1u) /
                       static_cast<float>(params.environment_height);
  const float cos_theta0 = cosf(theta0);
  const float cos_theta1 = cosf(theta1);
  const float cos_theta =
      cos_theta0 + (cos_theta1 - cos_theta0) * row_fraction;
  const float sin_theta =
      sqrtf(fmaxf(0.0f, 1.0f - cos_theta * cos_theta));
  const float u =
      (static_cast<float>(column) + column_fraction) /
      static_cast<float>(params.environment_width);
  const float phi = 2.0f * kPi * (u - 0.5f);
  const float3 local =
      f3(sin_theta * cosf(phi), cos_theta, sin_theta * sinf(phi));
  const float solid_angle =
      (2.0f * kPi / static_cast<float>(params.environment_width)) *
      (cos_theta0 - cos_theta1);
  pdf = solid_angle > 0.0f
      ? fmaxf(row_probability, 0.0f) *
            fmaxf(column_probability, 0.0f) / solid_angle
      : 0.0f;
  return normalize3(rotate_environment_to_world(local));
}

static __forceinline__ __device__ float3 sample_environment_direct_light(
    const SurfaceHit& hit, const MaterialData& material, float3 base_color,
    float3 wo, bool next_bsdf_ray_exists, Pcg32& rng,
    unsigned long long& traced_rays, VolumeCounters& volume_counters,
    const MediumState& media, WaterCounters& water_counters) {
  if (!has_environment() || !(params.environment_intensity > 0.0f) ||
      !supports_direct_lighting(material)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const bool count_rough_water =
      material.type == spectraldock::kMaterialWater &&
      material.roughness > 0.0f;
  if (count_rough_water) ++water_counters.rough_nee_attempts;
  float eta_i = 1.0f;
  float eta_t = 1.0f;
  if (is_rough_dielectric(material)) {
    dielectric_eta_pair(
        material, hit.front_face, hit.material_index,
        params.water_surface_count != 0u ? &media : nullptr,
        water_counters, eta_i, eta_t);
  }
  float light_pdf = 0.0f;
  const float3 wi =
      sample_environment_direction(rng.next_cdf(), rng.next_cdf(), light_pdf);
  if (!(light_pdf > 0.0f)) return f3(0.0f, 0.0f, 0.0f);
  const float signed_no_l = dot3(hit.normal, wi);
  bool transmitted_connection = signed_no_l < 0.0f;
  if (is_rough_dielectric(material) &&
      !rough_macro_sides_agree(
          hit.normal, hit.geometric_normal, wi,
          transmitted_connection)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float no_l = is_rough_dielectric(material)
      ? fabsf(signed_no_l) : signed_no_l;
  if (!(no_l > 0.0f)) return f3(0.0f, 0.0f, 0.0f);
  float3 bsdf;
  float bsdf_pdf;
  evaluate_bsdf(material, base_color, hit.normal, wo, wi,
                eta_i, eta_t, bsdf, bsdf_pdf);
  if (!(bsdf_pdf > 0.0f)) return f3(0.0f, 0.0f, 0.0f);

  const float3 offset_normal = is_rough_dielectric(material)
      ? hit.geometric_normal : hit.normal;
  const float side = transmitted_connection ? -1.0f : 1.0f;
  const float3 shadow_origin =
      add(hit.position,
          mul(offset_normal, side * params.scene_epsilon * 2.0f));
  const float3 surface_transmittance = direct_segment_transmittance(
      hit, material, shadow_origin, wi, kInfinity, -1,
      transmitted_connection, media,
      traced_rays, water_counters);
  if (!(max_component(surface_transmittance) > 0.0f)) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  if (track_volume(shadow_origin, wi, kInfinity, rng,
                   volume_counters).collided != 0) {
    return f3(0.0f, 0.0f, 0.0f);
  }
  const float mis = direct_light_mis_weight(
      light_pdf, bsdf_pdf, true, next_bsdf_ray_exists);
  const float3 contribution =
      mul(mul(mul(bsdf, environment_radiance(wi)),
                  surface_transmittance),
          no_l * mis / light_pdf);
  if (count_rough_water && max_component(contribution) > 0.0f) {
    ++water_counters.rough_nee_contributions;
  }
  return contribution;
}

static __forceinline__ __device__ float3 background(float3 direction) {
  if (params.background_type == spectraldock::kBackgroundEnvironment) {
    return environment_radiance(direction);
  }
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
  VolumeCounters volume_counters{};
  WaterCounters local_water_counters{};
  WaterCounters& water_counters = params.water_counters != nullptr
      ? params.water_counters[pixel]
      : local_water_counters;

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
    FiniteLightMode previous_light_mode = kFiniteLightPower;
    // Keep the unshifted predecessor vertex for emitter-hit light PDFs. The
    // numerical ray-origin offset must not change the sampling measure used by
    // the matching NEE strategy, especially at the sphere-cone boundary.
    float3 previous_position = ray_origin;
    int guide_written = 0;
    MediumState media{};
    int split_used = 0;

    // At most one extra state is needed: the first smooth-water event forks
    // into deterministic Fresnel reflection and transmission, and both
    // children carry split_used=1. Keeping a single pending state bounds work
    // and storage to two path states per camera sample.
    int pending_path = 0;
    float3 pending_origin{};
    float3 pending_direction{};
    float3 pending_throughput{};
    float pending_previous_pdf = 0.0f;
    int pending_previous_delta = 1;
    FiniteLightMode pending_previous_light_mode = kFiniteLightPower;
    float3 pending_previous_position{};
    unsigned int pending_bounce = 0u;
    MediumState pending_media{};
    unsigned long long pending_rng_state = 0ull;
    unsigned long long pending_rng_increment = 1ull;
    unsigned int bounce_start = 0u;

    for (;;) {
      for (unsigned int bounce = bounce_start;
           bounce < params.max_depth; ++bounce) {
      const float clamp_threshold =
          bounce == 0u ? params.clamp_direct : params.clamp_indirect;
      unsigned long long* clamped_counter = nullptr;
      if (params.firefly_counters != nullptr) {
        clamped_counter = bounce == 0u
            ? &params.firefly_counters->direct_clamped_contributions
            : &params.firefly_counters->indirect_clamped_contributions;
      }
      const SurfaceHit hit = trace_radiance(ray_origin, ray_direction, traced_rays);
      if (params.water_surface_count != 0u && hit.hit != 0) {
        infer_base_water_incident_medium(hit, media);
      }
      const VolumeCollision volume = track_volume(
          ray_origin, ray_direction, hit.hit != 0 ? hit.distance : kInfinity,
          rng, volume_counters);
      if (params.water_surface_count != 0u) {
        const float travel_distance = volume.collided != 0
            ? volume.distance
            : (hit.hit != 0 ? hit.distance : kInfinity);
        throughput = mul(
            throughput,
            medium_segment_transmittance(
                media, travel_distance, water_counters));
        if (!(max_component(throughput) > 0.0f)) break;
      }
      if (volume.collided != 0) {
        if (previous_delta != 0) {
          accumulate_path_contribution(
              radiance, mul(throughput, volume.source), clamp_threshold,
              clamped_counter);
        }
        break;
      }
      if (hit.hit == 0) {
        const float environment_pdf =
            previous_delta == 0 ? environment_direction_pdf(ray_direction)
                                : 0.0f;
        const float miss_weight =
            previous_delta != 0 || !(environment_pdf > 0.0f)
                ? 1.0f
                : power_heuristic(previous_pdf, environment_pdf);
        accumulate_path_contribution(
            radiance,
            mul(mul(throughput, background(ray_direction)), miss_weight),
            clamp_threshold, clamped_counter);
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
            ? light_direction_pdf(hit.light_index, previous_position,
                                  hit.position, previous_light_mode)
            : 0.0f;
        // A rough-water predecessor uses deterministic qG, qU and BSDF
        // techniques. If this endpoint lies in finite-light support, complete
        // their balance heuristic with pB/(pG+pU+pB). Back faces, inside-sphere
        // hits and unbound emitters retain their ordinary BSDF-hit weight.
        const bool use_water_finite_balance =
            emitter_is_bound_to_light &&
            previous_light_mode == kFiniteLightWaterPowerSample &&
            previous_delta == 0 &&
            light_pdf > 0.0f;
        const float weight = use_water_finite_balance
            ? balance_heuristic(previous_pdf, light_pdf)
            : emitter_hit_mis_weight(
                  previous_pdf, light_pdf, previous_delta != 0,
                  emitter_is_bound_to_light);
        accumulate_path_contribution(
            radiance, mul(mul(throughput, emitted), weight),
            clamp_threshold, clamped_counter);
        break;
      }

      const float3 wo = neg(ray_direction);
      const bool next_bsdf_ray_exists = bounce + 1u < params.max_depth;
      const FiniteLightMode current_light_mode =
          finite_light_mode(material, media);
      const float3 finite_direct =
          sample_finite_direct_light(hit, material, base_color, wo,
                                     next_bsdf_ray_exists, current_light_mode,
                                     rng, traced_rays,
                                     volume_counters, media, water_counters);
      float3 water_uniform_direct = f3(0.0f, 0.0f, 0.0f);
      if (current_light_mode == kFiniteLightWaterPowerSample) {
        // Deterministic two-component stratification: take one qG sample and
        // one qU sample. Their combined light density is qG + qU, so no 0.5
        // factor belongs here; a bound endpoint completes balance with BSDF.
        water_uniform_direct = sample_finite_direct_light(
            hit, material, base_color, wo, next_bsdf_ray_exists,
            kFiniteLightWaterUniformSample, rng, traced_rays,
            volume_counters, media, water_counters);
      }
      const float3 environment_direct =
          sample_environment_direct_light(
              hit, material, base_color, wo, next_bsdf_ray_exists, rng,
              traced_rays, volume_counters, media, water_counters);
      bool preserve_grouped_add = params.delta_light_count == 0u;
      if (preserve_grouped_add && clamp_threshold > 0.0f) {
        preserve_grouped_add =
            !scaled_path_contribution_needs_clamp(
                throughput, finite_direct, clamp_threshold) &&
            (current_light_mode != kFiniteLightWaterPowerSample ||
             !scaled_path_contribution_needs_clamp(
                 throughput, water_uniform_direct, clamp_threshold)) &&
            !scaled_path_contribution_needs_clamp(
                throughput, environment_direct, clamp_threshold);
      }
      if (preserve_grouped_add) {
        // If no independent term needs clamping, retain the pre-feature
        // operation tree even when a positive threshold is configured.
        float3 grouped_finite_direct = finite_direct;
        if (current_light_mode == kFiniteLightWaterPowerSample) {
          grouped_finite_direct = add(
              grouped_finite_direct, water_uniform_direct);
        }
        radiance = add(
            radiance,
            mul(throughput,
                add(grouped_finite_direct, environment_direct)));
      } else {
        const float3 finite_contribution =
            mul(throughput, finite_direct);
        const float3 uniform_contribution =
            mul(throughput, water_uniform_direct);
        const float3 environment_contribution =
            mul(throughput, environment_direct);
        accumulate_path_contribution(
            radiance, finite_contribution, clamp_threshold,
            clamped_counter);
        if (current_light_mode == kFiniteLightWaterPowerSample) {
          accumulate_path_contribution(
              radiance, uniform_contribution,
              clamp_threshold, clamped_counter);
        }
        accumulate_path_contribution(
            radiance, environment_contribution, clamp_threshold,
            clamped_counter);
        accumulate_delta_direct_lights(
            hit, material, base_color, wo, rng, traced_rays,
            volume_counters, media, water_counters, throughput,
            clamp_threshold, clamped_counter, radiance);
      }
      if (!next_bsdf_ray_exists) {
        break;
      }

      if (material.type == spectraldock::kMaterialWater &&
          material.roughness <= 0.0f && split_used == 0) {
        split_used = 1;
        float eta_i = 1.0f;
        float eta_t = 1.0f;
        dielectric_eta_pair(material, hit.front_face, hit.material_index,
                            &media, water_counters, eta_i, eta_t);
        const float eta = eta_i / eta_t;
        const float cos_theta =
            fminf(fmaxf(dot3(wo, hit.normal), 0.0f), 1.0f);
        float cos_transmitted = 0.0f;
        const float reflectance = dielectric_fresnel(
            cos_theta, eta_i, eta_t, &cos_transmitted);
        const float3 reflected = normalize3(
            reflect3(neg(wo), hit.normal));
        if (!(reflectance < 1.0f)) {
          throughput = clamp_nonnegative(mul(throughput, base_color));
          if (!(max_component(throughput) > 0.0f)) break;
          previous_pdf = 1.0f;
          previous_delta = 1;
          previous_light_mode = current_light_mode;
          previous_position = hit.position;
          ray_origin = add(
              hit.position,
              mul(hit.normal, params.scene_epsilon * 2.0f));
          ray_direction = reflected;
          continue;
        }

        const float3 perpendicular =
            mul(add(neg(wo), mul(hit.normal, cos_theta)), eta);
        const float3 transmitted = normalize3(add(
            perpendicular, mul(hit.normal, -cos_transmitted)));

        Pcg32 reflected_rng = rng;
        fork_rng(reflected_rng,
                 0x7265666cu ^ bounce ^
                     static_cast<unsigned int>(hit.material_index));
        fork_rng(rng,
                 0x7472616eu ^ bounce ^
                     static_cast<unsigned int>(hit.material_index));
        pending_path = 1;
        pending_origin = add(
            hit.position,
            mul(hit.normal, params.scene_epsilon * 2.0f));
        pending_direction = reflected;
        pending_throughput = clamp_nonnegative(
            mul(mul(throughput, base_color), reflectance));
        pending_previous_pdf = 1.0f;
        pending_previous_delta = 1;
        pending_previous_light_mode = current_light_mode;
        pending_previous_position = hit.position;
        pending_bounce = bounce + 1u;
        pending_media = media;
        pending_rng_state = reflected_rng.state;
        pending_rng_increment = reflected_rng.increment;
        ++water_counters.delta_splits;

        throughput = clamp_nonnegative(
            mul(mul(throughput, base_color),
                (1.0f - reflectance) * eta * eta));
        previous_pdf = 1.0f;
        previous_delta = 1;
        previous_light_mode = current_light_mode;
        previous_position = hit.position;
        ray_origin = add(
            hit.position,
            mul(hit.normal, -params.scene_epsilon * 2.0f));
        ray_direction = transmitted;
        if (!update_medium_after_transmission(
                media, hit.material_index, material, hit.front_face,
                water_counters) ||
            !(max_component(throughput) > 0.0f)) {
          break;
        }
        continue;
      }

      const BsdfSample scatter =
          sample_bsdf(material, base_color, hit.normal,
                      hit.geometric_normal, wo,
                      hit.front_face, hit.material_index, rng,
                      params.water_surface_count != 0u ? &media : nullptr,
                      water_counters);
      if (scatter.valid == 0) {
        break;
      }
      throughput = clamp_nonnegative(mul(throughput, scatter.weight));
      if (max_component(throughput) <= 0.0f) {
        break;
      }
      previous_pdf = scatter.pdf;
      previous_delta = scatter.delta;
      previous_light_mode = current_light_mode;
      previous_position = hit.position;

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
      const float3 offset_normal = is_rough_dielectric(material)
          ? hit.geometric_normal : hit.normal;
      const float side =
          dot3(scatter.wi, offset_normal) >= 0.0f ? 1.0f : -1.0f;
      ray_origin =
          add(hit.position, mul(offset_normal,
                                side * params.scene_epsilon * 2.0f));
      ray_direction = scatter.wi;
      }
      if (pending_path == 0) break;
      pending_path = 0;
      ray_origin = pending_origin;
      ray_direction = pending_direction;
      throughput = pending_throughput;
      previous_pdf = pending_previous_pdf;
      previous_delta = pending_previous_delta;
      previous_light_mode = pending_previous_light_mode;
      previous_position = pending_previous_position;
      bounce_start = pending_bounce;
      media = pending_media;
      rng.state = pending_rng_state;
      rng.increment = pending_rng_increment;
      split_used = 1;
    }
    beauty_sum = add(beauty_sum, radiance);
  }

  if (params.traced_rays != nullptr) {
    params.traced_rays[pixel] = traced_rays;
  }
  if (params.volume_counters != nullptr) {
    params.volume_counters[pixel] = volume_counters;
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
  hit->distance = t;
  hit->position = world_point;
  hit->geometric_normal = front_face ? world_outward : neg(world_outward);
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

extern "C" __global__ void __intersection__solid_sphere() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  const float3 offset = sub(optixGetObjectRayOrigin(), geometry.p0);
  const float3 direction = optixGetObjectRayDirection();
  report_quadratic(dot3(direction, direction),
                   2.0f * dot3(offset, direction),
                   dot3(offset, offset) - geometry.radius * geometry.radius,
                   geometry);
}

extern "C" __global__ void __intersection__water_surface() {
  const HitgroupData* record =
      reinterpret_cast<const HitgroupData*>(optixGetSbtDataPointer());
  const GeometryData& geometry = record->geometry;
  WaterCounters* counters = pixel_water_counters();
  if (counters != nullptr) ++counters->tile_tests;

  const unsigned int tiles_x = geometry.water_tiles_x;
  const unsigned int tiles_z = geometry.water_tiles_z;
  if (tiles_x == 0u || tiles_z == 0u ||
      !(geometry.water_size.x > 0.0f) ||
      !(geometry.water_size.y > 0.0f)) {
    if (counters != nullptr) ++counters->solver_overflows;
    return;
  }
  const unsigned int primitive =
      optixGetPrimitiveIndex() - geometry.primitive_index_base;
  if (primitive >= tiles_x * tiles_z) {
    if (counters != nullptr) ++counters->solver_overflows;
    return;
  }
  const unsigned int tile_x = primitive % tiles_x;
  const unsigned int tile_z = primitive / tiles_x;
  const float width_x = geometry.water_size.x / static_cast<float>(tiles_x);
  const float width_z = geometry.water_size.y / static_cast<float>(tiles_z);
  const float surface_min_x = geometry.p0.x - 0.5f * geometry.water_size.x;
  const float surface_min_z = geometry.p0.z - 0.5f * geometry.water_size.y;
  const float tile_min_x = surface_min_x + width_x * tile_x;
  const float tile_max_x =
      surface_min_x + width_x * static_cast<float>(tile_x + 1u);
  const float tile_min_z = surface_min_z + width_z * tile_z;
  const float tile_max_z =
      surface_min_z + width_z * static_cast<float>(tile_z + 1u);

  const float3 origin = optixGetObjectRayOrigin();
  const float3 direction = optixGetObjectRayDirection();
  float near_distance = optixGetRayTmin();
  float far_distance = optixGetRayTmax();
  const float mins[3] = {tile_min_x, geometry.aabb_min.y, tile_min_z};
  const float maxs[3] = {tile_max_x, geometry.aabb_max.y, tile_max_z};
  const float origins[3] = {origin.x, origin.y, origin.z};
  const float directions[3] = {direction.x, direction.y, direction.z};
  for (int axis = 0; axis < 3; ++axis) {
    if (fabsf(directions[axis]) < 1.0e-12f) {
      if (origins[axis] < mins[axis] || origins[axis] > maxs[axis]) return;
      continue;
    }
    float a = (mins[axis] - origins[axis]) / directions[axis];
    float b = (maxs[axis] - origins[axis]) / directions[axis];
    if (b < a) {
      const float temporary = a;
      a = b;
      b = temporary;
    }
    near_distance = fmaxf(near_distance, a);
    far_distance = fminf(far_distance, b);
    if (!(far_distance >= near_distance)) return;
  }

  float maximum_phase_rate = 0.0f;
  const unsigned int wave_count =
      geometry.water_wave_count < 4u ? geometry.water_wave_count : 4u;
  for (unsigned int i = 0u; i < wave_count; ++i) {
    const spectraldock::DeviceWaterWave& wave = geometry.water_waves[i];
    maximum_phase_rate = fmaxf(
        maximum_phase_rate,
        fabsf(wave.wave_number *
              (wave.direction.x * direction.x +
               wave.direction.y * direction.z)));
  }
  unsigned int intervals = maximum_phase_rate > 0.0f
      ? static_cast<unsigned int>(
            ceilf(maximum_phase_rate * (far_distance - near_distance) /
                  (kPi / 8.0f)))
      : 1u;
  intervals = intervals > 0u ? intervals : 1u;
  if (intervals > 64u) {
    if (counters != nullptr) ++counters->solver_overflows;
    return;
  }

  const float interval_width =
      (far_distance - near_distance) / static_cast<float>(intervals);
  constexpr unsigned int kRootCapacity = 32u;
  WaterRootCandidate root_candidates[kRootCapacity];
  unsigned int root_count = 0u;
  float coarse_lower = near_distance;
  float coarse_lower_value =
      water_function_value(geometry, origin, direction, coarse_lower);
  constexpr unsigned int kWorkCapacity = 64u;
  constexpr unsigned int kMaximumDepth = 24u;
  for (unsigned int coarse = 0u; coarse < intervals; ++coarse) {
    const float coarse_upper = coarse + 1u == intervals
        ? far_distance
        : near_distance + interval_width * static_cast<float>(coarse + 1u);
    const float coarse_upper_value =
        water_function_value(geometry, origin, direction, coarse_upper);
    WaterRootWorkItem work[kWorkCapacity];
    unsigned int work_count = 1u;
    work[0] = {coarse_lower, coarse_upper, coarse_lower_value,
               coarse_upper_value, 0u};
    while (work_count != 0u) {
      const WaterRootWorkItem item = work[--work_count];
      const ScalarInterval function_bounds = water_function_interval(
          geometry, origin, direction, item.lower, item.upper);
      if (function_bounds.lower > 0.0f || function_bounds.upper < 0.0f) {
        continue;
      }
      const ScalarInterval derivative_bounds = water_derivative_interval(
          geometry, origin, direction, item.lower, item.upper);
      const bool monotonic = derivative_bounds.lower > 0.0f ||
                             derivative_bounds.upper < 0.0f;
      if (monotonic) {
        if (item.lower_value == 0.0f || item.upper_value == 0.0f) {
          const float root = item.lower_value == 0.0f
              ? item.lower : item.upper;
          int orientation = 0;
          if (!validate_water_endpoint_crossing(
                  geometry, origin, direction, root, orientation)) {
            continue;
          }
          const float3 point = add(origin, mul(direction, root));
          if (water_tile_owns_point(
                  point, tile_min_x, tile_max_x, tile_min_z, tile_max_z,
                  tile_x, tile_z, tiles_x, tiles_z) && valid_t(root) &&
              !append_water_root_candidate(
                  root, 0.0f, orientation, root_candidates, root_count,
                  kRootCapacity)) {
            if (counters != nullptr) ++counters->solver_overflows;
            return;
          }
          continue;
        }
        if ((item.lower_value < 0.0f) == (item.upper_value < 0.0f)) {
          continue;
        }
        float root = solve_water_monotonic_root(
            geometry, origin, direction, item.lower, item.upper,
            item.lower_value, item.upper_value);
        float residual = fabsf(
            water_function_value(geometry, origin, direction, root));
        int orientation = item.lower_value < 0.0f ? 1 : -1;
        if (fabsf(water_derivative_value(
                geometry, origin, direction, root)) < 0.02f &&
            !refine_suspicious_water_bracket(
                geometry, origin, direction, item.lower, item.upper,
                root, residual, orientation)) {
          continue;
        }
        const float3 point = add(origin, mul(direction, root));
        const bool owned = water_tile_owns_point(
            point, tile_min_x, tile_max_x, tile_min_z, tile_max_z,
            tile_x, tile_z, tiles_x, tiles_z);
        if (residual > 1.0e-4f) {
          if (counters != nullptr) ++counters->solver_overflows;
          return;
        }
        if (owned && valid_t(root) &&
            !append_water_root_candidate(
                root, residual, orientation, root_candidates, root_count,
                kRootCapacity)) {
          if (counters != nullptr) ++counters->solver_overflows;
          return;
        }
        continue;
      }

      const float width = item.upper - item.lower;
      if (item.depth < kMaximumDepth && width > 1.0e-7f) {
        if (work_count + 2u > kWorkCapacity) {
          if (counters != nullptr) ++counters->solver_overflows;
          return;
        }
        const float middle = 0.5f * (item.lower + item.upper);
        const float middle_value =
            water_function_value(geometry, origin, direction, middle);
        // LIFO: push the farther interval first so the nearer one is always
        // processed first and the first accepted root is the nearest root.
        work[work_count++] = {middle, item.upper, middle_value,
                              item.upper_value, item.depth + 1u};
        work[work_count++] = {item.lower, middle, item.lower_value,
                              middle_value, item.depth + 1u};
        continue;
      }

      // The derivative interval still contains zero at terminal precision.
      // Isolate a stationary point and explicitly test it for an even/tangent
      // root. If interval arithmetic still cannot prove absence afterwards,
      // fail closed instead of silently losing an intersection.
      const float terminal_middle = 0.5f * (item.lower + item.upper);
      const float terminal_middle_value = water_function_value(
          geometry, origin, direction, terminal_middle);
      const float derivative_limit = fmaxf(
          fabsf(derivative_bounds.lower), fabsf(derivative_bounds.upper));
      const float evaluation_padding =
          8.0e-6f * (1.0f + fabsf(terminal_middle_value));
      const float maximum_variation =
          derivative_limit * 0.5f * width + evaluation_padding;
      if (terminal_middle_value - maximum_variation > 0.0f ||
          terminal_middle_value + maximum_variation < 0.0f) {
        continue;
      }
      float stationary = 0.5f * (item.lower + item.upper);
      float derivative_lower = water_derivative_value(
          geometry, origin, direction, item.lower);
      float derivative_upper = water_derivative_value(
          geometry, origin, direction, item.upper);
      if (derivative_lower == 0.0f) {
        stationary = item.lower;
      } else if (derivative_upper == 0.0f) {
        stationary = item.upper;
      } else if ((derivative_lower < 0.0f) != (derivative_upper < 0.0f)) {
        float stationary_lower = item.lower;
        float stationary_upper = item.upper;
        for (int iteration = 0; iteration < 20; ++iteration) {
          stationary = 0.5f * (stationary_lower + stationary_upper);
          const float derivative = water_derivative_value(
              geometry, origin, direction, stationary);
          if ((derivative < 0.0f) == (derivative_lower < 0.0f)) {
            stationary_lower = stationary;
            derivative_lower = derivative;
          } else {
            stationary_upper = stationary;
          }
        }
        stationary = 0.5f * (stationary_lower + stationary_upper);
      } else {
        const float middle = 0.5f * (item.lower + item.upper);
        const float derivative_middle = fabsf(water_derivative_value(
            geometry, origin, direction, middle));
        if (fabsf(derivative_lower) < derivative_middle &&
            fabsf(derivative_lower) <= fabsf(derivative_upper)) {
          stationary = item.lower;
        } else if (fabsf(derivative_upper) < derivative_middle) {
          stationary = item.upper;
        }
      }
      const float stationary_value =
          water_function_value(geometry, origin, direction, stationary);
      if (stationary_value == 0.0f &&
          ((item.lower_value < 0.0f) == (item.upper_value < 0.0f))) {
        continue;
      }
      const bool left_crosses =
          stationary > item.lower &&
          ((item.lower_value < 0.0f) != (stationary_value < 0.0f));
      const bool right_crosses =
          stationary < item.upper &&
          ((stationary_value < 0.0f) != (item.upper_value < 0.0f));
      bool found_crossing = false;
      if (left_crosses) {
        float root = solve_water_monotonic_root(
            geometry, origin, direction, item.lower, stationary,
            item.lower_value, stationary_value);
        float residual = fabsf(
            water_function_value(geometry, origin, direction, root));
        int orientation = item.lower_value < 0.0f ? 1 : -1;
        if (refine_suspicious_water_bracket(
                geometry, origin, direction, item.lower, stationary,
                root, residual, orientation)) {
          if (residual > 1.0e-4f) {
            if (counters != nullptr) ++counters->solver_overflows;
            return;
          }
          const float3 point = add(origin, mul(direction, root));
          if (water_tile_owns_point(
                  point, tile_min_x, tile_max_x, tile_min_z, tile_max_z,
                  tile_x, tile_z, tiles_x, tiles_z) && valid_t(root) &&
              !append_water_root_candidate(
                  root, residual, orientation, root_candidates, root_count,
                  kRootCapacity)) {
            if (counters != nullptr) ++counters->solver_overflows;
            return;
          }
          found_crossing = true;
        }
      }
      if (right_crosses) {
        float root = solve_water_monotonic_root(
            geometry, origin, direction, stationary, item.upper,
            stationary_value, item.upper_value);
        float residual = fabsf(
            water_function_value(geometry, origin, direction, root));
        int orientation = stationary_value < 0.0f ? 1 : -1;
        if (refine_suspicious_water_bracket(
                geometry, origin, direction, stationary, item.upper,
                root, residual, orientation)) {
          if (residual > 1.0e-4f) {
            if (counters != nullptr) ++counters->solver_overflows;
            return;
          }
          const float3 point = add(origin, mul(direction, root));
          if (water_tile_owns_point(
                  point, tile_min_x, tile_max_x, tile_min_z, tile_max_z,
                  tile_x, tile_z, tiles_x, tiles_z) && valid_t(root) &&
              !append_water_root_candidate(
                  root, residual, orientation, root_candidates, root_count,
                  kRootCapacity)) {
            if (counters != nullptr) ++counters->solver_overflows;
            return;
          }
          found_crossing = true;
        }
      }
      if (found_crossing || fabsf(stationary_value) <= 1.0e-4f) {
        // A stationary zero with no sign-changing side is a pure even/tangent
        // contact. It is geometrically valid but does not cross the medium
        // boundary, so it must not be reported to transport.
        continue;
      }
      if (counters != nullptr) ++counters->solver_overflows;
      return;
    }
    coarse_lower = coarse_upper;
    coarse_lower_value = coarse_upper_value;
  }

  for (unsigned int i = 1u; i < root_count; ++i) {
    const WaterRootCandidate value = root_candidates[i];
    unsigned int j = i;
    while (j > 0u &&
           root_candidates[j - 1u].distance > value.distance) {
      root_candidates[j] = root_candidates[j - 1u];
      --j;
    }
    root_candidates[j] = value;
  }
  for (unsigned int i = 0u; i < root_count;) {
    if (i + 1u < root_count &&
        root_candidates[i].orientation != root_candidates[i + 1u].orientation &&
        root_candidates[i + 1u].distance - root_candidates[i].distance <=
            2.0f * params.scene_epsilon) {
      // A sub-epsilon enter/exit pair is an unresolved grazing contact. A
      // single reported side would corrupt the LIFO medium stack, while the
      // pair has zero resolvable optical thickness and no net transition.
      i += 2u;
      continue;
    }
    if (counters != nullptr) ++counters->roots_reported;
    if (optixReportIntersection(root_candidates[i].distance, 0u)) return;
    ++i;
  }
}
