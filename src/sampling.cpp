#include "spectraldock/sampling.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <fstream>
#include <limits>
#include <locale>
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

struct Chromaticities {
  std::array<double, 2> red;
  std::array<double, 2> green;
  std::array<double, 2> blue;
  std::array<double, 2> white;
};

// Radiance's historical defaults use the standard Radiance RGB primaries and
// an equal-energy white. Files produced by this project declare Rec.709/D65
// explicitly, so the default is only used for otherwise valid legacy files.
constexpr Chromaticities kRadianceStandardChromaticities{
    {0.640, 0.330}, {0.290, 0.600}, {0.150, 0.060}, {0.3333, 0.3333}};
constexpr Chromaticities kRec709D65Chromaticities{
    {0.640, 0.330}, {0.300, 0.600}, {0.150, 0.060}, {0.3127, 0.3290}};

struct Matrix3 {
  std::array<double, 9> values{};
};

double matrix_value(const Matrix3& matrix, std::size_t row,
                    std::size_t column) {
  return matrix.values[row * 3 + column];
}

double& matrix_value(Matrix3& matrix, std::size_t row, std::size_t column) {
  return matrix.values[row * 3 + column];
}

std::array<double, 3> multiply(const Matrix3& matrix,
                               const std::array<double, 3>& vector) {
  std::array<double, 3> result{};
  for (std::size_t row = 0; row < 3; ++row) {
    for (std::size_t column = 0; column < 3; ++column) {
      result[row] += matrix_value(matrix, row, column) * vector[column];
    }
  }
  return result;
}

Matrix3 multiply(const Matrix3& first, const Matrix3& second) {
  Matrix3 result;
  for (std::size_t row = 0; row < 3; ++row) {
    for (std::size_t column = 0; column < 3; ++column) {
      for (std::size_t inner = 0; inner < 3; ++inner) {
        matrix_value(result, row, column) +=
            matrix_value(first, row, inner) *
            matrix_value(second, inner, column);
      }
    }
  }
  return result;
}

Matrix3 inverse(const Matrix3& matrix, const std::filesystem::path& path,
                const char* description) {
  double scale = 0.0;
  for (const double value : matrix.values) {
    if (!std::isfinite(value))
      hdr_error(path, std::string(description) + " matrix is non-finite");
    scale = std::max(scale, std::fabs(value));
  }
  if (!(scale > 0.0))
    hdr_error(path, std::string(description) + " matrix is singular");

  Matrix3 normalized = matrix;
  for (double& value : normalized.values) value /= scale;
  const double a = normalized.values[0];
  const double b = normalized.values[1];
  const double c = normalized.values[2];
  const double d = normalized.values[3];
  const double e = normalized.values[4];
  const double f = normalized.values[5];
  const double g = normalized.values[6];
  const double h = normalized.values[7];
  const double i = normalized.values[8];
  const double determinant =
      a * (e * i - f * h) - b * (d * i - f * g) +
      c * (d * h - e * g);
  if (!std::isfinite(determinant) || std::fabs(determinant) <= 1.0e-12)
    hdr_error(path, std::string(description) + " matrix is singular");

  Matrix3 result{{
      (e * i - f * h) / determinant,
      (c * h - b * i) / determinant,
      (b * f - c * e) / determinant,
      (f * g - d * i) / determinant,
      (a * i - c * g) / determinant,
      (c * d - a * f) / determinant,
      (d * h - e * g) / determinant,
      (b * g - a * h) / determinant,
      (a * e - b * d) / determinant,
  }};
  for (double& value : result.values) {
    value /= scale;
    if (!std::isfinite(value))
      hdr_error(path, std::string(description) + " matrix is ill-conditioned");
  }
  return result;
}

std::array<double, 3> xy_to_xyz(const std::array<double, 2>& xy,
                                const std::filesystem::path& path,
                                const char* description) {
  const double x = xy[0];
  const double y = xy[1];
  const std::array<double, 3> xyz{x / y, 1.0, (1.0 - x - y) / y};
  if (!std::isfinite(xyz[0]) || !std::isfinite(xyz[2]))
    hdr_error(path, std::string(description) +
                        " chromaticity cannot be represented");
  return xyz;
}

void validate_chromaticity(const std::array<double, 2>& xy,
                           const std::filesystem::path& path,
                           const char* description, bool white) {
  const double x = xy[0];
  const double y = xy[1];
  if (!std::isfinite(x) || !std::isfinite(y) || !(x > 0.0) ||
      !(y > 0.0) || x >= 1.0 || y >= 1.0 || x + y > 1.0 ||
      (white && x + y >= 1.0)) {
    hdr_error(path, std::string("malformed PRIMARIES header: ") +
                        description + " chromaticity is invalid");
  }
}

