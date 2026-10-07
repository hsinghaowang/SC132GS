#pragma once

#include <cstdint>
#include <memory>
#include <stop_token>
#include <string>
#include <vector>

namespace stereo_rtsp {

struct FramePair {
    std::uint32_t cam0_sequence{};
    std::uint32_t cam1_sequence{};
    std::int64_t cam0_timestamp_ns{};
    std::int64_t cam1_timestamp_ns{};
    std::vector<std::uint8_t> left_luma;
    std::vector<std::uint8_t> right_luma;
};

// Internal capture adapter. Only constructed on the capture thread.
class StereoCapture final {
public:
    StereoCapture(const std::string& cam0, const std::string& cam1, int scale,
                  int frame_rate, bool hdr_display = false);
    ~StereoCapture();
    StereoCapture(const StereoCapture&) = delete;
    StereoCapture& operator=(const StereoCapture&) = delete;
    StereoCapture(StereoCapture&&) noexcept;
    StereoCapture& operator=(StereoCapture&&) noexcept;
    FramePair next(std::stop_token stop);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace stereo_rtsp
