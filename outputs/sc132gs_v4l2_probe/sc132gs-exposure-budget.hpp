// SPDX-License-Identifier: GPL-2.0-only
#pragma once
#include <cstdint>

namespace sc132gs::exposure_budget {
// Unbinned <=30-FPS trigger profile: observed 0x3260/61 readout=1334 rows.
// Reserve 1350 including reset/blank/guard, then leave 5% exposure margin.
// The >30-FPS and binning profiles use different readout scheduling.
constexpr int reserved_rows(bool binning, int fps) noexcept {
    return !binning && fps<=30 ? 1350 : 0;
}
constexpr int ceiling(int row_rate, int fps, int reserved=0) noexcept {
    if(row_rate<=0 || fps<=0 || reserved<0) return 0;
    const auto available=static_cast<std::int64_t>(row_rate)-static_cast<std::int64_t>(reserved)*fps;
    return available>0 ? static_cast<int>(available*95/(static_cast<std::int64_t>(fps)*100)) : 0;
}
// HDR retains its verified 30-FPS limit. Lower cadence adds exposure headroom
// in the existing 135000 nominal-row/s timing; retain 5% of added time as guard.
// The VTS-8 register boundary (4492) stalled live capture at 15 FPS. The owner
// uses 4350, verified with both SECOND=1 AE and ratio-derived manual SECOND.
constexpr int hdr_ceiling(int fps) noexcept {
    if(fps<=0) return 0;
    if(fps>=30) return 1492;
    const auto extra=135000LL*(30-fps)*95/(30LL*fps*100);
    return extra+1492<4350 ? static_cast<int>(extra+1492) : 4350;
}
}
