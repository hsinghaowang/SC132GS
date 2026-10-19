// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <algorithm>

namespace sc132gs::sensor_signal {
// Measured pre-encoder luma with both lenses opaque-covered, 2026-10-12.
// Unbinned Linear 37; HDR 53. Gain indices 0,11,21 verified on both eyes.
inline constexpr int linear_black=37;
inline constexpr int hdr_black=53;
inline constexpr int black_level(bool hdr) noexcept { return hdr ? hdr_black : linear_black; }
inline constexpr int luma10(int raw,int black) noexcept {
    const int signal=std::clamp(raw-black,0,1023-black);
    return (signal*1023+(1023-black)/2)/(1023-black);
}
inline constexpr int raw_target(int percent,int black) noexcept {
    return black+(std::clamp(percent,0,100)*(1023-black)+50)/100;
}
}
