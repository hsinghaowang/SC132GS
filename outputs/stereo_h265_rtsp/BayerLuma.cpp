#include "BayerLuma.hpp"
#if defined(__ARM_NEON) && !defined(STEREO_FORCE_SCALAR)
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
    bool unpacked{};
    std::uint64_t near_saturated{};
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
        near_saturated = 0;
        for (int y = 0; y < height; ++y) {
            const auto* source = raw.data() + static_cast<std::size_t>(y) * stride;
            auto* row = pixels.data() + static_cast<std::size_t>(y) * width;
            int x = 0;
#if defined(__aarch64__) && defined(__ARM_NEON) && !defined(STEREO_FORCE_SCALAR)
            // Overlapping loads cover exactly 20 bytes: safe even at the row tail.
            const std::uint8_t high_indices[16] = {0,1,2,3,5,6,7,8,10,11,12,13,27,28,29,30};
            const std::uint8_t low_indices[16] = {4,4,4,4,9,9,9,9,14,14,14,14,31,31,31,31};
            const std::int8_t shifts[16] = {0,-2,-4,-6,0,-2,-4,-6,0,-2,-4,-6,0,-2,-4,-6};
            for (; x + 16 <= width; x += 16, source += 20) {
                uint8x16x2_t table;
                table.val[0] = vld1q_u8(source);
                table.val[1] = vld1q_u8(source + 4);
                const auto high = vqtbl2q_u8(table, vld1q_u8(high_indices));
                const auto low = vandq_u8(vshlq_u8(vqtbl2q_u8(table, vld1q_u8(low_indices)),
                                                   vld1q_s8(shifts)), vdupq_n_u8(3));
                const auto a = vorrq_u16(vshll_n_u8(vget_low_u8(high), 2), vmovl_u8(vget_low_u8(low)));
                const auto b = vorrq_u16(vshll_n_u8(vget_high_u8(high), 2), vmovl_u8(vget_high_u8(low)));
                vst1q_u16(row + x, a);
                vst1q_u16(row + x + 8, b);
                near_saturated += vaddvq_u16(vshrq_n_u16(vcgeq_u16(a, vdupq_n_u16(1008)), 15));
                near_saturated += vaddvq_u16(vshrq_n_u16(vcgeq_u16(b, vdupq_n_u16(1008)), 15));
            }
#endif
            for (; x < width; x += 4, source += 5) {
                const auto low = source[4];
                row[x] = (source[0] << 2) | (low & 3);
                row[x + 1] = (source[1] << 2) | ((low >> 2) & 3);
                row[x + 2] = (source[2] << 2) | ((low >> 4) & 3);
                row[x + 3] = (source[3] << 2) | ((low >> 6) & 3);
                for (int lane = 0; lane < 4; ++lane)
                    near_saturated += row[x + lane] >= 1008;
            }
        }
        unpacked = true;
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
#if defined(__ARM_NEON) && !defined(STEREO_FORCE_SCALAR)
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
    unpack(packed, stride);
    render(gray, scale);
}

void BayerLuma::convert10(std::span<const std::uint8_t> packed, int stride,
                          std::span<std::uint16_t> gray, int scale) {
    unpack(packed, stride);
    render10(gray, scale);
}

void BayerLuma::unpack(std::span<const std::uint8_t> packed, int stride) {
    impl_->unpacked = false;
    if (stride < impl_->width * 5 / 4 ||
        packed.size() < static_cast<std::size_t>(stride) * impl_->height)
        throw std::invalid_argument("RGGB RAW10 buffer or stride");
    impl_->unpack(packed, stride);
}

BayerLuma::RawStatistics BayerLuma::statistics() const {
    if (!impl_->unpacked) throw std::logic_error("RAW10 has not been unpacked");
    RawStatistics result;
    result.sample_count = static_cast<std::uint64_t>(impl_->width) * impl_->height;
    result.near_saturated_count = impl_->near_saturated;
    const int width = impl_->width, height = impl_->height;
    // Read only the owned decoded scratch, never the mapping after QBUF.
    for (int y = height / 10; y + 1 < height * 9 / 10; y += 8)
        for (int x = width / 10; x + 1 < width * 9 / 10; x += 8)
            for (int dy = 0; dy < 2; ++dy)
                for (int dx = 0; dx < 2; ++dx)
                    ++result.histogram[impl_->pixels[static_cast<std::size_t>(y + dy) * width + x + dx]];
    return result;
}

void BayerLuma::render(std::span<std::uint8_t> gray, int scale) const {
    if (!impl_->unpacked || (scale != 1 && scale != 2 && scale != 4) ||
        impl_->width % scale || impl_->height % scale ||
        gray.size() != static_cast<std::size_t>(impl_->width / scale) * (impl_->height / scale))
        throw std::invalid_argument("RGGB output or scale");
    impl_->grayscale(gray, scale);
}

void BayerLuma::render10(std::span<std::uint16_t> gray, int scale) const {
    if (!impl_->unpacked || (scale != 1 && scale != 2 && scale != 4) ||
        impl_->width % scale || impl_->height % scale ||
        gray.size() != static_cast<std::size_t>(impl_->width / scale) * (impl_->height / scale))
        throw std::invalid_argument("RGGB output or scale");
    impl_->grayscale(gray, scale);
}
} // namespace stereo_rtsp::detail
