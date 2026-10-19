#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>

namespace stereo_rtsp {

// One stateful mapper per stereo stream. All calls, including reset(), must be
// serialized by the owner. Input is black-corrected linear mono10 [0, 1023].
// Both eyes use the same monotonic LUT, anchored at sensor black and white.
// Output is final BT.709 limited-range Y' [16, 235], ready for NV12 (UV = 128).
// Do not apply another display transfer function to these bytes.
class StereoToneMapper final {
public:
    struct Config {
        double max_gain{4.0};
        double upper_percentile{0.99};
        double target_highlight{0.85}; // Normalized linear value before BT.709.
        std::uint16_t minimum_span{16};
        double bright_response_ms{80.0}; // Reduce gain quickly as light increases.
        double dark_response_ms{500.0}; // Increase gain slowly as light decreases.
    };

    struct Input {
        const std::uint16_t* data{};
        std::size_t size{};
    };
    struct Output {
        std::uint8_t* data{};
        std::size_t size{};
    };
    enum class ErrorCode {
        none,
        invalid_config,
        invalid_buffer,
        overlapping_buffers,
        sample_out_of_range,
        timestamp_regressed,
        moved_from
    };
    struct FrameInfo {
        std::uint64_t lut_revision{};
        std::uint64_t timestamp_ns{};
        double applied_gain{1.0};
        double requested_gain{1.0};
        std::uint16_t left_high_code{};
        std::uint16_t right_high_code{};
        bool fallback{}; // Near black or no robust intensity span in either eye.
    };
    struct Result {
        ErrorCode error{ErrorCode::none};
        FrameInfo frame{};
        explicit operator bool() const noexcept { return error == ErrorCode::none; }
    };

    StereoToneMapper();
    explicit StereoToneMapper(Config config);
    ~StereoToneMapper();
    StereoToneMapper(StereoToneMapper&&) noexcept;
    StereoToneMapper& operator=(StereoToneMapper&&) noexcept;
    StereoToneMapper(const StereoToneMapper&) = delete;
    StereoToneMapper& operator=(const StereoToneMapper&) = delete;

    // Buffers are borrowed only for this call; all four sizes must be equal and
    // nonzero. Outputs must not overlap each other or either input. Input eyes
    // may share storage. Timestamp is monotonic nanoseconds; an equal timestamp
    // keeps the previous temporal state. Errors leave outputs and history intact.
    // The returned revision identifies the LUT used for this entire stereo pair.
    Result process(Input left, Input right, Output left_y, Output right_y,
                   std::uint64_t timestamp_ns) noexcept;

    // Clear temporal history after a stream discontinuity. Revision IDs remain
    // unique for this object's lifetime, including across reset().
    void reset() noexcept;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace stereo_rtsp
