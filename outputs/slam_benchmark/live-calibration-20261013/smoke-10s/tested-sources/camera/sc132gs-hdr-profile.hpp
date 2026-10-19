// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <algorithm>
#include <cmath>

namespace sc132gs::hdr_profile {

// Display response only. Sensor exposure controls recover the highlights;
// this monotone curve restores midtones before 8-bit quantization.
inline constexpr double display_gamma = 0.38;
// Measured common output floor in the board's current HDRC profile, including
// minimum-TOTAL captures. This is a display calibration, not a RAW mutation.
inline constexpr unsigned black_level_raw10 = 52;

inline double display(double raw_unit) {
    constexpr double black = black_level_raw10 / 1023.0;
    return std::pow(std::clamp((raw_unit - black) / (1.0 - black), 0.0, 1.0),
                    display_gamma);
}

} // namespace sc132gs::hdr_profile
