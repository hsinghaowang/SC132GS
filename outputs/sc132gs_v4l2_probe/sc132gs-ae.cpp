// SPDX-License-Identifier: GPL-2.0-only
#include "sc132gs-ae.hpp"
#include "sc132gs-sensor-signal.hpp"
#include "sc132gs-exposure-budget.hpp"

#include <linux/videodev2.h>

#include "sc132gs-controls.h"
#include "sc132gs-hdr-profile.hpp"
#include "sc132gs-hdr-ae-policy.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <optional>
#include <string_view>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>

namespace {

constexpr int kWidth = 1088;
constexpr int kHeight = 1280;
constexpr int kStride = kWidth * 10 / 8;
constexpr int kUpdateEveryPairs = 4;

std::string sensor_node(std::string_view address_suffix) {
    const std::filesystem::path root{"/sys/class/video4linux"};
    for (const auto& entry : std::filesystem::directory_iterator(root)) {
        const auto name = entry.path().filename().string();
        if (!name.starts_with("v4l-subdev")) {
            continue;
        }
        std::ifstream identity(entry.path() / "name");
        std::string sensor_name;
        std::getline(identity, sensor_name);
        if (sensor_name.starts_with("sc132gs ") &&
            sensor_name.ends_with(address_suffix)) {
            return "/dev/" + name;
        }
    }
    throw AeError(AeErrorCode::device,
                  "SC132GS sensor subdevice " + std::string(address_suffix));
}

int median_luma(std::span<const std::uint8_t> pixels, int width, int height) {
    if (width <= 0 || height <= 0 ||
        pixels.size() != static_cast<std::size_t>(width) * height) {
        throw AeError(AeErrorCode::invalid_argument, "luma frame size");
    }
    std::array<int, 256> histogram{};
    int count = 0;
    for (int y = height / 10; y < height * 9 / 10; y += 8) {
        for (int x = width / 10; x < width * 9 / 10; x += 8) {
            ++histogram[pixels[static_cast<std::size_t>(y) * width + x]];
            ++count;
        }
    }
    int cumulative = 0;
    for (int value = 0; value < 256; ++value) {
        cumulative += histogram[value];
        if (cumulative >= (count + 1) / 2) {
            return (value * 1023 + 127) / 255;
        }
    }
    return 1023;
}

int median_luma10(std::span<const std::uint16_t> pixels, int width, int height) {
    if (width <= 0 || height <= 0 || pixels.size() != static_cast<std::size_t>(width) * height)
        throw AeError(AeErrorCode::invalid_argument, "10-bit luma frame size");
    std::array<int, 1024> histogram{};
    int count = 0;
    const int end_y = std::max(height / 10 + 1, static_cast<int>(height * 9LL / 10));
    const int end_x = std::max(width / 10 + 1, static_cast<int>(width * 9LL / 10));
    for (int y = height / 10; y < end_y; y += 8)
        for (int x = width / 10; x < end_x; x += 8) {
            const auto value = pixels[static_cast<std::size_t>(y) * width + x];
            if (value > 1023) throw AeError(AeErrorCode::invalid_argument, "10-bit luma range");
            ++histogram[value];
            ++count;
        }
    int cumulative = 0;
    for (int value = 0; value < 1024; ++value) {
        cumulative += histogram[value];
        if (cumulative >= (count + 1) / 2) return value;
    }
    return 1023;
}

int xioctl(int fd, unsigned long request, void* argument) {
    int result;
    do {
        result = ::ioctl(fd, request, argument);
    } while (result < 0 && errno == EINTR);
    return result;
}

class SensorDevice final {
public:
    explicit SensorDevice(std::string path) : path_(std::move(path)) {
        fd_ = ::open(path_.c_str(), O_RDWR | O_CLOEXEC);
        if (fd_ < 0) {
            throw AeError(AeErrorCode::device, "open " + path_, errno);
        }
        try {
            (void)limits(V4L2_CID_EXPOSURE);
            (void)limits(V4L2_CID_ANALOGUE_GAIN);
        } catch (...) {
            ::close(fd_);
            throw;
        }
    }
    SensorDevice(const SensorDevice&) = delete;
    SensorDevice& operator=(const SensorDevice&) = delete;
    ~SensorDevice() {
        if (fd_ >= 0) {
            ::close(fd_);
        }
    }

    v4l2_queryctrl limits(std::uint32_t id) const {
        v4l2_queryctrl query{};
        query.id = id;
        if (xioctl(fd_, VIDIOC_QUERYCTRL, &query) < 0 ||
            (query.flags & V4L2_CTRL_FLAG_DISABLED)) {
            throw AeError(AeErrorCode::control,
                          "query control " + path_, errno);
        }
        return query;
    }

