#include "LumaDenoise.hpp"
#include <algorithm>
#include <cstdlib>
#include <stdexcept>
#if defined(__aarch64__)
#include <arm_neon.h>
#endif

namespace stereo_rtsp::detail {
namespace {
void filter(std::span<const std::uint8_t> input,
            std::span<std::uint8_t> output, int width, int height, bool accelerated) {
#if !defined(__aarch64__)
    (void)accelerated;
#endif
    if (width < 1 || height < 1 || input.data() == output.data() ||
        input.size() != static_cast<std::size_t>(width)*height || output.size() != input.size())
        throw std::invalid_argument("luma denoise dimensions or storage");
    constexpr int range = 12;
    for (int y = 0; y < height; ++y) {
        const auto* up = input.data() + static_cast<std::size_t>(std::max(0,y-1))*width;
        const auto* row = input.data() + static_cast<std::size_t>(y)*width;
        const auto* down = input.data() + static_cast<std::size_t>(std::min(height-1,y+1))*width;
        for (int x = 0; x < width; ++x) {
#if defined(__aarch64__)
            if (accelerated && x > 0 && x + 8 < width) {
                const auto center = vld1_u8(row+x);
                auto weights = vdupq_n_u16(range*4);
                auto total = vmulq_n_u16(vmovl_u8(center), range*4);
                const auto add8 = [&](const std::uint8_t* values, unsigned spatial) {
                    const auto value = vld1_u8(values);
                    auto weight = vmovl_u8(vqsub_u8(vdup_n_u8(range), vabd_u8(value,center)));
                    if (spatial == 2) weight = vshlq_n_u16(weight,1);
                    weights = vaddq_u16(weights,weight);
                    total = vmlaq_u16(total,vmovl_u8(value),weight);
                };
                add8(up+x-1,1); add8(up+x,2); add8(up+x+1,1);
                add8(row+x-1,2); add8(row+x+1,2);
                add8(down+x-1,1); add8(down+x,2); add8(down+x+1,1);
                // Match integer round-to-nearest exactly; all values fit in 16 bits.
                total = vaddq_u16(total,vshrq_n_u16(weights,1));
                const auto divide4 = [](uint16x4_t numerator, uint16x4_t denominator) {
                    const auto quotient = vdivq_f32(vcvtq_f32_u32(vmovl_u16(numerator)),
                                                    vcvtq_f32_u32(vmovl_u16(denominator)));
                    return vmovn_u32(vcvtq_u32_f32(quotient));
                };
                vst1_u8(output.data()+static_cast<std::size_t>(y)*width+x,
                    vmovn_u16(vcombine_u16(divide4(vget_low_u16(total),vget_low_u16(weights)),
                                            divide4(vget_high_u16(total),vget_high_u16(weights)))));
                x += 7;
                continue;
            }
#endif
            const int left = std::max(0,x-1), right = std::min(width-1,x+1);
            const int center = row[x];
            int total = center * range * 4, weights = range * 4;
            const auto add = [&](int value, int spatial) {
                const int weight = std::max(0, range - std::abs(value-center))*spatial;
                total += value*weight; weights += weight;
            };
            add(up[left],1); add(up[x],2); add(up[right],1);
            add(row[left],2); add(row[right],2);
            add(down[left],1); add(down[x],2); add(down[right],1);
            output[static_cast<std::size_t>(y)*width+x] = (total+weights/2)/weights;
        }
    }
}
}
void denoise_luma(std::span<const std::uint8_t> input,
                  std::span<std::uint8_t> output, int width, int height) {
    filter(input,output,width,height,true);
}
void denoise_luma_scalar(std::span<const std::uint8_t> input,
                         std::span<std::uint8_t> output, int width, int height) {
    filter(input,output,width,height,false);
}
}