Matrix3 rgb_to_xyz_matrix(const Chromaticities& chromaticities,
                          const std::filesystem::path& path,
                          const char* description) {
  validate_chromaticity(chromaticities.red, path, "red", false);
  validate_chromaticity(chromaticities.green, path, "green", false);
  validate_chromaticity(chromaticities.blue, path, "blue", false);
  validate_chromaticity(chromaticities.white, path, "white", true);

  const std::array<double, 3> red =
      xy_to_xyz(chromaticities.red, path, "red primary");
  const std::array<double, 3> green =
      xy_to_xyz(chromaticities.green, path, "green primary");
  const std::array<double, 3> blue =
      xy_to_xyz(chromaticities.blue, path, "blue primary");
  Matrix3 primary_matrix{{red[0], green[0], blue[0], red[1], green[1],
                          blue[1], red[2], green[2], blue[2]}};
  const std::array<double, 3> white =
      xy_to_xyz(chromaticities.white, path, "white point");
  const std::array<double, 3> scales =
      multiply(inverse(primary_matrix, path, description), white);
  for (const double value : scales) {
    if (!std::isfinite(value) || !(value > 0.0))
      hdr_error(path, std::string("malformed PRIMARIES header: ") +
                          "white point is outside the primary gamut");
  }
  for (std::size_t row = 0; row < 3; ++row) {
    for (std::size_t column = 0; column < 3; ++column) {
      matrix_value(primary_matrix, row, column) *= scales[column];
    }
  }
  return primary_matrix;
}

Matrix3 source_to_rec709_matrix(const Chromaticities& source,
                                const std::filesystem::path& path) {
  const Matrix3 source_to_xyz =
      rgb_to_xyz_matrix(source, path, "source RGB-to-XYZ");
  const Matrix3 rec709_to_xyz = rgb_to_xyz_matrix(
      kRec709D65Chromaticities, path, "Rec.709 RGB-to-XYZ");

  // Bradford adaptation preserves neutral colors while moving a legacy
  // Radiance equal-energy white (or a declared source white) to D65.
  const Matrix3 bradford{{0.8951, 0.2664, -0.1614,
                          -0.7502, 1.7135, 0.0367,
                          0.0389, -0.0685, 1.0296}};
  const std::array<double, 3> source_white =
      xy_to_xyz(source.white, path, "source white point");
  const std::array<double, 3> target_white =
      xy_to_xyz(kRec709D65Chromaticities.white, path, "D65 white point");
  const std::array<double, 3> source_cone = multiply(bradford, source_white);
  const std::array<double, 3> target_cone = multiply(bradford, target_white);
  Matrix3 cone_scale;
  for (std::size_t component = 0; component < 3; ++component) {
    if (!std::isfinite(source_cone[component]) ||
        !std::isfinite(target_cone[component]) ||
        !(source_cone[component] > 0.0) ||
        !(target_cone[component] > 0.0)) {
      hdr_error(path, "PRIMARIES white point cannot be Bradford-adapted");
    }
    matrix_value(cone_scale, component, component) =
        target_cone[component] / source_cone[component];
  }
  const Matrix3 adaptation =
      multiply(multiply(inverse(bradford, path, "Bradford"), cone_scale),
               bradford);
  const Matrix3 result =
      multiply(multiply(inverse(rec709_to_xyz, path, "Rec.709 XYZ-to-RGB"),
                        adaptation),
               source_to_xyz);
  for (const double value : result.values) {
    if (!std::isfinite(value))
      hdr_error(path, "PRIMARIES color conversion is non-finite");
  }
  return result;
}

template <std::size_t Count>
std::array<double, Count> parse_header_numbers(
    const std::string& line, const char* prefix,
    const std::filesystem::path& path, const char* name) {
  std::istringstream values(line.substr(std::char_traits<char>::length(prefix)));
  values.imbue(std::locale::classic());
  std::array<double, Count> result{};
  for (double& value : result) {
    if (!(values >> value))
      hdr_error(path, std::string("malformed ") + name + " header");
  }
  values >> std::ws;
  if (!values.eof())
    hdr_error(path, std::string("malformed ") + name + " header");
  return result;
}

struct RadianceHeader {
  double exposure = 1.0;
  std::array<double, 3> color_correction{1.0, 1.0, 1.0};
  Chromaticities primaries = kRadianceStandardChromaticities;
  bool found_primaries = false;
};

