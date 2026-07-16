#include "spectraldock/obj_loader.h"

#define TINYOBJLOADER_IMPLEMENTATION
#include "tiny_obj_loader.h"

#include <array>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace spectraldock {
namespace {

[[noreturn]] void obj_fail(const std::filesystem::path& path,
                           const std::string& message) {
  throw std::runtime_error("OBJ " + path.string() + ": " + message);
}

struct Corner {
  int position = -1;
  int normal = -1;
  int texcoord = -1;
};

struct Face {
  std::array<Corner, 3> corners{};
  Vec3 weighted_normal{};
  unsigned int smoothing_group = 0;
  std::string context;
};

struct SmoothKey {
  int position = -1;
  unsigned int group = 0;

  bool operator==(const SmoothKey& other) const noexcept {
    return position == other.position && group == other.group;
  }
};

struct SmoothKeyHash {
  std::size_t operator()(const SmoothKey& key) const noexcept {
    const std::uint64_t bits =
        (static_cast<std::uint64_t>(static_cast<std::uint32_t>(key.position))
         << 32) |
        static_cast<std::uint64_t>(key.group);
    return std::hash<std::uint64_t>{}(bits);
  }
};

std::string shape_name(const tinyobj::shape_t& shape) {
  return shape.name.empty() ? "<unnamed>" : shape.name;
}

void validate_attribute_layout(const std::filesystem::path& path,
                               const tinyobj::attrib_t& attributes) {
  if (attributes.vertices.size() % 3 != 0)
    obj_fail(path, "position attribute array is malformed");
  if (attributes.normals.size() % 3 != 0)
    obj_fail(path, "normal attribute array is malformed");
  if (attributes.texcoords.size() % 2 != 0)
    obj_fail(path, "texture-coordinate attribute array is malformed");
  if (attributes.vertices.empty()) obj_fail(path, "contains no positions");
}

void check_index(const std::filesystem::path& path, int index,
                 std::size_t count, const std::string& kind,
                 const std::string& context, bool optional) {
  if (optional && index == -1) return;
  if (index < 0 || static_cast<std::size_t>(index) >= count) {
    obj_fail(path, context + " has invalid " + kind + " index " +
                       std::to_string(index));
  }
}

Vec3 read_position(const tinyobj::attrib_t& attributes, int index) {
  const std::size_t base = static_cast<std::size_t>(index) * 3;
  return {static_cast<float>(attributes.vertices[base]),
          static_cast<float>(attributes.vertices[base + 1]),
          static_cast<float>(attributes.vertices[base + 2])};
}

Vec3 read_normal(const tinyobj::attrib_t& attributes, int index) {
  const std::size_t base = static_cast<std::size_t>(index) * 3;
  return {static_cast<float>(attributes.normals[base]),
          static_cast<float>(attributes.normals[base + 1]),
          static_cast<float>(attributes.normals[base + 2])};
}

Vec2 read_texcoord(const tinyobj::attrib_t& attributes, int index) {
  const std::size_t base = static_cast<std::size_t>(index) * 2;
  return {static_cast<float>(attributes.texcoords[base]),
          static_cast<float>(attributes.texcoords[base + 1])};
}

Vec3 checked_unit_normal(const std::filesystem::path& path, Vec3 value,
                         const std::string& context) {
  if (!finite(value) || length_squared(value) <= 1.0e-20f)
    obj_fail(path, context + " has a zero or non-finite normal");
  return normalize(value);
}

}  // namespace

