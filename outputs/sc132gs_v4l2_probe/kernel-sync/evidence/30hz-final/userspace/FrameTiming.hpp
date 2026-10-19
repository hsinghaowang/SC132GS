#pragma once
namespace sc132gs::configuration::detail {
// Keep the 16-bit binning VTS representable below 3 FPS by extending HTS.
constexpr int binning_line_divisor(int fps) noexcept {
    return fps == 1 ? 3 : (fps == 2 ? 2 : 1);
}
constexpr int binning_rows_per_second(int fps) noexcept {
    return 162000 / binning_line_divisor(fps);
}
} // namespace sc132gs::configuration::detail
