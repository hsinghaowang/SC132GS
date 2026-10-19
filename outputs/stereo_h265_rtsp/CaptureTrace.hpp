#pragma once
#include <array>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <mutex>
#include <string>

namespace stereo_rtsp::detail {
enum class CaptureOperation {
    buffers, dequeue, requeue, unpack, statistics, render,
    pair, handoff_wait, consumer_gap, buffer_snapshot, fault,
    acquire, calibration, automatic_exposure, tone_mapping, depth_submit, encoder_submit, buffer_hold
};
inline const char* operation_name(CaptureOperation operation) noexcept {
    switch (operation) {
    case CaptureOperation::buffers: return "buffers";
    case CaptureOperation::dequeue: return "dqbuf";
    case CaptureOperation::requeue: return "qbuf";
    case CaptureOperation::unpack: return "unpack";
    case CaptureOperation::statistics: return "statistics";
    case CaptureOperation::render: return "render";
    case CaptureOperation::pair: return "pair";
    case CaptureOperation::handoff_wait: return "handoff_wait";
    case CaptureOperation::consumer_gap: return "consumer_gap";
    case CaptureOperation::buffer_snapshot: return "buffer_snapshot";
    case CaptureOperation::fault: return "fault";
    case CaptureOperation::acquire: return "acquire";
    case CaptureOperation::calibration: return "calibration";
    case CaptureOperation::automatic_exposure: return "ae";
    case CaptureOperation::tone_mapping: return "tone";
    case CaptureOperation::depth_submit: return "depth_submit";
    case CaptureOperation::encoder_submit: return "encoder_submit";
    case CaptureOperation::buffer_hold: return "buffer_hold";
    }
    return "unknown";
}
inline std::uint64_t capture_now_ns() noexcept {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}
struct CaptureTraceEvent {
    CaptureOperation operation{};
    unsigned eye{2}, index{}, sequence{}, flags{}, application_held{};
    std::uint64_t begin_ns{}, end_ns{}, value{};
    int system_error{};
};
// Fixed storage; hot path performs no I/O or allocation. Shared with the
// consumer only for timing markers; actual ioctl ownership stays on capture.
class CaptureTrace final {
public:
    struct Timing {
        std::uint64_t count{}, total_ns{}, max_ns{};
    };
    static constexpr std::size_t capacity = 4096;
    void record(CaptureTraceEvent event) {
        std::lock_guard lock(mutex_);
        events_[serial_++ % capacity] = event;
        auto& aggregate = timing_[static_cast<unsigned>(event.operation)][event.eye < 3 ? event.eye : 2];
        ++aggregate.count;
        const auto duration = event.end_ns >= event.begin_ns ? event.end_ns - event.begin_ns : 0;
        aggregate.total_ns += duration;
        if (duration > aggregate.max_ns) aggregate.max_ns = duration;
    }
    Timing timing(CaptureOperation operation, unsigned eye = 2) const {
        std::lock_guard lock(mutex_);
        return timing_[static_cast<unsigned>(operation)][eye < 3 ? eye : 2];
    }
    bool dump(const std::string& path) noexcept {
        try {
            std::lock_guard lock(mutex_);
            std::ofstream output(path);
            output << "{\"clock\":\"linux_CLOCK_MONOTONIC\",\"capacity\":" << capacity
                   << ",\"total_events\":" << serial_
                   << ",\"note\":\"application_held excludes driver DONE buffers; snapshots are non-atomic\",\"lifetime_timing\":[";
            bool first_timing = true;
            for (unsigned operation = 0; operation < timing_.size(); ++operation)
                for (unsigned eye = 0; eye < 3; ++eye) {
                    const auto& t = timing_[operation][eye];
                    if (!t.count) continue;
                    if (!first_timing) output << ',';
                    first_timing = false;
                    output << "{\"op\":\"" << operation_name(static_cast<CaptureOperation>(operation))
                           << "\",\"eye\":" << eye << ",\"count\":" << t.count
                           << ",\"total_ns\":" << t.total_ns << ",\"max_ns\":" << t.max_ns << '}';
                }
            output << "]}\n";
            const auto first = serial_ > capacity ? serial_ - capacity : 0;
            for (auto i = first; i < serial_; ++i) {
                const auto& e = events_[i % capacity];
                output << "{\"serial\":" << i << ",\"op\":\"" << operation_name(e.operation)
                       << "\",\"eye\":" << e.eye << ",\"index\":" << e.index
                       << ",\"sequence\":" << e.sequence << ",\"flags\":" << e.flags
                       << ",\"application_held\":" << e.application_held
                       << ",\"begin_ns\":" << e.begin_ns << ",\"end_ns\":" << e.end_ns
                       << ",\"value\":" << e.value << ",\"errno\":" << e.system_error << "}\n";
            }
            output.flush();
            return static_cast<bool>(output);
        } catch (...) { return false; }
    }
private:
    mutable std::mutex mutex_;
    std::array<CaptureTraceEvent, capacity> events_{};
    std::uint64_t serial_{};
    std::array<std::array<Timing, 3>, static_cast<unsigned>(CaptureOperation::buffer_hold) + 1> timing_{};
};
class CaptureSpan final {
public:
    CaptureSpan(CaptureTrace& trace, CaptureOperation operation, unsigned sequence = 0)
        : trace_(trace), operation_(operation), sequence_(sequence), begin_(capture_now_ns()) {}
    ~CaptureSpan() { finish(); }
    CaptureSpan(const CaptureSpan&) = delete;
    CaptureSpan& operator=(const CaptureSpan&) = delete;
    void finish() {
        if (finished_) return;
        finished_ = true;
        trace_.record({operation_, 2, 0, sequence_, 0, 0, begin_, capture_now_ns()});
    }
private:
    CaptureTrace& trace_;
    CaptureOperation operation_;
    unsigned sequence_;
    std::uint64_t begin_;
    bool finished_{};
};
}
