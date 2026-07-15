#include "spectraldock/sampling.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <fstream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace spectraldock {
namespace {

constexpr std::uint32_t kMaximumHdrWidth = 8192;
constexpr std::uint32_t kMaximumHdrHeight = 4096;
constexpr std::size_t kMaximumHdrPixels = std::size_t{1} << 25;
constexpr std::size_t kMaximumFiniteLights = 4096;

[[noreturn]] void hdr_error(const std::filesystem::path& path,
                            const std::string& message) {
  throw std::runtime_error("Radiance HDR " + path.string() + ": " + message);
}

std::uint8_t read_byte(std::istream& input,
                       const std::filesystem::path& path,
                       const char* context) {
  char byte = 0;
  if (!input.get(byte)) hdr_error(path, std::string("truncated ") + context);
  return static_cast<std::uint8_t>(static_cast<unsigned char>(byte));
}

void read_bytes(std::istream& input,
                std::uint8_t* destination,
                std::size_t count,
                const std::filesystem::path& path,
                const char* context) {
  if (count == 0) return;
  input.read(reinterpret_cast<char*>(destination),
             static_cast<std::streamsize>(count));
  if (input.gcount() != static_cast<std::streamsize>(count))
    hdr_error(path, std::string("truncated ") + context);
}

std::uint32_t parse_dimension(const std::string& token,
                              const std::filesystem::path& path,
                              const char* name,
                              std::uint32_t maximum) {
  std::uint64_t value = 0;
  const auto result =
      std::from_chars(token.data(), token.data() + token.size(), value);
  if (result.ec != std::errc{} || result.ptr != token.data() + token.size() ||
      value == 0 || value > maximum) {
    hdr_error(path, std::string(name) + " must be in [1, " +
                        std::to_string(maximum) + "]");
  }
  return static_cast<std::uint32_t>(value);
}

void decode_modern_scanline(std::istream& input,
                            std::vector<std::uint8_t>& channels,
                            std::uint32_t width,
                            const std::filesystem::path& path) {
  for (std::uint32_t channel = 0; channel < 4; ++channel) {
    std::size_t x = 0;
    std::uint8_t* output = channels.data() +
                           static_cast<std::size_t>(channel) * width;
    while (x < width) {
      const std::uint8_t code = read_byte(input, path, "RLE scanline");
      if (code == 0)
        hdr_error(path, "invalid zero-length RLE packet");
      if (code > 128) {
        const std::size_t count = static_cast<std::size_t>(code - 128);
        if (count > static_cast<std::size_t>(width) - x)
          hdr_error(path, "RLE run crosses a scanline boundary");
        const std::uint8_t value = read_byte(input, path, "RLE run");
        std::fill_n(output + x, count, value);
        x += count;
      } else {
        const std::size_t count = code;
        if (count > static_cast<std::size_t>(width) - x)
          hdr_error(path, "RLE literal crosses a scanline boundary");
        read_bytes(input, output + x, count, path, "RLE literal");
        x += count;
      }
    }
  }
}

Vec3 decode_rgbe(const std::uint8_t* rgbe) {
  if (rgbe[3] == 0) return Vec3{};
  const float scale = std::ldexp(1.0f, static_cast<int>(rgbe[3]) - 136);
  return {static_cast<float>(rgbe[0]) * scale,
          static_cast<float>(rgbe[1]) * scale,
          static_cast<float>(rgbe[2]) * scale};
}

struct FloatCdf {
  std::vector<float> boundaries;
  std::vector<float> probabilities;
};

FloatCdf make_float_cdf(const std::vector<double>& masses) {
  if (masses.empty()) return {{0.0f}, {}};

  long double total = 0.0L;
  for (const double mass : masses) {
    if (!std::isfinite(mass) || mass < 0.0)
      throw std::invalid_argument("sampling distribution has an invalid mass");
    total += static_cast<long double>(mass);
  }
  if (!(total > 0.0L) || !std::isfinite(total))
    throw std::invalid_argument("sampling distribution has no finite positive mass");

  const std::size_t count = masses.size();
  FloatCdf result;
  result.boundaries.resize(count + 1);
  result.probabilities.resize(count);
  result.boundaries.front() = 0.0f;
  result.boundaries.back() = 1.0f;

  // Precompute the largest representable boundary that still leaves one
  // positive float interval for every remaining outcome.
  std::vector<float> upper(count + 1, 1.0f);
  for (std::size_t i = count; i-- > 1;) {
    upper[i] = std::nextafter(upper[i + 1], 0.0f);
  }

  long double cumulative = 0.0L;
  for (std::size_t i = 1; i < count; ++i) {
    cumulative += static_cast<long double>(masses[i - 1]);
    float boundary = static_cast<float>(cumulative / total);
    const float lower =
        std::nextafter(result.boundaries[i - 1], 1.0f);
    boundary = std::max(lower, std::min(boundary, upper[i]));
    result.boundaries[i] = boundary;
  }

  for (std::size_t i = 0; i < count; ++i) {
    result.probabilities[i] =
        result.boundaries[i + 1] - result.boundaries[i];
    if (!(result.probabilities[i] > 0.0f))
      throw std::runtime_error("failed to construct a strictly increasing float CDF");
  }
  return result;
}

double luminance(Vec3 value) {
  return 0.2126 * static_cast<double>(value.x) +
         0.7152 * static_cast<double>(value.y) +
         0.0722 * static_cast<double>(value.z);
}

double finite_light_proxy(const Light& light) {
  if (light.type == LightType::Flame) {
    const double radius =
        static_cast<double>(std::max(light.radius_start, light.radius_end));
    const double volume = static_cast<double>(kPi) * radius * radius *
                          static_cast<double>(light.height);
    const Vec3 average_emission =
        (light.emission_start + light.emission_end) * 0.5f;
    return 4.0 * static_cast<double>(kPi) * volume *
           static_cast<double>(light.extinction) *
           static_cast<double>(light.density_scale) *
           luminance(average_emission);
  }

  double area = 0.0;
  switch (light.type) {
    case LightType::Sphere: {
      const double radius = light.radius;
      area = 4.0 * static_cast<double>(kPi) * radius * radius;
      break;
    }
    case LightType::Rectangle:
      area = static_cast<double>(length(cross(light.edge_u, light.edge_v)));
      break;
    case LightType::Disk: {
      const double radius = light.radius;
      area = static_cast<double>(kPi) * radius * radius;
      break;
    }
    case LightType::Flame:
      break;
    case LightType::Point:
    case LightType::Directional:
      return 0.0;
  }
  return static_cast<double>(kPi) * area * luminance(light.emission);
}

}  // namespace