    int get(std::uint32_t id) const {
        v4l2_control control{};
        control.id = id;
        if (xioctl(fd_, VIDIOC_G_CTRL, &control) < 0) {
            throw AeError(AeErrorCode::control,
                          "get control " + path_, errno);
        }
        return control.value;
    }

    bool hdr_enabled() const {
        v4l2_control control{};
        control.id = V4L2_CID_WIDE_DYNAMIC_RANGE;
        if (xioctl(fd_, VIDIOC_G_CTRL, &control) == 0)
            return control.value != 0;
        if (errno == EINVAL) return false; // Older linear-only driver.
        throw AeError(AeErrorCode::control, "get HDR mode " + path_, errno);
    }

    void set_hdr(int rows,int second,int ratio=256) const {
        v4l2_ext_control values[3]{};
        values[0].id=V4L2_CID_SC132GS_HDR_TOTAL_ROWS; values[0].value=rows;
        values[1].id=V4L2_CID_SC132GS_HDR_RATIO; values[1].value=ratio;
        values[2].id=V4L2_CID_SC132GS_HDR_SECOND; values[2].value=second;
        v4l2_ext_controls group{}; group.count=3; group.controls=values;
        if(xioctl(fd_,VIDIOC_S_EXT_CTRLS,&group)<0)
            throw AeError(AeErrorCode::control,"HDR exposure tuple "+path_,errno);
    }

    void set(std::uint32_t id, int value) const {
        v4l2_control control{};
        control.id = id;
        control.value = value;
        if (xioctl(fd_, VIDIOC_S_CTRL, &control) < 0) {
            throw AeError(AeErrorCode::control,
                          "set control " + path_, errno);
        }
    }

private:
    std::string path_;
    int fd_{-1};
};

int median_brightness(std::span<const std::uint8_t> raw) {
    if (raw.size() != static_cast<std::size_t>(kStride * kHeight)) {
        throw AeError(AeErrorCode::invalid_argument, "RAW10 frame size");
    }
    std::array<int, 1024> histogram{};
    int count = 0;
    for (int y = kHeight / 10; y < kHeight * 9 / 10; y += 8) {
        for (int x = kWidth / 10; x < kWidth * 9 / 10; x += 8) {
            const int offset = y * kStride + (x / 4) * 5;
            const int value = (raw[offset + (x % 4)] << 2) |
                              ((raw[offset + 4] >> ((x % 4) * 2)) & 3);
            ++histogram[value];
            ++count;
        }
    }
    int cumulative = 0;
    for (int value = 0; value < 1024; ++value) {
        cumulative += histogram[value];
        if (cumulative >= (count + 1) / 2) {
            return value;
        }
    }
    return 1023;
}

int rounded_percent(int raw) {
    return (raw * 100 + 511) / 1023;
}

} // namespace

AeError::AeError(AeErrorCode code, std::string operation, int system_error)
    : std::runtime_error(operation +
                         (system_error ? ": " + std::string(std::strerror(system_error))
                                       : "")),
      code(code),
      system_error(system_error) {}

struct AutoExposure::Impl {
    SensorDevice cam0{sensor_node("-0032")};
    SensorDevice cam1{sensor_node("-0030")};
    mutable std::mutex mutex;
    Snapshot state;
    int minimum_exposure{};
    int maximum_exposure{};
    int minimum_gain{};
    int maximum_gain{};
    int device_maximum_gain{};
    int max_exposure_us{};
    LinearTiming timing;
    bool hdr_mode{};
    bool display_encoded{};
    bool preview_b{};
    int update_counter{};
    sc132gs::hdr_ae::Hysteresis hdr_hysteresis;
    sc132gs::linear_ae::Policy linear_policy;
    std::array<int,4> hdr_statistics_sum{};
    bool priming{};
    std::optional<std::uint32_t> previous_sequence;
    std::optional<std::int64_t> previous_timestamp_ns;
    std::deque<std::int64_t> periods_ns;

