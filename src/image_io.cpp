#include "spectraldock/scene_types.h"

#include <avif/avif.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace spectraldock {
namespace {

constexpr std::uint32_t kMaximumTextureDimension = 16384;
constexpr double kDiffuseWhiteNits = 203.0;
constexpr double kPeakNits = 1000.0;

struct DecoderDeleter {
  void operator()(avifDecoder* decoder) const noexcept {
    avifDecoderDestroy(decoder);
  }
};

struct EncoderDeleter {
  void operator()(avifEncoder* encoder) const noexcept {
    avifEncoderDestroy(encoder);
  }
};

struct ImageDeleter {
  void operator()(avifImage* image) const noexcept { avifImageDestroy(image); }
};

using DecoderPtr = std::unique_ptr<avifDecoder, DecoderDeleter>;
using EncoderPtr = std::unique_ptr<avifEncoder, EncoderDeleter>;
using ImagePtr = std::unique_ptr<avifImage, ImageDeleter>;

class RgbPixels {
 public:
  explicit RgbPixels(avifRGBImage& image) : image_(image) {
    const avifResult result = avifRGBImageAllocatePixels(&image_);
    if (result != AVIF_RESULT_OK) {
      throw std::runtime_error(
          std::string("cannot allocate AVIF RGB pixels: ") +
          avifResultToString(result));
    }
  }
  RgbPixels(const RgbPixels&) = delete;
  RgbPixels& operator=(const RgbPixels&) = delete;
  ~RgbPixels() { avifRGBImageFreePixels(&image_); }

