// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>

namespace sc132gs::linear_ae {

inline constexpr int near_saturation_raw10 = 1008;

// The denominator is every pixel in the supplied pre-calibration 10-bit
// plane, including its border. This is deliberately not HDR's brightest 20%.
struct HighlightStatistics {
    std::uint64_t sample_count{};
    std::uint64_t near_saturated_count{};
    bool valid{};
};

inline bool valid(HighlightStatistics statistics) noexcept {
    return statistics.valid && statistics.sample_count > 0 &&
           statistics.near_saturated_count <= statistics.sample_count;
}

// RAW is metered at native resolution, while the calibrated luma plane may
// already have been downscaled. Both eyes must still cover the same RAW area.
inline bool valid_stereo_coverage(HighlightStatistics left,
                                  HighlightStatistics right,
                                  std::uint64_t luma_pixels) noexcept {
    return luma_pixels > 0 && valid(left) && valid(right) &&
           left.sample_count == right.sample_count && left.sample_count >= luma_pixels;
}

inline int saturation_bp(HighlightStatistics statistics) noexcept {
    if (!valid(statistics)) return 0;
    // Floating conversion avoids overflowing an externally supplied count.
    return static_cast<int>(std::ceil(10000.0L * statistics.near_saturated_count /
                                     statistics.sample_count));
}

inline HighlightStatistics measure_highlights10(const std::uint16_t* pixels,
                                                std::size_t count) noexcept {
    if (!pixels || count == 0) return {};
    HighlightStatistics result{count, 0, true};
    for (std::size_t i = 0; i < count; ++i) {
        if (pixels[i] > 1023) return {};
        if (pixels[i] >= near_saturation_raw10) ++result.near_saturated_count;
    }
    return result;
}

inline HighlightStatistics measure_packed_raw10(const std::uint8_t* pixels,
        std::size_t bytes, int width, int height, int stride) noexcept {
    if (!pixels || width < 4 || width % 4 != 0 || height < 1 || stride < 1) return {};
    const auto row_bytes = static_cast<std::size_t>(width / 4) * 5;
    const auto row_stride = static_cast<std::size_t>(stride);
    const auto rows = static_cast<std::size_t>(height);
    if (row_stride < row_bytes || rows > std::numeric_limits<std::size_t>::max() / row_stride ||
        bytes < row_stride * rows) return {};
    HighlightStatistics result{static_cast<std::uint64_t>(width) * rows, 0, true};
    for (std::size_t y = 0; y < rows; ++y) {
        const auto* row = pixels + y * row_stride;
        for (int x = 0; x < width; x += 4) {
            const auto* group = row + static_cast<std::size_t>(x / 4) * 5;
            for (unsigned phase = 0; phase < 4; ++phase) {
                const unsigned value = (static_cast<unsigned>(group[phase]) << 2) |
                                       ((group[4] >> (2 * phase)) & 3);
                if (value >= near_saturation_raw10) ++result.near_saturated_count;
            }
        }
    }
    return result;
}

struct Settings {
    int target_percent{18};
    int saturation_limit_bp{50}; // 0.5% of either complete image.
    int release_limit_bp{25};
    int release_observations{3};
    // Minority clipped pixels may be emitters/specular regions. Limit their
    // influence on the linear body target; this is an area budget, not object detection.
    int small_highlight_limit_bp{1000}; // 10% of the worse complete RAW frame.
    double max_small_highlight_darkening_ev{0.25};
    double max_large_highlight_darkening_ev{2.0};
};
struct Limits {
    int minimum_rows{8};
    int maximum_rows{1492};
    int minimum_gain{};
    int maximum_gain{128};
};
struct Exposure { int rows{}; int gain{}; };
struct Measurements {
    int left_median{};
    int right_median{};
    HighlightStatistics left_highlights;
    HighlightStatistics right_highlights;
};
enum class Constraint { none, highlights, exposure_and_gain, minimum_exposure, invalid_statistics,
                        highlight_tradeoff };
struct Decision {
    Exposure exposure;
    bool brightness_limited{};
    bool highlight_limited{};
    Constraint constraint{Constraint::none};
    int effective_target_luma10{};
    int highlight_darkening_ev_x100{};
};

// Hardware-independent, single-owner controller. Only its owner feeds settled
// observations; the caller decides when a command may have taken effect.
class Policy final {
public:
    Policy() = default;
    Policy(const Policy&) = delete;
    Policy& operator=(const Policy&) = delete;
    Policy(Policy&&) noexcept = default;
    Policy& operator=(Policy&&) noexcept = default;

    void reset() noexcept { highlight_hold_ = false; release_count_ = 0; held_penalty_ev_ = 0; }

