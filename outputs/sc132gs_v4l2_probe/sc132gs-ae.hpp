// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <cstdint>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>
#include "sc132gs-ae-statistics.hpp"
#include "sc132gs-linear-ae-policy.hpp"

enum class AeErrorCode {
    device,
    control,
    invalid_argument,
};

struct AeError final : std::runtime_error {
    AeError(AeErrorCode code, std::string operation, int system_error = 0);

    AeErrorCode code;
    int system_error;
};

class AutoExposure final {
public:
    enum class LumaEncoding { sensor_linear, hdr_display, hdr_preview_b, sensor_signal };
    enum class SaturationBasis { unavailable, hdr_brightest_twenty_percent, linear_full_raw_frame };
    struct LinearTiming {
        int rows_per_second{84000};
        // Zero uses the device limit. Nonzero bounds an experimental profile.
        int max_exposure_rows{};
        int nominal_fps{60}; // Safe initial exposure budget before measured frames.
        int reserved_readout_rows{}; // Non-overlapping trigger readout/reset budget.
        // Conservative command pacing only: sensor effect-frame latency is unvalidated.
        int control_holdoff_pairs{3};
    };
    struct Configuration {
        bool enabled{true};
        int target_percent{18};
        int exposure_rows{}; // Linear rows or managed HDR TOTAL nominal rows.
        int gain_index{};
        int max_exposure_us{};
        int max_gain_index{128};
    };

    struct Snapshot {
        bool enabled{};
        bool brightness_limited{};
        int target_percent{50};
        int cam0_percent{};
        int cam1_percent{};
        // HDR managed profile: TOTAL nominal rows; Linear: exposure rows.
        int exposure_lines{};
        int analogue_gain_index{};
        int fps_x10{};
        int max_exposure_lines{};
        int last_error{};
        bool hdr_enabled{};
        int hdr_ratio{};
        int display_gamma_x100{100};
        int display_black_raw10{};
        int signal_black_raw10{}; // Physical black offset, independent of display curves.
        int max_exposure_us{};
        int max_gain_index{};
        int hdr_second_ticks{};
        int cam0_saturation_bp{};
        int cam1_saturation_bp{};
        int saturation_limit_bp{500};
        bool highlight_limited{};
        int cam0_shadow_raw10{};
        int cam1_shadow_raw10{};
        SaturationBasis saturation_basis{SaturationBasis::unavailable};
        int near_saturation_raw10{};
        sc132gs::linear_ae::Constraint linear_constraint{sc132gs::linear_ae::Constraint::none};
        std::uint64_t command_generation{};
        std::uint32_t last_command_input_sequence{};
        bool command_sequence_valid{};
        bool control_effect_frame_validated{};
        int remaining_holdoff_pairs{};
        int linear_effective_target_luma10{};
        int linear_highlight_darkening_ev_x100{};
    };

    explicit AutoExposure(LumaEncoding encoding = LumaEncoding::sensor_linear);
    AutoExposure(LumaEncoding encoding, LinearTiming timing);
    ~AutoExposure();
    AutoExposure(const AutoExposure&) = delete;
    AutoExposure& operator=(const AutoExposure&) = delete;
    AutoExposure(AutoExposure&&) noexcept;
    AutoExposure& operator=(AutoExposure&&) noexcept;

    void set_target(int percent);
    void set_hdr_saturation_limit(int percent);
    void process_hdr_statistics(sc132gs::hdr_ae::Statistics left,
                                sc132gs::hdr_ae::Statistics right,
                                std::uint32_t sequence, std::int64_t timestamp_ns);
    void set_max_exposure_us(int microseconds);
    void disable();
    // Validates the whole update, serializes against AE, and rolls controls
    // back on write failure. Callbacks are not involved in synchronous apply.
    void configure(const Configuration& configuration);
    [[nodiscard]] Snapshot snapshot() const;
    void process(std::span<const std::uint8_t> cam0,
                 std::span<const std::uint8_t> cam1,
                 std::uint32_t cam0_sequence,
                 std::int64_t cam0_timestamp_ns);
    // Luma follows the constructor's encoding; RAW process() always accepts
    // unmodified packed sensor samples.
    void process_luma(std::span<const std::uint8_t> cam0,
                      std::span<const std::uint8_t> cam1,
                      int width, int height,
                      std::uint32_t cam0_sequence,
                      std::int64_t cam0_timestamp_ns);

    void process_luma10(std::span<const std::uint16_t> cam0,
                        std::span<const std::uint16_t> cam1,
                        int width, int height, std::uint32_t sequence,
                        std::int64_t timestamp_ns);
    // Calibrated linear medians and untouched packed-RAW clipping are separate
    // inputs. Each highlight denominator must include every RAW pixel in that eye.
    // RAW may be larger than the luma plane when capture downscales its output.
    void process_linear_luma10(std::span<const std::uint16_t> cam0,
                               std::span<const std::uint16_t> cam1,
                               int width, int height,
                               sc132gs::linear_ae::HighlightStatistics raw_cam0,
                               sc132gs::linear_ae::HighlightStatistics raw_cam1,
                               std::uint32_t sequence, std::int64_t timestamp_ns);
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