 private:
  avifRGBImage& image_;
};

class RwData {
 public:
  avifRWData value = AVIF_DATA_EMPTY;
  RwData() = default;
  RwData(const RwData&) = delete;
  RwData& operator=(const RwData&) = delete;
  ~RwData() { avifRWDataFree(&value); }
};

[[noreturn]] void fail_avif(const std::string& operation,
                            const std::filesystem::path& path,
                            avifResult result) {
  throw std::runtime_error(operation + " AVIF '" + path.string() + "': " +
                           avifResultToString(result));
}

void require_avif_path(const std::filesystem::path& path) {
  if (path.extension() != ".avif") {
    throw std::runtime_error("AVIF path must use the lowercase .avif extension: " +
                             path.string());
  }
}

std::size_t checked_sample_count(std::uint32_t width, std::uint32_t height,
                                 std::size_t channels,
                                 const char* description) {
  if (width == 0 || height == 0) {
    throw std::runtime_error(std::string(description) +
                             " dimensions must be non-zero");
  }
  if (width > kMaximumTextureDimension ||
      height > kMaximumTextureDimension) {
    throw std::runtime_error(std::string(description) +
                             " dimensions exceed the 16384-pixel limit");
  }
  if (static_cast<std::size_t>(width) >
      std::numeric_limits<std::size_t>::max() / channels /
          static_cast<std::size_t>(height)) {
    throw std::runtime_error(std::string(description) +
                             " dimensions overflow host address space");
  }
  return static_cast<std::size_t>(width) * height * channels;
}

std::uint32_t encoder_thread_count() {
  const unsigned int available = std::thread::hardware_concurrency();
  return std::max(1u, std::min(available == 0 ? 1u : available, 16u));
}

EncoderPtr make_encoder() {
  EncoderPtr encoder(avifEncoderCreate());
  if (!encoder) throw std::runtime_error("cannot create AVIF encoder");
  encoder->codecChoice = AVIF_CODEC_CHOICE_AOM;
  encoder->maxThreads = encoder_thread_count();
  encoder->speed = 6;
  encoder->quality = AVIF_QUALITY_LOSSLESS;
  encoder->qualityAlpha = AVIF_QUALITY_LOSSLESS;
  encoder->autoTiling = AVIF_TRUE;
  return encoder;
}

void write_bytes_atomically(const std::filesystem::path& path,
                            const std::uint8_t* data, std::size_t size) {
  if (data == nullptr || size == 0) {
    throw std::runtime_error("cannot write empty AVIF payload: " +
                             path.string());
  }
  if (!path.parent_path().empty()) {
    std::filesystem::create_directories(path.parent_path());
  }

  static std::atomic<std::uint64_t> serial{0};
  std::ostringstream temporary_name;
  temporary_name << '.' << path.filename().string() << '.'
                 << std::chrono::steady_clock::now().time_since_epoch().count()
                 << '.' << serial.fetch_add(1, std::memory_order_relaxed)
                 << ".tmp";
  const std::filesystem::path temporary =
      (path.parent_path().empty() ? std::filesystem::path(".")
                                  : path.parent_path()) /
      temporary_name.str();
  try {
    std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
    if (!output) {
      throw std::runtime_error("cannot open temporary AVIF for writing: " +
                               temporary.string());
    }
    output.write(reinterpret_cast<const char*>(data),
                 static_cast<std::streamsize>(size));
    output.close();
    if (!output) {
      throw std::runtime_error("cannot write temporary AVIF: " +
                               temporary.string());
    }
    std::filesystem::rename(temporary, path);
  } catch (...) {
    std::error_code ignored;
    std::filesystem::remove(temporary, ignored);
    throw;
  }
}

void encode_image(const std::filesystem::path& path, const avifImage* image) {
  EncoderPtr encoder = make_encoder();
  RwData output;
  const avifResult result =
      avifEncoderWrite(encoder.get(), image, &output.value);
  if (result != AVIF_RESULT_OK) fail_avif("cannot encode", path, result);
  write_bytes_atomically(path, output.value.data, output.value.size);
}

bool primaries_are_unspecified_or(avifColorPrimaries actual,
                                  avifColorPrimaries expected) {
  return actual == AVIF_COLOR_PRIMARIES_UNSPECIFIED || actual == expected;
}

bool transfer_is_unspecified_or(avifTransferCharacteristics actual,
                                avifTransferCharacteristics expected) {
  return actual == AVIF_TRANSFER_CHARACTERISTICS_UNSPECIFIED ||
         actual == expected;
}

void validate_texture_profile(const avifDecoder& decoder,
                              const std::filesystem::path& path, bool srgb) {
  const avifImage& image = *decoder.image;
  const auto reject = [&](const std::string& reason) {
    throw std::runtime_error("unsupported AVIF texture '" + path.string() +
                             "': " + reason);
  };
  if (decoder.imageCount != 1 || decoder.imageSequenceTrackPresent ||
      decoder.progressiveState != AVIF_PROGRESSIVE_STATE_UNAVAILABLE) {
    reject("animated or layered images are not supported");
  }
  if (image.width == 0 || image.height == 0 ||
      image.width > kMaximumTextureDimension ||
      image.height > kMaximumTextureDimension) {
    reject("dimensions must be in [1, 16384]");
  }
  if (image.depth != 8) reject("textures must be 8-bit");
  if (image.yuvFormat == AVIF_PIXEL_FORMAT_NONE ||
      image.yuvFormat == AVIF_PIXEL_FORMAT_YUV400) {
    reject("textures must contain RGB color planes");
  }
  if (image.transformFlags != AVIF_TRANSFORM_NONE) {
    reject("clean-aperture, rotation, and mirroring transforms are forbidden");
  }
  if (image.alphaPremultiplied) reject("premultiplied alpha is forbidden");
  if (image.icc.size != 0) reject("ICC profiles are forbidden");
  if (image.gainMap != nullptr) reject("gain maps are not supported");

  if (srgb) {
    if (!primaries_are_unspecified_or(image.colorPrimaries,
                                      AVIF_COLOR_PRIMARIES_BT709)) {
      reject("sRGB textures require BT.709 primaries");
    }
    if (!transfer_is_unspecified_or(image.transferCharacteristics,
                                    AVIF_TRANSFER_CHARACTERISTICS_SRGB)) {
      reject("sRGB textures require the sRGB transfer characteristic");
    }
    const avifMatrixCoefficients matrix = image.matrixCoefficients;
    if (matrix != AVIF_MATRIX_COEFFICIENTS_IDENTITY &&
        matrix != AVIF_MATRIX_COEFFICIENTS_BT709 &&
        matrix != AVIF_MATRIX_COEFFICIENTS_BT601 &&
        matrix != AVIF_MATRIX_COEFFICIENTS_UNSPECIFIED) {
      reject("sRGB texture matrix coefficients conflict with BT.709");
    }
  } else {
    if (image.yuvFormat != AVIF_PIXEL_FORMAT_YUV444 ||
        image.yuvRange != AVIF_RANGE_FULL ||
        image.matrixCoefficients != AVIF_MATRIX_COEFFICIENTS_IDENTITY ||
        image.transferCharacteristics !=
            AVIF_TRANSFER_CHARACTERISTICS_LINEAR ||
        image.colorPrimaries != AVIF_COLOR_PRIMARIES_BT709) {
      reject("linear textures require 8-bit YUV444 full-range, BT.709 "
             "primaries, linear transfer, and identity matrix");
    }
  }
}

double pq_encode(double nits) {
  constexpr double m1 = 2610.0 / 16384.0;
  constexpr double m2 = 2523.0 / 32.0;
  constexpr double c1 = 3424.0 / 4096.0;
  constexpr double c2 = 2413.0 / 128.0;
  constexpr double c3 = 2392.0 / 128.0;
  const double normalized = std::clamp(nits / 10000.0, 0.0, 1.0);
  const double powered = std::pow(normalized, m1);
  return std::pow((c1 + c2 * powered) / (1.0 + c3 * powered), m2);
}

std::uint16_t quantize_10bit(double value) {
  return static_cast<std::uint16_t>(
      std::clamp(std::floor(value * 1023.0 + 0.5), 0.0, 1023.0));
}

std::uint16_t quantize_chroma_10bit(double value) {
  // H.273 full-range chroma uses a 2^(bitDepth-1) neutral bias while its
  // signed excursion is scaled by 2^bitDepth-1, matching libavif reformat.c.
  return static_cast<std::uint16_t>(std::clamp(
      std::floor(value * 1023.0 + 512.5), 0.0, 1023.0));
}

std::uint16_t content_light_level(double value) {
  // CLLI fields are integer upper bounds; zero means "unknown" and causes
  // libavif to omit the property, so even an all-black known frame uses 1 nit.
  return static_cast<std::uint16_t>(
      std::clamp(std::ceil(value), 1.0, 65535.0));
}

}  // namespace

