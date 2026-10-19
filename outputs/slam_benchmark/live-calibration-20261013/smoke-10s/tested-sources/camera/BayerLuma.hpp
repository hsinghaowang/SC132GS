#pragma once

#include <cstdint>
#include <memory>
#include <span>

namespace stereo_rtsp::detail {

// Full RAW10 precision, RGGB reconstruction, then BT.709 grayscale.
// Each capture device owns its converter and scratch storage.
class BayerLuma final {
public:
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

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace stereo_rtsp::detail
