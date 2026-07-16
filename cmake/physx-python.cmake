# GPU-only PhysX subprocess used by spectraldock.physics.
#
# Include this file only after finding PhysX::SDK and CUDAToolkit 12.8.  Keeping
# this target in a separate fragment makes the CUDA-12.8 process boundary
# explicit; it must never be linked into the CUDA-13.x renderer extension.

if(TARGET spectraldock_physx_worker)
  return()
endif()

if(NOT TARGET PhysX::SDK)
  message(FATAL_ERROR
    "cmake/physx-python.cmake requires the imported PhysX::SDK target")
endif()
if(NOT TARGET CUDA::cudart OR NOT TARGET CUDA::cuda_driver)
  message(FATAL_ERROR
    "cmake/physx-python.cmake requires CUDAToolkit 12.8")
endif()
if(NOT CUDAToolkit_VERSION MATCHES "^12\\.8(\\.|$)")
  message(FATAL_ERROR
    "spectraldock_physx_worker must be built with CUDA Toolkit 12.8 exactly; "
    "found ${CUDAToolkit_VERSION}")
endif()

add_executable(spectraldock_physx_worker
  "${PROJECT_SOURCE_DIR}/tools/physx_worker.cpp")
target_link_libraries(spectraldock_physx_worker PRIVATE
  PhysX::SDK
  CUDA::cudart
  CUDA::cuda_driver)
target_compile_features(spectraldock_physx_worker PRIVATE cxx_std_17)
target_compile_options(spectraldock_physx_worker PRIVATE
  -Wall -Wextra -Wpedantic)
