#pragma once

#include <cstdint>
#include <span>

namespace stereo_rtsp::detail {

// Encode normalized linear grayscale as BT.709 limited-range video Y'.
// Only the encoder copy is changed; sensor/AE luma remains linear.
void encode_linear_video_luma(std::span<std::uint8_t> luma) noexcept;

} // namespace stereo_rtsp::detail
