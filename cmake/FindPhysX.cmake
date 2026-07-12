# Locate an installed NVIDIA PhysX SDK built with the SpectralDock GPU preset.
#
# Inputs:
#   PHYSX_ROOT       Installed SDK root (include/ and bin/linux.x86_64/).
#   PHYSX_BUILD_TYPE debug, checked, profile, or release.
#
# Result target:
#   PhysX::SDK       Static CPU SDK libraries plus pthread/dl. The GPU runtime
#                    remains dynamically loaded by PhysX from libPhysXGpu_64.so.

include(FindPackageHandleStandardArgs)

if(NOT PHYSX_ROOT)
  set(PHYSX_ROOT "$ENV{PHYSX_ROOT}")
endif()
if(NOT PHYSX_ROOT)
  set(PHYSX_ROOT "/opt/physx")
endif()
if(NOT PHYSX_BUILD_TYPE)
  set(PHYSX_BUILD_TYPE "checked")
endif()

set(_PhysX_valid_build_types debug checked profile release)
if(NOT PHYSX_BUILD_TYPE IN_LIST _PhysX_valid_build_types)
  message(FATAL_ERROR
    "PHYSX_BUILD_TYPE must be one of: debug, checked, profile, release")
endif()

set(PhysX_LIBRARY_DIR
  "${PHYSX_ROOT}/bin/linux.x86_64/${PHYSX_BUILD_TYPE}")

find_path(PhysX_INCLUDE_DIR
  NAMES PxPhysicsAPI.h
  HINTS "${PHYSX_ROOT}/include"
  NO_DEFAULT_PATH)
find_file(PhysX_CONFIG_HEADER
  NAMES PxConfig.h
  HINTS "${PHYSX_ROOT}/include"
  NO_DEFAULT_PATH)

find_library(PhysX_EXTENSIONS_LIBRARY
  NAMES PhysXExtensions_static_64
  HINTS "${PhysX_LIBRARY_DIR}"
  NO_DEFAULT_PATH)
find_library(PhysX_CORE_LIBRARY
  NAMES PhysX_static_64
  HINTS "${PhysX_LIBRARY_DIR}"
  NO_DEFAULT_PATH)
find_library(PhysX_PVD_LIBRARY
  NAMES PhysXPvdSDK_static_64
  HINTS "${PhysX_LIBRARY_DIR}"
  NO_DEFAULT_PATH)
find_library(PhysX_COOKING_LIBRARY
  NAMES PhysXCooking_static_64
  HINTS "${PhysX_LIBRARY_DIR}"
  NO_DEFAULT_PATH)
find_library(PhysX_COMMON_LIBRARY
  NAMES PhysXCommon_static_64
  HINTS "${PhysX_LIBRARY_DIR}"
  NO_DEFAULT_PATH)
find_library(PhysX_FOUNDATION_LIBRARY
  NAMES PhysXFoundation_static_64
  HINTS "${PhysX_LIBRARY_DIR}"
  NO_DEFAULT_PATH)
find_file(PhysX_GPU_LIBRARY
  NAMES libPhysXGpu_64.so
  HINTS "${PhysX_LIBRARY_DIR}"
  NO_DEFAULT_PATH)

if(PhysX_INCLUDE_DIR AND EXISTS "${PhysX_INCLUDE_DIR}/foundation/PxPhysicsVersion.h")
  file(STRINGS "${PhysX_INCLUDE_DIR}/foundation/PxPhysicsVersion.h"
    _PhysX_version_lines
    REGEX "^#define PX_PHYSICS_VERSION_(MAJOR|MINOR|BUGFIX)[ \t]+[0-9]+")
  foreach(_part MAJOR MINOR BUGFIX)
    foreach(_line IN LISTS _PhysX_version_lines)
      if(_line MATCHES "PX_PHYSICS_VERSION_${_part}[ \t]+([0-9]+)")
        set(_PhysX_version_${_part} "${CMAKE_MATCH_1}")
      endif()
    endforeach()
  endforeach()
  if(DEFINED _PhysX_version_MAJOR AND DEFINED _PhysX_version_MINOR AND
     DEFINED _PhysX_version_BUGFIX)
    set(PhysX_VERSION
      "${_PhysX_version_MAJOR}.${_PhysX_version_MINOR}.${_PhysX_version_BUGFIX}")
  endif()
endif()

find_package_handle_standard_args(PhysX
  REQUIRED_VARS
    PhysX_INCLUDE_DIR
    PhysX_CONFIG_HEADER
    PhysX_EXTENSIONS_LIBRARY
    PhysX_CORE_LIBRARY
    PhysX_PVD_LIBRARY
    PhysX_COOKING_LIBRARY
    PhysX_COMMON_LIBRARY
    PhysX_FOUNDATION_LIBRARY
    PhysX_GPU_LIBRARY
  VERSION_VAR PhysX_VERSION)

if(PhysX_FOUND AND NOT TARGET PhysX::SDK)
  find_package(Threads REQUIRED)

  add_library(PhysX::Extensions STATIC IMPORTED)
  set_target_properties(PhysX::Extensions PROPERTIES
    IMPORTED_LOCATION "${PhysX_EXTENSIONS_LIBRARY}")
  add_library(PhysX::PhysX STATIC IMPORTED)
  set_target_properties(PhysX::PhysX PROPERTIES
    IMPORTED_LOCATION "${PhysX_CORE_LIBRARY}")
  add_library(PhysX::PvdSDK STATIC IMPORTED)
  set_target_properties(PhysX::PvdSDK PROPERTIES
    IMPORTED_LOCATION "${PhysX_PVD_LIBRARY}")
  add_library(PhysX::Cooking STATIC IMPORTED)
  set_target_properties(PhysX::Cooking PROPERTIES
    IMPORTED_LOCATION "${PhysX_COOKING_LIBRARY}")
  add_library(PhysX::Common STATIC IMPORTED)
  set_target_properties(PhysX::Common PROPERTIES
    IMPORTED_LOCATION "${PhysX_COMMON_LIBRARY}")
  add_library(PhysX::Foundation STATIC IMPORTED)
  set_target_properties(PhysX::Foundation PROPERTIES
    IMPORTED_LOCATION "${PhysX_FOUNDATION_LIBRARY}")

  add_library(PhysX::SDK INTERFACE IMPORTED)
  set_target_properties(PhysX::SDK PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES "${PhysX_INCLUDE_DIR}"
    INTERFACE_COMPILE_DEFINITIONS "PX_PHYSX_STATIC_LIB"
    INTERFACE_LINK_LIBRARIES
      "$<LINK_GROUP:RESCAN,PhysX::Extensions,PhysX::PhysX,PhysX::PvdSDK,PhysX::Cooking,PhysX::Common,PhysX::Foundation>;Threads::Threads;${CMAKE_DL_LIBS}")
endif()

mark_as_advanced(
  PhysX_INCLUDE_DIR
  PhysX_CONFIG_HEADER
  PhysX_EXTENSIONS_LIBRARY
  PhysX_CORE_LIBRARY
  PhysX_PVD_LIBRARY
  PhysX_COOKING_LIBRARY
  PhysX_COMMON_LIBRARY
  PhysX_FOUNDATION_LIBRARY
  PhysX_GPU_LIBRARY)