    Decision decide(Settings settings, Limits limits, Exposure current,
                    Measurements measured) noexcept {
        Decision result{current};
        auto& next = result.exposure;
        if (!valid(measured.left_highlights) || !valid(measured.right_highlights) ||
            measured.left_median < 0 || measured.left_median > 1023 ||
            measured.right_median < 0 || measured.right_median > 1023 ||
            settings.target_percent < 0 || settings.target_percent > 100 ||
            settings.saturation_limit_bp < 0 || settings.saturation_limit_bp > 10000 ||
            settings.release_limit_bp < 0 || settings.release_limit_bp > settings.saturation_limit_bp ||
            settings.release_observations < 1 || limits.minimum_rows < 1 ||
            settings.small_highlight_limit_bp <= settings.saturation_limit_bp ||
            settings.small_highlight_limit_bp > 10000 ||
            !std::isfinite(settings.max_small_highlight_darkening_ev) ||
            settings.max_small_highlight_darkening_ev < 0 || settings.max_small_highlight_darkening_ev > 1 ||
            !std::isfinite(settings.max_large_highlight_darkening_ev) ||
            settings.max_large_highlight_darkening_ev < settings.max_small_highlight_darkening_ev ||
            settings.max_large_highlight_darkening_ev > 4 ||
            limits.maximum_rows < limits.minimum_rows || limits.minimum_gain < 0 ||
            limits.maximum_gain < limits.minimum_gain || current.rows < limits.minimum_rows ||
            current.gain < limits.minimum_gain) {
            result.brightness_limited = true;
            result.constraint = Constraint::invalid_statistics;
            return result;
        }
        const int clipped = std::max(saturation_bp(measured.left_highlights),
                                     saturation_bp(measured.right_highlights));
        const bool excess = clipped > settings.saturation_limit_bp;
        if (excess) {
            highlight_hold_ = true;
            release_count_ = 0;
            if (clipped <= settings.small_highlight_limit_bp) {
                const double area = static_cast<double>(clipped - settings.saturation_limit_bp) /
                    (settings.small_highlight_limit_bp - settings.saturation_limit_bp);
                held_penalty_ev_ = area * settings.max_small_highlight_darkening_ev;
            } else {
                const double area = static_cast<double>(clipped - settings.small_highlight_limit_bp) /
                    (10000 - settings.small_highlight_limit_bp);
                held_penalty_ev_ = settings.max_small_highlight_darkening_ev + area *
                    (settings.max_large_highlight_darkening_ev - settings.max_small_highlight_darkening_ev);
            }
        } else if (highlight_hold_) {
            if (clipped <= settings.release_limit_bp) {
                if (++release_count_ >= settings.release_observations) reset();
            } else release_count_ = 0;
        }
        const int median = std::max(1, (measured.left_median + measured.right_median) / 2);
        const int requested_target = settings.target_percent * 1023 / 100;
        // A remembered broad-area penalty must not follow a small source into
        // the release band. Both area segments drive the same body controller.
        const double penalty = std::min(held_penalty_ev_, clipped <= settings.small_highlight_limit_bp ?
            settings.max_small_highlight_darkening_ev : settings.max_large_highlight_darkening_ev);
        const int target = requested_target == 0 ? 0 : std::max(1,
            static_cast<int>(std::lround(requested_target * std::exp2(-penalty))));
        result.effective_target_luma10 = target;
        result.highlight_darkening_ev_x100 = static_cast<int>(std::lround(penalty * 100));
        result.highlight_limited = highlight_hold_;
        if (highlight_hold_) result.constraint = clipped > settings.small_highlight_limit_bp ?
            Constraint::highlights : Constraint::highlight_tradeoff;
        result.brightness_limited = target < requested_target && median < requested_target;
        // Lowering a configured safety ceiling is unconditional.
        next.rows = std::min(next.rows, limits.maximum_rows);
        next.gain = std::min(next.gain, limits.maximum_gain);
        if (next.rows != current.rows || next.gain != current.gain) return result;
        if (target == 0) {
            next = {limits.minimum_rows, limits.minimum_gain};
            result.brightness_limited = median > 5;
            return result;
        }
        const double ev = std::log2(static_cast<double>(target) / median);
        if (std::abs(ev) < 0.075 && (settings.target_percent != 100 || median >= 1018)) {
            // A bounded body target still permits low-noise gain/exposure reallocation.
            if (next.gain > limits.minimum_gain && next.rows < limits.maximum_rows) {
                int step = std::min(2, next.gain - limits.minimum_gain);
                while (step > 0) {
                    const double rows = std::ceil(next.rows * std::exp2(step / 32.0));
                    if (rows <= limits.maximum_rows) {
                        next.rows = static_cast<int>(rows); next.gain -= step; break;
                    }
                    --step;
                }
            }
            return result;
        }
        if (ev > 0) {
            // A remembered minority highlight penalty must never freeze a dark
            // body: it changes the target by at most the configured EV budget.
            if (next.rows < limits.maximum_rows) {
                next.rows = std::min(limits.maximum_rows, std::max(next.rows + 1,
                    static_cast<int>(std::lround(std::min(static_cast<double>(limits.maximum_rows),
                        next.rows * std::exp2(std::min(ev, 0.25)))))));
            } else if (next.gain < limits.maximum_gain) {
                const int step = std::clamp(static_cast<int>(std::lround(ev * 12)), 1, 4);
                next.gain += std::min(step, limits.maximum_gain - next.gain);
            } else {
                result.brightness_limited = true;
                result.constraint = Constraint::exposure_and_gain;
            }
        } else if (next.gain > limits.minimum_gain) {
            const int step = std::clamp(static_cast<int>(std::lround(-ev * 12)), 1, 4);
            next.gain = std::max(limits.minimum_gain, next.gain - step);
        } else if (next.rows > limits.minimum_rows) {
            next.rows = std::max(limits.minimum_rows, std::min(next.rows - 1,
                static_cast<int>(std::lround(next.rows * std::exp2(std::max(ev, -0.25))))));
        } else {
            result.brightness_limited = true;
            result.constraint = Constraint::minimum_exposure;
        }
        return result;
    }

private:
    bool highlight_hold_{};
    int release_count_{};
    double held_penalty_ev_{};
};

} // namespace sc132gs::linear_ae
