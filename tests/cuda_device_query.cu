#include <cuda_runtime.h>

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void check(cudaError_t status, const char* operation) {
  if (status != cudaSuccess) {
    throw std::runtime_error(std::string(operation) + ": " +
                             cudaGetErrorString(status));
  }
}

__global__ void smoke_kernel(unsigned int* value) {
  if (blockIdx.x == 0 && threadIdx.x == 0) {
    *value = 0x5090u;
  }
}

}  // namespace

int main() {
  try {
    int device = 0;
    check(cudaGetDevice(&device), "cudaGetDevice");
    cudaDeviceProp properties{};
    check(cudaGetDeviceProperties(&properties, device),
          "cudaGetDeviceProperties");

    unsigned int* device_value = nullptr;
    check(cudaMalloc(&device_value, sizeof(*device_value)), "cudaMalloc");
    smoke_kernel<<<1, 32>>>(device_value);
    check(cudaGetLastError(), "smoke_kernel launch");
    check(cudaDeviceSynchronize(), "cudaDeviceSynchronize");
    unsigned int value = 0;
    check(cudaMemcpy(&value, device_value, sizeof(value),
                     cudaMemcpyDeviceToHost),
          "cudaMemcpy");
    check(cudaFree(device_value), "cudaFree");
    if (value != 0x5090u) {
      throw std::runtime_error("CUDA smoke kernel returned the wrong value");
    }

    std::cout << properties.name << "\ncompute capability "
              << properties.major << '.' << properties.minor
              << "\nglobal memory " << properties.totalGlobalMem
              << " bytes\nCUDA kernel smoke passed\n";
    return EXIT_SUCCESS;
  } catch (const std::exception& error) {
    std::cerr << "error: " << error.what() << '\n';
    return EXIT_FAILURE;
  }
}
