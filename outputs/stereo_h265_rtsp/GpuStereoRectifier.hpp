#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <variant>
#include <vector>
#include "VideoRange.hpp"

namespace stereo_rtsp::detail {
enum class RectificationCode { map_file, geometry, initialization, upload, kernel, download };
struct RectificationError { RectificationCode code; int native_code{}; };
struct RectificationTiming { std::uint64_t gpu_ns{}; };
// Private backend. Native, unmirrored mono10 in; full-resolution cam1|cam0 out.
class GpuStereoRectifier final {
public:
    explicit GpuStereoRectifier(const std::string& map_file);
    ~GpuStereoRectifier();
    GpuStereoRectifier(GpuStereoRectifier&&) noexcept;
    GpuStereoRectifier& operator=(GpuStereoRectifier&&) noexcept;
    GpuStereoRectifier(const GpuStereoRectifier&)=delete;
    GpuStereoRectifier& operator=(const GpuStereoRectifier&)=delete;
    std::variant<RectificationTiming,RectificationError> process(
        const std::uint16_t* cam0,const std::uint16_t* cam1,
        std::size_t pixels_per_eye,std::vector<std::uint16_t>& stereo10);
    // Y8 in; unmirrored, rectified cam1|cam0 Y8 out. Border is the selected
    // video range's black (16 limited, 0 full); no additional transfer/LUT.
    std::variant<RectificationTiming,RectificationError> process8(
        const std::uint8_t* cam0,const std::uint8_t* cam1,
        std::size_t pixels_per_eye,std::vector<std::uint8_t>& stereo_y8,
        VideoRange range=VideoRange::limited);
private:
    struct Impl;std::unique_ptr<Impl> impl_;
};
}
