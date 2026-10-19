#pragma once

#include <algorithm>
#include <cstdint>
#include <stdexcept>

namespace sc132gs::detail {

// Monotonic nanoseconds. Keep the nominal phase under ordinary scheduler
// jitter, but skip expired slots rather than emitting catch-up pulses.
class FsyncSchedule final {
public:
    FsyncSchedule(std::int64_t period, std::int64_t pulse)
        : period_(period), pulse_(pulse), jitter_(std::min<std::int64_t>(period / 100, 100'000)) {
        if (period <= 0 || pulse <= 0 || pulse >= period)
            throw std::invalid_argument("invalid FSYNC period/pulse");
    }
    FsyncSchedule(const FsyncSchedule&) = delete;
    FsyncSchedule& operator=(const FsyncSchedule&) = delete;
    FsyncSchedule(FsyncSchedule&&) = default;
    FsyncSchedule& operator=(FsyncSchedule&&) = default;

    std::int64_t asserted(std::int64_t planned_ns, std::int64_t completed_ns) noexcept {
        next_ = planned_ns + period_;
        skip_before(completed_ns + period_ - jitter_);
        return completed_ns + pulse_;
    }
    std::int64_t deasserted(std::int64_t completed_ns) noexcept {
        skip_before(completed_ns + period_ - pulse_ - jitter_);
        return next_;
    }

private:
    void skip_before(std::int64_t earliest) noexcept {
        if (next_ < earliest)
            next_ += ((earliest - next_ + period_ - 1) / period_) * period_;
    }
    std::int64_t period_;
    std::int64_t pulse_;
    std::int64_t jitter_;
    std::int64_t next_{};
};

} // namespace sc132gs::detail
