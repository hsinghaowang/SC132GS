#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include <variant>
#include <vector>

namespace stereo_rtsp::detail::depth_gpu {
enum class Stage { initialization, geometry, upload, kernel, download, file };
struct Error { Stage stage; int native_code{}; };
template<class T> using Result=std::variant<T,Error>;
struct Calibration {
    std::vector<std::int32_t> left_map, right_map; // Interleaved x/y, 1/32 native pixel.
    std::vector<std::uint8_t> left_valid, right_valid;
    std::vector<std::int32_t> full_left_map, full_right_map;
    std::vector<std::uint8_t> yuv_palette;
    float focal_times_baseline_m_px{};
    bool emit_gray{true}; // Independent depth worker never emits/owns /stereo.
};
struct StereoView {
    const std::uint16_t* cam0_right{};
    const std::uint16_t* cam1_left{};
    std::size_t pixels_per_eye{};
};
enum class Preview { none, left_luma };
struct DepthFrame {
    std::vector<float> meters; // 544x640, optical-axis Z; invalid=NaN.
    std::vector<std::uint8_t> left_luma;
    std::vector<std::uint8_t> gray_nv12, depth_nv12;
    double gpu_ms{}, rectify_ms{};
};
// Synchronous GPU consumer; borrowed StereoView pixels must survive process().
class GpuStereoDepth final {
public:
    static Result<GpuStereoDepth> open(const Calibration&);
    ~GpuStereoDepth();
    GpuStereoDepth(GpuStereoDepth&&) noexcept;
    GpuStereoDepth& operator=(GpuStereoDepth&&) noexcept;
    GpuStereoDepth(const GpuStereoDepth&)=delete;
    GpuStereoDepth& operator=(const GpuStereoDepth&)=delete;
    Result<DepthFrame> process(StereoView,Preview=Preview::none); // One caller.
    void recycle(DepthFrame&&); // Return storage after synchronous stream submission.
private:
    struct Impl;
    explicit GpuStereoDepth(std::unique_ptr<Impl>) noexcept;
    std::unique_ptr<Impl> impl_;
};
}
