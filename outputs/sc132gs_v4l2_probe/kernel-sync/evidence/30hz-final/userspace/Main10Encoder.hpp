#pragma once
#include <cstdint>
#include <memory>
#include <span>
#include <stdexcept>
#include <vector>

namespace stereo_rtsp::detail {
enum class EncoderErrorCode { device, configuration, buffer, streaming };
struct EncoderError : std::runtime_error {
    EncoderErrorCode code;
    int system_error;
    EncoderError(EncoderErrorCode value, const char* operation, int error);
};
struct EncodedFrame {
    std::vector<std::uint8_t> bytes;
    std::int64_t timestamp_ns{};
    bool keyframe{};
};
// Capture-thread-owned encoder. Owns the fd, mappings and queued buffers.
// R16 holds linear 0..1023 values. The implementation packs full-range P010.
class Main10Encoder final {
public:
    Main10Encoder(int width, int height, int fps, int bitrate);
    ~Main10Encoder();
    Main10Encoder(const Main10Encoder&) = delete;
    Main10Encoder& operator=(const Main10Encoder&) = delete;
    Main10Encoder(Main10Encoder&&) noexcept;
    Main10Encoder& operator=(Main10Encoder&&) noexcept;
    // False means backpressure: caller may drop this input frame.
    bool submit(std::span<const std::uint16_t> luma, std::int64_t timestamp_ns);
    std::vector<EncodedFrame> receive();
    void request_keyframe();
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace stereo_rtsp::detail
