#pragma once

#include <cstdint>

namespace stereo_rtsp::detail {

// Internal conversion for packed RAW10. The output keeps each pixel's high
// eight bits; scale selects every first, second, or fourth source pixel/row.
void raw10_luma_scalar(const std::uint8_t* raw, int raw_stride,
                       std::uint8_t* luma, int output_width,
                       int output_height, int scale) noexcept;

void raw10_luma_accelerated(const std::uint8_t* raw, int raw_stride,
                            std::uint8_t* luma, int output_width,
                            int output_height, int scale) noexcept;

bool raw10_luma_uses_neon() noexcept;

} // namespace stereo_rtsp::detail
