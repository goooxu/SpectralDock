cmake_minimum_required(VERSION 3.28)
project(SpectralDock VERSION 0.1.0 LANGUAGES C CXX)

option(SPECTRALDOCK_ENABLE_GPU "Build the CUDA/OptiX renderer" ON)
option(SPECTRALDOCK_ENABLE_VALIDATION "Enable OptiX validation by default" OFF)
option(SPECTRALDOCK_ENABLE_PHYSX_SCENE
  "Build the optional NVIDIA PhysX GPU worker" OFF)
set(SPECTRALDOCK_OPTIX_MODULE_FORMAT "optixir" CACHE STRING
  "OptiX device module input format: optixir or ptx")
set_property(CACHE SPECTRALDOCK_OPTIX_MODULE_FORMAT PROPERTY STRINGS
  optixir ptx)
if(NOT SPECTRALDOCK_OPTIX_MODULE_FORMAT STREQUAL "optixir" AND
   NOT SPECTRALDOCK_OPTIX_MODULE_FORMAT STREQUAL "ptx")
  message(FATAL_ERROR
    "SPECTRALDOCK_OPTIX_MODULE_FORMAT must be exactly 'optixir' or 'ptx' "
    "(got '${SPECTRALDOCK_OPTIX_MODULE_FORMAT}')")
endif()

if(SPECTRALDOCK_ENABLE_GPU AND SPECTRALDOCK_ENABLE_PHYSX_SCENE)
  message(FATAL_ERROR
    "Build the OptiX extension and PhysX worker in separate build trees; "
    "they intentionally use different CUDA toolkits")
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CTest)
find_package(PNG REQUIRED)
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(pybind11 CONFIG REQUIRED)

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
target_link_libraries(spectraldock_core PUBLIC PNG::PNG)
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

if(SPECTRALDOCK_ENABLE_PHYSX_SCENE)
  list(PREPEND CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/cmake")
  set(PHYSX_ROOT "/opt/physx" CACHE PATH
    "Installed NVIDIA PhysX SDK root")
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

  if(SPECTRALDOCK_OPTIX_MODULE_FORMAT STREQUAL "optixir")
    set(OPTIX_MODULE_COMPILE_FLAG --optix-ir)
    set(OPTIX_MODULE_INPUT
      "${CMAKE_CURRENT_BINARY_DIR}/device_programs.optixir")
  else()
    set(OPTIX_MODULE_COMPILE_FLAG --ptx)
    set(OPTIX_MODULE_INPUT "${CMAKE_CURRENT_BINARY_DIR}/device_programs.ptx")
  endif()
  add_custom_command(
    OUTPUT "${OPTIX_MODULE_INPUT}"
    COMMAND "${CMAKE_CUDA_COMPILER}"
      "${OPTIX_MODULE_COMPILE_FLAG}" --std=c++17 --use_fast_math -lineinfo
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

  add_library(spectraldock_postprocess STATIC src/postprocess.cu)
  set_target_properties(spectraldock_postprocess PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "75;86;89;100;120"
    POSITION_INDEPENDENT_CODE ON)

  target_sources(_native PRIVATE src/optix_renderer.cpp)
  target_include_directories(_native PRIVATE "${OPTIX_INCLUDE_DIR}")
  target_link_libraries(_native PRIVATE
    spectraldock_postprocess
    CUDA::cudart
    CUDA::cuda_driver
    CUDA::nvtx3
    ${CMAKE_DL_LIBS})
  target_compile_definitions(_native PRIVATE
    SPECTRALDOCK_OPTIX_MODULE_INPUT_PATH="${OPTIX_MODULE_INPUT}"
    SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT=$<BOOL:${SPECTRALDOCK_ENABLE_VALIDATION}>)
  add_dependencies(_native spectraldock_device_module_input)
endif()

if(BUILD_TESTING)
  add_executable(spectraldock_tests tests/test_core.cpp)
  target_include_directories(spectraldock_tests PRIVATE include)
  target_link_libraries(spectraldock_tests PRIVATE spectraldock_core)
  target_compile_options(spectraldock_tests PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME core COMMAND spectraldock_tests)
endif()
