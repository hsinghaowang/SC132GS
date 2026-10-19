#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
namespace stereo_rtsp {struct FramePair;}
namespace stereo_rtsp::detail {
class Main10Encoder;class GpuStereoRectifier;
enum class StereoProcessingStage { rectification, encoding, internal };
struct StereoProcessingError {StereoProcessingStage stage;int native_code{};};
struct StereoAccessUnit {const std::uint8_t* data;std::size_t bytes;std::uint64_t pts_ns;bool keyframe;};
struct StereoOutputStatistics {std::uint64_t processed{},submitted{},dropped{},replaced{},gpu_ns{};};
// Single owner of GPU remap and Main10 calls; capture never waits for processing.
class StereoOutputWorker final {
public:
    class Observer {
    public:
        virtual ~Observer()=default;
        virtual void on_stereo_access_unit(const StereoAccessUnit&)noexcept=0;
        virtual void on_stereo_processing_error(StereoProcessingError)noexcept=0;
    };
    StereoOutputWorker(Main10Encoder&,GpuStereoRectifier&,Observer&);
    ~StereoOutputWorker();
    StereoOutputWorker(StereoOutputWorker&&)noexcept;
    StereoOutputWorker& operator=(StereoOutputWorker&&)noexcept;
    StereoOutputWorker(const StereoOutputWorker&)=delete;
    StereoOutputWorker& operator=(const StereoOutputWorker&)=delete;
    void submit(FramePair&&); // Moves owned pixels into one latest-frame slot.
    void request_keyframe()noexcept;
    void stop()noexcept;
    StereoOutputStatistics statistics()const noexcept;
private:struct Impl;std::unique_ptr<Impl> impl_;
};
}