    Impl(LumaEncoding encoding, LinearTiming profile) : timing(profile) {
        if (timing.rows_per_second <= 0 || timing.rows_per_second > 1'000'000 ||
            timing.max_exposure_rows < 0 || timing.nominal_fps < 1 || timing.nominal_fps > 120 ||
            timing.control_holdoff_pairs < 0 || timing.control_holdoff_pairs > 120 ||
            timing.reserved_readout_rows<0 ||
            sc132gs::exposure_budget::ceiling(timing.rows_per_second,timing.nominal_fps,timing.reserved_readout_rows)<8)
            throw AeError(AeErrorCode::invalid_argument, "linear timing profile");
        hdr_mode = cam0.hdr_enabled();
        state.hdr_enabled = hdr_mode;
        if (hdr_mode) {
            state.saturation_basis = SaturationBasis::hdr_brightest_twenty_percent;
            state.near_saturation_raw10 = 1020;
        }
        if (!hdr_mode) state.saturation_limit_bp = sc132gs::linear_ae::Settings{}.saturation_limit_bp;
        if (hdr_mode != cam1.hdr_enabled())
            throw AeError(AeErrorCode::control, "stereo HDR modes differ");
        display_encoded = hdr_mode && encoding == LumaEncoding::hdr_display;
        preview_b = hdr_mode && encoding == LumaEncoding::hdr_preview_b;
        state.signal_black_raw10=encoding==LumaEncoding::sensor_signal ? sc132gs::sensor_signal::black_level(hdr_mode) : 0;
        state.display_gamma_x100 = display_encoded ? static_cast<int>(std::lround(
            sc132gs::hdr_profile::display_gamma * 100)) : 100;
        state.display_black_raw10 = display_encoded ? sc132gs::hdr_profile::black_level_raw10 : 0;
        minimum_exposure = std::max(cam0.limits(exposure_control()).minimum,
                                    cam1.limits(exposure_control()).minimum);
        maximum_exposure = std::min(cam0.limits(exposure_control()).maximum,
                                    cam1.limits(exposure_control()).maximum);
        if (!hdr_mode && timing.max_exposure_rows > 0) {
            if (timing.max_exposure_rows < minimum_exposure)
                throw AeError(AeErrorCode::invalid_argument, "linear exposure ceiling");
            maximum_exposure = std::min(maximum_exposure, timing.max_exposure_rows);
        }
        minimum_gain = std::max(cam0.limits(V4L2_CID_ANALOGUE_GAIN).minimum,
                                cam1.limits(V4L2_CID_ANALOGUE_GAIN).minimum);
        maximum_gain = std::min(cam0.limits(V4L2_CID_ANALOGUE_GAIN).maximum,
                     cam1.limits(V4L2_CID_ANALOGUE_GAIN).maximum);
        device_maximum_gain = maximum_gain;
        configure_hdr();
        state.exposure_lines = cam0.get(exposure_control());
        state.analogue_gain_index = cam0.get(V4L2_CID_ANALOGUE_GAIN);
        state.max_exposure_lines = fps_exposure_ceiling();
    }

    std::uint32_t exposure_control() const {
        return hdr_mode ? V4L2_CID_SC132GS_HDR_TOTAL_ROWS : V4L2_CID_EXPOSURE;
    }

    void configure_hdr() {
        if (!hdr_mode) return;
        // Increasing SECOND alone cannot brighten the useful midtones while
        // retaining the knee. Keep the ratio fixed; AE adjusts TOTAL before gain.
        set_hdr_pair(cam0.get(exposure_control()),0);
        set_pair(V4L2_CID_ANALOGUE_GAIN, minimum_gain);
        state.hdr_ratio = SC132GS_HDR_RATIO_DEFAULT;
    }

    void set_hdr_pair(int rows,int second) {
        const int prior_rows=cam0.get(exposure_control());
        const int prior_second=cam0.get(V4L2_CID_SC132GS_HDR_SECOND);
        const int prior_ratio=cam0.get(V4L2_CID_SC132GS_HDR_RATIO);
        cam0.set_hdr(rows,second);
        try { cam1.set_hdr(rows,second); }
        catch(...) { try {cam0.set_hdr(prior_rows,prior_second,prior_ratio);} catch(...) {} throw; }
        state.hdr_second_ticks=second ? second : std::max(1,(rows*16+128)/256);
    }

    std::int64_t frame_period_ns() const {
        if (periods_ns.empty()) {
            return 1'000'000'000LL / timing.nominal_fps;
        }
        auto sorted = periods_ns;
        std::sort(sorted.begin(), sorted.end());
        return sorted[sorted.size() / 2];
    }

    int fps_exposure_ceiling() const {
        // HDR units remain nominal rows, not calibrated microseconds. Lower
        // cadence permits more TOTAL while the driver also enforces VTS-8.
        if (hdr_mode) return std::min(maximum_exposure,
                                     sc132gs::exposure_budget::hdr_ceiling(timing.nominal_fps));
        // The requested cadence owns this deadline. If long exposure drops
        // frames, using measured FPS would enlarge the ceiling again and
        // prevent recovery. Keep measured FPS solely as observable telemetry.
        const int frame_cap=sc132gs::exposure_budget::ceiling(
            timing.rows_per_second,timing.nominal_fps,timing.reserved_readout_rows);
        int cap = std::clamp(frame_cap, minimum_exposure, maximum_exposure);
        if (max_exposure_us > 0) {
            cap = std::min(cap, std::max(minimum_exposure,
                                        static_cast<int>(
                                            1LL * max_exposure_us * timing.rows_per_second /
                                            1'000'000)));
        }
        return cap;
    }

