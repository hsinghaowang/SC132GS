#include "BayerLuma.hpp"
#if defined(__ARM_NEON)
#include <arm_neon.h>
#endif
#include "sc132gs-hdr-profile.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace stereo_rtsp::detail {

struct BayerLuma::Impl {
    int width;
    int height;
    std::vector<std::uint16_t> pixels;
    bool hdr_display;
    std::array<std::uint8_t, 1024> display_lut{};
    std::array<std::uint16_t, 1024> display_lut10{};

    Impl(int w, int h, bool hdr) : width(w), height(h), hdr_display(hdr) {
        if (w < 4 || w % 4 || h < 2 || h % 2)
            throw std::invalid_argument("RGGB dimensions must be width multiple of four, even height");
        pixels.resize(static_cast<std::size_t>(w) * h);
        if (hdr_display)
            for (unsigned i = 0; i < display_lut.size(); ++i) {
                display_lut[i] = static_cast<std::uint8_t>(std::lround(
                    255 * sc132gs::hdr_profile::display(i / 1023.0)));
                display_lut10[i] = static_cast<std::uint16_t>(std::lround(
                    1023 * sc132gs::hdr_profile::display(i / 1023.0)));
            }
    }

    void unpack(std::span<const std::uint8_t> raw, int stride) {
        for (int y = 0; y < height; ++y) {
            const auto* source = raw.data() + static_cast<std::size_t>(y) * stride;
            auto* row = pixels.data() + static_cast<std::size_t>(y) * width;
            for (int x = 0; x < width; x += 4, source += 5) {
                const auto low = source[4];
                row[x] = (source[0] << 2) | (low & 3);
                row[x + 1] = (source[1] << 2) | ((low >> 2) & 3);
                row[x + 2] = (source[2] << 2) | ((low >> 4) & 3);
                row[x + 3] = (source[3] << 2) | ((low >> 6) & 3);
            }
        }
    }

