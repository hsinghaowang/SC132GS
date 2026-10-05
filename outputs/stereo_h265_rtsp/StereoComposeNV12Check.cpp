#include "StereoComposeNV12.hpp"

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <utility>
#include <vector>

int main() {
    try {
        for (const auto& [width, height] : {std::pair{2, 2}, std::pair{18, 6},
                                            std::pair{20, 4}, std::pair{1088, 1280}}) {
            const std::size_t eye_bytes = static_cast<std::size_t>(width) * height;
            const std::size_t output_bytes = eye_bytes * 3;
            std::vector<std::uint8_t> left(eye_bytes);
            std::vector<std::uint8_t> right(eye_bytes);
            std::vector<std::uint8_t> output(output_bytes + 32, 0xa5);
            for (std::size_t i = 0; i < eye_bytes; ++i) {
                left[i] = static_cast<std::uint8_t>(i * 37 + 1);
                right[i] = static_cast<std::uint8_t>(i * 29 + 2);
            }
            stereo_rtsp::detail::compose_mirrored_side_by_side_nv12(
                left.data(), right.data(), output.data(), width, height);
            for (int y = 0; y < height; ++y) {
                for (int x = 0; x < width; ++x) {
                    const auto input_index = static_cast<std::size_t>(y) * width +
                                             (width - 1 - x);
                    const auto output_index = static_cast<std::size_t>(y) * width * 2 + x;
                    if (output[output_index] != left[input_index] ||
                        output[output_index + width] != right[input_index])
                        throw std::runtime_error("per-eye mirror or placement mismatch");
                }
            }
            if (!std::all_of(output.begin() + eye_bytes * 2,
                             output.begin() + output_bytes,
                             [](std::uint8_t value) { return value == 128; }))
                throw std::runtime_error("NV12 chroma mismatch");
            if (!std::all_of(output.begin() + output_bytes, output.end(),
                             [](std::uint8_t value) { return value == 0xa5; }))
                throw std::runtime_error("output overrun");
        }
        std::cout << "per-eye mirrored side-by-side NV12 composition passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
