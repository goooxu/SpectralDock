cmake_minimum_required(VERSION 3.28)
project(SpectralDock VERSION 0.1.0 LANGUAGES CXX)

option(SPECTRALDOCK_ENABLE_GPU "Build the CUDA/OptiX renderer" ON)
option(SPECTRALDOCK_ENABLE_VALIDATION "Enable OptiX validation by default" OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CTest)
find_package(PNG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)

add_library(spectraldock_core STATIC
  src/scene.cpp
  src/obj_loader.cpp
  src/image_io.cpp
)
target_include_directories(spectraldock_core PUBLIC include)
target_include_directories(spectraldock_core SYSTEM PRIVATE third_party/tinyobjloader)
target_link_libraries(spectraldock_core PUBLIC PNG::PNG nlohmann_json::nlohmann_json)
target_compile_options(spectraldock_core PRIVATE -Wall -Wextra -Wpedantic)

if(SPECTRALDOCK_ENABLE_GPU)
  enable_language(CUDA)
  find_package(CUDAToolkit 13.0 REQUIRED)

  set(OptiX_ROOT "/opt/optix" CACHE PATH "Extracted NVIDIA OptiX SDK root")
  find_path(OPTIX_INCLUDE_DIR optix.h
    HINTS "${OptiX_ROOT}/include"
    REQUIRED
    NO_DEFAULT_PATH)

  set(OPTIX_IR "${CMAKE_CURRENT_BINARY_DIR}/device_programs.optixir")
  add_custom_command(
    OUTPUT "${OPTIX_IR}"
    COMMAND "${CMAKE_CUDA_COMPILER}"
      --optix-ir --std=c++17 --use_fast_math -lineinfo
      -I"${CMAKE_CURRENT_SOURCE_DIR}/include"
      -I"${OPTIX_INCLUDE_DIR}"
      -DSPECTRALDOCK_DEVICE_CODE=1
      "${CMAKE_CURRENT_SOURCE_DIR}/src/device_programs.cu"
      -o "${OPTIX_IR}"
    DEPENDS
      src/device_programs.cu
      include/spectraldock/device_types.h
      include/spectraldock/integrator_policy.h
      include/spectraldock/math.h
    VERBATIM)
  add_custom_target(spectraldock_device_ir DEPENDS "${OPTIX_IR}")

  add_library(spectraldock_postprocess STATIC src/postprocess.cu)
  target_include_directories(spectraldock_postprocess PUBLIC include)
  set_target_properties(spectraldock_postprocess PROPERTIES
    CUDA_STANDARD 17
    CUDA_STANDARD_REQUIRED ON
    CUDA_ARCHITECTURES "75;86;89;120")

  add_executable(spectraldock
    src/main.cpp
    src/optix_renderer.cpp
  )
  target_include_directories(spectraldock PRIVATE include "${OPTIX_INCLUDE_DIR}")
  target_link_libraries(spectraldock PRIVATE
    spectraldock_core
    spectraldock_postprocess
    CUDA::cudart
    CUDA::cuda_driver
    CUDA::nvtx3
    ${CMAKE_DL_LIBS})
  target_compile_definitions(spectraldock PRIVATE
    SPECTRALDOCK_OPTIX_IR_PATH="${OPTIX_IR}"
    SPECTRALDOCK_ENABLE_VALIDATION_DEFAULT=$<BOOL:${SPECTRALDOCK_ENABLE_VALIDATION}>)
  add_dependencies(spectraldock spectraldock_device_ir)
  target_compile_options(spectraldock PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(BUILD_TESTING)
  add_executable(spectraldock_tests tests/test_core.cpp)
  target_include_directories(spectraldock_tests PRIVATE include)
  target_link_libraries(spectraldock_tests PRIVATE spectraldock_core)
  target_compile_options(spectraldock_tests PRIVATE -Wall -Wextra -Wpedantic)
  add_test(NAME core COMMAND spectraldock_tests)
  add_test(NAME shipped_scenes COMMAND spectraldock_tests
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/scenes/smoke.json"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/scenes/light-shapes-smoke.json"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/scenes/geometry-smoke.json"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/scenes/mesh-composite-smoke.json")
endif()
