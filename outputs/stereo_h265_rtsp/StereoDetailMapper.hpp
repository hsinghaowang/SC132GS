#pragma once
#include <cstddef>
#include <cstdint>
#include <memory>

namespace stereo_rtsp {
// Matching-oriented global quantizer. Both eyes use one monotonic RAW10-to-Y8
// LUT. Input/AE remains immutable; output is full-range [0,255], with no OETF.
// Calls must be serialized. Output is a feature representation, not radiometry.
class StereoDetailMapper final {
public:
    struct Config {
        double strength{1.0};
        double clip_limit{4.0}; // Bound density relative to a uniform histogram.
        double response_ms{500.0};
        std::uint16_t minimum_span{16};
    };
    struct Input { const std::uint16_t* data{}; std::size_t size{}; };
    struct Output { std::uint8_t* data{}; std::size_t size{}; };
    enum class ErrorCode { none, invalid_config, invalid_buffer, overlapping_buffers,
                           sample_out_of_range, timestamp_regressed, moved_from };
    struct FrameInfo { std::uint64_t revision{}; bool fallback{}; };
    struct Result {
        ErrorCode error{ErrorCode::none}; FrameInfo frame{};
        explicit operator bool() const noexcept { return error==ErrorCode::none; }
    };
    StereoDetailMapper();
    explicit StereoDetailMapper(Config config);
    ~StereoDetailMapper();
    StereoDetailMapper(StereoDetailMapper&&) noexcept;
    StereoDetailMapper& operator=(StereoDetailMapper&&) noexcept;
    StereoDetailMapper(const StereoDetailMapper&)=delete;
    StereoDetailMapper& operator=(const StereoDetailMapper&)=delete;
    // Black-corrected linear mono10. Buffers borrowed for this call only.
    // Errors leave output and temporal history unchanged; equal timestamps
    // retain the preceding LUT. Output cannot alias either input or each other.
    Result process(Input left, Input right, Output left_y, Output right_y,
                   std::uint64_t timestamp_ns) noexcept;
    void reset() noexcept;
private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
}