    void set_pair(std::uint32_t control_id, int value) {
        const int prior = cam0.get(control_id);
        cam0.set(control_id, value);
        try {
            cam1.set(control_id, value);
        } catch (...) {
            try {
                cam0.set(control_id, prior);
            } catch (...) {
                // The original control failure remains the primary error.
            }
            throw;
        }
    }

    void observe_period(std::uint32_t sequence, std::int64_t timestamp_ns) {
        if (previous_sequence && previous_timestamp_ns &&
            sequence > *previous_sequence && timestamp_ns > *previous_timestamp_ns) {
            const auto steps = sequence - *previous_sequence;
            const auto period = (timestamp_ns - *previous_timestamp_ns) / steps;
            if (period >= 5'000'000 && period <= 1'500'000'000) {
                periods_ns.push_back(period);
                if (periods_ns.size() > 16) {
                    periods_ns.pop_front();
                }
            }
        }
        previous_sequence = sequence;
        previous_timestamp_ns = timestamp_ns;
        state.fps_x10 = static_cast<int>(
            10'000'000'000LL / frame_period_ns());
        state.max_exposure_lines = fps_exposure_ceiling();
    }

    void update(int raw0, int raw1,
                const sc132gs::linear_ae::HighlightStatistics* highlights0 = nullptr,
                const sc132gs::linear_ae::HighlightStatistics* highlights1 = nullptr) {
        const int cap = state.max_exposure_lines;
        if (state.exposure_lines > cap) {
            set_pair(exposure_control(), cap);
            state.exposure_lines = cap;
            return;
        }
        if (priming) {
            // Start the automatic loop from minimum analogue gain.
            set_pair(V4L2_CID_ANALOGUE_GAIN, minimum_gain);
            state.analogue_gain_index = minimum_gain;
            priming = false;
            return;
        }

        if (!hdr_mode && highlights0 && highlights1) {
            const auto decision = linear_policy.decide(
                {state.target_percent, state.saturation_limit_bp,
                 state.saturation_limit_bp / 2, 3},
                {minimum_exposure, cap, minimum_gain, maximum_gain},
                {state.exposure_lines, state.analogue_gain_index},
                {raw0, raw1, *highlights0, *highlights1});
            if (decision.constraint == sc132gs::linear_ae::Constraint::invalid_statistics)
                throw AeError(AeErrorCode::invalid_argument, "linear AE measurements", EINVAL);
            // Write a decreasing gain before increasing rows during gain/exposure
            // tradeoff. Two sensors still receive sequential control writes.
            if (decision.exposure.gain != state.analogue_gain_index) {
                set_pair(V4L2_CID_ANALOGUE_GAIN, decision.exposure.gain);
                state.analogue_gain_index = decision.exposure.gain;
            }
            if (decision.exposure.rows != state.exposure_lines) {
                set_pair(exposure_control(), decision.exposure.rows);
                state.exposure_lines = decision.exposure.rows;
            }
            state.brightness_limited = decision.brightness_limited;
            state.highlight_limited = decision.highlight_limited;
            state.linear_constraint = decision.constraint;
            state.linear_effective_target_luma10 = decision.effective_target_luma10;
            state.linear_highlight_darkening_ev_x100 = decision.highlight_darkening_ev_x100;
            return;
        }

        const int measured = std::max(1, (raw0 + raw1) / 2);
        if (state.target_percent == 0) {
            set_pair(V4L2_CID_ANALOGUE_GAIN, minimum_gain);
            set_pair(exposure_control(), minimum_exposure);
            state.analogue_gain_index = minimum_gain;
            state.exposure_lines = minimum_exposure;
            state.brightness_limited = measured > 5;
            return;
        }
        const int target = state.target_percent * 1023 / 100;
        const double display_ev = std::log2(static_cast<double>(target) / measured);
        const double ev = display_encoded ?
            display_ev / sc132gs::hdr_profile::display_gamma : display_ev;
        if (std::abs(display_ev) < (hdr_mode ? 0.03 : 0.075) &&
            (state.target_percent != 100 || measured >= 1018)) {
            // Trade gain for exposure after a cap or target change. The vendor
            // gain LUT is approximately 32 indices per EV. Only trade when
            // enough exposure headroom compensates for the gain reduction.
            if (state.analogue_gain_index > minimum_gain &&
                state.exposure_lines < cap) {
                int steps = std::min(2, state.analogue_gain_index - minimum_gain);
                int next_exposure = state.exposure_lines;
                while (steps > 0) {
                    next_exposure = static_cast<int>(std::ceil(
                        state.exposure_lines * std::exp2(steps / 32.0)));
                    if (next_exposure <= cap) break;
                    --steps;
                }
                if (steps > 0) {
                    set_pair(exposure_control(), next_exposure);
                    state.exposure_lines = next_exposure;
                    set_pair(V4L2_CID_ANALOGUE_GAIN,
                             state.analogue_gain_index - steps);
                    state.analogue_gain_index -= steps;
                }
            }
            state.brightness_limited = false;
            return;
        }

        if (ev > 0) {
            if (state.exposure_lines < cap) {
                const int next = std::min(
                    cap, std::max(state.exposure_lines + 1,
                                  static_cast<int>(std::lround(
                                      state.exposure_lines *
                                      std::exp2(std::min(ev, 0.25))))));
                set_pair(exposure_control(), next);
                state.exposure_lines = next;
            } else if (state.analogue_gain_index < maximum_gain) {
                const int step = std::clamp(
                    static_cast<int>(std::lround(ev * 12)), 1, 4);
                const int next = std::min(maximum_gain,
                                          state.analogue_gain_index + step);
                set_pair(V4L2_CID_ANALOGUE_GAIN, next);
                state.analogue_gain_index = next;
            } else {
                state.brightness_limited = true;
                return;
            }
        } else {
            if (state.analogue_gain_index > minimum_gain) {
                const int step = std::clamp(
                    static_cast<int>(std::lround(-ev * 12)), 1, 4);
                const int next = std::max(minimum_gain,
                                          state.analogue_gain_index - step);
                set_pair(V4L2_CID_ANALOGUE_GAIN, next);
                state.analogue_gain_index = next;
            } else if (state.exposure_lines > minimum_exposure) {
                const int next = std::max(
                    minimum_exposure,
                    std::min(state.exposure_lines - 1,
                             static_cast<int>(std::lround(
                                 state.exposure_lines *
                                 std::exp2(std::max(ev, -0.25))))));
                set_pair(exposure_control(), next);
                state.exposure_lines = next;
            } else {
                state.brightness_limited = true;
                return;
            }
        }
        state.brightness_limited = false;
    }

    void process_measured(int raw0, int raw1,
                          std::uint32_t cam0_sequence,
                          std::int64_t cam0_timestamp_ns,
                          const sc132gs::linear_ae::HighlightStatistics* highlights0 = nullptr,
                          const sc132gs::linear_ae::HighlightStatistics* highlights1 = nullptr) {
        std::lock_guard guard(mutex);
        state.cam0_percent = rounded_percent(raw0);
        state.cam1_percent = rounded_percent(raw1);
        const bool raw_highlights = !hdr_mode && highlights0 && highlights1;
        if (raw_highlights) {
            state.cam0_saturation_bp = sc132gs::linear_ae::saturation_bp(*highlights0);
            state.cam1_saturation_bp = sc132gs::linear_ae::saturation_bp(*highlights1);
            state.saturation_basis = SaturationBasis::linear_full_raw_frame;
            state.near_saturation_raw10 = sc132gs::linear_ae::near_saturation_raw10;
        } else if (!hdr_mode) {
            state.saturation_basis = SaturationBasis::unavailable;
            state.near_saturation_raw10 = 0;
            state.cam0_saturation_bp = state.cam1_saturation_bp = 0;
            state.highlight_limited = false;
            state.linear_constraint = sc132gs::linear_ae::Constraint::none;
            state.linear_effective_target_luma10 = 0;
            state.linear_highlight_darkening_ev_x100 = 0;
        }
        observe_period(cam0_sequence, cam0_timestamp_ns);
        // Manual commands also need settling. Counting must continue with AE
        // disabled, otherwise depth would remain withheld indefinitely.
        if (raw_highlights && state.remaining_holdoff_pairs > 0) {
            --state.remaining_holdoff_pairs;
            return;
        }
        const int update_every = std::clamp(static_cast<int>(std::lround(
            1'000'000'000.0 / frame_period_ns() / 15)), 1, kUpdateEveryPairs);
        if (!state.enabled || ++update_counter < update_every) {
            return;
        }
        update_counter = 0;
        const auto prior_rows = state.exposure_lines;
        const auto prior_gain = state.analogue_gain_index;
        try {
            update(raw0, raw1, highlights0, highlights1);
        } catch (const AeError& error) {
            state.enabled = false;
            state.last_error = error.system_error ? error.system_error : EIO;
        }
        if (raw_highlights && (prior_rows != state.exposure_lines || prior_gain != state.analogue_gain_index)) {
            ++state.command_generation;
            state.last_command_input_sequence = cam0_sequence;
            state.command_sequence_valid = true;
            state.remaining_holdoff_pairs = timing.control_holdoff_pairs;
        }
    }
};

AutoExposure::AutoExposure(LumaEncoding encoding)
    : AutoExposure(encoding, LinearTiming{}) {}
AutoExposure::AutoExposure(LumaEncoding encoding, LinearTiming timing)
    : impl_(std::make_unique<Impl>(encoding, timing)) {}
AutoExposure::~AutoExposure() = default;
AutoExposure::AutoExposure(AutoExposure&&) noexcept = default;
AutoExposure& AutoExposure::operator=(AutoExposure&&) noexcept = default;

void AutoExposure::set_target(int percent) {
    if (percent < 0 || percent > 100) {
        throw AeError(AeErrorCode::invalid_argument, "target brightness must be 0..100");
    }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->state.enabled) {
        impl_->configure_hdr();
        impl_->state.exposure_lines = impl_->cam0.get(impl_->exposure_control());
        impl_->state.analogue_gain_index =
            impl_->cam0.get(V4L2_CID_ANALOGUE_GAIN);
        impl_->priming = true;
    }
    impl_->hdr_hysteresis={}; impl_->hdr_statistics_sum={}; impl_->update_counter=0;
    impl_->linear_policy.reset();
    impl_->state.highlight_limited = false;
    impl_->state.linear_constraint = sc132gs::linear_ae::Constraint::none;
    impl_->state.target_percent = percent;
    impl_->state.enabled = true;
    impl_->state.brightness_limited = false;
    impl_->state.last_error = 0;
}

void AutoExposure::set_max_exposure_us(int microseconds) {
    if (microseconds < 0 || microseconds > 40'000) {
        throw AeError(AeErrorCode::invalid_argument,
                      "max exposure must be 0..40000 us");
    }
    std::lock_guard lock(impl_->mutex);
    if (impl_->hdr_mode && microseconds > 0)
        throw AeError(AeErrorCode::control,
                      "HDR exposure time conversion is not characterized", EOPNOTSUPP);
    impl_->max_exposure_us = microseconds;
    impl_->state.max_exposure_lines = impl_->fps_exposure_ceiling();
}

void AutoExposure::disable() {
    std::lock_guard lock(impl_->mutex);
    impl_->state.enabled = false;
}

void AutoExposure::set_hdr_saturation_limit(int percent) {
    std::lock_guard guard(impl_->mutex);
    if(percent<0 || percent>100 || !impl_->hdr_mode)
        throw AeError(AeErrorCode::invalid_argument,"HDR saturation limit",EINVAL);
    impl_->state.saturation_limit_bp=percent*100;
    impl_->hdr_hysteresis={}; impl_->hdr_statistics_sum={}; impl_->update_counter=0;
}


void AutoExposure::process_hdr_statistics(sc132gs::hdr_ae::Statistics left,
        sc132gs::hdr_ae::Statistics right,std::uint32_t sequence,std::int64_t timestamp_ns) {
    std::lock_guard guard(impl_->mutex);
    auto& state=impl_->state;
    if(!impl_->hdr_mode || left.shadow<0 || left.shadow>1023 ||
       right.shadow<0 || right.shadow>1023 || left.saturation_bp<0 ||
       left.saturation_bp>10000 || right.saturation_bp<0 || right.saturation_bp>10000)
        throw AeError(AeErrorCode::invalid_argument,"HDR statistics",EINVAL);
    // Sensor profiles share Linear's P50 meter. The opt-in B display profile
    // retains its historical P40 calibration; clipping remains independent.
    const int left_luma=left.luma_median, right_luma=right.luma_median;
    if(left_luma>1023 || right_luma>1023 || left_luma< -1 || right_luma< -1)
        throw AeError(AeErrorCode::invalid_argument,"HDR luma statistics",EINVAL);
    left=sc132gs::hdr_ae::summarize(left.histogram,impl_->preview_b);
    right=sc132gs::hdr_ae::summarize(right.histogram,impl_->preview_b);
    if(!impl_->preview_b) {
        if(left_luma>=0) left.shadow=left_luma;
        if(right_luma>=0) right.shadow=right_luma;
    }
    state.cam0_shadow_raw10=left.shadow; state.cam1_shadow_raw10=right.shadow;
    if(state.signal_black_raw10) {
        left.shadow=sc132gs::sensor_signal::luma10(left.shadow,state.signal_black_raw10);
        right.shadow=sc132gs::sensor_signal::luma10(right.shadow,state.signal_black_raw10);
    }
    state.display_gamma_x100=impl_->preview_b ? sc132gs::HdrDisplay::gamma_x100 : 100;
    state.display_black_raw10=impl_->preview_b ? sc132gs::HdrDisplay::black : 0;
    state.cam0_percent=impl_->preview_b ? sc132gs::HdrDisplay::displayed_percent(left.shadow) : rounded_percent(left.shadow);
    state.cam1_percent=impl_->preview_b ? sc132gs::HdrDisplay::displayed_percent(right.shadow) : rounded_percent(right.shadow);
    state.cam0_saturation_bp=left.saturation_bp; state.cam1_saturation_bp=right.saturation_bp;
    state.saturation_basis=SaturationBasis::hdr_brightest_twenty_percent;
    state.near_saturation_raw10=1020;
    impl_->observe_period(sequence,timestamp_ns);
    if(!state.enabled) return;
    ++impl_->update_counter;
    if(impl_->update_counter<=3) return; // Discard N+2 activation/settling frames.
    auto& sums=impl_->hdr_statistics_sum;
    sums[0]+=left.shadow; sums[1]+=right.shadow;
    sums[2]+=left.saturation_bp; sums[3]+=right.saturation_bp;
    if(impl_->update_counter<12) return; // Average nine settled pairs, update ~2.5 Hz.
    left.shadow=sums[0]/9; right.shadow=sums[1]/9;
    left.saturation_bp=(sums[2]+8)/9; right.saturation_bp=(sums[3]+8)/9;
    sums={}; impl_->update_counter=0;
    try {
        const auto decision=sc132gs::hdr_ae::decide(
            {state.target_percent,state.saturation_limit_bp,impl_->preview_b},
            {impl_->minimum_exposure,state.max_exposure_lines,impl_->maximum_gain},
            {state.exposure_lines,state.hdr_second_ticks,state.analogue_gain_index},left,right,&impl_->hdr_hysteresis);
        const auto next=decision.exposure;
        if(next.total_rows!=state.exposure_lines || next.second_ticks!=state.hdr_second_ticks)
            impl_->set_hdr_pair(next.total_rows,next.second_ticks);
        if(next.gain!=state.analogue_gain_index) impl_->set_pair(V4L2_CID_ANALOGUE_GAIN,next.gain);
        state.exposure_lines=next.total_rows; state.analogue_gain_index=next.gain;
        state.brightness_limited=decision.shadow_limited;
        state.highlight_limited=decision.highlight_limited;
    } catch(const AeError& error) {
        state.enabled=false; state.last_error=error.system_error ? error.system_error : EIO;
    }
}

void AutoExposure::configure(const Configuration& config) {
    std::lock_guard guard(impl_->mutex);
    if (config.target_percent < 0 || config.target_percent > 100 ||
        config.max_exposure_us < 0 || config.max_exposure_us > 40000 ||
        config.max_gain_index < impl_->minimum_gain ||
        config.max_gain_index > impl_->device_maximum_gain ||
        config.gain_index < impl_->minimum_gain ||
        config.gain_index > config.max_gain_index ||
        config.exposure_rows < impl_->minimum_exposure ||
        config.exposure_rows > impl_->maximum_exposure)
        throw AeError(AeErrorCode::invalid_argument, "exposure configuration", EINVAL);
    if (impl_->hdr_mode && config.max_exposure_us > 0)
        throw AeError(AeErrorCode::control, "HDR time conversion is uncharacterized", EOPNOTSUPP);
    const auto previous = impl_->state;
    const int prior_us = impl_->max_exposure_us;
    const int prior_max_gain = impl_->maximum_gain;
    impl_->max_exposure_us = config.max_exposure_us;
    impl_->maximum_gain = config.max_gain_index;
    const int ceiling = impl_->fps_exposure_ceiling();
    if (!config.enabled && config.exposure_rows > ceiling) {
        impl_->max_exposure_us = prior_us;
        impl_->maximum_gain = prior_max_gain;
        throw AeError(AeErrorCode::invalid_argument, "manual exposure exceeds ceiling", ERANGE);
    }
    try {
        if(impl_->hdr_mode)
            impl_->set_hdr_pair(std::min(config.exposure_rows,ceiling),config.enabled ?
                std::clamp(impl_->cam0.get(V4L2_CID_SC132GS_HDR_SECOND),1,std::min(config.exposure_rows,ceiling)*16-1) : 0);
        else impl_->set_pair(impl_->exposure_control(), std::min(config.exposure_rows, ceiling));
        impl_->set_pair(V4L2_CID_ANALOGUE_GAIN, config.gain_index);
    } catch (...) {
        impl_->max_exposure_us = prior_us;
        impl_->maximum_gain = prior_max_gain;
        try {
            if(impl_->hdr_mode) impl_->set_hdr_pair(previous.exposure_lines,previous.hdr_second_ticks);
            else impl_->set_pair(impl_->exposure_control(), previous.exposure_lines);
            impl_->set_pair(V4L2_CID_ANALOGUE_GAIN, previous.analogue_gain_index);
        } catch (...) {
            impl_->state.enabled = false;
            impl_->state.last_error = EIO;
        }
        throw;
    }
    impl_->state.enabled = config.enabled;
    impl_->state.target_percent = config.target_percent;
    impl_->state.exposure_lines = std::min(config.exposure_rows, ceiling);
    impl_->state.analogue_gain_index = config.gain_index;
    impl_->state.max_exposure_lines = ceiling;
    impl_->state.brightness_limited = false;
    impl_->state.last_error = 0;
    impl_->update_counter = 0;
    impl_->hdr_statistics_sum={}; impl_->hdr_hysteresis={};
    impl_->linear_policy.reset();
    impl_->state.linear_constraint = sc132gs::linear_ae::Constraint::none;
    if (!impl_->hdr_mode) {
        ++impl_->state.command_generation;
        impl_->state.command_sequence_valid = false;
        impl_->state.remaining_holdoff_pairs = impl_->timing.control_holdoff_pairs;
    }
    impl_->state.highlight_limited=false;
    impl_->priming = false;
}

AutoExposure::Snapshot AutoExposure::snapshot() const {
    std::lock_guard lock(impl_->mutex);
    auto state = impl_->state;
    state.max_exposure_us = impl_->max_exposure_us;
    state.max_gain_index = impl_->maximum_gain;
    if (!state.enabled) {
        state.exposure_lines = impl_->cam0.get(impl_->exposure_control());
        state.analogue_gain_index = impl_->cam0.get(V4L2_CID_ANALOGUE_GAIN);
    }
    if (impl_->hdr_mode) {
        state.hdr_ratio = impl_->cam0.get(V4L2_CID_SC132GS_HDR_RATIO);
        const int second=impl_->cam0.get(V4L2_CID_SC132GS_HDR_SECOND);
        state.hdr_second_ticks=second ? second : std::max(1,(state.exposure_lines*16+128)/256);
    }
    return state;
}

void AutoExposure::process(std::span<const std::uint8_t> cam0,
                           std::span<const std::uint8_t> cam1,
                           std::uint32_t cam0_sequence,
                           std::int64_t cam0_timestamp_ns) {
    if(impl_->hdr_mode) {
        process_hdr_statistics(sc132gs::hdr_ae::measure_raw10(cam0,kWidth,kHeight,kStride),
            sc132gs::hdr_ae::measure_raw10(cam1,kWidth,kHeight,kStride),
            cam0_sequence,cam0_timestamp_ns);
        return;
    }
    const auto measure = [this](std::span<const std::uint8_t> raw) {
        const int value = median_brightness(raw);
        return impl_->display_encoded ? static_cast<int>(std::lround(
            1023 * sc132gs::hdr_profile::display(value / 1023.0))) : value;
    };
    const int raw0 = measure(cam0);
    const int raw1 = measure(cam1);
    impl_->process_measured(raw0, raw1, cam0_sequence, cam0_timestamp_ns);
}

void AutoExposure::process_luma(std::span<const std::uint8_t> cam0,
                                std::span<const std::uint8_t> cam1,
                                int width, int height,
                                std::uint32_t cam0_sequence,
                                std::int64_t cam0_timestamp_ns) {
    const int raw0 = median_luma(cam0, width, height);
    const int raw1 = median_luma(cam1, width, height);
    impl_->process_measured(raw0, raw1, cam0_sequence, cam0_timestamp_ns);
}

void AutoExposure::process_luma10(std::span<const std::uint16_t> cam0,
                                  std::span<const std::uint16_t> cam1,
                                  int width, int height, std::uint32_t sequence,
                                  std::int64_t timestamp_ns) {
    const auto measure = [this, width, height](std::span<const std::uint16_t> pixels) {
        const int value = median_luma10(pixels, width, height);
        // Only transform the statistic: the R16 camera frames remain unchanged.
        // process_luma() already receives display-encoded HDR gray; this
        // 10-bit entry point receives unmodified sensor gray codes instead.
        return impl_->display_encoded ? static_cast<int>(std::lround(
            1023 * sc132gs::hdr_profile::display(value / 1023.0))) : value;
    };
    impl_->process_measured(measure(cam0),measure(cam1),sequence,timestamp_ns);
}

void AutoExposure::process_linear_luma10(std::span<const std::uint16_t> cam0,
        std::span<const std::uint16_t> cam1, int width, int height,
        sc132gs::linear_ae::HighlightStatistics raw_cam0,
        sc132gs::linear_ae::HighlightStatistics raw_cam1,
        std::uint32_t sequence, std::int64_t timestamp_ns) {
    if (impl_->hdr_mode || !sc132gs::linear_ae::valid(raw_cam0) ||
        !sc132gs::linear_ae::valid(raw_cam1))
        throw AeError(AeErrorCode::invalid_argument, "linear RAW highlight statistics", EINVAL);
    const auto expected = width > 0 && height > 0 ?
        static_cast<std::uint64_t>(width) * height : 0;
    if (!sc132gs::linear_ae::valid_stereo_coverage(raw_cam0, raw_cam1, expected))
        throw AeError(AeErrorCode::invalid_argument, "linear RAW highlight coverage", EINVAL);
    impl_->process_measured(median_luma10(cam0, width, height), median_luma10(cam1, width, height),
                            sequence, timestamp_ns, &raw_cam0, &raw_cam1);
}