ImageRgba8 load_avif_rgba8(const std::filesystem::path& path, bool srgb) {
  require_avif_path(path);
  DecoderPtr decoder(avifDecoderCreate());
  if (!decoder) throw std::runtime_error("cannot create AVIF decoder");
  decoder->codecChoice = AVIF_CODEC_CHOICE_AOM;
  decoder->maxThreads = encoder_thread_count();
  decoder->imageDimensionLimit = kMaximumTextureDimension;
  decoder->strictFlags = AVIF_STRICT_ENABLED;
  const std::string native_path = path.string();
  avifResult result = avifDecoderSetIOFile(decoder.get(), native_path.c_str());
  if (result != AVIF_RESULT_OK) fail_avif("cannot open", path, result);
  result = avifDecoderParse(decoder.get());
  if (result != AVIF_RESULT_OK) fail_avif("cannot parse", path, result);
  if (decoder->imageCount != 1 || decoder->imageSequenceTrackPresent ||
      decoder->progressiveState != AVIF_PROGRESSIVE_STATE_UNAVAILABLE) {
    throw std::runtime_error("unsupported AVIF texture '" + path.string() +
                             "': animated or layered images are not supported");
  }
  result = avifDecoderNextImage(decoder.get());
  if (result != AVIF_RESULT_OK) fail_avif("cannot decode", path, result);
  validate_texture_profile(*decoder, path, srgb);

  avifRGBImage rgb;
  avifRGBImageSetDefaults(&rgb, decoder->image);
  rgb.format = AVIF_RGB_FORMAT_RGBA;
  rgb.depth = 8;
  RgbPixels pixels(rgb);
  result = avifImageYUVToRGB(decoder->image, &rgb);
  if (result != AVIF_RESULT_OK) fail_avif("cannot convert", path, result);

  ImageRgba8 output;
  output.width = rgb.width;
  output.height = rgb.height;
  const std::size_t count =
      checked_sample_count(output.width, output.height, 4, "AVIF texture");
  output.pixels.resize(count);
  const std::size_t packed_row = static_cast<std::size_t>(output.width) * 4u;
  for (std::uint32_t y = 0; y < output.height; ++y) {
    std::copy_n(rgb.pixels + static_cast<std::size_t>(y) * rgb.rowBytes,
                packed_row,
                output.pixels.data() + static_cast<std::size_t>(y) *
                                           packed_row);
  }
  return output;
}

