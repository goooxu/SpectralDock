#include "spectraldock/scene_types.h"

#include <png.h>

#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>

namespace spectraldock {
namespace {

std::runtime_error png_image_error(const char* operation,
                                   const std::filesystem::path& path,
                                   const png_image& image) {
  return std::runtime_error(std::string(operation) + " PNG '" + path.string() + "': " +
                            (image.message[0] ? image.message : "unknown libpng error"));
}

struct RawPngReadState {
  std::FILE* file = nullptr;
  png_structp png = nullptr;
  png_infop info = nullptr;
  png_bytep pixels = nullptr;
  png_bytep* rows = nullptr;
  char error[256]{};

  ~RawPngReadState() {
    if (png != nullptr) png_destroy_read_struct(&png, &info, nullptr);
    std::free(rows);
    std::free(pixels);
    if (file != nullptr) std::fclose(file);
  }
};

void PNGAPI raw_png_error(png_structp png, png_const_charp message) {
  auto* state = static_cast<RawPngReadState*>(png_get_error_ptr(png));
  if (state != nullptr) {
    const char* source = message != nullptr ? message : "unknown libpng error";
    std::strncpy(state->error, source, sizeof(state->error) - 1u);
    state->error[sizeof(state->error) - 1u] = '\0';
  }
  png_longjmp(png, 1);
}

void PNGAPI raw_png_warning(png_structp, png_const_charp) {}

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
  const std::string native_path = path.string();
  auto state = std::make_unique<RawPngReadState>();
  state->file = std::fopen(native_path.c_str(), "rb");
  if (state->file == nullptr) {
    const int file_error = errno;
    throw std::runtime_error("cannot read PNG '" + path.string() + "': " +
                             std::strerror(file_error));
  }

  state->png = png_create_read_struct(PNG_LIBPNG_VER_STRING, state.get(),
                                      raw_png_error, raw_png_warning);
  if (state->png == nullptr)
    throw std::runtime_error("cannot read PNG '" + path.string() +
                             "': cannot create libpng read state");
  state->info = png_create_info_struct(state->png);
  if (state->info == nullptr)
    throw std::runtime_error("cannot read PNG '" + path.string() +
                             "': cannot create libpng info state");

  if (setjmp(png_jmpbuf(state->png)) != 0) {
    throw std::runtime_error("cannot decode PNG '" + path.string() + "': " +
                             (state->error[0] != '\0'
                                  ? state->error
                                  : "unknown libpng error"));
  }

  png_init_io(state->png, state->file);
  png_read_info(state->png, state->info);

  const png_uint_32 width = png_get_image_width(state->png, state->info);
  const png_uint_32 height = png_get_image_height(state->png, state->info);
  const int bit_depth = png_get_bit_depth(state->png, state->info);
  const int color_type = png_get_color_type(state->png, state->info);
  const bool has_alpha = (color_type & PNG_COLOR_MASK_ALPHA) != 0;
  const bool has_transparency =
      png_get_valid(state->png, state->info, PNG_INFO_tRNS) != 0;

  if (bit_depth == 16) png_set_strip_16(state->png);
  if (color_type == PNG_COLOR_TYPE_PALETTE)
    png_set_palette_to_rgb(state->png);
  if (color_type == PNG_COLOR_TYPE_GRAY && bit_depth < 8)
    png_set_expand_gray_1_2_4_to_8(state->png);
  if (has_transparency) png_set_tRNS_to_alpha(state->png);
  if (color_type == PNG_COLOR_TYPE_GRAY ||
      color_type == PNG_COLOR_TYPE_GRAY_ALPHA)
    png_set_gray_to_rgb(state->png);
  if (!has_alpha && !has_transparency)
    png_set_add_alpha(state->png, 0xffu, PNG_FILLER_AFTER);

  // Deliberately do not install a gamma or ICC transform. Texture color
  // space is selected by SceneBuilder, so the loader must preserve PNG sample
  // codes and leave the single requested transfer conversion to the sampler.
  (void)png_set_interlace_handling(state->png);
  png_read_update_info(state->png, state->info);

  if (png_get_bit_depth(state->png, state->info) != 8 ||
      png_get_color_type(state->png, state->info) != PNG_COLOR_TYPE_RGB_ALPHA ||
      png_get_channels(state->png, state->info) != 4) {
    throw std::runtime_error("cannot decode PNG '" + path.string() +
                             "': unsupported transformed pixel format");
  }

  const std::size_t byte_count = checked_size(width, height);
  const std::size_t row_size = static_cast<std::size_t>(width) * 4u;
  if (png_get_rowbytes(state->png, state->info) != row_size)
    throw std::runtime_error("cannot decode PNG '" + path.string() +
                             "': unexpected transformed row size");
  if (static_cast<std::size_t>(height) >
      std::numeric_limits<std::size_t>::max() / sizeof(png_bytep))
    throw std::runtime_error("PNG dimensions overflow host address space");

  state->pixels = static_cast<png_bytep>(std::malloc(byte_count));
  state->rows = static_cast<png_bytep*>(
      std::malloc(static_cast<std::size_t>(height) * sizeof(png_bytep)));
  if (state->pixels == nullptr || state->rows == nullptr)
    throw std::runtime_error("cannot decode PNG '" + path.string() +
                             "': cannot allocate pixel storage");
  for (png_uint_32 y = 0; y < height; ++y)
    state->rows[y] = state->pixels + static_cast<std::size_t>(y) * row_size;

  png_read_image(state->png, state->rows);
  png_read_end(state->png, nullptr);

  ImageRgba8 result;
  result.width = width;
  result.height = height;
  result.pixels.assign(state->pixels, state->pixels + byte_count);
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
    const auto error = png_image_error("cannot write", path, image);
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
