// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <cstdint>
#include <memory>
#include <span>
#include <stdexcept>
#include <string>

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
    struct Snapshot {
        bool enabled{};
        bool brightness_limited{};
        int target_percent{50};
        int cam0_percent{};
        int cam1_percent{};
        int exposure_lines{};
        int analogue_gain_index{};
        int fps_x10{};
        int max_exposure_lines{};
        int last_error{};
    };

    AutoExposure();
    ~AutoExposure();
    AutoExposure(const AutoExposure&) = delete;
    AutoExposure& operator=(const AutoExposure&) = delete;
    AutoExposure(AutoExposure&&) noexcept;
    AutoExposure& operator=(AutoExposure&&) noexcept;

    void set_target(int percent);
    void set_max_exposure_us(int microseconds);
    void disable();
    [[nodiscard]] Snapshot snapshot() const;
    void process(std::span<const std::uint8_t> cam0,
                 std::span<const std::uint8_t> cam1,
                 std::uint32_t cam0_sequence,
                 std::int64_t cam0_timestamp_ns);
    void process_luma(std::span<const std::uint8_t> cam0,
                      std::span<const std::uint8_t> cam1,
                      int width, int height,
                      std::uint32_t cam0_sequence,
                      std::int64_t cam0_timestamp_ns);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