    template<class Pixel>
    void grayscale(std::span<Pixel> gray, int scale) const {
        const int out_width = width / scale;
        for (int oy = 0; oy < height / scale; ++oy) {
            const int y = oy * scale;
            // Reflect at the boundary to preserve the CFA color parity.
            const int above = y == 0 ? 1 : y - 1;
            const int below = y == height - 1 ? height - 2 : y + 1;
            const auto* row = pixels.data() + static_cast<std::size_t>(y) * width;
            const auto* up = pixels.data() + static_cast<std::size_t>(above) * width;
            const auto* down = pixels.data() + static_cast<std::size_t>(below) * width;
            auto* output = gray.data() + static_cast<std::size_t>(oy) * out_width;
            for (int ox = 0; ox < out_width; ++ox) {
                const int x = ox * scale;
#if defined(__ARM_NEON)
                if constexpr (sizeof(Pixel) == 2) {
                    if (scale == 1 && !hdr_display && x > 0 && x + 8 < width) {
                        const auto center = vld1q_u16(row+x);
                        const auto horizontal = vrshrq_n_u16(vaddq_u16(vld1q_u16(row+x-1),vld1q_u16(row+x+1)),1);
                        const auto vertical = vrshrq_n_u16(vaddq_u16(vld1q_u16(up+x),vld1q_u16(down+x)),1);
                        const auto diagonal = vrshrq_n_u16(vaddq_u16(
                            vaddq_u16(vld1q_u16(up+x-1),vld1q_u16(up+x+1)),
                            vaddq_u16(vld1q_u16(down+x-1),vld1q_u16(down+x+1))),2);
                        const auto cross = vrshrq_n_u16(vaddq_u16(
                            vaddq_u16(vld1q_u16(row+x-1),vld1q_u16(row+x+1)),
                            vaddq_u16(vld1q_u16(up+x),vld1q_u16(down+x))),2);
                        const std::uint16_t even_lane[8]={0,65535,0,65535,0,65535,0,65535};
                        auto even = vld1q_u16(even_lane);
                        if ((x&1)==0) even=vmvnq_u16(even);
                        auto rv = (y&1) ? vbslq_u16(even,vertical,diagonal) : vbslq_u16(even,center,horizontal);
                        auto bv = (y&1) ? vbslq_u16(even,horizontal,center) : vbslq_u16(even,diagonal,vertical);
                        auto gv = (y&1) ? vbslq_u16(even,center,cross) : vbslq_u16(even,cross,center);
                        auto lo=vmull_n_u16(vget_low_u16(rv),54);
                        auto hi=vmull_n_u16(vget_high_u16(rv),54);
                        lo=vmlal_n_u16(lo,vget_low_u16(gv),183); hi=vmlal_n_u16(hi,vget_high_u16(gv),183);
                        lo=vmlal_n_u16(lo,vget_low_u16(bv),19); hi=vmlal_n_u16(hi,vget_high_u16(bv),19);
                        vst1q_u16(output+ox,vcombine_u16(vrshrn_n_u32(lo,8),vrshrn_n_u32(hi,8)));
                        ox+=7;
                        continue;
                    }
                }
#endif
                const int left = x == 0 ? 1 : x - 1;
                const int right = x == width - 1 ? width - 2 : x + 1;
                unsigned r, g, b;
                if ((y & 1) == (x & 1)) {
                    const unsigned diagonal = (up[left] + up[right] + down[left] + down[right] + 2) / 4;
                    g = (row[left] + row[right] + up[x] + down[x] + 2) / 4;
                    r = (y & 1) ? diagonal : row[x];
                    b = (y & 1) ? row[x] : diagonal;
                } else {
                    const unsigned horizontal = (row[left] + row[right] + 1) / 2;
                    const unsigned vertical = (up[x] + down[x] + 1) / 2;
                    g = row[x];
                    r = (y & 1) ? vertical : horizontal;
                    b = (y & 1) ? horizontal : vertical;
                }
                const unsigned weighted = 54*r + 183*g + 19*b;
                if constexpr (sizeof(Pixel) == 2)
                    output[ox] = hdr_display ? display_lut10[(weighted + 128) >> 8] :
                        static_cast<std::uint16_t>((weighted + 128) >> 8);
                else
                    output[ox] = hdr_display ? display_lut[(weighted + 128) >> 8] :
                        static_cast<std::uint8_t>(std::min(255U, (weighted + 512) >> 10));
            }
        }
    }
};

BayerLuma::BayerLuma(int width, int height, bool hdr_display)
    : impl_(std::make_unique<Impl>(width, height, hdr_display)) {}
BayerLuma::~BayerLuma() = default;
BayerLuma::BayerLuma(BayerLuma&&) noexcept = default;
BayerLuma& BayerLuma::operator=(BayerLuma&&) noexcept = default;

void BayerLuma::convert(std::span<const std::uint8_t> packed, int stride,
                        std::span<std::uint8_t> gray, int scale) {
    if ((scale != 1 && scale != 2 && scale != 4) ||
        impl_->width % scale || impl_->height % scale ||
        stride < impl_->width * 5 / 4 ||
        packed.size() < static_cast<std::size_t>(stride) * impl_->height ||
        gray.size() != static_cast<std::size_t>(impl_->width / scale) * (impl_->height / scale))
        throw std::invalid_argument("RGGB RAW10 buffer, stride or scale");
    impl_->unpack(packed, stride);
    impl_->grayscale(gray, scale);
}

void BayerLuma::convert10(std::span<const std::uint8_t> packed, int stride,
                          std::span<std::uint16_t> gray, int scale) {
    if ((scale != 1 && scale != 2 && scale != 4) ||
        impl_->width % scale || impl_->height % scale ||
        stride < impl_->width * 5 / 4 ||
        packed.size() < static_cast<std::size_t>(stride) * impl_->height ||
        gray.size() != static_cast<std::size_t>(impl_->width / scale) * (impl_->height / scale))
        throw std::invalid_argument("RGGB RAW10 buffer, stride or scale");
    impl_->unpack(packed, stride);
    impl_->grayscale(gray, scale);
}
} // namespace stereo_rtsp::detail
