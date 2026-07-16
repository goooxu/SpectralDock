#pragma once

#include "spectraldock/scene_types.h"

#include <filesystem>

namespace spectraldock {

// Loads every OBJ shape/group into one indexed triangle mesh. MTL declarations
// and usemtl assignments are deliberately ignored; Renderer handles own
// material bindings.
TriangleMesh load_obj_mesh(const std::filesystem::path& path);

}  // namespace spectraldock
