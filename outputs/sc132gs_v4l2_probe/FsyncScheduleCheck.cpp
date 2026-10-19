#include "FsyncSchedule.hpp"

#include <iostream>
#include <array>
#include <stdexcept>

namespace {
void require(bool condition) {
    if (!condition) throw std::runtime_error("FSYNC scheduling invariant failed");
}
}

int main() {
    constexpr std::int64_t period = 16'666'667, pulse = 100'000;
    sc132gs::detail::FsyncSchedule schedule(period, pulse);
    std::int64_t next = 100'000'000;
    for (const auto delay : {0LL, 50'000LL, 300'000'000LL, 2'000'000'000LL}) {
        const auto actual = next + delay;
        const auto planned = next;
        const auto end = schedule.asserted(planned, actual);
        require(end - actual >= pulse);
        next = schedule.deasserted(end);
        require(next - actual >= period - 100'000);
        require((next - planned) % period == 0);
        // Slow GPIO deassertion also cannot compress the inactive interval.
        next = schedule.deasserted(end + period * 3);
        require(next - (end + period * 3) >= period - pulse - 100'000);
        require(next > actual);
    }
    next = 100'000'000;
    const auto phase = next;
    for (int i = 0; i < 60'000; ++i) {
        const auto end = schedule.asserted(next, next + 50'000);
        next = schedule.deasserted(end + 20'000);
    }
    require(next == phase + period * 60'000); // No accumulated timing drift.
    for (const auto invalid : std::array<std::int64_t, 4>{0, -1, period, period + 1}) {
        bool rejected = false;
        try { sc132gs::detail::FsyncSchedule bad(period, invalid); }
        catch (const std::invalid_argument&) { rejected = true; }
        require(rejected);
    }
    std::cout << "FSYNC late wakeup, slow GPIO, and pulse bounds passed\n";
}
