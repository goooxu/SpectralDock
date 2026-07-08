#pragma once

#include "spectraldock/integrator_policy.h"

#include <cmath>
#include <type_traits>

#ifndef SPECTRALDOCK_HD
#if defined(__CUDACC__)
#define SPECTRALDOCK_HD __host__ __device__
#define SPECTRALDOCK_INLINE __forceinline__
#else
#define SPECTRALDOCK_HD
#define SPECTRALDOCK_INLINE inline
#endif
#endif

namespace spectraldock {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kRayEpsilon = 1.0e-4f;

struct Vec2 {
  float x = 0.0f;
  float y = 0.0f;
  SPECTRALDOCK_HD constexpr Vec2() = default;
  SPECTRALDOCK_HD constexpr Vec2(float x_, float y_) : x(x_), y(y_) {}
};

struct Vec3 {
  float x = 0.0f;
  float y = 0.0f;
  float z = 0.0f;
  SPECTRALDOCK_HD constexpr Vec3() = default;
  SPECTRALDOCK_HD constexpr explicit Vec3(float v) : x(v), y(v), z(v) {}
  SPECTRALDOCK_HD constexpr Vec3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}
};

static_assert(sizeof(Vec3) == 3 * sizeof(float), "Vec3 must match CUDA float3 layout");
static_assert(std::is_standard_layout<Vec3>::value, "Vec3 must remain standard-layout");
static_assert(std::is_trivially_copyable<Vec3>::value, "Vec3 must be device-copyable");

