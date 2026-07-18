cmake_minimum_required(VERSION 3.28)
project(SpectralDock VERSION 0.2.0 LANGUAGES C CXX)

option(SPECTRALDOCK_ENABLE_GPU "Build the CUDA/OptiX renderer" ON)
option(SPECTRALDOCK_ENABLE_VALIDATION "Enable OptiX validation by default" OFF)
option(SPECTRALDOCK_ENABLE_PHYSX_SCENE
  "Build the optional NVIDIA PhysX GPU worker" OFF)
if(SPECTRALDOCK_ENABLE_GPU AND SPECTRALDOCK_ENABLE_PHYSX_SCENE)
  message(FATAL_ERROR
    "Build the OptiX extension and PhysX worker in separate build trees; "
    "they intentionally use different CUDA toolkits")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CTest)
if(NOT SPECTRALDOCK_ENABLE_PHYSX_SCENE)
include(FetchContent)
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

# Keep the raster I/O stack identical on every supported host architecture.
# libavif's LOCAL AOM backend has runtime CPU dispatch enabled, so this does
# not bake the build host's ISA into the resulting renderer.
set(AVIF_CODEC_AOM LOCAL CACHE STRING "libavif AOM backend" FORCE)
set(AVIF_LIBYUV OFF CACHE STRING "Disable optional libyuv" FORCE)
set(AVIF_LIBSHARPYUV OFF CACHE STRING "Disable optional libsharpyuv" FORCE)
set(AVIF_JPEG OFF CACHE STRING "Disable JPEG support" FORCE)
set(AVIF_ZLIBPNG OFF CACHE STRING "Disable PNG support" FORCE)
set(AVIF_BUILD_APPS OFF CACHE BOOL "Do not build libavif applications" FORCE)
set(AVIF_BUILD_EXAMPLES OFF CACHE BOOL "Do not build libavif examples" FORCE)
set(AVIF_BUILD_TESTS OFF CACHE BOOL "Do not build libavif tests" FORCE)
set(AVIF_ENABLE_WERROR OFF CACHE BOOL "Do not inherit libavif warnings" FORCE)
FetchContent_Declare(libavif
  GIT_REPOSITORY https://github.com/AOMediaCodec/libavif.git
  GIT_TAG c5240fc79fe5c2407e10afd35f5505ef6333ea49
  GIT_SHALLOW FALSE)
FetchContent_MakeAvailable(libavif)

add_library(spectraldock_core STATIC
  src/scene.cpp
  src/scene_builder.cpp
  src/sampling.cpp
  src/obj_loader.cpp
  src/image_io.cpp
  third_party/mikktspace/mikktspace.c
)
set_target_properties(spectraldock_core PROPERTIES
  C_STANDARD 11
  C_STANDARD_REQUIRED ON
  POSITION_INDEPENDENT_CODE ON)
target_include_directories(spectraldock_core PUBLIC include)
target_include_directories(spectraldock_core SYSTEM PRIVATE
  third_party/mikktspace
  third_party/tinyobjloader)
target_link_libraries(spectraldock_core PUBLIC avif)
target_compile_options(spectraldock_core PRIVATE -Wall -Wextra -Wpedantic)

# Keep the Python package and the extension in one import root.  This also
# makes a configured build self-contained: PYTHONPATH only needs build/python.
file(COPY "${CMAKE_CURRENT_SOURCE_DIR}/python/spectraldock"
  DESTINATION "${CMAKE_CURRENT_BINARY_DIR}/python")