ImageRgb32f load_radiance_hdr(const std::filesystem::path& path) {
  std::ifstream input(path, std::ios::binary);
  if (!input) hdr_error(path, "cannot open file");

  std::string line;
  if (!std::getline(input, line)) hdr_error(path, "missing signature");
  if (!line.empty() && line.back() == '\r') line.pop_back();
  if (line != "#?RADIANCE" && line != "#?RGBE")
    hdr_error(path, "expected #?RADIANCE or #?RGBE signature");

  bool found_format = false;
  bool ended_header = false;
  while (std::getline(input, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line.size() > 4096) hdr_error(path, "header line is too long");
    if (line.empty()) {
      ended_header = true;
      break;
    }
    if (line.rfind("FORMAT=", 0) == 0) {
      if (line != "FORMAT=32-bit_rle_rgbe")
        hdr_error(path, "unsupported FORMAT (expected 32-bit_rle_rgbe)");
      if (found_format) hdr_error(path, "duplicate FORMAT header");
      found_format = true;
    }
  }
  if (!ended_header) hdr_error(path, "unterminated header");
  if (!found_format) hdr_error(path, "missing FORMAT=32-bit_rle_rgbe header");

  if (!std::getline(input, line)) hdr_error(path, "missing resolution line");
  if (!line.empty() && line.back() == '\r') line.pop_back();
  std::istringstream resolution(line);
  std::string y_axis;
  std::string height_token;
  std::string x_axis;
  std::string width_token;
  std::string extra;
  if (!(resolution >> y_axis >> height_token >> x_axis >> width_token) ||
      (resolution >> extra) || y_axis != "-Y" || x_axis != "+X") {
    hdr_error(path, "expected resolution line '-Y height +X width'");
  }
  const std::uint32_t height =
      parse_dimension(height_token, path, "height", kMaximumHdrHeight);
  const std::uint32_t width =
      parse_dimension(width_token, path, "width", kMaximumHdrWidth);
  const std::size_t pixel_count =
      static_cast<std::size_t>(width) * static_cast<std::size_t>(height);
  if (pixel_count > kMaximumHdrPixels)
    hdr_error(path, "pixel count must be at most 2^25");

  ImageRgb32f image;
  image.width = width;
  image.height = height;
  image.pixels.resize(pixel_count * 3);

  std::vector<std::uint8_t> channels(static_cast<std::size_t>(width) * 4);
  std::vector<std::uint8_t> raw(static_cast<std::size_t>(width) * 4);
  for (std::uint32_t y = 0; y < height; ++y) {
    std::array<std::uint8_t, 4> prefix{};
    read_bytes(input, prefix.data(), prefix.size(), path, "scanline");
    const bool modern = width >= 8 && width <= 32767 && prefix[0] == 2 &&
                        prefix[1] == 2 && (prefix[2] & 0x80u) == 0;
    if (modern) {
      const std::uint32_t encoded_width =
          (static_cast<std::uint32_t>(prefix[2]) << 8u) | prefix[3];
      if (encoded_width != width)
        hdr_error(path, "RLE scanline width does not match resolution");
      decode_modern_scanline(input, channels, width, path);
    } else {
      std::copy(prefix.begin(), prefix.end(), raw.begin());
      read_bytes(input, raw.data() + prefix.size(), raw.size() - prefix.size(),
                 path, "raw scanline");
    }

    for (std::uint32_t x = 0; x < width; ++x) {
      std::array<std::uint8_t, 4> rgbe{};
      if (modern) {
        for (std::uint32_t channel = 0; channel < 4; ++channel) {
          rgbe[channel] =
              channels[static_cast<std::size_t>(channel) * width + x];
        }
      } else {
        std::copy_n(raw.data() + static_cast<std::size_t>(x) * 4, 4,
                    rgbe.data());
      }
      const Vec3 rgb = decode_rgbe(rgbe.data());
      const std::size_t destination =
          (static_cast<std::size_t>(y) * width + x) * 3;
      image.pixels[destination] = rgb.x;
      image.pixels[destination + 1] = rgb.y;
      image.pixels[destination + 2] = rgb.z;
    }
  }
  char trailing = 0;
  if (input.get(trailing)) hdr_error(path, "unexpected trailing data");
  if (!input.eof()) hdr_error(path, "failed while checking trailing data");
  return image;
}

