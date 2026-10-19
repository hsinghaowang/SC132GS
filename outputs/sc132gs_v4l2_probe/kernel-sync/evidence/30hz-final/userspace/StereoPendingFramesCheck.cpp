#include "StereoPendingFrames.hpp"
#include "CaptureProgress.hpp"

#include <chrono>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
struct Frame {
    std::uint32_t sequence;
    std::int64_t timestamp_ns;
    std::unique_ptr<std::uint32_t> payload;
};
using Queue = stereo_rtsp::detail::StereoPendingFrames<Frame>;
using Progress = stereo_rtsp::detail::CaptureProgress;

void require(bool condition, const char* detail) {
    if (!condition) throw std::runtime_error(detail);
}
Frame frame(std::uint32_t sequence, std::int64_t timestamp) {
    return {sequence, timestamp, std::make_unique<std::uint32_t>(sequence)};
}

void recover_missing_eye(int fps, unsigned missing_eye) {
    const std::int64_t period = 1'000'000'000LL / fps;
    Queue queue(500'000);
    for (unsigned index = 0; index < 10; ++index) {
        queue.enqueue(0, frame(index, index * period));
        queue.enqueue(1, frame(index, index * period + 100'000));
        auto result = queue.take();
        auto* pair = std::get_if<Queue::Pair>(&result);
        require(pair && (*pair)[0].sequence == index && (*pair)[1].sequence == index,
                "normal stereo pairing changed");
    }
    // Replay the observed 549 ms absence, extended to 1.5 seconds. The old
    // 32-frame fatal condition is crossed at both configured frame rates.
    const unsigned last = 10 + fps * 3 / 2;
    for (unsigned index = 10; index <= last; ++index) {
        queue.enqueue(1 - missing_eye, frame(index, index * period));
        require(queue.depth(1 - missing_eye) <= 32, "pending payload grew without bound");
        require(std::holds_alternative<std::monostate>(queue.take()),
                "a stereo pair was fabricated while one eye was absent");
    }
    require(queue.capacity_discarded(1 - missing_eye) != 0,
            "fixture did not cross the historical overrun boundary");
    queue.enqueue(missing_eye, frame(last, last * period + 100'000));
    auto result = queue.take();
    auto* pair = std::get_if<Queue::Pair>(&result);
    require(pair && (*pair)[0].sequence == last && (*pair)[1].sequence == last,
            "returning eye did not resume current timestamp pairing");
    require(*(*pair)[0].payload == last && *(*pair)[1].payload == last,
            "frame ownership/payload was corrupted");
    require(queue.depth(0) == 0 && queue.depth(1) == 0,
            "stale frames were retained after recovery");
}

void independent_deadlines() {
    const auto began = Progress::Clock::time_point{};
    for (unsigned missing = 0; missing < 2; ++missing) {
        Progress progress(began);
        progress.received(0, began);
        progress.received(1, began);
        progress.paired();
        for (int millisecond = 1; millisecond <= 3000; ++millisecond) {
            const auto now = began + std::chrono::milliseconds(millisecond);
            progress.received(1 - missing, now);
            require(progress.stalled_eyes(now) == (millisecond < 3000 ? 0 : (1u << missing)),
                    "healthy camera postponed missing camera deadline");
        }
        const auto resumed = began + std::chrono::milliseconds(3001);
        progress.received(missing, resumed);
        require(progress.stalled_eyes(resumed) == 0, "dequeue did not clear its own deadline");
    }
    Progress startup(began);
    startup.set_startup_timeout(std::chrono::seconds(15));
    require(startup.stalled_eyes(began + std::chrono::seconds(14)) == 0,
            "experimental profile startup grace was lost");
    require(startup.stalled_eyes(began + std::chrono::seconds(15)) == 3,
            "both absent cameras were not reported");
    startup.received(0, began + std::chrono::seconds(15));
    startup.received(1, began + std::chrono::seconds(15));
    startup.paired();
    require(startup.stalled_eyes(began + std::chrono::seconds(18)) == 3,
            "runtime deadline retained startup grace");
}

void reject_unpairable_streams() {
    Queue queue(500'000);
    for (unsigned index = 0; index <= 300; ++index) {
        const auto timestamp = static_cast<std::int64_t>(index) * 33'333'333;
        queue.enqueue(0, frame(index, timestamp));
        queue.enqueue(1, frame(index, timestamp + 10'000'000));
        auto result = queue.take();
        if (std::holds_alternative<Queue::PairingError>(result)) return;
        require(std::holds_alternative<std::monostate>(result),
                "mismatched timestamps produced a pair");
    }
    throw std::runtime_error("persistent timestamp mismatch was silently accepted");
}
void exact_trigger_pairing() {
    Queue queue(0);
    queue.enqueue(0, frame(10, 1'000'000));
    queue.enqueue(1, frame(3, 1'001'000));
    require(std::holds_alternative<std::monostate>(queue.take()),
            "exact trigger pairing accepted a one-microsecond mismatch");
    queue.enqueue(0, frame(11, 1'001'000));
    auto result = queue.take();
    auto* pair = std::get_if<Queue::Pair>(&result);
    require(pair && (*pair)[0].sequence == 11 && (*pair)[1].sequence == 3,
            "exact trigger pairing incorrectly used local sequence numbers");
    queue.require_contiguous_pairs();
    queue.enqueue(0, frame(12, 2'000'000));
    queue.enqueue(1, frame(4, 2'000'001));
    require(std::holds_alternative<Queue::PairingError>(queue.take()),
            "locked trigger stream silently discarded a mismatch");
    Queue bounded(0, 1);
    bounded.require_contiguous_pairs();
    bounded.enqueue(0, frame(0, 0));
    require(bounded.enqueue(0, frame(1, 1)) == Queue::EnqueueResult::overflow,
            "locked trigger stream silently discarded an overflow");
}
} // namespace

int main() {
    try {
        for (const int fps : {30, 60})
            for (unsigned missing = 0; missing < 2; ++missing)
                recover_missing_eye(fps, missing);
        independent_deadlines();
        reject_unpairable_streams();
        exact_trigger_pairing();
        std::cout << "passed: both-eye 30/60 FPS gap recovery, bounded ownership, "
                     "independent deadlines, timestamp mismatch rejection\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