void multiply_header_factor(double& cumulative, double value,
                            const std::filesystem::path& path,
                            const char* name) {
  if (!std::isfinite(value) || !(value > 0.0))
    hdr_error(path, std::string(name) +
                        " header values must be finite and positive");
  cumulative *= value;
  if (!std::isfinite(cumulative) || !(cumulative > 0.0))
    hdr_error(path, std::string("cumulative ") + name +
                        " header value must be finite and positive");
}

void parse_exposure(const std::string& line, RadianceHeader& header,
                    const std::filesystem::path& path) {
  const auto values =
      parse_header_numbers<1>(line, "EXPOSURE=", path, "EXPOSURE");
  multiply_header_factor(header.exposure, values[0], path, "EXPOSURE");
}

void parse_color_correction(const std::string& line, RadianceHeader& header,
                            const std::filesystem::path& path) {
  const auto values =
      parse_header_numbers<3>(line, "COLORCORR=", path, "COLORCORR");
  for (std::size_t component = 0; component < 3; ++component) {
    multiply_header_factor(header.color_correction[component],
                           values[component], path, "COLORCORR");
  }
}

void parse_primaries(const std::string& line, RadianceHeader& header,
                     const std::filesystem::path& path) {
  if (header.found_primaries)
    hdr_error(path, "duplicate PRIMARIES header");
  const auto values =
      parse_header_numbers<8>(line, "PRIMARIES=", path, "PRIMARIES");
  header.primaries = {{values[0], values[1]}, {values[2], values[3]},
                      {values[4], values[5]}, {values[6], values[7]}};
  // This validates the chromaticities, primary independence and whether the
  // declared white can be represented by positive RGB values.
  (void)rgb_to_xyz_matrix(header.primaries, path, "source RGB-to-XYZ");
  header.found_primaries = true;
}

bool malformed_known_header(const std::string& line, const char* name) {
  const std::size_t length = std::char_traits<char>::length(name);
  if (line.compare(0, length, name) != 0) return false;
  if (line.size() == length) return true;
  return line[length] == ' ' || line[length] == '\t' || line[length] == ':';
}

Vec3 normalize_and_convert_rgbe(const std::uint8_t* rgbe,
                                const RadianceHeader& header,
                                const Matrix3& color_conversion,
                                const std::filesystem::path& path) {
  const Vec3 decoded = decode_rgbe(rgbe);
  const std::array<double, 3> source{
      static_cast<double>(decoded.x) / header.exposure /
          header.color_correction[0],
      static_cast<double>(decoded.y) / header.exposure /
          header.color_correction[1],
      static_cast<double>(decoded.z) / header.exposure /
          header.color_correction[2],
  };
  for (const double value : source) {
    if (!std::isfinite(value) || value < 0.0)
      hdr_error(path, "header normalization produced an invalid RGB sample");
  }
  std::array<double, 3> converted = multiply(color_conversion, source);
  for (double& value : converted) {
    if (!std::isfinite(value) ||
        std::fabs(value) > std::numeric_limits<float>::max())
      hdr_error(path,
                "color conversion produced a non-finite or out-of-range sample");
    // A valid source-gamut color can lie outside Rec.709 and therefore
    // produce negative Rec.709 components. Match the HDR AVIF input policy:
    // preserve representable positive energy and clip only those negatives.
    value = std::max(0.0, value);
  }
  return {static_cast<float>(converted[0]), static_cast<float>(converted[1]),
          static_cast<float>(converted[2])};
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
  RadianceHeader header;
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
    } else if (line.rfind("EXPOSURE=", 0) == 0) {
      parse_exposure(line, header, path);
    } else if (line.rfind("COLORCORR=", 0) == 0) {
      parse_color_correction(line, header, path);
    } else if (line.rfind("PRIMARIES=", 0) == 0) {
      parse_primaries(line, header, path);
    } else if (malformed_known_header(line, "EXPOSURE") ||
               malformed_known_header(line, "COLORCORR") ||
               malformed_known_header(line, "PRIMARIES")) {
      hdr_error(path, "malformed Radiance header variable");
    }
  }
  if (!ended_header) hdr_error(path, "unterminated header");
  if (!found_format) hdr_error(path, "missing FORMAT=32-bit_rle_rgbe header");
  const Matrix3 color_conversion =
      source_to_rec709_matrix(header.primaries, path);

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
      const Vec3 rgb = normalize_and_convert_rgbe(
          rgbe.data(), header, color_conversion, path);
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