FiniteLightDistribution build_finite_light_distribution(
    const std::vector<Light>& lights,
    DirectLightSampling mode) {
  if (lights.size() > kMaximumFiniteLights)
    throw std::invalid_argument("finite-light distribution supports at most 4096 lights");
  std::vector<std::uint32_t> indices;
  indices.reserve(lights.size());
  for (std::size_t i = 0; i < lights.size(); ++i) {
    if (lights[i].type != LightType::Point &&
        lights[i].type != LightType::Directional) {
      indices.push_back(static_cast<std::uint32_t>(i));
    }
  }
  if (indices.empty()) return {{}, {0.0f}, {}};

  const std::size_t count = indices.size();
  std::vector<double> masses(count, 1.0 / static_cast<double>(count));
  if (mode == DirectLightSampling::Importance) {
    std::vector<double> proxies(count);
    long double proxy_sum = 0.0L;
    for (std::size_t i = 0; i < count; ++i) {
      proxies[i] = finite_light_proxy(lights[indices[i]]);
      if (!std::isfinite(proxies[i]) || proxies[i] < 0.0)
        throw std::invalid_argument("finite light has an invalid power proxy");
      proxy_sum += static_cast<long double>(proxies[i]);
    }
    const double floor = 0.01 / static_cast<double>(count);
    if (proxy_sum > 0.0L && std::isfinite(proxy_sum)) {
      for (std::size_t i = 0; i < count; ++i) {
        masses[i] = 0.99 * static_cast<double>(
                               static_cast<long double>(proxies[i]) / proxy_sum) +
                    floor;
      }
    }
  }

  FloatCdf distribution = make_float_cdf(masses);
  return {std::move(indices),
          std::move(distribution.boundaries),
          std::move(distribution.probabilities)};
}

