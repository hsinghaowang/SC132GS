#pragma once

#include <array>
#include <cstdint>
#include <deque>
#include <stdexcept>
#include <utility>
#include <variant>

namespace stereo_rtsp::detail {

// Capture-thread-only ownership of unmatched frames. A missing eye must not
// turn the healthy eye into an unbounded producer or manufacture stereo pairs.
template<class Frame>
class StereoPendingFrames final {
public:
    enum class EnqueueResult { queued, oldest_discarded, overflow };
    struct PairingError { std::int64_t delta_ns; };
    using Pair = std::array<Frame, 2>;
    using Result = std::variant<std::monostate, Pair, PairingError>;

    explicit StereoPendingFrames(std::int64_t maximum_delta_ns,
                                 std::size_t capacity = 32)
        : maximum_delta_ns_(maximum_delta_ns), capacity_(capacity) {
        if (maximum_delta_ns < 0 || capacity == 0)
            throw std::invalid_argument("invalid stereo pending-frame bounds");
    }
    StereoPendingFrames(const StereoPendingFrames&) = delete;
    StereoPendingFrames& operator=(const StereoPendingFrames&) = delete;
    StereoPendingFrames(StereoPendingFrames&&) = default;
    StereoPendingFrames& operator=(StereoPendingFrames&&) = default;

    void set_maximum_delta(std::int64_t nanoseconds) {
        if (nanoseconds < 0) throw std::invalid_argument("negative pairing delta");
        maximum_delta_ns_ = nanoseconds;
    }
    // Startup may discard pre-existing frames until the first exact pair.
    // Once locked, any absent trigger or queue overflow is an error.
    void require_contiguous_pairs() noexcept { strict_ = true; }

    EnqueueResult enqueue(unsigned eye, Frame frame) {
        auto& queue = frames_.at(eye);
        const bool full = queue.size() == capacity_;
        if (full && strict_) return EnqueueResult::overflow;
        if (full) {
            queue.pop_front();
            ++capacity_discarded_[eye];
        }
        queue.push_back(std::move(frame));
        return full ? EnqueueResult::oldest_discarded : EnqueueResult::queued;
    }

    Result take() {
        while (!frames_[0].empty() && !frames_[1].empty()) {
            const auto delta = frames_[1].front().timestamp_ns -
                               frames_[0].front().timestamp_ns;
            if (delta > maximum_delta_ns_ || delta < -maximum_delta_ns_) {
                if (strict_) return PairingError{delta};
                if (++unmatched_ > 300) return PairingError{delta};
                const unsigned older = delta > 0 ? 0 : 1;
                frames_[older].pop_front();
                ++alignment_discarded_[older];
                continue;
            }
            Pair pair{std::move(frames_[0].front()), std::move(frames_[1].front())};
            frames_[0].pop_front();
            frames_[1].pop_front();
            unmatched_ = 0;
            return Result{std::move(pair)};
        }
        return std::monostate{};
    }

    std::size_t depth(unsigned eye) const { return frames_.at(eye).size(); }
    std::int64_t head_timestamp(unsigned eye) const {
        const auto& queue = frames_.at(eye);
        return queue.empty() ? -1 : queue.front().timestamp_ns;
    }
    std::uint64_t capacity_discarded(unsigned eye) const {
        return capacity_discarded_.at(eye);
    }
    std::uint64_t alignment_discarded(unsigned eye) const {
        return alignment_discarded_.at(eye);
    }

private:
    std::array<std::deque<Frame>, 2> frames_;
    std::array<std::uint64_t, 2> capacity_discarded_{};
    std::array<std::uint64_t, 2> alignment_discarded_{};
    std::int64_t maximum_delta_ns_;
    std::size_t capacity_;
    unsigned unmatched_{};
    bool strict_{};
};

} // namespace stereo_rtsp::detail
