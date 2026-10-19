#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>
#include "VideoRange.hpp"
namespace stereo_rtsp {struct FramePair;}
namespace stereo_rtsp::detail {
class Main10Encoder;class GpuStereoRectifier;
enum class StereoProcessingStage { rectification, encoding, internal };
struct StereoProcessingError {StereoProcessingStage stage;int native_code{};};
struct StereoAccessUnit {const std::uint8_t* data;std::size_t bytes;std::uint64_t pts_ns;bool keyframe;};
struct StereoLuma8 {const std::uint8_t* data;std::size_t bytes;std::uint64_t pts_ns;};
struct StereoOutputStatistics {std::uint64_t processed{},submitted{},dropped{},replaced{},gpu_ns{};};
// Single owner of display mapping, GPU remap and encoder calls.
// Capture never waits for processing; matching pixels have already been copied.
class StereoOutputWorker final {
public:
    class Observer {
    public:
        virtual ~Observer()=default;
        virtual void on_stereo_access_unit(const StereoAccessUnit&)noexcept=0;
        virtual void on_stereo_processing_error(StereoProcessingError)noexcept=0;
    };
    class Luma8Observer {
    public:
        virtual ~Luma8Observer()=default;
        // Borrowed pixels remain valid only for this call. False means dropped.
        virtual bool on_stereo_luma8(const StereoLuma8&)noexcept=0;
        virtual void on_stereo_processing_error(StereoProcessingError)noexcept=0;
    };
    StereoOutputWorker(Main10Encoder&,GpuStereoRectifier&,Observer&);
    StereoOutputWorker(GpuStereoRectifier&,Luma8Observer&,VideoRange output=VideoRange::limited,VideoRange input=VideoRange::limited);
    ~StereoOutputWorker();
    StereoOutputWorker(StereoOutputWorker&&)noexcept;
    StereoOutputWorker& operator=(StereoOutputWorker&&)noexcept;
    StereoOutputWorker(const StereoOutputWorker&)=delete;
    StereoOutputWorker& operator=(const StereoOutputWorker&)=delete;
    void submit(FramePair&&); // Moves owned pixels into one latest-frame slot.
    void submit8(FramePair&&,std::uint64_t pts_ns);
    void request_keyframe()noexcept;
    void stop()noexcept;
    StereoOutputStatistics statistics()const noexcept;
private:struct Impl;std::unique_ptr<Impl> impl_;
};
}
