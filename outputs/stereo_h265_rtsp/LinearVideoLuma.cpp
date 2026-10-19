#include "LinearVideoLuma.hpp"

#include <array>
#include <cmath>

namespace stereo_rtsp::detail {

void encode_linear_video_luma(std::span<std::uint8_t> luma) noexcept {
    static const auto lut = [] {
        std::array<std::uint8_t, 256> values{};
        for (unsigned i = 0; i < values.size(); ++i) {
            const double linear = i / 255.0;
            const double encoded = linear < 0.018 ? 4.5 * linear :
                1.099 * std::pow(linear, 0.45) - 0.099;
            values[i] = static_cast<std::uint8_t>(std::lround(16 + 219 * encoded));
        }
        return values;
    }();
    for (auto& value : luma) value = lut[value];
}

} // namespace stereo_rtsp::detail
