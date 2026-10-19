#include "LinearVideoLuma.hpp"

#include <array>
#include <iostream>

int main() {
    std::array<std::uint8_t, 256> ramp{};
    for (unsigned i = 0; i < ramp.size(); ++i) ramp[i] = static_cast<std::uint8_t>(i);
    stereo_rtsp::detail::encode_linear_video_luma(ramp);
    // Black/white video levels, near-black transfer slope, 18% gray and midpoint.
    if (ramp[0] != 16 || ramp[255] != 235 || ramp[1] != 20 ||
        ramp[46] != 106 || ramp[128] != 171) return 1;
    for (unsigned i = 1; i < ramp.size(); ++i)
        if (ramp[i] < ramp[i-1] || ramp[i] < 16 || ramp[i] > 235) return 2;
    std::cout << "BT.709 grayscale reference levels and monotonicity passed\n";
}
