#pragma once

#include <cstdint>

namespace stereo_rtsp::detail {

// Inputs are tightly packed eye_width x eye_height luma planes. The output is
// tightly packed NV12 at (2 * eye_width) x eye_height. Each eye is mirrored
// horizontally within its own half; the left and right eye order is preserved.
void compose_mirrored_side_by_side_nv12(const std::uint8_t* left,
                                        const std::uint8_t* right,
                                        std::uint8_t* output,
                                        int eye_width,
                                        int eye_height) noexcept;

} // namespace stereo_rtsp::detail
