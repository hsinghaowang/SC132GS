#pragma once
#include <cstdint>
#include <array>
#include <memory>
#include <string>
#include <variant>

namespace stereo_rtsp::sync {
enum class ErrorCode { io, malformed_status, unsupported_abi };
struct Error { ErrorCode code; int system_errno{}; };
enum class TimestampSource { fsync_host_reference, exposure_midpoint_estimate, exposure_start_estimate };
struct Status {
    std::uint32_t abi{}, mode{}, driver_error{}, trigger_hz{}, frame_step{}, locked_mask{};
    bool running{};
    std::uint64_t session{}, trigger_id{}, skipped{}, error_count{}, startup_dropped{};
    std::uint64_t timestamp_offset_ns{}; // ABI 3/4; ABI 2 is always zero.
    std::array<std::uint32_t, 2> video_nodes{}, startup_sequence_end{};
    TimestampSource source{TimestampSource::fsync_host_reference};
    // Sequence is used only to classify an ERROR prefix, never to match eyes.
    bool is_startup_buffer(std::uint32_t node, std::uint32_t sequence,
                           std::uint64_t expected_session) const noexcept;
};
// Synchronous, read-only diagnostics. This reader never owns or stops FSYNC.
// The CAMSS group controller owns the session and capture owns STREAMOFF.
// A caller must serialize reads on the same instance.
class StatusReader final {
public:
    static std::variant<StatusReader, Error> open(const std::string& control_path);
    ~StatusReader();
    StatusReader(StatusReader&&) noexcept;
    StatusReader& operator=(StatusReader&&) noexcept;
    StatusReader(const StatusReader&) = delete;
    StatusReader& operator=(const StatusReader&) = delete;
    std::variant<Status, Error> read() const;
private:
    struct Impl;
    explicit StatusReader(std::unique_ptr<Impl>) noexcept;
    std::unique_ptr<Impl> impl_;
};
}