SPECTRALDOCK_HD constexpr Vec2 operator+(Vec2 a, Vec2 b) { return {a.x + b.x, a.y + b.y}; }
SPECTRALDOCK_HD constexpr Vec2 operator-(Vec2 a, Vec2 b) { return {a.x - b.x, a.y - b.y}; }
SPECTRALDOCK_HD constexpr Vec2 operator*(Vec2 v, float s) { return {v.x * s, v.y * s}; }
SPECTRALDOCK_HD constexpr Vec3 operator+(Vec3 a, Vec3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
SPECTRALDOCK_HD constexpr Vec3 operator-(Vec3 a, Vec3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
SPECTRALDOCK_HD constexpr Vec3 operator-(Vec3 v) { return {-v.x, -v.y, -v.z}; }
SPECTRALDOCK_HD constexpr Vec3 operator*(Vec3 v, float s) { return {v.x * s, v.y * s, v.z * s}; }
SPECTRALDOCK_HD constexpr Vec3 operator*(float s, Vec3 v) { return v * s; }
SPECTRALDOCK_HD constexpr Vec3 operator*(Vec3 a, Vec3 b) { return {a.x * b.x, a.y * b.y, a.z * b.z}; }
SPECTRALDOCK_HD constexpr Vec3 operator/(Vec3 v, float s) { return {v.x / s, v.y / s, v.z / s}; }
SPECTRALDOCK_HD constexpr Vec3 operator/(Vec3 a, Vec3 b) { return {a.x / b.x, a.y / b.y, a.z / b.z}; }
SPECTRALDOCK_HD constexpr Vec3& operator+=(Vec3& a, Vec3 b) { a = a + b; return a; }
SPECTRALDOCK_HD constexpr Vec3& operator*=(Vec3& a, Vec3 b) { a = a * b; return a; }
SPECTRALDOCK_HD constexpr Vec3& operator*=(Vec3& a, float s) { a = a * s; return a; }

SPECTRALDOCK_HD constexpr float dot(Vec3 a, Vec3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
SPECTRALDOCK_HD constexpr Vec3 cross(Vec3 a, Vec3 b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
SPECTRALDOCK_HD constexpr float length_squared(Vec3 v) { return dot(v, v); }
SPECTRALDOCK_HD SPECTRALDOCK_INLINE float length(Vec3 v) { return ::sqrtf(length_squared(v)); }
SPECTRALDOCK_HD SPECTRALDOCK_INLINE Vec3 normalize(Vec3 v) {
  const float n = length(v);
  return n > 0.0f ? v / n : Vec3{};
}
SPECTRALDOCK_HD constexpr float clamp(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
SPECTRALDOCK_HD constexpr Vec3 clamp(Vec3 v, float lo, float hi) {
  return {clamp(v.x, lo, hi), clamp(v.y, lo, hi), clamp(v.z, lo, hi)};
}
SPECTRALDOCK_HD constexpr float max_component(Vec3 v) {
  return v.x > v.y ? (v.x > v.z ? v.x : v.z) : (v.y > v.z ? v.y : v.z);
}
SPECTRALDOCK_HD constexpr float luminance(Vec3 v) { return 0.2126f * v.x + 0.7152f * v.y + 0.0722f * v.z; }
SPECTRALDOCK_HD constexpr bool finite(float x) {
  constexpr float max_float = 3.402823466e+38F;
  return x == x && x >= -max_float && x <= max_float;
}
SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool finite(Vec3 v) { return finite(v.x) && finite(v.y) && finite(v.z); }

struct Ray {
  Vec3 origin{};
  Vec3 direction{};
  SPECTRALDOCK_HD constexpr Vec3 at(float t) const { return origin + direction * t; }
};

struct Aabb {
  Vec3 min{};
  Vec3 max{};
  SPECTRALDOCK_HD constexpr bool ordered() const {
    return min.x <= max.x && min.y <= max.y && min.z <= max.z;
  }
  SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool valid() const { return ordered() && finite(min) && finite(max); }
  SPECTRALDOCK_HD constexpr bool contains(Vec3 p, float eps = 0.0f) const {
    return p.x >= min.x - eps && p.x <= max.x + eps &&
           p.y >= min.y - eps && p.y <= max.y + eps &&
           p.z >= min.z - eps && p.z <= max.z + eps;
  }
};

struct SurfaceHit {
  float t = 0.0f;
  Vec3 position{};
  Vec3 outward_normal{};
  Vec3 normal{};
  Vec2 uv{};
  bool front_face = true;
};

SPECTRALDOCK_HD SPECTRALDOCK_INLINE void orient_hit(const Ray& ray, SurfaceHit& hit) {
  hit.front_face = dot(ray.direction, hit.outward_normal) < 0.0f;
  hit.normal = hit.front_face ? hit.outward_normal : -hit.outward_normal;
}

SPECTRALDOCK_HD constexpr Vec3 reflect(Vec3 incident, Vec3 normal) {
  return incident - 2.0f * dot(incident, normal) * normal;
}

// eta_ratio is eta_incident / eta_transmitted.
SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool refract(Vec3 incident, Vec3 normal, float eta_ratio, Vec3& transmitted) {
  const Vec3 wi = normalize(incident);
  const float cos_theta = clamp(dot(-wi, normal), 0.0f, 1.0f);
  const Vec3 perpendicular = eta_ratio * (wi + cos_theta * normal);
  const float parallel_sq = 1.0f - length_squared(perpendicular);
  if (parallel_sq < 0.0f) return false;
  transmitted = perpendicular - ::sqrtf(parallel_sq) * normal;
  return true;
}

SPECTRALDOCK_HD SPECTRALDOCK_INLINE float fresnel_schlick(float cosine, float eta_i, float eta_t) {
  float r0 = (eta_i - eta_t) / (eta_i + eta_t);
  r0 *= r0;
  const float m = clamp(1.0f - cosine, 0.0f, 1.0f);
  const float m2 = m * m;
  return r0 + (1.0f - r0) * m2 * m2 * m;
}

SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool intersect_sphere(const Ray& ray, Vec3 center, float radius,
                                                   float t_min, float t_max, SurfaceHit& hit) {
  const Vec3 oc = ray.origin - center;
  const float a = length_squared(ray.direction);
  const float half_b = dot(oc, ray.direction);
  const float c = length_squared(oc) - radius * radius;
  const float discriminant = half_b * half_b - a * c;
  if (discriminant < 0.0f || a <= 0.0f) return false;
  const float s = ::sqrtf(discriminant);
  float t = (-half_b - s) / a;
  if (t < t_min || t > t_max) {
    t = (-half_b + s) / a;
    if (t < t_min || t > t_max) return false;
  }
  hit.t = t;
  hit.position = ray.at(t);
  hit.outward_normal = (hit.position - center) / radius;
  const float phi = ::atan2f(hit.outward_normal.z, hit.outward_normal.x);
  const float theta = ::asinf(clamp(hit.outward_normal.y, -1.0f, 1.0f));
  hit.uv = {1.0f - (phi + kPi) / (2.0f * kPi), (theta + 0.5f * kPi) / kPi};
  orient_hit(ray, hit);
  return true;
}

// p1, p2 and p3 are consecutive parallelogram corners. The outward normal
// follows the legacy renderer convention cross(p3-p2, p2-p1).
SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool intersect_parallelogram(
    const Ray& ray, Vec3 p1, Vec3 p2, Vec3 p3, float t_min, float t_max,
    SurfaceHit& hit) {
  const Vec3 edge_v = p2 - p1;
  const Vec3 edge_u = p3 - p2;
  const Vec3 outward = normalize(cross(edge_u, edge_v));
  const float denominator = dot(outward, ray.direction);
  if (::fabsf(denominator) < 1.0e-8f) return false;
  const float t = dot(outward, p1 - ray.origin) / denominator;
  if (t < t_min || t > t_max) return false;
  const Vec3 point = ray.at(t);
  const Vec3 relative = point - p1;
  const float vv = length_squared(edge_v);
  const float uu = length_squared(edge_u);
  const float v = dot(relative, edge_v) / vv;
  const float u = dot(relative, edge_u) / uu;
  if (u < 0.0f || u > 1.0f || v < 0.0f || v > 1.0f) return false;
  hit.t = t;
  hit.position = point;
  hit.outward_normal = outward;
  hit.uv = {u, v};
  orient_hit(ray, hit);
  return true;
}

SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool intersect_disk(const Ray& ray, Vec3 center, Vec3 unit_normal,
                                                 float radius, float t_min, float t_max,
                                                 SurfaceHit& hit) {
  const float denom = dot(unit_normal, ray.direction);
  if (::fabsf(denom) < 1.0e-8f) return false;
  const float t = dot(unit_normal, center - ray.origin) / denom;
  if (t < t_min || t > t_max) return false;
  const Vec3 p = ray.at(t);
  if (length_squared(p - center) > radius * radius) return false;
  hit.t = t;
  hit.position = p;
  hit.outward_normal = unit_normal;
  const Vec3 helper = ::fabsf(unit_normal.z) < 0.999f
                          ? Vec3{0.0f, 0.0f, 1.0f}
                          : Vec3{0.0f, 1.0f, 0.0f};
  const Vec3 u = normalize(cross(helper, unit_normal));
  const Vec3 v = cross(unit_normal, u);
  const Vec3 q = p - center;
  const float inv_diameter = 0.5f / radius;
  hit.uv = {0.5f + dot(q, u) * inv_diameter,
            0.5f + dot(q, v) * inv_diameter};
  orient_hit(ray, hit);
  return true;
}

// Open finite cylinder. The axis runs from base to base + unit_axis * height.
SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool intersect_cylinder(const Ray& ray, Vec3 base, Vec3 unit_axis,
                                                     float height, float radius, float t_min,
                                                     float t_max, SurfaceHit& hit) {
  const Vec3 oc = ray.origin - base;
  const float d_axis = dot(ray.direction, unit_axis);
  const float o_axis = dot(oc, unit_axis);
  const Vec3 d_perp = ray.direction - d_axis * unit_axis;
  const Vec3 o_perp = oc - o_axis * unit_axis;
  const float a = length_squared(d_perp);
  if (a < 1.0e-12f) return false;
  const float half_b = dot(o_perp, d_perp);
  const float c = length_squared(o_perp) - radius * radius;
  const float discriminant = half_b * half_b - a * c;
  if (discriminant < 0.0f) return false;
  const float root = ::sqrtf(discriminant);
  const float roots[2] = {(-half_b - root) / a, (-half_b + root) / a};
  for (int i = 0; i < 2; ++i) {
    const float t = roots[i];
    if (t < t_min || t > t_max) continue;
    const float axial = o_axis + t * d_axis;
    if (axial < 0.0f || axial > height) continue;
    const Vec3 p = ray.at(t);
    hit.t = t;
    hit.position = p;
    hit.outward_normal = normalize(p - (base + axial * unit_axis));
    const Vec3 helper = ::fabsf(unit_axis.z) < 0.999f
                            ? Vec3{0.0f, 0.0f, 1.0f}
                            : Vec3{0.0f, 1.0f, 0.0f};
    const Vec3 u = normalize(cross(helper, unit_axis));
    const Vec3 v = cross(unit_axis, u);
    const float azimuth = 0.5f +
        ::atan2f(dot(hit.outward_normal, v), dot(hit.outward_normal, u)) /
            (2.0f * kPi);
    hit.uv = {axial / height, azimuth};
    orient_hit(ray, hit);
    return true;
  }
  return false;
}

// Finite clipped parabolic cylinder matching the legacy renderer equation.
SPECTRALDOCK_HD SPECTRALDOCK_INLINE bool intersect_parabola(const Ray& ray, Vec3 origin, Vec3 normal,
                                                     Vec3 focus, const Aabb& clip, float t_min,
                                                     float t_max, SurfaceHit& hit) {
  const Vec3 n = normalize(normal);
  const Vec3 focus_delta = focus - origin;
  const float focal_distance = length(focus_delta);
  if (focal_distance <= 0.0f) return false;
  const Vec3 m = focus_delta / focal_distance;
  const Vec3 v_raw = cross(m, n);
  if (length_squared(v_raw) < 1.0e-12f) return false;
  const Vec3 v = normalize(v_raw);
  const float vv = dot(v, v);
  const float nv = dot(n, v);
  const float nn = dot(n, n);
  const Vec3 oa = ray.origin - origin;
  const Vec3 of = ray.origin - focus;
  const Vec3 od = ray.origin - (origin - focus_delta);
  const float un = dot(ray.direction, n);
  const float uv = dot(ray.direction, v);
  const float noa = dot(n, oa);
  const float vod = dot(v, od);
  const float p1 = un / nn;
  const float p2 = noa / nn;
  const float p3 = (uv - nv * p1) / vv;
  const float p4 = (vod - nv * p2) / vv;
  const Vec3 d0 = ray.direction - p1 * n;
  const Vec3 d1 = d0 - p3 * v;
  const Vec3 o0 = of - p2 * n;
  const Vec3 o1 = od - p2 * n - p4 * v;
  const float a = length_squared(d0) - length_squared(d1);
  const float b = dot(d0, o0) - dot(d1, o1);
  const float c = length_squared(o0) - length_squared(o1);
  float roots[2]{};
  int count = 0;
  if (::fabsf(a) < 1.0e-12f) {
    if (::fabsf(b) < 1.0e-12f) return false;
    roots[count++] = -c / (2.0f * b);
  } else {
    const float discriminant = b * b - a * c;
    if (discriminant < 0.0f) return false;
    const float s = ::sqrtf(discriminant);
    roots[0] = (-b - s) / a;
    roots[1] = (-b + s) / a;
    if (roots[1] < roots[0]) { const float tmp = roots[0]; roots[0] = roots[1]; roots[1] = tmp; }
    count = 2;
  }
  for (int i = 0; i < count; ++i) {
    const float t = roots[i];
    if (t < t_min || t > t_max) continue;
    const Vec3 p = ray.at(t);
    if (!clip.contains(p, 2.0f * kRayEpsilon)) continue;
    const float axial = (t * un + noa) / nn;
    const float x = dot(p - (origin + axial * n), v);
    hit.t = t;
    hit.position = p;
    hit.outward_normal = normalize(v * (x / (2.0f * focal_distance)) - m);
    hit.uv = {x, axial};
    orient_hit(ray, hit);
    return true;
  }
  return false;
}

SPECTRALDOCK_HD SPECTRALDOCK_INLINE float linear_to_srgb(float x) {
  x = x < 0.0f ? 0.0f : x;
  return x <= 0.0031308f ? 12.92f * x : 1.055f * ::powf(x, 1.0f / 2.4f) - 0.055f;
}
SPECTRALDOCK_HD SPECTRALDOCK_INLINE Vec3 linear_to_srgb(Vec3 c) {
  return {linear_to_srgb(c.x), linear_to_srgb(c.y), linear_to_srgb(c.z)};
}
SPECTRALDOCK_HD SPECTRALDOCK_INLINE float srgb_to_linear(float x) {
  x = clamp(x, 0.0f, 1.0f);
  return x <= 0.04045f ? x / 12.92f : ::powf((x + 0.055f) / 1.055f, 2.4f);
}
SPECTRALDOCK_HD SPECTRALDOCK_INLINE Vec3 srgb_to_linear(Vec3 c) {
  return {srgb_to_linear(c.x), srgb_to_linear(c.y), srgb_to_linear(c.z)};
}
// Krzysztof Narkowicz's CC0/MIT ACES-inspired fitted curve, used here under
// CC0-1.0. See THIRD_PARTY_NOTICES.md.
SPECTRALDOCK_HD SPECTRALDOCK_INLINE Vec3 aces_tonemap(Vec3 x) {
  const Vec3 numerator = x * (2.51f * x + Vec3{0.03f});
  const Vec3 denominator = x * (2.43f * x + Vec3{0.59f}) + Vec3{0.14f};
  return clamp(numerator / denominator, 0.0f, 1.0f);
}

}  // namespace spectraldock
