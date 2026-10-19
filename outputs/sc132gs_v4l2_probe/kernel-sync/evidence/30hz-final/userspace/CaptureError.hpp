#pragma once

#include <cstdint>
#include <stdexcept>
#include <string>

namespace stereo_rtsp::detail {

enum class CaptureErrorCode { frame_timeout, timestamp_mismatch, invalid_buffer, frame_overflow, invalid_sync_state };

class CaptureError final : public std::runtime_error {
public:
    CaptureError(CaptureErrorCode error_code, std::uint8_t eyes = 0,
                 std::int64_t timestamp_delta = 0)
        : std::runtime_error(message(error_code, eyes, timestamp_delta)),
          code(error_code), eye_mask(eyes), delta_ns(timestamp_delta) {}
    const CaptureErrorCode code;
    const std::uint8_t eye_mask;
    const std::int64_t delta_ns;

private:
    static std::string message(CaptureErrorCode code, std::uint8_t eyes,
                               std::int64_t delta) {
        if (code == CaptureErrorCode::frame_timeout)
            return "camera capture timed out; stalled_eye_mask=" + std::to_string(eyes);
        if (code == CaptureErrorCode::invalid_buffer)
            return "camera driver returned an invalid buffer";
        if (code == CaptureErrorCode::frame_overflow)
            return "kernel synchronized capture queue overflow";
        if (code == CaptureErrorCode::invalid_sync_state)
            return "kernel synchronization status is unavailable or invalid";
        return "cannot pair camera timestamps; latest delta_ns=" + std::to_string(delta);
    }
};

} // namespace stereo_rtsp::detail
