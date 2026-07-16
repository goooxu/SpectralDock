#include "spectraldock/scene_types.h"

#include <cmath>

namespace spectraldock {

TransformMatrix3x4 compose_transform(const Transform& transform) {
  const float radians = kPi / 180.0f;
  const float cx = std::cos(transform.rotate_degrees.x * radians);
  const float sx = std::sin(transform.rotate_degrees.x * radians);
  const float cy = std::cos(transform.rotate_degrees.y * radians);
  const float sy = std::sin(transform.rotate_degrees.y * radians);
  const float cz = std::cos(transform.rotate_degrees.z * radians);
  const float sz = std::sin(transform.rotate_degrees.z * radians);

  // Rz * Ry * Rx, followed by column-wise scale and affine translation.
  return {
      cz * cy * transform.scale.x,
      (cz * sy * sx - sz * cx) * transform.scale.y,
      (cz * sy * cx + sz * sx) * transform.scale.z,
      transform.translate.x,
      sz * cy * transform.scale.x,
      (sz * sy * sx + cz * cx) * transform.scale.y,
      (sz * sy * cx - cz * sx) * transform.scale.z,
      transform.translate.y,
      -sy * transform.scale.x,
      cy * sx * transform.scale.y,
      cy * cx * transform.scale.z,
      transform.translate.z,
  };
}

}  // namespace spectraldock
