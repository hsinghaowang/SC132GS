// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <array>
namespace sc132gs::hdr_ae {
struct Statistics {
    int shadow{}; // RAW10 median of the selected darker samples.
    int saturation_bp{}; // Brightest 20% of metering samples; 10000 = 100%.
    std::array<unsigned,1024> histogram{};
    int luma_median{-1}; // Unmodified converted luma P50; raw histogram independently protects highlights.
};
}
