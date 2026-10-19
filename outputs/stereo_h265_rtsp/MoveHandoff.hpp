#pragma once
#include <condition_variable>
#include <exception>
#include <mutex>
#include <optional>
#include <utility>

namespace stereo_rtsp::detail {
// One owned frame slot, no pixel copy, replacement or silent loss. A slow
// consumer applies bounded-memory backpressure, which diagnostics must expose.
template<class T> class MoveHandoff final {
public:
    MoveHandoff() = default;
    MoveHandoff(const MoveHandoff&) = delete;
    MoveHandoff& operator=(const MoveHandoff&) = delete;
    bool put(T&& value) {
        std::unique_lock lock(mutex_);
        condition_.wait(lock, [this] { return closed_ || !slot_; });
        if (closed_) return false;
        slot_.emplace(std::move(value));
        condition_.notify_all();
        return true;
    }
    std::optional<T> take() {
        std::unique_lock lock(mutex_);
        condition_.wait(lock, [this] { return closed_ || slot_ || error_; });
        if (error_) std::rethrow_exception(error_);
        if (closed_) return std::nullopt;
        auto value = std::move(slot_);
        slot_.reset();
        condition_.notify_all();
        return value;
    }
    void fail(std::exception_ptr error) {
        std::lock_guard lock(mutex_);
        if (!error_) error_ = std::move(error);
        closed_ = true;
        slot_.reset(); // Fail closed: do not deliver pending frames after a fault.
        condition_.notify_all();
    }
    void close() {
        std::lock_guard lock(mutex_);
        closed_ = true;
        slot_.reset();
        condition_.notify_all();
    }
private:
    std::mutex mutex_;
    std::condition_variable condition_;
    std::optional<T> slot_;
    std::exception_ptr error_;
    bool closed_{};
};
}
