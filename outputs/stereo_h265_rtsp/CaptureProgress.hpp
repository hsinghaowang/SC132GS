#pragma once

#include <array>
#include <chrono>
#include <cstdint>
#include <optional>

namespace stereo_rtsp::detail {

// Time advances independently of poll readiness. A readable healthy camera
// cannot reset the missing camera's deadline. Hardware access belongs elsewhere.
class CaptureProgress final {
public:
    using Clock = std::chrono::steady_clock;
    explicit CaptureProgress(Clock::time_point started) : started_(started) {}
    CaptureProgress(const CaptureProgress&) = delete;
    CaptureProgress& operator=(const CaptureProgress&) = delete;
    CaptureProgress(CaptureProgress&&) = default;
    CaptureProgress& operator=(CaptureProgress&&) = default;

    void set_startup_timeout(std::chrono::seconds timeout) noexcept {
        startup_timeout_ = timeout;
    }
    void received(unsigned eye, Clock::time_point now) { last_.at(eye) = now; }
    void paired() noexcept { have_pair_ = true; }
    std::int64_t age_ms(unsigned eye, Clock::time_point now) const {
        const auto& last = last_.at(eye);
        return last ? std::chrono::duration_cast<std::chrono::milliseconds>(
                          now - *last).count() : -1;
    }
    std::uint8_t stalled_eyes(Clock::time_point now) const noexcept {
        const auto limit = have_pair_ ? std::chrono::seconds(3) : startup_timeout_;
        std::uint8_t result = 0;
        for (unsigned eye = 0; eye < last_.size(); ++eye)
            if (now - last_[eye].value_or(started_) >= limit)
                result |= static_cast<std::uint8_t>(1u << eye);
        return result;
    }

private:
    Clock::time_point started_;
    std::array<std::optional<Clock::time_point>, 2> last_;
    std::chrono::seconds startup_timeout_{3};
    bool have_pair_{};
};

} // namespace stereo_rtsp::detail
