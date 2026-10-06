#include "BayerLuma.hpp"

#include <algorithm>
#include <cstddef>
#include <stdexcept>
#include <vector>

namespace stereo_rtsp::detail {

struct BayerLuma::Impl {
    int width;
    int height;
    std::vector<std::uint16_t> pixels;

    Impl(int w, int h) : width(w), height(h) {
        if (w < 4 || w % 4 || h < 2 || h % 2)
            throw std::invalid_argument("RGGB dimensions must be width multiple of four, even height");
        pixels.resize(static_cast<std::size_t>(w) * h);
    }

    void unpack(std::span<const std::uint8_t> raw, int stride) {
        for (int y = 0; y < height; ++y) {
            const auto* source = raw.data() + static_cast<std::size_t>(y) * stride;
            auto* row = pixels.data() + static_cast<std::size_t>(y) * width;
            for (int x = 0; x < width; x += 4, source += 5) {
                const auto low = source[4];
                row[x] = (source[0] << 2) | (low & 3);
                row[x + 1] = (source[1] << 2) | ((low >> 2) & 3);
                row[x + 2] = (source[2] << 2) | ((low >> 4) & 3);
                row[x + 3] = (source[3] << 2) | ((low >> 6) & 3);
            }
        }
    }

    void grayscale(std::span<std::uint8_t> gray, int scale) const {
        const int out_width = width / scale;
        for (int oy = 0; oy < height / scale; ++oy) {
            const int y = oy * scale;
            // Reflect at the boundary to preserve the CFA color parity.
            const int above = y == 0 ? 1 : y - 1;
            const int below = y == height - 1 ? height - 2 : y + 1;
            const auto* row = pixels.data() + static_cast<std::size_t>(y) * width;
            const auto* up = pixels.data() + static_cast<std::size_t>(above) * width;
            const auto* down = pixels.data() + static_cast<std::size_t>(below) * width;
            auto* output = gray.data() + static_cast<std::size_t>(oy) * out_width;
            for (int ox = 0; ox < out_width; ++ox) {
                const int x = ox * scale;
                const int left = x == 0 ? 1 : x - 1;
                const int right = x == width - 1 ? width - 2 : x + 1;
                unsigned r, g, b;
                if ((y & 1) == (x & 1)) {
                    const unsigned diagonal = (up[left] + up[right] + down[left] + down[right] + 2) / 4;
                    g = (row[left] + row[right] + up[x] + down[x] + 2) / 4;
                    r = (y & 1) ? diagonal : row[x];
                    b = (y & 1) ? row[x] : diagonal;
                } else {
                    const unsigned horizontal = (row[left] + row[right] + 1) / 2;
                    const unsigned vertical = (up[x] + down[x] + 1) / 2;
                    g = row[x];
                    r = (y & 1) ? vertical : horizontal;
                    b = (y & 1) ? horizontal : vertical;
                }
                output[ox] = static_cast<std::uint8_t>(std::min(255U, (54*r + 183*g + 19*b + 512) >> 10));
            }
        }
    }
};

BayerLuma::BayerLuma(int width, int height) : impl_(std::make_unique<Impl>(width, height)) {}
BayerLuma::~BayerLuma() = default;
BayerLuma::BayerLuma(BayerLuma&&) noexcept = default;
BayerLuma& BayerLuma::operator=(BayerLuma&&) noexcept = default;

void BayerLuma::convert(std::span<const std::uint8_t> packed, int stride,
                        std::span<std::uint8_t> gray, int scale) {
    if ((scale != 1 && scale != 2 && scale != 4) ||
        impl_->width % scale || impl_->height % scale ||
        stride < impl_->width * 5 / 4 ||
        packed.size() < static_cast<std::size_t>(stride) * impl_->height ||
        gray.size() != static_cast<std::size_t>(impl_->width / scale) * (impl_->height / scale))
        throw std::invalid_argument("RGGB RAW10 buffer, stride or scale");
    impl_->unpack(packed, stride);
    impl_->grayscale(gray, scale);
}

} // namespace stereo_rtsp::detail
