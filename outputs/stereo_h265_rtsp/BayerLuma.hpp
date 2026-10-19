#pragma once

#include <cstdint>
#include <array>
#include <memory>
#include <span>

namespace stereo_rtsp::detail {

// Full RAW10 precision, RGGB reconstruction, then BT.709 grayscale.
// Each capture device owns its converter and scratch storage.
class BayerLuma final {
public:
    struct RawStatistics {
        std::array<unsigned, 1024> histogram{}; // Same CFA sampling grid as HDR metering.
        std::uint64_t sample_count{};
        std::uint64_t near_saturated_count{}; // All native pixels, threshold 1008.
    };
    BayerLuma(int width, int height, bool hdr_display = false);
    ~BayerLuma();
    BayerLuma(BayerLuma&&) noexcept;
    BayerLuma& operator=(BayerLuma&&) noexcept;
    BayerLuma(const BayerLuma&) = delete;
    BayerLuma& operator=(const BayerLuma&) = delete;

    void convert(std::span<const std::uint8_t> packed, int stride,
                 std::span<std::uint8_t> gray, int scale);
    void convert10(std::span<const std::uint8_t> packed, int stride,
                   std::span<std::uint16_t> gray, int scale);

    // unpack() is the only operation that reads the borrowed V4L2 mapping.
    // The caller can QBUF immediately afterwards; render/statistics use owned scratch.
    void unpack(std::span<const std::uint8_t> packed, int stride);
    RawStatistics statistics() const;
    void render(std::span<std::uint8_t> gray, int scale) const;
    void render10(std::span<std::uint16_t> gray, int scale) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace stereo_rtsp::detail
