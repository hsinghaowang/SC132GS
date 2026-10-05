#include "Raw10Luma.hpp"

#if defined(__aarch64__)
#include <arm_neon.h>
#endif

namespace stereo_rtsp::detail {

void raw10_luma_scalar(const std::uint8_t* raw, int raw_stride,
                       std::uint8_t* luma, int output_width,
                       int output_height, int scale) noexcept {
    for (int y = 0; y < output_height; ++y) {
        const auto* src = raw + y * scale * raw_stride;
        auto* dst = luma + y * output_width;
        if (scale == 1) {
            int x = 0;
            for (; x + 4 <= output_width; x += 4) {
                const auto* group = src + (x / 4) * 5;
                dst[x] = group[0];
                dst[x + 1] = group[1];
                dst[x + 2] = group[2];
                dst[x + 3] = group[3];
            }
            for (; x < output_width; ++x)
                dst[x] = src[(x / 4) * 5 + x % 4];
        } else {
            for (int x = 0; x < output_width; ++x) {
                const int source_x = x * scale;
                dst[x] = src[(source_x / 4) * 5 + source_x % 4];
            }
        }
    }
}

void raw10_luma_accelerated(const std::uint8_t* raw, int raw_stride,
                            std::uint8_t* luma, int output_width,
                            int output_height, int scale) noexcept {
#if defined(__aarch64__)
    if (scale == 1) {
        // Four RAW10 pixels occupy five bytes. TBL removes every fifth byte
        // from a 20-byte group. Read 32 bytes only while still inside the row.
        static constexpr std::uint8_t positions[16] = {
            0, 1, 2, 3, 5, 6, 7, 8, 10, 11, 12, 13, 15, 16, 17, 18
        };
        const uint8x16_t indexes = vld1q_u8(positions);
        for (int y = 0; y < output_height; ++y) {
            const auto* src = raw + y * raw_stride;
            auto* dst = luma + y * output_width;
            int x = 0;
            int offset = 0;
            for (; x + 16 <= output_width && offset + 32 <= raw_stride;
                 x += 16, offset += 20) {
                uint8x16x2_t table{};
                table.val[0] = vld1q_u8(src + offset);
                table.val[1] = vld1q_u8(src + offset + 16);
                vst1q_u8(dst + x, vqtbl2q_u8(table, indexes));
            }
            for (; x < output_width; ++x)
                dst[x] = src[(x / 4) * 5 + x % 4];
        }
        return;
    }
#endif
    raw10_luma_scalar(raw, raw_stride, luma, output_width, output_height,
                      scale);
}

bool raw10_luma_uses_neon() noexcept {
#if defined(__aarch64__)
    return true;
#else
    return false;
#endif
}

} // namespace stereo_rtsp::detail