DecodedAvif read_avif_rgba8(const std::filesystem::path& path) {
  require_avif_path(path);
  DecoderPtr decoder(avifDecoderCreate());
  if (!decoder) throw std::runtime_error("cannot create AVIF decoder");
  decoder->codecChoice = AVIF_CODEC_CHOICE_AOM;
  decoder->maxThreads = encoder_thread_count();
  decoder->imageDimensionLimit = kMaximumTextureDimension;
  decoder->strictFlags = AVIF_STRICT_ENABLED;
  const std::string native_path = path.string();
  avifResult result = avifDecoderSetIOFile(decoder.get(), native_path.c_str());
  if (result != AVIF_RESULT_OK) fail_avif("cannot open", path, result);
  result = avifDecoderParse(decoder.get());
  if (result != AVIF_RESULT_OK) fail_avif("cannot parse", path, result);
  const bool animated =
      decoder->imageCount != 1 || decoder->imageSequenceTrackPresent ||
      decoder->progressiveState != AVIF_PROGRESSIVE_STATE_UNAVAILABLE;
  result = avifDecoderNextImage(decoder.get());
  if (result != AVIF_RESULT_OK) fail_avif("cannot decode", path, result);

  avifRGBImage rgb;
  avifRGBImageSetDefaults(&rgb, decoder->image);
  rgb.format = AVIF_RGB_FORMAT_RGBA;
  rgb.depth = 8;
  RgbPixels pixels(rgb);
  result = avifImageYUVToRGB(decoder->image, &rgb);
  if (result != AVIF_RESULT_OK) fail_avif("cannot convert", path, result);

  DecodedAvif output;
  output.image.width = rgb.width;
  output.image.height = rgb.height;
  const std::size_t count = checked_sample_count(
      output.image.width, output.image.height, 4, "AVIF image");
  output.image.pixels.resize(count);
  const std::size_t packed_row =
      static_cast<std::size_t>(output.image.width) * 4u;
  for (std::uint32_t y = 0; y < output.image.height; ++y) {
    std::copy_n(rgb.pixels + static_cast<std::size_t>(y) * rgb.rowBytes,
                packed_row,
                output.image.pixels.data() +
                    static_cast<std::size_t>(y) * packed_row);
  }

  const avifImage& image = *decoder->image;
  output.info.bit_depth = image.depth;
  switch (image.yuvFormat) {
    case AVIF_PIXEL_FORMAT_YUV444: output.info.yuv_format = "4:4:4"; break;
    case AVIF_PIXEL_FORMAT_YUV422: output.info.yuv_format = "4:2:2"; break;
    case AVIF_PIXEL_FORMAT_YUV420: output.info.yuv_format = "4:2:0"; break;
    case AVIF_PIXEL_FORMAT_YUV400: output.info.yuv_format = "4:0:0"; break;
    case AVIF_PIXEL_FORMAT_NONE: output.info.yuv_format = "none"; break;
    case AVIF_PIXEL_FORMAT_COUNT: output.info.yuv_format = "invalid"; break;
  }
  output.info.full_range = image.yuvRange == AVIF_RANGE_FULL;
  output.info.color_primaries =
      static_cast<std::uint16_t>(image.colorPrimaries);
  output.info.transfer_characteristics =
      static_cast<std::uint16_t>(image.transferCharacteristics);
  output.info.matrix_coefficients =
      static_cast<std::uint16_t>(image.matrixCoefficients);
  output.info.premultiplied = image.alphaPremultiplied != AVIF_FALSE;
  output.info.animated = animated;
  output.info.has_alpha = image.alphaPlane != nullptr;
  output.info.max_cll = image.clli.maxCLL;
  output.info.max_pall = image.clli.maxPALL;
  return output;
}