pybind11_add_module(_native MODULE src/python_bindings.cpp)
set_target_properties(_native PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/python/spectraldock")
target_include_directories(_native PRIVATE include)
target_link_libraries(_native PRIVATE spectraldock_core)
target_compile_definitions(_native PRIVATE
  SPECTRALDOCK_ENABLE_GPU=$<BOOL:${SPECTRALDOCK_ENABLE_GPU}>)
target_compile_options(_native PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(SPECTRALDOCK_ENABLE_PHYSX_SCENE)
  list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
  set(_spectraldock_physx_root_default "/opt/physx")
  if(DEFINED ENV{PHYSX_ROOT} AND NOT "$ENV{PHYSX_ROOT}" STREQUAL "")
    set(_spectraldock_physx_root_default "$ENV{PHYSX_ROOT}")
  endif()
  set(PHYSX_ROOT "${_spectraldock_physx_root_default}" CACHE PATH
    "Installed NVIDIA PhysX SDK root")
  unset(_spectraldock_physx_root_default)
  set(PHYSX_BUILD_TYPE "checked" CACHE STRING
    "PhysX library configuration")
  set_property(CACHE PHYSX_BUILD_TYPE PROPERTY STRINGS
    debug checked profile release)

  find_package(PhysX 5.8 REQUIRED MODULE)
  find_package(CUDAToolkit 12.8 REQUIRED)
  include(cmake/physx-python.cmake)
endif()

if(SPECTRALDOCK_ENABLE_GPU)
  enable_language(CUDA)
  find_package(CUDAToolkit 13.0 REQUIRED)

  set(OptiX_ROOT "/opt/optix" CACHE PATH "Extracted NVIDIA OptiX SDK root")
  find_path(OPTIX_INCLUDE_DIR optix.h
    HINTS "${OptiX_ROOT}/include"
    REQUIRED
    NO_DEFAULT_PATH)

  # Ship virtual PTX instead of GPU-specific SASS.  Use the oldest virtual
  # architecture understood by the selected CUDA toolkit, which maximizes
  # the set of GPUs that can JIT the module without inspecting or assuming a
  # device model. PTX also keeps module loading on the portable driver JIT path
  # while preserving the exact same OptiX programs.
  execute_process(
    COMMAND "${CMAKE_CUDA_COMPILER}" --list-gpu-arch
    OUTPUT_VARIABLE SPECTRALDOCK_CUDA_VIRTUAL_ARCHITECTURES
    RESULT_VARIABLE SPECTRALDOCK_CUDA_ARCH_LIST_RESULT
    OUTPUT_STRIP_TRAILING_WHITESPACE)
  if(NOT SPECTRALDOCK_CUDA_ARCH_LIST_RESULT EQUAL 0)
    message(FATAL_ERROR
      "nvcc --list-gpu-arch failed; cannot select a portable PTX target")
  endif()
  string(REGEX MATCHALL "compute_[0-9]+"
    SPECTRALDOCK_PTX_VIRTUAL_ARCHITECTURES
    "${SPECTRALDOCK_CUDA_VIRTUAL_ARCHITECTURES}")
  if(NOT SPECTRALDOCK_PTX_VIRTUAL_ARCHITECTURES)
    message(FATAL_ERROR
      "nvcc did not report a supported virtual PTX architecture")
  endif()
  list(REMOVE_DUPLICATES SPECTRALDOCK_PTX_VIRTUAL_ARCHITECTURES)
  list(SORT SPECTRALDOCK_PTX_VIRTUAL_ARCHITECTURES
    COMPARE NATURAL ORDER ASCENDING)
  list(GET SPECTRALDOCK_PTX_VIRTUAL_ARCHITECTURES 0
    SPECTRALDOCK_PTX_VIRTUAL_ARCH)
  message(STATUS
    "Portable OptiX PTX baseline: ${SPECTRALDOCK_PTX_VIRTUAL_ARCH}")

  set(OPTIX_MODULE_INPUT
    "${CMAKE_CURRENT_BINARY_DIR}/device_programs.ptx")
  add_custom_command(
    OUTPUT "${OPTIX_MODULE_INPUT}"
    COMMAND "${CMAKE_CUDA_COMPILER}"
      --ptx
      "--gpu-architecture=${SPECTRALDOCK_PTX_VIRTUAL_ARCH}"
      --std=c++17 --use_fast_math -lineinfo
      -I"${CMAKE_CURRENT_SOURCE_DIR}/include"
      -I"${OPTIX_INCLUDE_DIR}"
      "${CMAKE_CURRENT_SOURCE_DIR}/src/device_programs.cu"
      -o "${OPTIX_MODULE_INPUT}"
    DEPENDS
      src/device_programs.cu
      include/spectraldock/device_types.h
    VERBATIM)
  add_custom_target(spectraldock_device_module_input
    DEPENDS "${OPTIX_MODULE_INPUT}")

  target_sources(_native PRIVATE src/optix_renderer.cpp)
  target_include_directories(_native PRIVATE "${OPTIX_INCLUDE_DIR}")
  target_link_libraries(_native PRIVATE
    CUDA::cudart
    CUDA::cuda_driver
    CUDA::nvtx3
    ${CMAKE_DL_LIBS})
  target_compile_definitions(_native PRIVATE
    SPECTRALDOCK_OPTIX_MODULE_INPUT_PATH="${OPTIX_MODULE_INPUT}"
    SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT=$<BOOL:${SPECTRALDOCK_ENABLE_VALIDATION}>)
  add_dependencies(_native spectraldock_device_module_input)
endif()

if(BUILD_TESTING AND NOT SPECTRALDOCK_ENABLE_PHYSX_SCENE)
  add_executable(spectraldock_tests tests/test_core.cpp)
  target_include_directories(spectraldock_tests PRIVATE include)
  target_link_libraries(spectraldock_tests PRIVATE spectraldock_core)
  target_compile_options(spectraldock_tests PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME core COMMAND spectraldock_tests)
endif()
