#pragma once
namespace stereo_rtsp::detail::depth_gpu {
#define STEREO_MONO8_SOURCE(...) inline constexpr const char* mono8_rectification_kernels=#__VA_ARGS__;
#include "Mono8Rectification.cl.inc"
#undef STEREO_MONO8_SOURCE
}
