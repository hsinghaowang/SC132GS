#pragma once

#include "CaptureMode.hpp"
#include "VideoRange.hpp"

#include <cstdint>
#include <memory>
#include <string>
#include <variant>

namespace stereo_rtsp {

enum class ErrorCode { invalid_config, input, pipeline, server };

struct Error {
    ErrorCode code;
    std::string detail;
};

struct Settings {
    std::string cam0;
    std::string cam1;
    std::string bind_address{"127.0.0.1"};
    std::string port{"8554"};
    std::string mount{"/stereo"};
    int downscale{1};
    int frame_rate{30};
    int target_brightness_percent{30};
    bool auto_exposure{true};
    bool main10{false};
    bool shared_tone_map{false}; // Linear mono10 capture/AE -> shared final 8-bit Y'.
    bool detail_tone_map{false}; // Matching-oriented full-range shared quantizer.
    VideoRange display_range{VideoRange::limited}; // Matching remains unchanged.
    bool hdr_display_b{false}; // Main10 HDR display and matching AE target encoding.
    bool capture_api{false}; // Common library, Linear/mono10/30 Hz only.
    std::string gpu_rectification_map; // Empty explicitly selects legacy output.
    std::string depth_calibration; // Empty disables the independent /depth pipeline.
    int bitrate{20000000};
    CaptureMode capture_mode{CaptureMode::external_trigger};
};

// Captures timestamp-paired V4L2 frames until SIGINT/SIGTERM.
class StereoRtspServer final {
public:
    explicit StereoRtspServer(Settings settings);
    ~StereoRtspServer();
    StereoRtspServer(StereoRtspServer&&) noexcept;
    StereoRtspServer& operator=(StereoRtspServer&&) noexcept;
    StereoRtspServer(const StereoRtspServer&) = delete;
    StereoRtspServer& operator=(const StereoRtspServer&) = delete;

    std::variant<std::monostate, Error> run();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace stereo_rtsp
