#pragma once

#include "spectraldock/scene_types.h"

#include <filesystem>
#include <string>
#include <vector>

namespace spectraldock {

// Loads every OBJ shape/group into one indexed triangle mesh. MTL declarations
// and usemtl assignments are deliberately ignored; Renderer handles own
// material bindings.
TriangleMesh load_obj_mesh(const std::filesystem::path& path);

// Loads the OBJ together with its sibling MTL declarations and returns the
// resolved usemtl name for every output triangle. Every face must have a valid
// material assignment when this strict overload is used.
TriangleMesh load_obj_mesh(
    const std::filesystem::path& path,
    std::vector<std::string>& triangle_material_names);

}  // namespace spectraldock
