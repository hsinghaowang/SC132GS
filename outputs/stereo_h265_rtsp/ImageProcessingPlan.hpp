#pragma once
#include "StereoRtspServer.hpp"

namespace stereo_rtsp::detail {
enum class ImagePlanError { tone_output, tone_mode, depth_geometry,
                            rectification_profile, capture_api_mode, display_range, detail_mapping };
struct ImageProcessingPlan {
    bool capture10{};
    bool sensor_signal{};
    bool shared_y8{};
};
// Codec choice cannot silently select a lower precision AE input in the shared
// tone path. This value-only contract is also checked without camera hardware.
inline std::variant<ImageProcessingPlan,ImagePlanError> image_processing_plan(const Settings& s) {
    const bool external=s.capture_mode==CaptureMode::external_trigger;
    if(s.detail_tone_map&&(!s.shared_tone_map||s.main10||s.gpu_rectification_map.empty()))return ImagePlanError::detail_mapping;
    if(s.display_range==VideoRange::full&&(!s.shared_tone_map||s.main10||s.gpu_rectification_map.empty()))return ImagePlanError::display_range;
    if(s.shared_tone_map && s.main10) return ImagePlanError::tone_output;
    if(s.shared_tone_map && (!external || s.hdr_display_b)) return ImagePlanError::tone_mode;
    const bool capture10=s.main10 || s.shared_tone_map;
    if(!s.depth_calibration.empty() && (!capture10 || s.downscale!=1 || !external))
        return ImagePlanError::depth_geometry;
    // Both mono10 and shared limited-range Y8 use the same stereo geometry.
    if(!s.gpu_rectification_map.empty() && (!capture10 || s.downscale!=1 || !external))
        return ImagePlanError::rectification_profile;
    if(s.capture_api && (!capture10 || s.frame_rate!=30 || !external))
        return ImagePlanError::capture_api_mode;
    return ImageProcessingPlan{capture10,capture10 && !s.hdr_display_b && external,s.shared_tone_map};
}
}
