#include "StereoComposeNV12.hpp"

#include <cstddef>
#include <cstring>

#if defined(__aarch64__)
#include <arm_neon.h>
#endif

namespace stereo_rtsp::detail {

namespace {

void mirror_row(const std::uint8_t* source, std::uint8_t* destination,
                std::size_t width) noexcept {
    std::size_t x = 0;
#if defined(__aarch64__)
    for (; x + 16 <= width; x += 16) {
        const auto pixels = vld1q_u8(source + width - x - 16);
        const auto reversed_halves = vrev64q_u8(pixels);
        const auto reversed = vcombine_u8(vget_high_u8(reversed_halves),
                                          vget_low_u8(reversed_halves));
        vst1q_u8(destination + x, reversed);
    }
#endif
    for (; x < width; ++x)
        destination[x] = source[width - 1 - x];
}

} // namespace

void compose_mirrored_side_by_side_nv12(const std::uint8_t* left,
                                        const std::uint8_t* right,
                                        std::uint8_t* output,
                                        int eye_width,
                                        int eye_height) noexcept {
    const auto width = static_cast<std::size_t>(eye_width);
    const auto height = static_cast<std::size_t>(eye_height);
    const auto output_stride = width * 2;
    for (std::size_t y = 0; y < height; ++y) {
        auto* row = output + y * output_stride;
        mirror_row(left + y * width, row, width);
        mirror_row(right + y * width, row + width, width);
    }
    const auto y_bytes = output_stride * height;
    std::memset(output + y_bytes, 128, y_bytes / 2);
}

} // namespace stereo_rtsp::detail