void write_texture_avif_rgba8(const std::filesystem::path& path,
                              std::uint32_t width, std::uint32_t height,
                              const std::uint8_t* pixels, bool srgb,
                              std::size_t row_stride) {
  require_avif_path(path);
  if (pixels == nullptr) {
    throw std::runtime_error("cannot write AVIF texture: pixel pointer is null");
  }
  (void)checked_sample_count(width, height, 4, "AVIF texture");
  const std::size_t packed_row = static_cast<std::size_t>(width) * 4u;
  if (row_stride == 0) row_stride = packed_row;
  if (row_stride < packed_row ||
      row_stride > std::numeric_limits<std::uint32_t>::max()) {
    throw std::runtime_error("cannot write AVIF texture: invalid row stride");
  }

  ImagePtr image(avifImageCreate(width, height, 8,
                                 AVIF_PIXEL_FORMAT_YUV444));
  if (!image) throw std::runtime_error("cannot create AVIF texture image");
  image->colorPrimaries = AVIF_COLOR_PRIMARIES_BT709;
  image->transferCharacteristics =
      srgb ? AVIF_TRANSFER_CHARACTERISTICS_SRGB
           : AVIF_TRANSFER_CHARACTERISTICS_LINEAR;
  image->matrixCoefficients = AVIF_MATRIX_COEFFICIENTS_IDENTITY;
  image->yuvRange = AVIF_RANGE_FULL;
  image->alphaPremultiplied = AVIF_FALSE;

  avifRGBImage rgb;
  avifRGBImageSetDefaults(&rgb, image.get());
  rgb.format = AVIF_RGB_FORMAT_RGBA;
  rgb.depth = 8;
  bool has_non_opaque_alpha = false;
  for (std::uint32_t y = 0; y < height && !has_non_opaque_alpha; ++y) {
    const std::uint8_t* row =
        pixels + static_cast<std::size_t>(y) * row_stride;
    for (std::uint32_t x = 0; x < width; ++x) {
      if (row[static_cast<std::size_t>(x) * 4u + 3u] != 255u) {
        has_non_opaque_alpha = true;
        break;
      }
    }
  }
  // Opaque RGBA callers still produce an RGB-only AVIF item. Retain a real
  // alpha item only when at least one sample carries transparency.
  rgb.ignoreAlpha = has_non_opaque_alpha ? AVIF_FALSE : AVIF_TRUE;
  rgb.pixels = const_cast<std::uint8_t*>(pixels);
  rgb.rowBytes = static_cast<std::uint32_t>(row_stride);
  const avifResult result = avifImageRGBToYUV(image.get(), &rgb);
  if (result != AVIF_RESULT_OK) fail_avif("cannot convert", path, result);
  encode_image(path, image.get());
}

void write_texture_avif_rgba8(const std::filesystem::path& path,
                              std::uint32_t width, std::uint32_t height,
                              const std::vector<std::uint8_t>& pixels,
                              bool srgb) {
  require_avif_path(path);
  const std::size_t required =
      checked_sample_count(width, height, 4, "AVIF texture");
  if (pixels.size() != required) {
    throw std::runtime_error("cannot write AVIF texture: expected " +
                             std::to_string(required) + " RGBA bytes, got " +
                             std::to_string(pixels.size()));
  }
  write_texture_avif_rgba8(path, width, height, pixels.data(), srgb, 0);
}