TriangleMesh load_obj_mesh(const std::filesystem::path& input_path) {
  const std::filesystem::path path =
      std::filesystem::absolute(input_path).lexically_normal();
  std::ifstream input(path, std::ios::binary);
  if (!input) obj_fail(path, "cannot open file");
  const std::string source((std::istreambuf_iterator<char>(input)),
                           std::istreambuf_iterator<char>());
  if (!input.good() && !input.eof()) obj_fail(path, "failed while reading file");

  tinyobj::ObjReaderConfig config;
  config.triangulate = true;
  config.vertex_color = false;
  tinyobj::ObjReader reader;
  // ParseFromString intentionally ignores mtllib lines. The typed SceneBuilder
  // remains the sole source of material, texture, and face-sidedness data.
  if (!reader.ParseFromString(source, std::string{}, config)) {
    const std::string detail = reader.Error().empty()
                                   ? "could not parse file"
                                   : reader.Error();
    obj_fail(path, detail);
  }

  const tinyobj::attrib_t& attributes = reader.GetAttrib();
  validate_attribute_layout(path, attributes);
  const std::size_t position_count = attributes.vertices.size() / 3;
  const std::size_t normal_count = attributes.normals.size() / 3;
  const std::size_t texcoord_count = attributes.texcoords.size() / 2;

  std::vector<Face> faces;
  bool normals_complete = true;
  bool texcoords_complete = true;
  for (const tinyobj::shape_t& shape : reader.GetShapes()) {
    const tinyobj::mesh_t& mesh = shape.mesh;
    if (mesh.normal_indices.size() != mesh.vertex_indices.size() ||
        mesh.texcoord_indices.size() != mesh.vertex_indices.size()) {
      obj_fail(path, "shape '" + shape_name(shape) +
                         "' has inconsistent corner index arrays");
    }
    std::size_t offset = 0;
    for (std::size_t face_index = 0;
         face_index < mesh.num_face_vertices.size(); ++face_index) {
      const unsigned int vertex_count = mesh.num_face_vertices[face_index];
      const std::string context =
          "shape '" + shape_name(shape) + "' face " +
          std::to_string(face_index);
      if (vertex_count != 3)
        obj_fail(path, context + " was not triangulated");
      if (offset > mesh.vertex_indices.size() ||
          mesh.vertex_indices.size() - offset < 3)
        obj_fail(path, context + " has a truncated index list");

      Face face;
      face.context = context;
      face.smoothing_group =
          face_index < mesh.smoothing_group_ids.size()
              ? mesh.smoothing_group_ids[face_index]
              : 0u;
      for (std::size_t corner_index = 0; corner_index < 3; ++corner_index) {
        Corner& corner = face.corners[corner_index];
        corner.position = mesh.vertex_indices[offset + corner_index];
        corner.normal = mesh.normal_indices[offset + corner_index];
        corner.texcoord = mesh.texcoord_indices[offset + corner_index];
        check_index(path, corner.position, position_count, "position", context,
                    false);
        check_index(path, corner.normal, normal_count, "normal", context, true);
        check_index(path, corner.texcoord, texcoord_count, "texture coordinate",
                    context, true);
        normals_complete = normals_complete && corner.normal >= 0;
        texcoords_complete = texcoords_complete && corner.texcoord >= 0;
      }
      const Vec3 p0 = read_position(attributes, face.corners[0].position);
      const Vec3 p1 = read_position(attributes, face.corners[1].position);
      const Vec3 p2 = read_position(attributes, face.corners[2].position);
      if (!finite(p0) || !finite(p1) || !finite(p2))
        obj_fail(path, context + " contains a non-finite position");
      face.weighted_normal = cross(p1 - p0, p2 - p0);
      if (!finite(face.weighted_normal) ||
          length_squared(face.weighted_normal) <= 1.0e-20f)
        obj_fail(path, context + " is degenerate");
      faces.push_back(std::move(face));
      offset += 3;
    }
    if (offset != mesh.vertex_indices.size())
      obj_fail(path, "shape '" + shape_name(shape) +
                         "' contains unsupported non-face indices");
  }
  if (faces.empty()) obj_fail(path, "contains no triangle faces");

  std::unordered_map<SmoothKey, Vec3, SmoothKeyHash> smooth_normals;
  if (!normals_complete) {
    for (const Face& face : faces) {
      if (face.smoothing_group == 0) continue;
      for (const Corner& corner : face.corners) {
        smooth_normals[{corner.position, face.smoothing_group}] +=
            face.weighted_normal;
      }
    }
    for (auto& item : smooth_normals) {
      item.second = checked_unit_normal(
          path, item.second,
          "smoothing group " + std::to_string(item.first.group));
    }
  }

  TriangleMesh result;
  const std::size_t corner_count = faces.size() * 3;
  if (corner_count > std::numeric_limits<std::uint32_t>::max())
    obj_fail(path, "expanded vertex count exceeds uint32 range");
  result.positions.reserve(corner_count);
  result.normals.reserve(corner_count);
  result.indices.reserve(faces.size());
  if (texcoords_complete) result.texcoords.reserve(corner_count);

  for (const Face& face : faces) {
    const std::uint32_t base =
        static_cast<std::uint32_t>(result.positions.size());
    const Vec3 flat_normal = normalize(face.weighted_normal);
    for (const Corner& corner : face.corners) {
      result.positions.push_back(read_position(attributes, corner.position));
      if (normals_complete) {
        result.normals.push_back(checked_unit_normal(
            path, read_normal(attributes, corner.normal), face.context));
      } else if (face.smoothing_group == 0) {
        result.normals.push_back(flat_normal);
      } else {
        const auto it = smooth_normals.find(
            {corner.position, face.smoothing_group});
        if (it == smooth_normals.end())
          obj_fail(path, face.context + " has no generated smooth normal");
        result.normals.push_back(it->second);
      }
      if (texcoords_complete) {
        const Vec2 uv = read_texcoord(attributes, corner.texcoord);
        if (!std::isfinite(uv.x) || !std::isfinite(uv.y))
          obj_fail(path, face.context +
                             " contains a non-finite texture coordinate");
        // OBJ v remains bottom-origin. Device texture sampling performs the
        // single conversion to PNG's top-origin row convention.
        result.texcoords.push_back(uv);
      }
    }
    result.indices.push_back({base, base + 1u, base + 2u});
  }
  return result;
}

}  // namespace spectraldock
