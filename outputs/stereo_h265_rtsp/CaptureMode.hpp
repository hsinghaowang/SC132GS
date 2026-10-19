#pragma once

namespace stereo_rtsp {

enum class CaptureMode {
    external_trigger,
    experimental_linear120_free_running,
    experimental_linear120_binning,
    experimental_linear60_binning,
    linear_binning
};

} // namespace stereo_rtsp
