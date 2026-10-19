#pragma once
#include <cstdint>
#include <span>

namespace stereo_rtsp::detail {
// Single-frame 3x3 spatial/range filter. Separate output storage is required.
void denoise_luma(std::span<const std::uint8_t> input,
                  std::span<std::uint8_t> output, int width, int height);
void denoise_luma_scalar(std::span<const std::uint8_t> input,
                         std::span<std::uint8_t> output, int width, int height);
}