EnvironmentDistribution build_environment_distribution(
    const ImageRgb32f& image,
    DirectLightSampling mode) {
  if (image.width == 0 || image.height == 0 ||
      image.width > kMaximumHdrWidth || image.height > kMaximumHdrHeight) {
    throw std::invalid_argument("environment image dimensions are invalid");
  }
  const std::size_t pixel_count =
      static_cast<std::size_t>(image.width) * image.height;
  if (pixel_count > kMaximumHdrPixels)
    throw std::invalid_argument(
        "environment image pixel count must be at most 2^25");
  if (image.pixels.size() != pixel_count * 3)
    throw std::invalid_argument("environment image RGB storage size is invalid");

  std::vector<double> importance(pixel_count);
  std::vector<double> sphere_mass(pixel_count);
  long double importance_sum = 0.0L;
  for (std::uint32_t y = 0; y < image.height; ++y) {
    const double theta0 = static_cast<double>(kPi) * y / image.height;
    const double theta1 = static_cast<double>(kPi) * (y + 1u) / image.height;
    const double solid_angle =
        (2.0 * static_cast<double>(kPi) / image.width) *
        (std::cos(theta0) - std::cos(theta1));
    for (std::uint32_t x = 0; x < image.width; ++x) {
      const std::size_t pixel = static_cast<std::size_t>(y) * image.width + x;
      const Vec3 rgb{image.pixels[pixel * 3], image.pixels[pixel * 3 + 1],
                     image.pixels[pixel * 3 + 2]};
      if (!finite(rgb) || rgb.x < 0.0f || rgb.y < 0.0f || rgb.z < 0.0f)
        throw std::invalid_argument(
            "environment image contains a non-finite or negative sample");
      importance[pixel] = luminance(rgb) * solid_angle;
      sphere_mass[pixel] = solid_angle / (4.0 * static_cast<double>(kPi));
      importance_sum += static_cast<long double>(importance[pixel]);
    }
  }

  EnvironmentDistribution result;
  result.width = image.width;
  result.height = image.height;
  result.black = !(importance_sum > 0.0L) || !std::isfinite(importance_sum);

  std::vector<double> joint(pixel_count);
  for (std::size_t pixel = 0; pixel < pixel_count; ++pixel) {
    if (mode == DirectLightSampling::Uniform || result.black) {
      joint[pixel] = sphere_mass[pixel];
    } else {
      joint[pixel] =
          0.99 * static_cast<double>(
                     static_cast<long double>(importance[pixel]) /
                     importance_sum) +
          0.01 * sphere_mass[pixel];
    }
  }

  std::vector<double> row_masses(image.height, 0.0);
  for (std::uint32_t y = 0; y < image.height; ++y) {
    for (std::uint32_t x = 0; x < image.width; ++x) {
      row_masses[y] += joint[static_cast<std::size_t>(y) * image.width + x];
    }
  }
  FloatCdf rows = make_float_cdf(row_masses);
  result.row_cdf = std::move(rows.boundaries);
  result.row_probabilities = std::move(rows.probabilities);

  result.conditional_cdf.resize(
      static_cast<std::size_t>(image.height) * (image.width + 1u));
  result.conditional_probabilities.resize(pixel_count);
  std::vector<double> row(image.width);
  for (std::uint32_t y = 0; y < image.height; ++y) {
    const std::size_t source = static_cast<std::size_t>(y) * image.width;
    std::copy_n(joint.data() + source, image.width, row.data());
    FloatCdf conditional = make_float_cdf(row);
    const std::size_t cdf_destination =
        static_cast<std::size_t>(y) * (image.width + 1u);
    std::copy(conditional.boundaries.begin(), conditional.boundaries.end(),
              result.conditional_cdf.begin() + cdf_destination);
    std::copy(conditional.probabilities.begin(),
              conditional.probabilities.end(),
              result.conditional_probabilities.begin() + source);
  }
  return result;
}

}  // namespace spectraldock
