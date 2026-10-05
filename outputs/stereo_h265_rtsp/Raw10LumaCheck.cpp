#include "Raw10Luma.hpp"

#include <array>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace {

using Convert = void (*)(const std::uint8_t*, int, std::uint8_t*, int,
                         int, int) noexcept;

void check_case(int width, int height, int scale) {
    const int source_width = width * scale;
    const int stride = source_width * 5 / 4;
    std::vector<std::uint8_t> raw(stride * height * scale);
    for (std::size_t i = 0; i < raw.size(); ++i)
        raw[i] = static_cast<std::uint8_t>(i * 73 + i / 7 * 19 + 31);

    std::vector<std::uint8_t> expected(width * height);
    for (int y = 0; y < height; ++y) {
        const auto* row = raw.data() + y * scale * stride;
        for (int x = 0; x < width; ++x) {
            const int source_x = x * scale;
            expected[y * width + x] =
                row[(source_x / 4) * 5 + source_x % 4];
        }
    }

    for (const auto& [name, convert] :
         std::array<std::pair<std::string_view, Convert>, 2>{{
             {"scalar", stereo_rtsp::detail::raw10_luma_scalar},
             {"accelerated", stereo_rtsp::detail::raw10_luma_accelerated},
         }}) {
        std::vector<std::uint8_t> output(expected.size() + 32, 0xa5);
        convert(raw.data(), stride, output.data(), width, height, scale);
        for (std::size_t i = 0; i < expected.size(); ++i) {
            if (output[i] != expected[i]) {
                throw std::runtime_error(std::string(name) + " mismatch at " +
                                         std::to_string(i) + " width=" +
                                         std::to_string(width) + " scale=" +
                                         std::to_string(scale));
            }
        }
        for (std::size_t i = expected.size(); i < output.size(); ++i) {
            if (output[i] != 0xa5)
                throw std::runtime_error(std::string(name) + " output overrun");
        }
    }
}

double benchmark(Convert convert, const std::vector<std::uint8_t>& raw,
                 std::vector<std::uint8_t>& output, int iterations,
                 std::uint64_t& checksum) {
    constexpr int width = 1088;
    constexpr int height = 1280;
    constexpr int stride = width * 5 / 4;
    const auto start = std::chrono::steady_clock::now();
    for (int iteration = 0; iteration < iterations; ++iteration) {
        convert(raw.data(), stride, output.data(), width, height, 1);
        checksum += output[iteration % output.size()];
    }
    return std::chrono::duration<double, std::milli>(
               std::chrono::steady_clock::now() - start)
        .count();
}

} // namespace

int main(int argc, char** argv) {
    try {
        for (int scale : {1, 2, 4}) {
            for (int width : {4, 16, 20, 36, 1088 / scale})
                check_case(width, 3, scale);
            check_case(1088 / scale, 1280 / scale, scale);
        }
        std::cout << "RAW10 luma correctness passed; neon="
                  << stereo_rtsp::detail::raw10_luma_uses_neon() << '\n';
        if (argc > 1 && std::string_view(argv[1]) == "--bench") {
            constexpr int iterations = 600;
            std::vector<std::uint8_t> raw(1088 * 1280 * 5 / 4);
            std::vector<std::uint8_t> output(1088 * 1280);
            for (std::size_t i = 0; i < raw.size(); ++i)
                raw[i] = static_cast<std::uint8_t>(i * 73 + 31);
            std::uint64_t checksum = 0;
            const double scalar_ms = benchmark(
                stereo_rtsp::detail::raw10_luma_scalar, raw, output,
                iterations, checksum);
            const double accelerated_ms = benchmark(
                stereo_rtsp::detail::raw10_luma_accelerated, raw, output,
                iterations, checksum);
            std::cout << "frames=" << iterations << " scalar_ms=" << scalar_ms
                      << " accelerated_ms=" << accelerated_ms
                      << " speedup=" << scalar_ms / accelerated_ms
                      << " checksum=" << checksum << '\n';
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
