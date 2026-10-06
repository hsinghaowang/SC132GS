// SPDX-License-Identifier: GPL-2.0-only
#include "sc132gs-ae.hpp"

#include <linux/videodev2.h>

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
constexpr int kLineRate = 84000; // 63 MHz pixel rate / 750-pixel HTS
constexpr std::int64_t kDefaultPeriodNs = 16'666'667;
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
    int minimum_exposure;
    int maximum_exposure;
    int minimum_gain;
    int maximum_gain;
    int max_exposure_us{};
    bool hdr_mode{};
    int update_counter{};
    bool priming{};
    std::optional<std::uint32_t> previous_sequence;
    std::optional<std::int64_t> previous_timestamp_ns;
    std::deque<std::int64_t> periods_ns;

    Impl()
        : minimum_exposure(std::max(cam0.limits(V4L2_CID_EXPOSURE).minimum,
                                    cam1.limits(V4L2_CID_EXPOSURE).minimum)),
          maximum_exposure(std::min(cam0.limits(V4L2_CID_EXPOSURE).maximum,
                                    cam1.limits(V4L2_CID_EXPOSURE).maximum)),
          minimum_gain(std::max(cam0.limits(V4L2_CID_ANALOGUE_GAIN).minimum,
                                cam1.limits(V4L2_CID_ANALOGUE_GAIN).minimum)),
          maximum_gain(std::min(cam0.limits(V4L2_CID_ANALOGUE_GAIN).maximum,
                                cam1.limits(V4L2_CID_ANALOGUE_GAIN).maximum)) {
        hdr_mode = cam0.hdr_enabled();
        state.hdr_enabled = hdr_mode;
        if (hdr_mode != cam1.hdr_enabled())
            throw AeError(AeErrorCode::control, "stereo HDR modes differ");
        state.exposure_lines = cam0.get(V4L2_CID_EXPOSURE);
        state.analogue_gain_index = cam0.get(V4L2_CID_ANALOGUE_GAIN);
        state.max_exposure_lines = fps_exposure_ceiling();
    }

    std::int64_t frame_period_ns() const {
        if (periods_ns.empty()) {
            return kDefaultPeriodNs;
        }
        auto sorted = periods_ns;
        std::sort(sorted.begin(), sorted.end());
        return sorted[sorted.size() / 2];
    }

    int fps_exposure_ceiling() const {
        // HDR exposure uses vendor-specific units at 0x3e31/32. Respect the
        // driver's validated bound rather than reuse linear-mode line timing.
        if (hdr_mode) return maximum_exposure;
        // The trigger rate is an integer FPS. Quantize the measured interval
        // before deriving its exposure ceiling so timestamp jitter does not
        // make the limit (and exposure register) oscillate every few frames.
        const int fps = std::clamp(static_cast<int>(std::lround(
                                       1'000'000'000.0 / frame_period_ns())),
                                   1, 120);
        const int frame_cap = kLineRate * 95 / (fps * 100);
        int cap = std::clamp(frame_cap, minimum_exposure, maximum_exposure);
        if (max_exposure_us > 0) {
            cap = std::min(cap, std::max(minimum_exposure,
                                        static_cast<int>(
                                            1LL * max_exposure_us * kLineRate /
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
            if (period >= 5'000'000 && period <= 100'000'000) {
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

    void update(int raw0, int raw1) {
        const int cap = state.max_exposure_lines;
        if (state.exposure_lines > cap) {
            set_pair(V4L2_CID_EXPOSURE, cap);
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

        const int measured = std::max(1, (raw0 + raw1) / 2);
        const int target = state.target_percent * 1023 / 100;
        const double ev = std::log2(static_cast<double>(target) / measured);
        if (std::abs(ev) < 0.075) {
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
                    set_pair(V4L2_CID_EXPOSURE, next_exposure);
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
                set_pair(V4L2_CID_EXPOSURE, next);
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
                set_pair(V4L2_CID_EXPOSURE, next);
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
                          std::int64_t cam0_timestamp_ns) {
        std::lock_guard guard(mutex);
        state.cam0_percent = rounded_percent(raw0);
        state.cam1_percent = rounded_percent(raw1);
        observe_period(cam0_sequence, cam0_timestamp_ns);
        if (!state.enabled || ++update_counter < kUpdateEveryPairs) {
            return;
        }
        update_counter = 0;
        try {
            update(raw0, raw1);
        } catch (const AeError& error) {
            state.enabled = false;
            state.last_error = error.system_error ? error.system_error : EIO;
        }
    }
};

AutoExposure::AutoExposure() : impl_(std::make_unique<Impl>()) {}
AutoExposure::~AutoExposure() = default;
AutoExposure::AutoExposure(AutoExposure&&) noexcept = default;
AutoExposure& AutoExposure::operator=(AutoExposure&&) noexcept = default;

void AutoExposure::set_target(int percent) {
    if (percent < 1 || percent > 90) {
        throw AeError(AeErrorCode::invalid_argument, "target brightness must be 1..90");
    }
    std::lock_guard lock(impl_->mutex);
    if (!impl_->state.enabled) {
        impl_->state.exposure_lines = impl_->cam0.get(V4L2_CID_EXPOSURE);
        impl_->state.analogue_gain_index =
            impl_->cam0.get(V4L2_CID_ANALOGUE_GAIN);
        impl_->priming = true;
    }
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

AutoExposure::Snapshot AutoExposure::snapshot() const {
    std::lock_guard lock(impl_->mutex);
    auto state = impl_->state;
    if (!state.enabled) {
        state.exposure_lines = impl_->cam0.get(V4L2_CID_EXPOSURE);
        state.analogue_gain_index = impl_->cam0.get(V4L2_CID_ANALOGUE_GAIN);
    }
    return state;
}

void AutoExposure::process(std::span<const std::uint8_t> cam0,
                           std::span<const std::uint8_t> cam1,
                           std::uint32_t cam0_sequence,
                           std::int64_t cam0_timestamp_ns) {
    const int raw0 = median_brightness(cam0);
    const int raw1 = median_brightness(cam1);
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