HdrAvifInfo write_hdr_avif_rgb32f(const std::filesystem::path& path,
                                  std::uint32_t width,
                                  std::uint32_t height,
                                  const std::vector<float>& pixels,
                                  float exposure) {
  require_avif_path(path);
  if (!std::isfinite(exposure)) {
    throw std::runtime_error("HDR AVIF exposure must be finite");
  }
  const std::size_t required =
      checked_sample_count(width, height, 3, "HDR AVIF");
  if (pixels.size() != required) {
    throw std::runtime_error("cannot write HDR AVIF: expected " +
                             std::to_string(required) + " RGB floats, got " +
                             std::to_string(pixels.size()));
  }

  ImagePtr image(avifImageCreate(width, height, 10,
                                 AVIF_PIXEL_FORMAT_YUV444));
  if (!image) throw std::runtime_error("cannot create HDR AVIF image");
  image->colorPrimaries = AVIF_COLOR_PRIMARIES_BT2020;
  image->transferCharacteristics =
      AVIF_TRANSFER_CHARACTERISTICS_SMPTE2084;
  image->matrixCoefficients = AVIF_MATRIX_COEFFICIENTS_BT2020_NCL;
  image->yuvRange = AVIF_RANGE_FULL;
  avifResult result = avifImageAllocatePlanes(image.get(), AVIF_PLANES_YUV);
  if (result != AVIF_RESULT_OK) fail_avif("cannot allocate", path, result);

  const double multiplier =
      std::exp2(std::clamp(static_cast<double>(exposure), -128.0, 128.0));
  double maximum_light = 0.0;
  long double average_light_sum = 0.0;
  for (std::uint32_t y = 0; y < height; ++y) {
    auto* y_plane = reinterpret_cast<std::uint16_t*>(
        image->yuvPlanes[AVIF_CHAN_Y] +
        static_cast<std::size_t>(y) * image->yuvRowBytes[AVIF_CHAN_Y]);
    auto* u_plane = reinterpret_cast<std::uint16_t*>(
        image->yuvPlanes[AVIF_CHAN_U] +
        static_cast<std::size_t>(y) * image->yuvRowBytes[AVIF_CHAN_U]);
    auto* v_plane = reinterpret_cast<std::uint16_t*>(
        image->yuvPlanes[AVIF_CHAN_V] +
        static_cast<std::size_t>(y) * image->yuvRowBytes[AVIF_CHAN_V]);
    for (std::uint32_t x = 0; x < width; ++x) {
      const std::size_t offset =
          (static_cast<std::size_t>(y) * width + x) * 3u;
      const auto clean = [&](float sample) {
        return std::isfinite(sample) && sample > 0.0f
                   ? static_cast<double>(sample) * multiplier
                   : 0.0;
      };
      const double r709 = clean(pixels[offset + 0u]);
      const double g709 = clean(pixels[offset + 1u]);
      const double b709 = clean(pixels[offset + 2u]);

      // Linear-light Rec.709/sRGB primaries to Rec.2020 primaries.
      double r = 0.6274038959 * r709 + 0.3292830384 * g709 +
                 0.0433130657 * b709;
      double g = 0.0690972894 * r709 + 0.9195403951 * g709 +
                 0.0113623156 * b709;
      double b = 0.0163914389 * r709 + 0.0880133079 * g709 +
                 0.8955952532 * b709;
      const double maximum = std::max({r, g, b});
      if (maximum > 0.0) {
        const double mapped =
            maximum <= 1.0
                ? kDiffuseWhiteNits * maximum
                : kDiffuseWhiteNits +
                      (kPeakNits - kDiffuseWhiteNits) *
                          (1.0 - std::exp(-kDiffuseWhiteNits *
                                          (maximum - 1.0) /
                                          (kPeakNits - kDiffuseWhiteNits)));
        const double scale = mapped / maximum;
        r *= scale;
        g *= scale;
        b *= scale;
      }
      r = std::clamp(r, 0.0, kPeakNits);
      g = std::clamp(g, 0.0, kPeakNits);
      b = std::clamp(b, 0.0, kPeakNits);
      // CTA-861/H.274 CLLI uses the maximum linear-light primary at each
      // sample location (E_Max), not CIE weighted luminance. MaxCLL is the
      // largest E_Max and MaxPALL is the frame average of the same quantity.
      const double pixel_light = std::max({r, g, b});
      maximum_light = std::max(maximum_light, pixel_light);
      average_light_sum += pixel_light;

      // CICP 9/16/9 describes BT.2020 non-constant-luminance conversion
      // applied to nonlinear PQ component signals.
      const double rp = pq_encode(r);
      const double gp = pq_encode(g);
      const double bp = pq_encode(b);
      const double luma = 0.2627 * rp + 0.6780 * gp + 0.0593 * bp;
      const double chroma_blue = (bp - luma) / 1.8814;
      const double chroma_red = (rp - luma) / 1.4746;
      y_plane[x] = quantize_10bit(luma);
      u_plane[x] = quantize_chroma_10bit(chroma_blue);
      v_plane[x] = quantize_chroma_10bit(chroma_red);
    }
  }

  HdrAvifInfo info;
  info.max_cll = content_light_level(maximum_light);
  info.max_pall = content_light_level(static_cast<double>(
      average_light_sum / static_cast<long double>(width) /
      static_cast<long double>(height)));
  image->clli.maxCLL = info.max_cll;
  image->clli.maxPALL = info.max_pall;
  encode_image(path, image.get());
  return info;
}

}  // namespace spectraldock
