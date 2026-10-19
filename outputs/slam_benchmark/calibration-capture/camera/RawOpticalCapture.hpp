#pragma once
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <variant>

namespace stereo_rtsp::optical {
enum class ErrorCode { invalid_configuration, system, invalid_frame, timeout };
struct Error {
    ErrorCode code{};
    int system_errno{};
    int eye{-1};
    const char* operation{};
};
struct FrameView {
    int eye{};
    std::uint32_t sequence{}, flags{};
    std::int64_t receiver_timestamp_ns{}, dequeue_timestamp_ns{};
    int width{}, height{}, stride{};
    std::span<const std::uint8_t> packed_raw10;
};
struct CaptureOptions { std::string first_device, second_device; };

class RawOpticalCapture final {
public:
    class Observer {
    public:
        virtual ~Observer() = default;
        // Called synchronously on run's thread. View expires on return.
        // False requests a clean stop; the observer owns its output errors.
        virtual bool on_frame(const FrameView&) noexcept = 0;
    };
    // Observer must outlive this move-only capture object.
    static std::variant<RawOpticalCapture, Error> open(const CaptureOptions&, Observer&) noexcept;
    ~RawOpticalCapture();
    RawOpticalCapture(RawOpticalCapture&&) noexcept;
    RawOpticalCapture& operator=(RawOpticalCapture&&) noexcept;
    RawOpticalCapture(const RawOpticalCapture&) = delete;
    RawOpticalCapture& operator=(const RawOpticalCapture&) = delete;
    std::optional<Error> run() noexcept;
private:
    struct Impl;
    explicit RawOpticalCapture(std::unique_ptr<Impl>) noexcept;
    std::unique_ptr<Impl> impl_;
};
}
