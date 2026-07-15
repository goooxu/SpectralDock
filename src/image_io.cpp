#include "spectraldock/scene_types.h"

#include <png.h>

#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>

namespace spectraldock {
namespace {

std::runtime_error png_error(const char* operation,
                             const std::filesystem::path& path,
                             const png_image& image) {
  return std::runtime_error(std::string(operation) + " PNG '" + path.string() + "': " +
                            (image.message[0] ? image.message : "unknown libpng error"));
}

std::size_t checked_size(std::uint32_t width, std::uint32_t height) {
  if (width == 0 || height == 0) throw std::runtime_error("PNG dimensions must be non-zero");
  constexpr std::size_t channels = 4;
  if (static_cast<std::size_t>(width) >
      std::numeric_limits<std::size_t>::max() / channels / static_cast<std::size_t>(height)) {
    throw std::runtime_error("PNG dimensions overflow host address space");
  }
  return static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * channels;
}

}  // namespace

ImageRgba8 load_png_rgba8(const std::filesystem::path& path) {
  png_image image{};
  image.version = PNG_IMAGE_VERSION;
  const std::string native_path = path.string();
  if (!png_image_begin_read_from_file(&image, native_path.c_str())) {
    const auto error = png_error("cannot read", path, image);
    png_image_free(&image);
    throw error;
  }
  image.format = PNG_FORMAT_RGBA;
  ImageRgba8 result;
  result.width = image.width;
  result.height = image.height;
  result.pixels.resize(checked_size(result.width, result.height));
  if (!png_image_finish_read(&image, nullptr, result.pixels.data(), 0, nullptr)) {
    const auto error = png_error("cannot decode", path, image);
    png_image_free(&image);
    throw error;
  }
  png_image_free(&image);
  return result;
}

void write_png_rgba8(const std::filesystem::path& path,
                     std::uint32_t width,
                     std::uint32_t height,
                     const std::uint8_t* pixels,
                     std::size_t row_stride) {
  if (pixels == nullptr) throw std::runtime_error("cannot write PNG: pixel pointer is null");
  const std::size_t packed_stride = static_cast<std::size_t>(width) * 4u;
  (void)checked_size(width, height);
  if (row_stride == 0) row_stride = packed_stride;
  if (row_stride < packed_stride) throw std::runtime_error("cannot write PNG: row stride is too small");
  if (row_stride > static_cast<std::size_t>(std::numeric_limits<png_int_32>::max()))
    throw std::runtime_error("cannot write PNG: row stride exceeds libpng limit");

  png_image image{};
  image.version = PNG_IMAGE_VERSION;
  image.width = width;
  image.height = height;
  image.format = PNG_FORMAT_RGBA;
  const std::string native_path = path.string();
  if (!png_image_write_to_file(&image,
                               native_path.c_str(),
                               0,
                               pixels,
                               static_cast<png_int_32>(row_stride),
                               nullptr)) {
    const auto error = png_error("cannot write", path, image);
    png_image_free(&image);
    throw error;
  }
  png_image_free(&image);
}

void write_png_rgba8(const std::filesystem::path& path,
                     std::uint32_t width,
                     std::uint32_t height,
                     const std::vector<std::uint8_t>& pixels) {
  const std::size_t required = checked_size(width, height);
  if (pixels.size() != required)
    throw std::runtime_error("cannot write PNG: expected " + std::to_string(required) +
                             " RGBA bytes, got " + std::to_string(pixels.size()));
  write_png_rgba8(path, width, height, pixels.data(), 0);
}

void write_pfm_rgb32f(const std::filesystem::path& path,
                      std::uint32_t width,
                      std::uint32_t height,
                      const std::vector<float>& pixels) {
  static_assert(sizeof(float) == sizeof(std::uint32_t),
                "PFM output requires 32-bit float");
  static_assert(std::numeric_limits<float>::is_iec559,
                "PFM output requires IEEE-754 float");
  if (width == 0 || height == 0)
    throw std::runtime_error("PFM dimensions must be non-zero");
  constexpr std::size_t channels = 3;
  if (static_cast<std::size_t>(width) >
      std::numeric_limits<std::size_t>::max() / channels /
          static_cast<std::size_t>(height)) {
    throw std::runtime_error("PFM dimensions overflow host address space");
  }
  const std::size_t required = static_cast<std::size_t>(width) *
                               static_cast<std::size_t>(height) * channels;
  if (required > std::numeric_limits<std::size_t>::max() / sizeof(float))
    throw std::runtime_error("PFM dimensions overflow host address space");
  if (pixels.size() != required) {
    throw std::runtime_error("cannot write PFM: expected " +
                             std::to_string(required) + " RGB floats, got " +
                             std::to_string(pixels.size()));
  }
  for (const float value : pixels) {
    if (!std::isfinite(value))
      throw std::runtime_error("cannot write PFM: samples must be finite");
  }

  std::ofstream output(path, std::ios::binary);
  if (!output)
    throw std::runtime_error("cannot open PFM for writing: " + path.string());
  output << "PF\n" << width << ' ' << height << "\n-1.0\n";

  const std::size_t row_values = static_cast<std::size_t>(width) * channels;
  std::vector<std::uint8_t> row(row_values * sizeof(float));
  for (std::uint32_t source_y = height; source_y-- > 0;) {
    const float* source = pixels.data() +
                          static_cast<std::size_t>(source_y) * row_values;
    for (std::size_t i = 0; i < row_values; ++i) {
      std::uint32_t bits = 0;
      std::memcpy(&bits, source + i, sizeof(bits));
      const std::size_t offset = i * sizeof(bits);
      row[offset + 0] = static_cast<std::uint8_t>(bits);
      row[offset + 1] = static_cast<std::uint8_t>(bits >> 8u);
      row[offset + 2] = static_cast<std::uint8_t>(bits >> 16u);
      row[offset + 3] = static_cast<std::uint8_t>(bits >> 24u);
    }
    output.write(reinterpret_cast<const char*>(row.data()),
                 static_cast<std::streamsize>(row.size()));
  }
  if (!output)
    throw std::runtime_error("cannot write PFM: " + path.string());
}

}  // namespace spectraldock
