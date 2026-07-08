#pragma once

#ifndef SPECTRALDOCK_HD
#if defined(__CUDACC__)
#define SPECTRALDOCK_HD __host__ __device__
#define SPECTRALDOCK_INLINE __forceinline__
#else
#define SPECTRALDOCK_HD
#define SPECTRALDOCK_INLINE inline
#endif
#endif

namespace spectraldock {

// Russian roulette changes path throughput, not the local solid-angle BSDF
// density used by MIS. Keeping both values in one result makes that convention
// explicit at the call site and testable on the CPU.
struct ContinuationResolution {
  bool survived = false;
  float throughput_scale = 0.0f;
  float bsdf_pdf = 0.0f;
};

SPECTRALDOCK_HD SPECTRALDOCK_INLINE ContinuationResolution resolve_continuation(
    float bsdf_pdf, float survival_probability, float roulette_sample) {
  const bool survived = survival_probability > 0.0f &&
                        roulette_sample < survival_probability;
  return {survived,
          survived ? 1.0f / survival_probability : 0.0f,
          bsdf_pdf};
}

// Normalize by the larger PDF before squaring. This preserves the complementary
// power-heuristic weights without overflowing large PDFs or imposing an
// arbitrary denominator floor on small PDFs.
SPECTRALDOCK_HD SPECTRALDOCK_INLINE float power_heuristic(float pdf_a, float pdf_b) {
  if (!(pdf_a > 0.0f)) return 0.0f;
  if (!(pdf_b > 0.0f)) return 1.0f;
  const float scale = pdf_a > pdf_b ? pdf_a : pdf_b;
  const float a = pdf_a / scale;
  const float b = pdf_b / scale;
  const float aa = a * a;
  const float bb = b * b;
  return aa / (aa + bb);
}

SPECTRALDOCK_HD SPECTRALDOCK_INLINE float direct_light_mis_weight(
    float light_pdf, float bsdf_pdf, bool light_can_be_hit,
    bool next_bsdf_ray_exists) {
  return light_can_be_hit && next_bsdf_ray_exists
             ? power_heuristic(light_pdf, bsdf_pdf)
             : 1.0f;
}

SPECTRALDOCK_HD SPECTRALDOCK_INLINE float emitter_hit_mis_weight(
    float bsdf_pdf, float light_pdf, bool previous_event_was_delta,
    bool emitter_is_bound_to_light) {
  return previous_event_was_delta || !emitter_is_bound_to_light
             ? 1.0f
             : power_heuristic(bsdf_pdf, light_pdf);
}

}  // namespace spectraldock
