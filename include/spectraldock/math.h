#pragma once

#include <cmath>
#include <type_traits>

namespace spectraldock {

constexpr float kPi = 3.14159265358979323846f;

struct Vec2 {
  float x = 0.0f;
  float y = 0.0f;
  constexpr Vec2() = default;
  constexpr Vec2(float x_, float y_) : x(x_), y(y_) {}
};

struct Vec3 {
  float x = 0.0f;
  float y = 0.0f;
  float z = 0.0f;
  constexpr Vec3() = default;
  constexpr explicit Vec3(float v) : x(v), y(v), z(v) {}
  constexpr Vec3(float x_, float y_, float z_) : x(x_), y(y_), z(z_) {}
};

static_assert(sizeof(Vec3) == 3 * sizeof(float), "Vec3 must match CUDA float3 layout");
static_assert(std::is_standard_layout<Vec3>::value, "Vec3 must remain standard-layout");
static_assert(std::is_trivially_copyable<Vec3>::value, "Vec3 must be device-copyable");

constexpr Vec3 operator+(Vec3 a, Vec3 b) {
  return {a.x + b.x, a.y + b.y, a.z + b.z};
}
constexpr Vec3 operator-(Vec3 a, Vec3 b) {
  return {a.x - b.x, a.y - b.y, a.z - b.z};
}
constexpr Vec3 operator-(Vec3 v) { return {-v.x, -v.y, -v.z}; }
constexpr Vec3 operator*(Vec3 v, float s) {
  return {v.x * s, v.y * s, v.z * s};
}
constexpr Vec3 operator*(float s, Vec3 v) { return v * s; }
constexpr Vec3 operator*(Vec3 a, Vec3 b) {
  return {a.x * b.x, a.y * b.y, a.z * b.z};
}
constexpr Vec3 operator/(Vec3 v, float s) {
  return {v.x / s, v.y / s, v.z / s};
}
constexpr Vec3& operator+=(Vec3& a, Vec3 b) {
  a = a + b;
  return a;
}

constexpr float dot(Vec3 a, Vec3 b) {
  return a.x * b.x + a.y * b.y + a.z * b.z;
}
constexpr Vec3 cross(Vec3 a, Vec3 b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
constexpr float length_squared(Vec3 v) { return dot(v, v); }
inline float length(Vec3 v) { return ::sqrtf(length_squared(v)); }
inline Vec3 normalize(Vec3 v) {
  const float n = length(v);
  return n > 0.0f ? v / n : Vec3{};
}
constexpr float max_component(Vec3 v) {
  return v.x > v.y ? (v.x > v.z ? v.x : v.z) : (v.y > v.z ? v.y : v.z);
}
constexpr bool finite(float x) {
  constexpr float max_float = 3.402823466e+38F;
  return x == x && x >= -max_float && x <= max_float;
}
inline bool finite(Vec3 v) {
  return finite(v.x) && finite(v.y) && finite(v.z);
}

struct Aabb {
  Vec3 min{};
  Vec3 max{};
  constexpr bool ordered() const {
    return min.x <= max.x && min.y <= max.y && min.z <= max.z;
  }
  bool valid() const { return ordered() && finite(min) && finite(max); }
};

}  // namespace spectraldock
