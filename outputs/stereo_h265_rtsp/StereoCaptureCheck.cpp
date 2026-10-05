#include "StereoCapture.hpp"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <stop_token>
#include <string>

int main(int argc, char** argv) {
    try {
        const int frames = argc > 1 ? std::stoi(argv[1]) : 600;
        const int fps = argc > 2 ? std::stoi(argv[2]) : 60;
        if (frames < 2 || (fps != 30 && fps != 60))
            throw std::invalid_argument("usage: stereo-capture-check [frames >= 2] [30|60]");

        if (argc < 5)
            throw std::invalid_argument("usage: stereo-capture-check FRAMES FPS CAM0_NODE CAM1_NODE");
        stereo_rtsp::StereoCapture capture(argv[3], argv[4], 1, fps);
        std::stop_source stop;
        auto first = capture.next(stop.get_token());
        const auto start = std::chrono::steady_clock::now();
        std::int64_t max_delta_ns = 0;
        std::uint64_t checksum = 0;
        std::uint32_t last0 = first.cam0_sequence;
        std::uint32_t last1 = first.cam1_sequence;
        for (int i = 1; i < frames; ++i) {
            auto pair = capture.next(stop.get_token());
            if (pair.cam0_sequence != last0 + 1 || pair.cam1_sequence != last1 + 1)
                throw std::runtime_error("capture sequence gap");
            if (pair.left_luma.size() != 1088 * 1280 ||
                pair.right_luma.size() != 1088 * 1280)
                throw std::runtime_error("unexpected luma size");
            last0 = pair.cam0_sequence;
            last1 = pair.cam1_sequence;
            const std::int64_t delta = pair.cam0_timestamp_ns >= pair.cam1_timestamp_ns
                ? pair.cam0_timestamp_ns - pair.cam1_timestamp_ns
                : pair.cam1_timestamp_ns - pair.cam0_timestamp_ns;
            max_delta_ns = std::max(max_delta_ns, delta);
            checksum += pair.left_luma[(i * 101) % pair.left_luma.size()];
            checksum += pair.right_luma[(i * 113) % pair.right_luma.size()];
        }
        const double seconds = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - start).count();
        std::cout << "pairs=" << frames << " elapsed_s=" << seconds
                  << " fps=" << (frames - 1) / seconds
                  << " max_timestamp_delta_us=" << max_delta_ns / 1000.0
                  << " cam0_sequence=" << first.cam0_sequence << ".." << last0
                  << " cam1_sequence=" << first.cam1_sequence << ".." << last1
                  << " luma_checksum=" << checksum << '\n';
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
