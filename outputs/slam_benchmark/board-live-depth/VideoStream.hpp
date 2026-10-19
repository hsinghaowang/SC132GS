#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <vector>
namespace board_depth {
struct StreamStatistics {std::uint64_t submitted{},encoded{},max_queue{},missing_metadata{};bool failed{};};
// Owns one resident VPU encoder; RTSP connections only own packetization.
class VideoStream final {
public:
    VideoStream(int width,int height,int port,std::string mount,std::string csv,bool timing_marker=false);
    ~VideoStream();
    VideoStream(VideoStream&&)noexcept;
    VideoStream& operator=(VideoStream&&)noexcept;
    VideoStream(const VideoStream&)=delete;VideoStream& operator=(const VideoStream&)=delete;
    bool push(const std::vector<std::uint8_t>& nv12,std::uint64_t source_ns,std::uint64_t depth_ready_ns);
    StreamStatistics statistics()const;
    void close();
private:struct Impl;std::unique_ptr<Impl> impl_;
};
}
