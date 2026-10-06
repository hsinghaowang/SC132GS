#pragma once

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
    int target_brightness_percent{40};
    bool auto_exposure{true};
};

// Captures synchronized V4L2 camera frames until SIGINT/SIGTERM.
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
